import json
from pathlib import Path

from audioscribe.export import render_markdown, transcript_to_dict, write_transcript_json
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


def test_transcript_to_dict_structure():
    d = transcript_to_dict(_sample())
    assert d["version"] == 1
    assert d["source"] == "meeting.m4a"
    assert d["num_speakers"] == 2
    assert "source_path" in d  # absoluter Pfad zum Original-Medium (FR-12)
    assert d["paragraphs"][0] == {
        "index": 0,
        "start": 5.0,
        "end": 10.0,
        "speaker": "Sprecher 1",
        "text": "Guten Morgen, fangen wir an.",
    }
    assert d["paragraphs"][1]["index"] == 1
    assert d["paragraphs"][1]["text"] == "Ja, einverstanden."


def test_write_transcript_json_roundtrip(tmp_path):
    out = write_transcript_json(_sample(), tmp_path)
    assert out.name == "transcript.json"
    assert out.parent.name == "meeting"  # <out_dir>/<stem>/transcript.json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["language"] == "de"
    assert len(data["paragraphs"]) == 2
    assert data["paragraphs"][1]["speaker"] == "Sprecher 2"
