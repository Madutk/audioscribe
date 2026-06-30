"""Framegenaue Standbild-Extraktion aus dem Originalvideo (FR-14).

Nutzt das von ``imageio-ffmpeg`` gebuendelte ffmpeg-Binary (kein System-ffmpeg noetig).
``-ss`` VOR ``-i`` seekt schnell zum nahen Keyframe und dekodiert dann exakt bis zur
Zielzeit – bei aktuellem ffmpeg schnell UND framegenau (PRD §13.8: Genauigkeit vor Tempo).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from audioscribe.models import format_timecode


def frame_filename(t: float) -> str:
    """Stabiler Dateiname aus dem Zeitstempel, z.B. ``83.4 -> '00-01-23.png'``."""
    return format_timecode(t).replace(":", "-") + ".png"


def build_extract_cmd(ffmpeg: str, video: str | Path, t: float, out_png: str | Path) -> list[str]:
    """Baut die ffmpeg-Argumentliste fuer EIN framegenaues PNG (rein, testbar)."""
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, t):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(out_png),
    ]


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_frame(
    video: str | Path, t: float, out_png: str | Path, *, ffmpeg: str | None = None
) -> Path:
    """Extrahiert das Standbild bei Sekunde ``t`` nach ``out_png`` und liefert den Pfad."""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_extract_cmd(ffmpeg or _ffmpeg_exe(), Path(video), t, out_png)
    subprocess.run(cmd, check=True, capture_output=True)
    return out_png
