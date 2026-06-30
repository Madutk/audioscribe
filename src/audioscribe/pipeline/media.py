"""Video-Unterstuetzung: Audiospur aus einer Videodatei extrahieren (ffmpeg).

Whisper braucht 16-kHz-Mono-Audio; genau das erzeugen wir hier in einem ffmpeg-Lauf
und legen es als WAV in ``work/`` ab (wiederverwendbares Artefakt).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from audioscribe.config import ensure_ffmpeg_on_path, settings
from audioscribe.progress import Reporter

# Container, die wir als Video behandeln (Audiospur wird extrahiert).
VIDEO_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv",
    ".flv", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".ogv",
}
# Reine Audioformate (werden direkt geladen, keine Extraktion noetig).
AUDIO_SUFFIXES = {
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif",
}


def is_video(path: Path) -> bool:
    """True, wenn die Datei an ihrer Endung als Video gilt."""
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def extract_audio(video: Path, reporter: Reporter | None = None) -> Path:
    """Extrahiert die Audiospur als 16-kHz-Mono-WAV nach ``work/`` und liefert den Pfad."""
    video = Path(video)
    ffmpeg = ensure_ffmpeg_on_path()
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    out = settings.work_dir / f"{video.stem}.16k.wav"

    cmd = [
        ffmpeg, "-y", "-i", str(video),
        "-vn",                 # kein Video
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz (Whisper-Eingang)
        "-c:a", "pcm_s16le",   # unkomprimiertes WAV
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise RuntimeError(
            f"Audio-Extraktion aus '{video.name}' fehlgeschlagen "
            f"(hat die Datei eine Tonspur?).\n" + "\n".join(tail)
        )

    if reporter:
        reporter.info(f"Audiospur extrahiert -> work/{out.name}")
    return out
