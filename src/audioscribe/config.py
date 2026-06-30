"""Zentrale Konfiguration fuer audioscribe.

Alle Pfade/Modelle an einer Stelle, ueberschreibbar via Umgebungsvariablen
(Prefix ``AUDIOSCRIBE_``) oder einer ``.env`` im Projekt-Root.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimaler .env-Loader (KEY=VALUE), ohne externe Abhaengigkeit.

    Setzt nur Variablen, die noch nicht in der Umgebung stehen.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"AUDIOSCRIBE_{name}", default)


def _flag(name: str, default: str) -> bool:
    return _env(name, default).lower() in ("1", "true", "yes", "on")


def _opt_int(name: str) -> int | None:
    raw = os.environ.get(f"AUDIOSCRIBE_{name}")
    return int(raw) if raw and raw.strip() else None


@dataclass(frozen=True)
class Settings:
    # --- Verzeichnisse ---
    project_root: Path = PROJECT_ROOT
    input_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "input")
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    work_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "work")
    # WSL-natives Cache-Verzeichnis (chmod/+x zuverlaessig; nicht auf /mnt/c).
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "audioscribe")

    # --- Rechen-Backend ---
    device: str = field(default_factory=lambda: _env("DEVICE", "cuda"))

    # --- Stufe 1+2: Transkription (faster-whisper via WhisperX) ---
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "large-v3"))
    whisper_compute_type: str = field(default_factory=lambda: _env("WHISPER_COMPUTE_TYPE", "float16"))
    # "de" = Deutsch erzwingen (kein Sprach-Detection-Overhead); "auto" = erkennen lassen.
    whisper_language: str = field(default_factory=lambda: _env("WHISPER_LANGUAGE", "de"))
    batch_size: int = field(default_factory=lambda: int(_env("BATCH_SIZE", "8")))

    # --- Stufe 3: Wort-Alignment (wav2vec2) ---
    enable_alignment: bool = field(default_factory=lambda: _flag("ALIGNMENT", "1"))

    # --- Ausgabe: Zeitstempel-Granularitaet ---
    # Neuer Zeitstempel alle N Saetze (0 = ganzer Sprecher-Beitrag als ein Block).
    sentences_per_timestamp: int = field(
        default_factory=lambda: int(_env("SENTENCES_PER_TIMESTAMP", "2"))
    )

    # --- Stufe 4: Diarisierung (pyannote) — Kern-Feature, standardmaessig AN ---
    enable_diarization: bool = field(default_factory=lambda: _flag("DIARIZATION", "1"))
    diarization_model: str = field(
        default_factory=lambda: _env("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
    )
    num_speakers: int | None = field(default_factory=lambda: _opt_int("NUM_SPEAKERS"))
    min_speakers: int | None = field(default_factory=lambda: _opt_int("MIN_SPEAKERS"))
    max_speakers: int | None = field(default_factory=lambda: _opt_int("MAX_SPEAKERS"))
    hf_token: str | None = field(
        default_factory=lambda: os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    )

    def ensure_dirs(self) -> None:
        for d in (self.input_dir, self.output_dir, self.work_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()


def ensure_ffmpeg_on_path() -> str:
    """Sorgt dafuer, dass ``ffmpeg`` ueber PATH aufrufbar ist; gibt den Pfad zurueck.

    WhisperX dekodiert Audio per ``ffmpeg``-Subprozess. Auf dieser WSL-Umgebung ist
    kein System-ffmpeg installiert (und ``sudo apt`` braucht ein Passwort), darum
    faellt die Funktion auf das von ``imageio-ffmpeg`` gebuendelte Binary zurueck und
    legt dafuer einen ``ffmpeg``-Wrapper im (WSL-nativen) Cache-Verzeichnis an.
    """
    system = shutil.which("ffmpeg")
    if system:
        return system

    try:
        import imageio_ffmpeg

        binary = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001 - klare Fehlermeldung statt Stacktrace
        raise RuntimeError(
            "ffmpeg nicht gefunden und 'imageio-ffmpeg' nicht verfuegbar. "
            "Installiere ffmpeg (sudo apt install ffmpeg) oder 'uv sync'."
        ) from exc

    bin_dir = settings.cache_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "ffmpeg"
    # Wrapper-Skript statt Symlink: funktioniert unabhaengig vom Dateisystem (auch DrvFs).
    wrapper.write_text(f'#!/bin/sh\nexec "{binary}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    path = os.environ.get("PATH", "")
    if str(bin_dir) not in path.split(os.pathsep):
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{path}"
    return str(wrapper)
