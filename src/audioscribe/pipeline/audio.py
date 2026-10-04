"""Stufe 1 - Audio laden.

WhisperX dekodiert die Eingabe (mp3/m4a/wav/...) per ffmpeg zu 16-kHz-Mono-float32.
Wir geben das so geladene Array an alle weiteren Stufen weiter, damit nicht jede Stufe
neu dekodiert. (Bei Video laeuft ffmpeg zweimal: ``media.extract_audio`` schreibt ein
16-kHz-WAV, das hier billig eingelesen wird - dafuer gibt es bei fehlender Tonspur eine
verstaendliche Meldung statt der rohen ffmpeg-Ausgabe.)
"""

from __future__ import annotations

from pathlib import Path

from audioscribe.config import ensure_ffmpeg_on_path
from audioscribe.progress import Reporter

SAMPLE_RATE = 16_000


def load_audio(path: Path, reporter: Reporter | None = None):
    """Laedt die Audiodatei als float32-Numpy-Array (16 kHz mono) und liefert (array, dauer_s)."""
    import whisperx

    ensure_ffmpeg_on_path()
    audio = whisperx.load_audio(str(path))
    duration = len(audio) / SAMPLE_RATE
    if reporter:
        from audioscribe.models import format_timecode

        reporter.info(f"{path.name}: {format_timecode(duration)} ({duration:.0f}s)")
    return audio, duration
