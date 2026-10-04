"""Reihenfolge der Pipeline-Stufen - ohne Modelle, ffmpeg oder echtes Video."""

from dataclasses import replace

import numpy as np

from audioscribe.pipeline import orchestrator
from audioscribe.review.marks import Mark, save_marks


class _StummerReporter:
    def stage(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


def _vorbereiten(tmp_path, monkeypatch):
    video = tmp_path / "aufnahme.mp4"
    video.write_bytes(b"")
    s = replace(
        orchestrator.settings,
        enable_alignment=False,
        enable_diarization=False,
        enable_screens=True,
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(orchestrator, "settings", s)
    monkeypatch.setattr(orchestrator, "extract_audio", lambda src, rep: src)
    monkeypatch.setattr(orchestrator, "load_audio", lambda p, rep: (np.zeros(16), 12.0))
    monkeypatch.setattr(
        orchestrator,
        "transcribe",
        lambda audio, rep: {
            "language": "de",
            "segments": [{"start": 0.0, "end": 2.0, "text": "Hallo Welt."}],
        },
    )
    return video, tmp_path / "out" / "aufnahme"


def test_transkript_liegt_vor_der_bildwechsel_erkennung_auf_der_platte(tmp_path, monkeypatch):
    """Ein Abbruch im langen Video-Scan darf die fertige Transkription nicht kosten."""
    video, ziel = _vorbereiten(tmp_path, monkeypatch)
    gesehen = {}

    def fake_erkennung(src, ziel_dir, dauer, rep):
        gesehen["md"] = (ziel_dir / "transkript.md").is_file()
        gesehen["json"] = (ziel_dir / "transcript.json").is_file()
        return []

    monkeypatch.setattr(orchestrator, "_erkenne_bildwechsel", fake_erkennung)
    orchestrator.run_pipeline(video, output_dir=tmp_path / "out", reporter=_StummerReporter())

    assert gesehen == {"md": True, "json": True}


def test_ohne_marks_verschwindet_die_alte_annotierte_fassung(tmp_path, monkeypatch):
    video, ziel = _vorbereiten(tmp_path, monkeypatch)
    ziel.mkdir(parents=True)
    alt = ziel / "transkript.annotiert.md"
    alt.write_text("veraltet", encoding="utf-8")
    monkeypatch.setattr(orchestrator, "_erkenne_bildwechsel", lambda *a: [])

    orchestrator.run_pipeline(video, output_dir=tmp_path / "out", reporter=_StummerReporter())

    assert not alt.exists()


def test_manuelle_marks_werden_neu_annotiert(tmp_path, monkeypatch):
    """Auch ohne neue Auto-Bilder: die annotierte Fassung folgt dem neuen Transkript."""
    video, ziel = _vorbereiten(tmp_path, monkeypatch)
    ziel.mkdir(parents=True)
    save_marks(ziel, [Mark(t=1.0, png="frames/00-00-01.png", note="von Hand")])
    (ziel / "transkript.annotiert.md").write_text("veraltet", encoding="utf-8")
    monkeypatch.setattr(orchestrator, "_erkenne_bildwechsel", lambda *a: [])

    orchestrator.run_pipeline(video, output_dir=tmp_path / "out", reporter=_StummerReporter())

    text = (ziel / "transkript.annotiert.md").read_text(encoding="utf-8")
    assert "veraltet" not in text
    assert "Hallo Welt." in text
