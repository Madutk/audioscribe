"""Ablage einer Live-Sitzung im Format eines Offline-Laufs (FR-42).

Bewusst dieselben Dateien wie ``run``: die KI-Analyse erkennt den Ordner an
``transkript.md`` und braucht keine Sonderbehandlung.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from audioscribe.export import render_markdown, transcript_to_dict
from audioscribe.models import Segment, TranscriptMeta, TranscriptResult
from audioscribe.pipeline.merge import UNKNOWN, build_paragraphs
from audioscribe.review.exporter import export_annotated

MIC_WAV = "audio/mikrofon.wav"
SYSTEM_WAV = "audio/system.wav"

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
