from pathlib import Path

from audioscribe.export import render_markdown
from audioscribe.models import Paragraph, TranscriptMeta, TranscriptResult


def _sample() -> TranscriptResult:
    meta = TranscriptMeta(
        source=Path("meeting.m4a"),
        duration_s=83,
        language="de",
        num_speakers=2,
        model="large-v3",
        created="2026-06-30 09:00",
    )
    paras = [
        Paragraph(5.0, 10.0, "Sprecher 1", "Guten Morgen, fangen wir an."),
        Paragraph(11.0, 14.0, "Sprecher 2", "Ja, einverstanden."),
    ]
    return TranscriptResult(meta=meta, paragraphs=paras, segments=[])


def test_render_markdown_has_header_and_lines():
    md = render_markdown(_sample())
    assert md.startswith("# Transkript: meeting.m4a")
    assert "| Sprecher | 2 |" in md
    assert "| Laenge | 00:01:23 |" in md
    assert "| Modell | large-v3 (WhisperX) |" in md
    assert "**[00:00:05] Sprecher 1:** Guten Morgen, fangen wir an." in md
    assert "**[00:00:11] Sprecher 2:** Ja, einverstanden." in md


def test_render_markdown_ends_with_newline():
    md = render_markdown(_sample())
    assert md.endswith("\n")
