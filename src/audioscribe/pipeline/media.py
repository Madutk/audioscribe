"""Video-Unterstuetzung: Audiospur aus einer Videodatei extrahieren (ffmpeg).

Whisper braucht 16-kHz-Mono-Audio; genau das erzeugen wir hier in einem ffmpeg-Lauf
und legen es als WAV in ``work/`` ab. Die Datei ist ein Zwischenprodukt je Lauf: der
Orchestrator loescht sie, sobald das Audio geladen ist.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
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
    """Extrahiert die Audiospur als 16-kHz-Mono-WAV nach ``work/`` und liefert den Pfad.

    Der Dateiname ist je Aufruf eindeutig: zwei gleichnamige Videos aus verschiedenen
    Ordnern (oder zwei parallele Laeufe) ueberschreiben sich sonst gegenseitig das WAV.
    Aufraeumen ist Sache des Aufrufers.
    """
    video = Path(video)
    ffmpeg = ensure_ffmpeg_on_path()
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f"{video.stem}.", suffix=".16k.wav", dir=settings.work_dir)
    os.close(fd)
    out = Path(name)

    cmd = [
        ffmpeg, "-y", "-nostdin", "-i", str(video),
        "-vn",                 # kein Video
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz (Whisper-Eingang)
        "-c:a", "pcm_s16le",   # unkomprimiertes WAV
        str(out),
    ]
    # stdin=DEVNULL wie in _run_probe (sonst blockiert ffmpeg im Serverprozess);
    # errors="replace": ffmpeg schreibt UTF-8, Windows dekodiert sonst mit cp1252 und
    # scheitert an Dateinamen wie 'Łódź.mp4', obwohl die Extraktion geklappt hat.
    proc = subprocess.run(  # noqa: S603 - festes Kommando
        cmd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL
    )
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise RuntimeError(
            f"Audio-Extraktion aus '{video.name}' fehlgeschlagen "
            f"(hat die Datei eine Tonspur?).\n" + "\n".join(tail)
        )

    if reporter:
        reporter.info(f"Audiospur extrahiert -> work/{out.name}")
    return out


# "  Duration: 00:06:58.97, start: 0.000000, bitrate: 4713 kb/s"
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def parse_ffmpeg_duration(text: str) -> float | None:
    """Liest die Laufzeit aus einer ffmpeg-Ausgabe; ``None``, wenn keine drinsteht.

    ``Duration: N/A`` ist ein realer Fall (MPEG-TS und manche FLV/MKV ohne Dauer-Feld)
    und liefert korrekt ``None``.
    """
    match = _DURATION_RE.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def probe_duration(media: Path, *, timeout: float = 20.0) -> float | None:
    """Laufzeit einer Medien-Datei in Sekunden, ohne sie zu dekodieren.

    Nutzt ``ffprobe``, wenn vorhanden (eine saubere Zahl), sonst ``ffmpeg -i`` und die
    ``Duration:``-Zeile. ``ffprobe`` gehoert NICHT zu den Abhaengigkeiten - das von
    ``imageio-ffmpeg`` gebuendelte Paket enthaelt nur ``ffmpeg``.

    Der Exit-Code wird bewusst ignoriert: ``ffmpeg -i`` ohne Ausgabedatei endet je nach
    Version mit 0 oder ungleich 0, und bei kaputter Eingabe mit 183. Nur der Text zaehlt.
    ``None`` heisst "Laufzeit unbekannt" - **kein** Gueltigkeitstest fuer die Datei.
    """
    media = Path(media)
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(media),
        ]
        out = _run_probe(cmd, timeout)
        if out is not None:
            try:
                value = float(out[0].strip())
            except (ValueError, IndexError):
                value = 0.0
            if value > 0:
                return value

    try:
        ffmpeg = ensure_ffmpeg_on_path()
    except RuntimeError:
        return None
    out = _run_probe([ffmpeg, "-hide_banner", "-nostdin", "-i", str(media)], timeout)
    return parse_ffmpeg_duration(out[0] + out[1]) if out is not None else None


def _run_probe(cmd: list[str], timeout: float) -> tuple[str, str] | None:
    """Fuehrt ein Probe-Kommando aus und liefert ``(stdout, stderr)`` oder ``None``.

    ``stdin=DEVNULL``: ffmpeg liest sonst von stdin und blockiert im Serverprozess.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - festes Kommando, Pfad kommt aus scan_media
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout or "", proc.stderr or ""
