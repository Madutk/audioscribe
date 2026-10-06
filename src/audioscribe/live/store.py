"""Ablage einer Live-Sitzung im Format eines Offline-Laufs (FR-42).

Bewusst dieselben Dateien wie ``run``: die KI-Analyse erkennt den Ordner an
``transkript.md`` und braucht keine Sonderbehandlung.
"""

from __future__ import annotations

import json
import os
import shutil
import wave
from datetime import datetime
from pathlib import Path

from audioscribe.export import render_markdown, transcript_to_dict
from audioscribe.models import Segment, TranscriptMeta, TranscriptResult
from audioscribe.pipeline.merge import UNKNOWN, build_paragraphs
from audioscribe.review.exporter import export_annotated

MIC_WAV = "audio/mikrofon.wav"
SYSTEM_WAV = "audio/system.wav"
# Spurname der Sitzung -> fertiger Mitschnitt. Nach einer Wiederaufnahme (PRD §21) liegen
# die Teile daneben als ``mikrofon.teil2.wav`` usw., bis ``verbinde_teile`` sie zusammensetzt.
SPUR_WAV = {"mic": MIC_WAV, "system": SYSTEM_WAV}
_SAMPLE_RATE = 16_000  # wie live.track.SAMPLE_RATE (dort hängt numpy dran)
_WAV_KOPF = 44
_BLOCK = 1 << 20

# transkript.md mit k, transcript.json mit c - wie im Offline-Lauf.
_LIVE_COPIES = (
    ("transkript.md", "transkript.live.md"),
    ("transcript.json", "transcript.live.json"),
    ("transkript.txt", "transkript.live.txt"),
)


def render_plain(paragraphs: list) -> str:
    """Reiner Text ohne Zeitstempel und Sprecher (FR-49) - für WER-Vergleiche gegen eine
    Referenz. Ein Absatz je Zeile, wie ``build_paragraphs`` sie schneidet."""
    return "\n".join(p.text.strip() for p in paragraphs if p.text.strip()) + "\n"


