"""Gemeinsame Datenstrukturen der Transkriptions-Pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def format_timecode(seconds: float) -> str:
    """Sekunden -> ``HH:MM:SS``."""
    s = int(round(max(0.0, seconds)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


@dataclass
class Word:
    start: float | None
    end: float | None
    text: str
    speaker: str | None = None


@dataclass
class Segment:
    """Ein zusammenhaengendes Transkript-Segment (Whisper-/WhisperX-Granularitaet)."""

    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[Word] = field(default_factory=list)


@dataclass
class Paragraph:
    """Aufeinanderfolgende Segmente desselben Sprechers, zu einem Absatz vereint (FR-5)."""

    start: float
    end: float
    speaker: str
    text: str


@dataclass
class TranscriptMeta:
    source: Path
    duration_s: float
    language: str
    num_speakers: int
    model: str
    created: str | None = None


@dataclass
class TranscriptResult:
    meta: TranscriptMeta
    paragraphs: list[Paragraph]
    segments: list[Segment]
    output_path: Path | None = None
