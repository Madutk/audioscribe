"""Befunde aus dem Pipeline-Review (Punkte 4-10) - ohne Modelle und ohne echtes Video."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest

from audioscribe.pipeline import diarize, media, screens
from audioscribe.pipeline.merge import _count_sentences
from audioscribe.pipeline.transcribe_mlx import speech_windows

R = 16_000


# --- media.extract_audio ---


@pytest.fixture
def fake_ffmpeg_run(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "settings", replace(media.settings, work_dir=tmp_path / "work"))
    monkeypatch.setattr(media, "ensure_ffmpeg_on_path", lambda: "ffmpeg")
    aufrufe: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        aufrufe.append((cmd, kwargs))
        with open(cmd[-1], "wb") as f:
            f.write(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    return aufrufe


def test_extract_audio_liest_kein_stdin_und_dekodiert_tolerant(fake_ffmpeg_run, tmp_path):
    media.extract_audio(tmp_path / "Łódź.mp4")
    cmd, kwargs = fake_ffmpeg_run[0]
    assert "-nostdin" in cmd
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["errors"] == "replace"


def test_gleichnamige_videos_teilen_kein_wav(fake_ffmpeg_run, tmp_path):
    a = media.extract_audio(tmp_path / "eins" / "meeting.mp4")
    b = media.extract_audio(tmp_path / "zwei" / "meeting.mp4")
    assert a != b
    assert a.name.endswith(".16k.wav") and a.name.startswith("meeting.")


def test_fehlgeschlagene_extraktion_hinterlaesst_kein_wav(tmp_path, monkeypatch):
    work = tmp_path / "work"
    monkeypatch.setattr(media, "settings", replace(media.settings, work_dir=work))
    monkeypatch.setattr(media, "ensure_ffmpeg_on_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "no audio stream"),
    )
    with pytest.raises(RuntimeError, match="Tonspur"):
        media.extract_audio(tmp_path / "stumm.mp4")
    assert list(work.iterdir()) == []


# --- diarize: hook nur, wenn die Pipeline ihn kennt ---


class _MitHook:
    def apply(self, file, num_speakers=None, hook=None):
        pass


class _OhneHook:
    def apply(self, file, num_speakers=None):
        pass


class _MitKwargs:
    def apply(self, file, **kwargs):
        pass


def test_hook_erkennung_per_signatur():
    assert diarize._akzeptiert_hook(_MitHook())
    assert not diarize._akzeptiert_hook(_OhneHook())
    assert diarize._akzeptiert_hook(_MitKwargs())
    assert not diarize._akzeptiert_hook(object())


# --- screens.detect_changes: Exit-Code und Fortschritt ---


def _python_als_ffmpeg(monkeypatch, code: str):
    monkeypatch.setattr(screens, "build_scan_cmd", lambda *a, **k: [sys.executable, "-c", code])


def test_gescheiterter_scan_ist_kein_ohne_wechsel(monkeypatch):
    _python_als_ffmpeg(monkeypatch, "import sys; sys.stderr.write('kein Videostream'); sys.exit(1)")
    with pytest.raises(RuntimeError, match="kein Videostream"):
        screens.detect_changes("v.mp4", ffmpeg="ffmpeg")


def _frames_code(anzahl: int) -> str:
    groesse = screens.SCAN_WIDTH * screens.SCAN_HEIGHT
    return f"import sys; sys.stdout.buffer.write(bytes({groesse}) * {anzahl})"


def test_sauberer_scan_ohne_wechsel_liefert_leer(monkeypatch):
    _python_als_ffmpeg(monkeypatch, _frames_code(10))
    assert screens.detect_changes("v.mp4", ffmpeg="ffmpeg") == []


@pytest.mark.parametrize("aktiv, erwartet", [(False, 0), (True, 2)])
def test_fortschritt_nur_wenn_eingeschaltet(monkeypatch, aktiv, erwartet):
    _python_als_ffmpeg(monkeypatch, _frames_code(100))
    monkeypatch.setattr(screens, "settings", replace(screens.settings, emit_progress=aktiv))
    gemeldet: list[float] = []
    monkeypatch.setattr(screens, "emit_progress", gemeldet.append)
    screens.detect_changes("v.mp4", ffmpeg="ffmpeg", fps=2, dauer_s=50)
    assert len(gemeldet) == erwartet


# --- transcribe_mlx.speech_windows ---


def test_fenster_ueberlappen_nicht():
    # Zwei Spannen 0,3 s auseinander, das erste Fenster ist voll: die Polsterung der
    # zweiten darf nicht in das erste Fenster zurueckreichen.
    spans = [(0, 29 * R), (int(29.3 * R), 35 * R)]
    win = speech_windows(spans, 60 * R, pad_s=0.3, rate=R)
    for (_, ende), (anfang, _) in zip(win, win[1:]):
        assert anfang >= ende


def test_lange_spanne_wird_an_der_leisesten_stelle_geschnitten():
    audio = np.full(60 * R, 0.5, dtype=np.float32)
    audio[27 * R : int(27.2 * R)] = 0.0  # Atempause bei 27 s
    win = speech_windows([(0, 60 * R)], 60 * R, pad_s=0.0, rate=R, audio=audio)
    assert 27 * R <= win[0][1] <= int(27.2 * R)
    assert win[1][0] == win[0][1]


def test_ohne_audio_bleibt_der_harte_schnitt():
    win = speech_windows([(0, 45 * R)], 45 * R, pad_s=0.0, rate=R)
    assert win == [(0, 30 * R), (30 * R, 45 * R)]


# --- merge._count_sentences ---


@pytest.mark.parametrize(
    "text, erwartet",
    [
        ("am 4. Oktober haben wir 10.000 Euro.", 1),
        ("Termin ist der 4.10.2026.", 1),
        ("z.B. das hier, d.h. jenes.", 1),
        ("Das ist bzw. war so. Wirklich?", 2),
        ("Hallo. Welt! Wie geht's? Gut…", 4),
        ("Das Jahr 2026.", 1),
    ],
)
def test_satzende_zaehlt_keine_ordinalzahlen_und_abkuerzungen(text, erwartet):
    assert _count_sentences(text) == erwartet
