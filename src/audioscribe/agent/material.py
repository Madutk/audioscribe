"""Auftrag eines Analyse-Laufs, Arbeitsordner und Uebernahme des Materials.

Das Material (Transkript, Frames, Markierungen) wird in den Arbeitsordner KOPIERT,
nicht nur referenziert:

* Der Ausgabeordner ist danach in sich vollstaendig - Dokumente, die auf
  ``material/frames/0001_….jpg`` verweisen, funktionieren auch nach einem Umzug.
* Die Skills rufen Skripte auf, die Zwischenstaende NEBEN die Eingabe schreiben
  (z. B. ``transkript.normalisiert.md``). Auf der Kopie landet das im Ausgabeordner
  statt im audioscribe-Ergebnisordner, der unveraendert bleibt (NFR-12).
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Hauptdokument: das annotierte Transkript (mit Bildverweisen) hat Vorrang.
TRANSCRIPT_CANDIDATES: tuple[str, ...] = ("transkript.annotiert.md", "transkript.md")
# Weitere Dateien des Ergebnisordners, die mitgenommen werden (sofern vorhanden).
EXTRA_FILES: tuple[str, ...] = ("transkript.md", "transcript.json", "marks.json")
FRAMES_DIR = "frames"
MATERIAL_DIR = "material"
KONTEXT_DIR = "kontext"

# Textdateien, deren Inhalt direkt in den Auftrag wandert; alles andere (PDF, Bilder,
# Office) wird nur kopiert und per Pfad genannt - der Agent liest es selbst.
_INLINE_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
_INLINE_MAX_BYTES = 200_000


@dataclass(frozen=True)
class Auftrag:
    """Alles, was ein Analyse-Lauf von aussen bekommt."""

    name: str  # Prozessname, z. B. "Rechnungspruefung Kreditoren"
    quelle: Path  # audioscribe-Ergebnisordner (output/<stem>)
    ausgabe: Path  # vom Nutzer gewaehlter Ausgabeordner (Elternordner)
    kontext_text: str = ""
    kontext_dateien: tuple[Path, ...] = ()
    skills: tuple[str, ...] = ()
    model: str | None = None
    max_turns: int | None = None
    bash: bool = True
    resume: str | None = None  # Session-ID fuer eine Fortsetzung (Chat-Vorbereitung)

    @property
    def workspace(self) -> Path:
        """Arbeits- und Ergebnisordner des Laufs: ``<ausgabe>/<slug(name)>``."""
        return Path(self.ausgabe) / slugify(self.name)


def slugify(text: str) -> str:
    """Ordnertauglicher Name: Umlaute ausgeschrieben, nur ``[a-z0-9-]``.

    Laeuft unter Windows und WSL gleich (keine reservierten Zeichen, kein Punkt am
    Ende). Ein leerer Rest faellt auf ``analyse`` zurueck.
    """
    value = text.strip().lower()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        value = value.replace(src, dst)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:80].rstrip("-") or "analyse"


def find_transcript(quelle: Path) -> Path:
    """Das Haupt-Transkript im Ergebnisordner (annotiert bevorzugt).

    Fehlt beides, erklaert die Meldung, womit man es erzeugt.
    """
    for name in TRANSCRIPT_CANDIDATES:
        candidate = Path(quelle) / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Kein Transkript in {quelle} gefunden (erwartet: transkript.md). "
        "Zuerst transkribieren, fuer Bildschirmaufnahmen mit Standbildern: "
        "audioscribe run <video> --frames"
    )


@dataclass(frozen=True)
class Material:
    """Was nach der Uebernahme im Arbeitsordner liegt (Pfade relativ dazu)."""

    transkript: str
    dateien: tuple[str, ...]
    frames: int  # Anzahl Standbilder
    kontext_inline: tuple[tuple[str, str], ...]  # (Dateiname, Inhalt)
    kontext_dateien: tuple[str, ...]  # nur per Pfad genannt


def copy_material(auftrag: Auftrag) -> Material:
    """Kopiert Transkript, Frames und Kontextdateien in den Arbeitsordner."""
    ws = auftrag.workspace
    haupt = find_transcript(auftrag.quelle)
    ziel = ws / MATERIAL_DIR
    ziel.mkdir(parents=True, exist_ok=True)

    dateien: list[str] = []
    for name in dict.fromkeys((haupt.name, *EXTRA_FILES)):
        src = Path(auftrag.quelle) / name
        if src.is_file():
            shutil.copy2(src, ziel / name)
            dateien.append(f"{MATERIAL_DIR}/{name}")

    frames = 0
    src_frames = Path(auftrag.quelle) / FRAMES_DIR
    if src_frames.is_dir():
        dst_frames = ziel / FRAMES_DIR
        if dst_frames.exists():
            shutil.rmtree(dst_frames)  # alte Kopie eines frueheren Laufs ersetzen
        shutil.copytree(src_frames, dst_frames)
        frames = sum(1 for p in dst_frames.iterdir() if p.is_file())

    inline: list[tuple[str, str]] = []
    per_pfad: list[str] = []
    if auftrag.kontext_dateien:
        kdir = ws / KONTEXT_DIR
        kdir.mkdir(parents=True, exist_ok=True)
        for src in auftrag.kontext_dateien:
            src = Path(src).expanduser()
            if not src.is_file():
                raise FileNotFoundError(f"Kontextdatei nicht gefunden: {src}")
            shutil.copy2(src, kdir / src.name)
            rel = f"{KONTEXT_DIR}/{src.name}"
            text = _read_inline(src)
            if text is not None:
                inline.append((rel, text))
            else:
                per_pfad.append(rel)

    return Material(
        transkript=f"{MATERIAL_DIR}/{haupt.name}",
        dateien=tuple(dateien),
        frames=frames,
        kontext_inline=tuple(inline),
        kontext_dateien=tuple(per_pfad),
    )


def _read_inline(path: Path) -> str | None:
    """Inhalt kleiner Textdateien; ``None`` fuer Binaeres oder zu Grosses."""
    if path.suffix.lower() not in _INLINE_SUFFIXES:
        return None
    try:
        if path.stat().st_size > _INLINE_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
