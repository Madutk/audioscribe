"""Automatische Erkennung von Bildschirmwechseln in Bildschirmaufnahmen (FR-23..FR-27).

Ein EINZIGER ffmpeg-Prozess streamt das Video stark verkleinert als Graustufen-Rohbilder
in eine Pipe; verglichen wird dann Frame gegen Vorgaenger. Das ist um Groessenordnungen
billiger als ein ffmpeg-Aufruf je Zeitpunkt und braucht konstant wenig Speicher, weil
immer nur ein Bild im RAM liegt.

**Der Mauszeiger ist die eigentliche Schwierigkeit.** Ein pixelweiser Vergleich schlaegt
schon bei einer Mausbewegung an, und in einer Bildschirmaufnahme bewegt sich die Maus
staendig. Deshalb wird das Bild in ein Raster aus 16x9 Bloecken zerlegt: ein Block gilt
als geaendert, wenn seine mittlere Absolutdifferenz ueber der Schwelle liegt, und eine
echte Bildschirmaenderung liegt erst vor, wenn MEHRERE Bloecke betroffen sind. Ein
Mauszeiger (oder ein blinkender Text-Cursor) beruehrt bei 192x108 genau einen Block.
Gemessen an einer 2560x1440-Aufnahme: Mauszeiger 1-2 Bloecke, echte Wechsel 14-113.

Animationen und Scroll-Vorgaenge erzeugen ganze Trefferserien (ein Fensterwechsel schlaegt
ueber 1-2 Sekunden mehrfach an). Eine Aenderung gilt darum erst als abgeschlossen, wenn
das Bild wieder ruhig ist - der Screenshot entsteht am ENDE der Serie und zeigt damit den
fertig aufgebauten Bildschirm, nicht die halbe Animation.

Verworfen wurde ffmpegs ``select='gt(scene,X)'``: kein Mauszeiger-Schutz, und die Schwelle
laesst sich bei Bildschirmarbeit (viele kleine Teilaenderungen) nicht sinnvoll setzen.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from audioscribe.models import format_timecode
from audioscribe.progress import Reporter, emit_progress
from audioscribe.review.marks import Mark, load_marks, save_marks

# Analyse-Aufloesung und Blockraster. Klein genug, dass das Dekodieren dominiert, und
# gross genug, dass ein Mauszeiger genau einen Block trifft.
SCAN_WIDTH = 192
SCAN_HEIGHT = 108
BLOCKS_X = 16
BLOCKS_Y = 9

# Herkunft eines Marks: automatisch erkannte werden bei jedem Lauf ersetzt, von Hand
# gesetzte (kind=None) bleiben unberuehrt.
KIND_AUTO = "auto"

# name -> (blockschwelle, mindestanzahl geaenderter Bloecke von 144)
SENSITIVITIES: dict[str, tuple[int, int]] = {
    "grob": (12, 10),  # nur grossflaechige Wechsel
    "mittel": (8, 3),  # Fenster-/Folienwechsel, Navigation, groessere Scroll-Spruenge
    "fein": (5, 2),  # auch Dialoge, Dropdowns, Teilbereiche
}

# name -> (dateiendung, maximale Breite in Pixel, jpeg-Qualitaet oder None fuer PNG)
# JPEG-Qualitaet 3 ist ffmpegs Skala (2 = beste, 31 = schlechteste); gemessen an einer
# 2560x1440-Aufnahme: jpg-1600 ~158 KB, jpg-1280 ~115 KB, png(1600) ~665 KB.
FORMATS: dict[str, tuple[str, int, int | None]] = {
    "jpg-1600": (".jpg", 1600, 3),
    "jpg-1280": (".jpg", 1280, 3),
    "png": (".png", 0, None),  # Breite 0 = unskaliert, volle Aufloesung
}

DEFAULT_SENSITIVITY = "mittel"
DEFAULT_FORMAT = "jpg-1600"
DEFAULT_FPS = 2.0
DEFAULT_MIN_GAP = 4.0
# Notausgang gegen Dauerbewegung (mitlaufende Kamerakachel in Besprechungsaufnahmen):
# haelt die Bewegung so lange an, wird trotzdem ein Bild gesichert.
DEFAULT_DAUERBEWEGUNG_S = 20.0
# Obergrenze der Standbilder je Aufnahme - schuetzt Plattenplatz und haelt die Bildmenge
# in einer Groesse, die eine KI noch gemeinsam mit dem Transkript lesen kann.
DEFAULT_MAX_BILDER = 400

# Anzahl ruhiger Abtastungen, nach denen eine Aenderungsserie als beendet gilt.
_RUHE_ABTASTUNGEN = 2


def build_scan_cmd(
    ffmpeg: str,
    video: str | Path,
    *,
    fps: float,
    width: int = SCAN_WIDTH,
    height: int = SCAN_HEIGHT,
) -> list[str]:
    """ffmpeg-Argumente fuer den Analyse-Durchlauf (rein, testbar).

    ``flags=area`` mittelt beim Verkleinern ueber die Quellpixel statt zu samplen - ohne
    das wuerde ein duenner Mauszeiger je nach Position mal verschwinden, mal einen ganzen
    Zielpixel fuellen und so Scheinaenderungen erzeugen.
    """
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(video),
        # Ton, Untertitel und Daten gar nicht erst dekodieren - bei einer 80-Minuten-Spur
        # spart das spuerbar Zeit, gebraucht wird ohnehin nur das Bild.
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={fps:g},scale={width}:{height}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]


def build_shot_cmd(
    ffmpeg: str,
    video: str | Path,
    t: float,
    out: str | Path,
    *,
    max_breite: int = 0,
    qualitaet: int | None = None,
) -> list[str]:
    """ffmpeg-Argumente fuer EIN Standbild, skaliert und komprimiert (rein, testbar).

    Wie ``review.frames.build_extract_cmd`` mit ``-ss`` VOR ``-i`` (schneller Seek zum
    nahen Keyframe, danach exakt bis zur Zielzeit dekodiert), zusaetzlich Skalierung und
    JPEG-Qualitaet. ``-2`` bei der Hoehe haelt das Seitenverhaeltnis und rundet auf eine
    gerade Zahl (JPEG-Encoder verlangen das).
    """
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{max(0.0, t):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-update",
        "1",
    ]
    if max_breite > 0:
        # Nur verkleinern, nie hochskalieren: min(iw, breite) laesst kleine Quellen in Ruhe.
        cmd += ["-vf", f"scale='min(iw,{max_breite})':-2:flags=lanczos"]
    if qualitaet is not None:
        cmd += ["-q:v", str(qualitaet)]
    cmd.append(str(out))
    return cmd


def block_means(frame, *, bx: int = BLOCKS_X, by: int = BLOCKS_Y):
    """Mittelt das Graustufenbild zu einem ``by x bx``-Raster (rein, testbar).

    Erwartet ein 2D-Array, dessen Kantenlaengen durch das Raster teilbar sind.
    """
    hoehe, breite = frame.shape
    return frame.reshape(by, hoehe // by, bx, breite // bx).mean(axis=(1, 3))


def changed_blocks(vorher, jetzt, schwelle: int) -> int:
    """Anzahl der Bloecke, deren Helligkeit sich um mehr als ``schwelle`` unterscheidet."""
    import numpy as np

    return int((np.abs(jetzt - vorher) > schwelle).sum())


def merge_runs(
    treffer: list[float],
    *,
    fps: float,
    min_gap: float = DEFAULT_MIN_GAP,
    ruhe_abtastungen: int = _RUHE_ABTASTUNGEN,
    dauerbewegung_s: float = DEFAULT_DAUERBEWEGUNG_S,
) -> list[float]:
    """Fasst zusammenhaengende Trefferserien zu je EINEM Zeitpunkt zusammen (rein, testbar).

    ``treffer`` sind die Zeitpunkte, an denen die Blockpruefung angeschlagen hat. Eine
    Serie endet, wenn ``ruhe_abtastungen`` lang nichts mehr passiert; genommen wird ihr
    LETZTER Zeitpunkt - dort ist die Animation durch und der Bildschirm fertig aufgebaut.
    ``min_gap`` verwirft anschliessend Ereignisse, die zu dicht am zuletzt behaltenen
    liegen.

    ``dauerbewegung_s`` ist der Notausgang: In Besprechungsaufnahmen laeuft haeufig eine
    Kamerakachel mit, die sich NIE beruhigt. Ohne diese Grenze waere die komplette
    Aufnahme eine einzige Serie und lieferte ein einziges Bild vom Ende. Haelt die
    Bewegung so lange an, wird trotzdem ein Bild genommen und die Serie neu begonnen.
    """
    if not treffer:
        return []

    ruhe_dauer = ruhe_abtastungen / fps if fps > 0 else 0.0
    serien: list[float] = []
    start = letzter = treffer[0]
    for t in treffer[1:]:
        if t - letzter > ruhe_dauer:
            serien.append(letzter)  # vorige Serie war beendet
            start = t
        elif dauerbewegung_s > 0 and t - start >= dauerbewegung_s:
            serien.append(t)  # Dauerbewegung: Zwischenstand sichern
            start = t
        letzter = t
    serien.append(letzter)

    out: list[float] = []
    for t in serien:
        if not out or t - out[-1] >= min_gap:
            out.append(t)
    return out


def _ffmpeg_exe() -> str:
    from audioscribe.review.frames import _ffmpeg_exe as exe

    return exe()


def detect_changes(
    video: str | Path,
    *,
    sensitivity: str = DEFAULT_SENSITIVITY,
    fps: float = DEFAULT_FPS,
    min_gap: float = DEFAULT_MIN_GAP,
    max_bilder: int = DEFAULT_MAX_BILDER,
    dauer_s: float | None = None,
    ffmpeg: str | None = None,
    reporter: Reporter | None = None,
) -> list[float]:
    """Liefert die Zeitpunkte (Sekunden), an denen sich der Bildschirm geaendert hat.

    Liest den ffmpeg-Rohstrom in Bloecken exakter Framegroesse; ein kurzer Block bedeutet
    Dateiende. Der Speicherbedarf bleibt damit unabhaengig von der Videolaenge.
    """
    import numpy as np

    schwelle, min_bloecke = SENSITIVITIES.get(sensitivity, SENSITIVITIES[DEFAULT_SENSITIVITY])
    cmd = build_scan_cmd(ffmpeg or _ffmpeg_exe(), video, fps=fps)
    frame_bytes = SCAN_WIDTH * SCAN_HEIGHT
    erwartet = int(dauer_s * fps) if dauer_s and dauer_s > 0 else 0

    treffer: list[float] = []
    vorher = None
    index = 0
    # stderr verwerfen statt abgreifen: sonst kann ffmpeg blockieren, wenn niemand die
    # Fehlerpipe leert, waehrend wir nur stdout lesen.
    proc = subprocess.Popen(  # noqa: S603 - festes Kommando, keine Nutzereingabe
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
    )
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if buf is None or len(buf) < frame_bytes:
                break
            jetzt = block_means(
                np.frombuffer(buf, dtype=np.uint8).reshape(SCAN_HEIGHT, SCAN_WIDTH).astype(np.int16)
            )
            if vorher is not None and changed_blocks(vorher, jetzt, schwelle) >= min_bloecke:
                treffer.append(index / fps)
            vorher = jetzt
            index += 1
            if erwartet and index % 50 == 0:
                emit_progress(100.0 * index / erwartet)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.poll() is None:
            # Bei einem Abbruch im Elternprozess sonst ein ffmpeg, das weiter auf einer
            # mehrere GB grossen Datei rechnet.
            proc.kill()
        proc.wait()

    zeitpunkte = merge_runs(treffer, fps=fps, min_gap=min_gap)
    if reporter:
        reporter.info(
            f"{index} Abtastungen ({sensitivity}), {len(treffer)} Rohtreffer "
            f"-> {len(zeitpunkte)} Bildwechsel"
        )
    if max_bilder > 0 and len(zeitpunkte) > max_bilder:
        # Nie stillschweigend abschneiden: der Nutzer muss erfahren, an welchem Regler
        # er drehen kann.
        if reporter:
            reporter.info(
                f"Auf {max_bilder} Bilder begrenzt (von {len(zeitpunkte)}) - mit "
                "--frame-min-gap oder --frame-sensitivity grob nachjustieren"
            )
        zeitpunkte = zeitpunkte[:max_bilder]
    return zeitpunkte


def shot_filename(bild_id: int, t: float, suffix: str) -> str:
    """Dateiname aus ID UND Zeitstempel, z.B. ``(1, 83.4, '.jpg') -> '0001_00-01-23.jpg'``.

    Die ID ist die Klammer zum Transkript (dort steht ``#0001``) und macht den Namen
    zugleich eindeutig - zwei Wechsel innerhalb derselben Sekunde kollidieren sonst.
    """
    return f"{bild_id:04d}_{format_timecode(t).replace(':', '-')}{suffix}"


def merge_marks(vorhandene: list[Mark], neue: list[Mark]) -> list[Mark]:
    """Ersetzt die automatisch erzeugten Marks, behaelt die von Hand gesetzten.

    ``save_marks`` schreibt die Datei immer komplett neu - ohne diese Zusammenfuehrung
    wuerde ein zweiter Lauf die manuellen Markierungen aus der Review-Oberflaeche
    stillschweigend loeschen.
    """
    manuell = [m for m in vorhandene if m.kind != KIND_AUTO]
    return sorted([*manuell, *neue], key=lambda m: m.t)


def _alte_bilder_loeschen(out_dir: Path, marks: list[Mark]) -> None:
    """Loescht die Bilddateien frueherer automatischer Laeufe (nur unterhalb ``frames/``)."""
    frames_dir = (out_dir / "frames").resolve()
    for mark in marks:
        if mark.kind != KIND_AUTO:
            continue
        pfad = (out_dir / mark.png).resolve()
        # Pfadpruefung wie in review/server.py: nie ausserhalb des Bilderordners loeschen.
        if frames_dir in pfad.parents and pfad.is_file():
            try:
                pfad.unlink()
            except OSError:  # noqa: PERF203 - eine gesperrte Datei darf den Lauf nicht kippen
                pass


def capture_screens(
    video: str | Path,
    out_dir: str | Path,
    *,
    sensitivity: str = DEFAULT_SENSITIVITY,
    bildformat: str = DEFAULT_FORMAT,
    fps: float = DEFAULT_FPS,
    min_gap: float = DEFAULT_MIN_GAP,
    max_bilder: int = DEFAULT_MAX_BILDER,
    dauer_s: float | None = None,
    reporter: Reporter | None = None,
) -> list[Mark]:
    """Erkennt Bildwechsel, sichert je einen Screenshot und schreibt ``marks.json``.

    Liefert die neu erzeugten Marks. Bereits vorhandene manuelle Markierungen bleiben
    erhalten, automatische aus frueheren Laeufen werden samt Bilddatei ersetzt - auch
    dann, wenn dieser Lauf gar keine Wechsel findet (sonst blieben Bilder eines frueheren
    Laufs stehen, die zum neuen Transkript nicht mehr passen).
    """
    out_dir = Path(out_dir)
    ffmpeg = _ffmpeg_exe()
    zeitpunkte = detect_changes(
        video,
        sensitivity=sensitivity,
        fps=fps,
        min_gap=min_gap,
        max_bilder=max_bilder,
        dauer_s=dauer_s,
        ffmpeg=ffmpeg,
        reporter=reporter,
    )
    if not zeitpunkte:
        vorhandene = load_marks(out_dir)
        # Nur schreiben, wenn es etwas aufzuraeumen gibt - kein leeres marks.json anlegen.
        if any(m.kind == KIND_AUTO for m in vorhandene):
            _alte_bilder_loeschen(out_dir, vorhandene)
            save_marks(out_dir, merge_marks(vorhandene, []))
        return []

    suffix, max_breite, qualitaet = FORMATS.get(bildformat, FORMATS[DEFAULT_FORMAT])
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    vorhandene = load_marks(out_dir)
    _alte_bilder_loeschen(out_dir, vorhandene)
    # Nur die BEHALTENEN Marks bestimmen die naechste ID: die automatischen von eben
    # werden ja gerade ersetzt. Wuerde man sie mitzaehlen, waendern die Nummern bei jedem
    # Lauf nach oben (0001-0004, dann 0005-0008 ...), obwohl es dieselben Bilder sind.
    behalten = [m for m in vorhandene if m.kind != KIND_AUTO]
    start_id = max((m.id or 0) for m in behalten) + 1 if behalten else 1
    erstellt = datetime.now().strftime("%Y-%m-%d %H:%M")

    neue: list[Mark] = []
    for versatz, t in enumerate(zeitpunkte):
        bild_id = start_id + versatz
        name = shot_filename(bild_id, t, suffix)
        cmd = build_shot_cmd(
            ffmpeg, video, t, frames_dir / name, max_breite=max_breite, qualitaet=qualitaet
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
        except (OSError, subprocess.CalledProcessError):
            # Ein einzelnes fehlgeschlagenes Standbild darf den Lauf nicht kippen.
            continue
        neue.append(
            Mark(
                t=round(t, 3),
                png=f"frames/{name}",
                note=None,
                created=erstellt,
                id=bild_id,
                kind=KIND_AUTO,
            )
        )

    save_marks(out_dir, merge_marks(vorhandene, neue))
    return neue


def screens_available() -> bool:
    """Ist die Bildanalyse nutzbar? (numpy kommt mit torch, fehlt aber in Minimal-Setups.)"""
    try:
        import numpy  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


__all__ = [
    "DEFAULT_DAUERBEWEGUNG_S",
    "DEFAULT_FORMAT",
    "DEFAULT_FPS",
    "DEFAULT_MAX_BILDER",
    "DEFAULT_MIN_GAP",
    "DEFAULT_SENSITIVITY",
    "FORMATS",
    "KIND_AUTO",
    "SENSITIVITIES",
    "block_means",
    "build_scan_cmd",
    "build_shot_cmd",
    "capture_screens",
    "changed_blocks",
    "detect_changes",
    "merge_marks",
    "merge_runs",
    "screens_available",
    "shot_filename",
]
