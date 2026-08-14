import json
from pathlib import Path

import pytest

from audioscribe.review.frames import build_extract_cmd, frame_filename
from audioscribe.review.marks import Mark, load_marks, save_marks
from audioscribe.review.merge import render_markdown_with_marks


# --- FR-14: Frame-Dateiname & ffmpeg-Kommando ---


def test_frame_filename_from_timestamp():
    assert frame_filename(83.4) == "00-01-23.png"
    assert frame_filename(0) == "00-00-00.png"


def test_build_extract_cmd_single_accurate_frame():
    cmd = build_extract_cmd("ffmpeg", Path("v.mp4"), 83.4, Path("out/00-01-23.png"))
    assert cmd[0] == "ffmpeg"
    # genau EIN Frame
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    # -ss steht VOR -i (schneller + framegenauer Seek)
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "83.400"
    assert cmd[-1].endswith("00-01-23.png")


def test_build_extract_cmd_clamps_negative_time():
    cmd = build_extract_cmd("ffmpeg", Path("v.mp4"), -1.5, Path("o.png"))
    assert cmd[cmd.index("-ss") + 1] == "0.000"


# --- FR-15: marks.json Sidecar ---


def test_marks_roundtrip_sorted(tmp_path):
    save_marks(tmp_path, [
        Mark(t=12.0, png="frames/00-00-12.png"),
        Mark(t=3.5, png="frames/00-00-03.png", note="Folie 1"),
    ])
    loaded = load_marks(tmp_path)
    assert [m.t for m in loaded] == [3.5, 12.0]  # nach t sortiert
    assert loaded[0].note == "Folie 1"
    raw = json.loads((tmp_path / "marks.json").read_text(encoding="utf-8"))
    assert raw[0]["png"] == "frames/00-00-03.png"
    assert "note" in raw[0] and "created" in raw[0]


def test_load_marks_missing_returns_empty(tmp_path):
    assert load_marks(tmp_path) == []


# --- FR-18: Merge-Export (Einfuege-Regel) ---


def _data():
    return {
        "source": "meeting.mp4",
        "duration_s": 30.0,
        "language": "de",
        "num_speakers": 2,
        "model": "large-v3",
        "created": "2026-06-30 15:40",
        "paragraphs": [
            {"index": 0, "start": 5.0, "end": 10.0, "speaker": "Sprecher 1", "text": "Erster Absatz."},
            {"index": 1, "start": 11.0, "end": 14.0, "speaker": "Sprecher 2", "text": "Zweiter Absatz."},
        ],
    }


def test_merge_inserts_image_after_nearest_paragraph():
    md = render_markdown_with_marks(_data(), [Mark(t=12.0, png="frames/00-00-12.png")])
    i_p1 = md.index("Erster Absatz.")
    i_p2 = md.index("Zweiter Absatz.")
    i_img = md.index("(frames/00-00-12.png)")
    assert i_p1 < i_p2 < i_img  # Bild hinter Absatz 2 (start 11 <= 12)


def test_merge_image_before_first_paragraph_attaches_to_first():
    md = render_markdown_with_marks(_data(), [Mark(t=1.0, png="frames/00-00-01.png")])
    i_p1 = md.index("Erster Absatz.")
    i_img = md.index("(frames/00-00-01.png)")
    i_p2 = md.index("Zweiter Absatz.")
    assert i_p1 < i_img < i_p2


def test_merge_header_and_note_and_trailing_newline():
    md = render_markdown_with_marks(_data(), [Mark(t=12.0, png="frames/x.png", note="Quartalszahlen")])
    assert md.startswith("# Transkript: meeting.mp4")
    assert "| Sprecher | 2 |" in md
    assert "Markierter Bildschirm 00:00:12 – Quartalszahlen" in md
    assert md.endswith("\n")


def test_merge_empty_transcript_still_lists_images():
    data = {**_data(), "paragraphs": []}
    md = render_markdown_with_marks(data, [Mark(t=5.0, png="frames/00-00-05.png")])
    assert "(frames/00-00-05.png)" in md


# --- Regression: POST /api/mark nimmt einen JSON-Body ---


def test_api_mark_liest_json_body(tmp_path):
    """MarkIn wird erst in create_app() definiert; mit 'from __future__ import annotations'
    fand FastAPI die Klasse nicht und erwartete den Body als Query-Parameter (422)."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from audioscribe.review.server import create_app

    (tmp_path / "transcript.json").write_text(
        json.dumps({"source_path": str(tmp_path / "fehlt.mp4"), "paragraphs": []}),
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/mark", json={"t": 1.0, "note": "hallo"})
    # 404 = Video fehlt (erwartet); entscheidend ist: KEIN 422 wegen des Bodys.
    assert response.status_code != 422