def session_name(now: datetime | None = None) -> str:
    return "live-" + (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")


def write_transcript(
    session_dir: Path,
    segments: list[Segment],
    *,
    duration_s: float,
    language: str,
    model: str,
    mode: str,
    sentences_per_timestamp: int = 2,
) -> None:
    """Schreibt ``transkript.md``, ``transkript.txt``, ``transcript.json`` und
    ``transkript.annotiert.md``."""
    session_dir = Path(session_dir)
    paragraphs = build_paragraphs(segments, sentences_per_timestamp)
    (session_dir / "transkript.txt").write_text(render_plain(paragraphs), encoding="utf-8")
    meta = TranscriptMeta(
        source=Path(session_dir.name),
        duration_s=duration_s,
        language=language,
        num_speakers=len({p.speaker for p in paragraphs} - {UNKNOWN}),
        model=model,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    result = TranscriptResult(meta=meta, paragraphs=paragraphs, segments=segments)
    (session_dir / "transkript.md").write_text(render_markdown(result), encoding="utf-8")

    data = transcript_to_dict(result)
    # Kein Video: die Quelle ist der Mitschnitt. "mode" unterscheidet live von nachgeschärft.
    data["source_path"] = str((session_dir / SYSTEM_WAV).resolve())
    data["mode"] = mode
    (session_dir / "transcript.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    export_annotated(session_dir)


def keep_live_copy(session_dir: Path, *, overwrite: bool) -> None:
    """Sichert die Live-Fassung neben dem Transkript (FR-43)."""
    for source, target in _LIVE_COPIES:
        src, dst = Path(session_dir) / source, Path(session_dir) / target
        if src.exists() and (overwrite or not dst.exists()):
            shutil.copyfile(src, dst)


# --- Aufnahme-Teile (Wiederaufnahme, PRD §21) -----------------------------------------


def teil_wav(spur: str, nr: int) -> str:
    """Relativer Pfad des Mitschnitts von Teil ``nr`` (Teil 1 einer frischen Sitzung = Endname)."""
    ziel = Path(SPUR_WAV[spur])
    return f"{ziel.parent.as_posix()}/{ziel.stem}.teil{nr}{ziel.suffix}"


def wav_frames(path: Path) -> int:
    """Samples eines 16-Bit-Mono-Mitschnitts nach Dateigröße - auch mit offenem Kopf.

    ``wave`` trägt die Länge erst beim Schließen ein; nach einem Absturz steht dort 0, die
    Daten liegen aber dahinter (s. ``track.load_wav``).
    """
    try:
        return max(0, (Path(path).stat().st_size - _WAV_KOPF) // 2)
    except OSError:
        return 0


def _kopf_stimmt(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() == wav_frames(path)
    except (OSError, wave.Error, EOFError):
        return False


def verbinde_teile(session_dir: Path) -> list[Path]:
    """Setzt die Aufnahme-Teile je Spur zu EINER WAV mit korrektem Kopf zusammen.

    Invariante: Sample-Position in der fertigen WAV = Sitzungszeit. Jeder Teil beginnt bei
    seinem ``start_sample`` (``sitzung.json``); davor wird mit Stille aufgefüllt - auch wenn
    eine Spur erst im zweiten Teil dazukam. Streamend auf Byte-Ebene, ohne den Mitschnitt in
    den Speicher zu laden. Idempotent: geschrieben wird in eine temporäre Datei und per
    ``os.replace`` getauscht; erst danach wird der Zustand auf einen Teil gesetzt und werden
    die Teil-Dateien entfernt. Bricht es dazwischen ab, baut der nächste Aufruf das Ziel
    einfach neu aus den Teilen. Liefert die geschriebenen Zieldateien.
    """
    from audioscribe.live import journal

    session_dir = Path(session_dir)
    status = journal.lies_status(session_dir)
    teile = sorted(
        (t for t in (status or {}).get("teile") or [] if isinstance(t, dict)),
        key=lambda t: int(t.get("nr") or 0),
    )
    if not teile:
        # Sitzung ohne Zustandsdatei (älterer Stand): höchstens den Kopf reparieren.
        teile = [{"nr": 1, "start_sample": 0, "spuren": dict(SPUR_WAV)}]

    geschrieben: list[Path] = []
    fertig: dict[str, str] = {}
    alt: set[Path] = set()
    for spur, rel in SPUR_WAV.items():
        ziel = session_dir / rel
        quellen = []
        for teil in teile:
            name = (teil.get("spuren") or {}).get(spur)
            if name and (session_dir / name).is_file():
                quellen.append((max(0, int(teil.get("start_sample") or 0)), session_dir / name))
        if not quellen:
            continue
        fertig[spur] = rel
        if len(quellen) == 1 and quellen[0] == (0, ziel) and _kopf_stimmt(ziel):
            continue
        tmp = ziel.with_suffix(".wav.tmp")
        with wave.open(str(tmp), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(_SAMPLE_RATE)
            pos = 0
            for start, pfad in quellen:
                frames = wav_frames(pfad)
                skip = 0
                if start > pos:
                    rest = start - pos
                    while rest > 0:
                        n = min(rest, _BLOCK)
                        out.writeframesraw(bytes(2 * n))
                        rest -= n
                    pos = start
                elif start < pos:
                    skip = min(frames, pos - start)  # Überlappung: nichts doppelt schreiben
                with pfad.open("rb") as src:
                    src.seek(_WAV_KOPF + 2 * skip)
                    rest = frames - skip
                    while rest > 0:
                        daten = src.read(2 * min(rest, _BLOCK))
                        daten = daten[: len(daten) - len(daten) % 2]
                        if not daten:
                            break
                        out.writeframesraw(daten)
                        rest -= len(daten) // 2
                        pos += len(daten) // 2
        os.replace(tmp, ziel)
        geschrieben.append(ziel)
        alt.update(pfad for _, pfad in quellen if pfad != ziel)

    if status is not None and fertig:
        journal.schreibe_status(session_dir, teile=[{"nr": 1, "start_sample": 0, "spuren": fertig}])
    if status is not None and status.get("teile"):
        # Auch nie eingetragene Teil-Dateien (gescheiterter Fortsetzungsversuch) räumen.
        ziele = {session_dir / rel for rel in SPUR_WAV.values()}
        for rel in SPUR_WAV.values():
            ziel = session_dir / rel
            if ziel.parent.is_dir():
                alt.update(p for p in ziel.parent.glob(f"{ziel.stem}.teil*{ziel.suffix}") if p not in ziele)
    for pfad in alt:
        try:
            pfad.unlink()
        except OSError:
            pass
    return geschrieben
