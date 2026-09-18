"""Zentrale Konfiguration fuer audioscribe.

Alle Pfade/Modelle an einer Stelle, ueberschreibbar via Umgebungsvariablen
(Prefix ``AUDIOSCRIBE_``) oder einer ``.env`` im Projekt-Root.
"""

from __future__ import annotations

import functools
import os
import shutil
from collections.abc import Callable
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
    # Rohwert: "auto" (CUDA falls verfuegbar, sonst CPU) | "cuda[:N]" | "cpu".
    # Aufloesung erst bei Gebrauch via resolve_device() (kein torch-Import beim Config-Import).
    device: str = field(default_factory=lambda: _env("DEVICE", "auto"))

    # --- Stufe 1+2: Transkription (faster-whisper via WhisperX) ---
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "large-v3"))
    # Rohwert: "auto" -> device-abhaengig (cuda: float16, cpu: int8), s. resolve_compute_type().
    whisper_compute_type: str = field(default_factory=lambda: _env("WHISPER_COMPUTE_TYPE", "auto"))
    # "de" = Deutsch erzwingen (kein Sprach-Detection-Overhead); "auto" = erkennen lassen.
    whisper_language: str = field(default_factory=lambda: _env("WHISPER_LANGUAGE", "de"))
    batch_size: int = field(default_factory=lambda: int(_env("BATCH_SIZE", "8")))

    # --- Stufe 3: Wort-Alignment (wav2vec2) ---
    enable_alignment: bool = field(default_factory=lambda: _flag("ALIGNMENT", "1"))

    # --- maschinenlesbare Fortschrittszeilen ("[Fortschritt] 42.5%") ---
    # Standardmaessig AUS, damit die Terminal-Ausgabe ruhig bleibt; die Browser-Oberflaeche
    # setzt AUDIOSCRIBE_PROGRESS=1 in der Umgebung des Kindprozesses (ui/jobs.child_env).
    emit_progress: bool = field(default_factory=lambda: _flag("PROGRESS", "0"))

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

    # --- Bildwechsel-Erkennung fuer Bildschirmaufnahmen (FR-23..FR-27) ---
    # Standardmaessig AUS: die Analyse dekodiert das komplette Video (grob ein Achtel der
    # Spieldauer) und ist nur bei Bildschirmaufnahmen sinnvoll.
    enable_screens: bool = field(default_factory=lambda: _flag("SCREENS", "0"))
    # Namen aus pipeline.screens.SENSITIVITIES bzw. .FORMATS; dort liegen auch die Defaults.
    # Hier bewusst als Rohtext gehalten - config darf nicht von der Pipeline abhaengen.
    screen_sensitivity: str = field(default_factory=lambda: _env("SCREEN_SENSITIVITY", "mittel"))
    screen_format: str = field(default_factory=lambda: _env("SCREEN_FORMAT", "jpg-1600"))
    # Abtastungen je Sekunde: 1 halbiert die Analysezeit, verpasst aber kurze Einblendungen.
    screen_fps: float = field(default_factory=lambda: float(_env("SCREEN_FPS", "2")))
    # Mindestabstand zwischen zwei Bildern (Sekunden) - gegen Bilderfluten bei Videos.
    screen_min_gap: float = field(default_factory=lambda: float(_env("SCREEN_MIN_GAP", "4")))

    # --- KI-Analyse per Claude-Agent (PRD §16, FR-28..34) ---
    # Modell fuer Claude Code; Aliase wie "opus"/"sonnet" funktionieren ebenfalls.
    agent_model: str = field(default_factory=lambda: _env("AGENT_MODEL", "claude-opus-5"))
    # Hier wird rekursiv nach SKILL.md gesucht (auch synced/<konto>/<skill>/).
    agent_skills_dir: Path = field(
        default_factory=lambda: Path(
            _env("AGENT_SKILLS_DIR", str(Path.home() / ".claude" / "skills"))
        ).expanduser()
    )
    # Vorauswahl (kommagetrennt); fehlende Skills werden in der Vorauswahl uebergangen.
    agent_skills: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip()
            for s in _env(
                "AGENT_SKILLS",
                "transkript-normalisierung,prozessrekonstruktion,prozessdoku-qs,"
                "arbeitsanweisung-ableiten",
            ).split(",")
            if s.strip()
        )
    )
    # prozessbild.png/.svg aus dem Mermaid-Diagramm (FR-35); Browser-Override ueber
    # AUDIOSCRIBE_BROWSER (wird direkt in agent/prozessbild.find_browser gelesen).
    agent_prozessbild: bool = field(default_factory=lambda: _flag("AGENT_PROZESSBILD", "1"))
    agent_max_turns: int | None = field(default_factory=lambda: _opt_int("AGENT_MAX_TURNS"))
    agent_output_dir: Path = field(
        default_factory=lambda: Path(_env("AGENT_OUTPUT_DIR", str(PROJECT_ROOT / "analysen")))
    )

    def ensure_dirs(self) -> None:
        for d in (self.input_dir, self.output_dir, self.work_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()


@functools.lru_cache(maxsize=1)
def cuda_available() -> bool:
    """Probet CUDA via torch (lazy + gecacht); False auch bei fehlendem torch/CPU-Build."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 - kein torch / kaputte Installation -> kein CUDA
        return False


def resolve_device(raw: str, cuda_check: Callable[[], bool] = cuda_available) -> str:
    """Loest den Rohwert aus ``settings.device`` in ein konkretes Geraet auf.

    ``"auto"`` -> ``"cuda"`` falls verfuegbar, sonst ``"cpu"``. Explizites
    ``"cpu"``/``"cuda[:N]"`` bleibt unveraendert (bei ``cpu`` ohne CUDA-Probe);
    explizit erzwungenes CUDA ohne verfuegbares CUDA ist ein harter Fehler.
    """
    value = raw.strip().lower()
    if value == "auto":
        return "cuda" if cuda_check() else "cpu"
    if value.startswith("cuda") and not cuda_check():
        raise RuntimeError(
            f"Geraet '{raw}' angefordert, aber CUDA ist nicht verfuegbar. "
            "Optionen: '--device auto' (automatischer CPU-Fallback), '--device cpu', "
            "oder Installation pruefen mit 'audioscribe doctor' ('uv sync --extra cu124')."
        )
    return value


def resolve_compute_type(raw: str, device: str) -> str:
    """Loest ``"auto"`` device-abhaengig auf: cuda -> float16, cpu -> int8.

    Explizite Werte gewinnen. (CTranslate2 unterstuetzt kein float16 auf CPU.)
    """
    if raw.strip().lower() != "auto":
        return raw
    return "float16" if device.startswith("cuda") else "int8"


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
