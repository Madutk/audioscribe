"""Reine Logik der Stapel-Oberflaeche: Medien finden, CLI-Aufruf bauen, Ausgabe deuten.

Bewusst frei von fastapi/torch-Importen, damit die Unit-Tests ohne optionale Pakete
und ohne Modell-Downloads laufen (gleiche Trennung wie ``review.frames`` vs.
``review.server``).

**Warum je Datei ein Subprozess und nicht direkt ``run_pipeline()``?**

1. ``compat.ensure_native_libs()`` startet den Prozess im CUDA-Pfad per ``os.execv``
   neu (cuDNN-Bootstrap) - das wuerde den laufenden Webserver ersetzen.
2. ``config.settings`` ist ein beim Import eingefrorenes Dataclass; die CLI setzt die
   Optionen ueber ``AUDIOSCRIBE_*``-Umgebungsvariablen VOR dem Config-Import. In einem
   langlebigen Server ist die Config laengst geladen - pro Job wechselnde Modelle,
   Sprachen oder Geraete waeren in-process nicht moeglich.

Ein Subprozess pro Datei loest beides und isoliert ausserdem Abstuerze: eine kaputte
Datei kippt nur ihren eigenen Lauf, nicht den ganzen Stapel.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from audioscribe.pipeline.media import AUDIO_SUFFIXES, VIDEO_SUFFIXES

# Alles, was die Pipeline verdauen kann (Video -> Audiospur wird extrahiert).
MEDIA_SUFFIXES: set[str] = VIDEO_SUFFIXES | AUDIO_SUFFIXES

# Zwischenprodukt von ``pipeline.media.extract_audio`` - nie als Eingabe anbieten.
_ARTEFACT_SUFFIX = ".16k.wav"

# Auswahl fuer die Oberflaeche; die CLI akzeptiert daneben jeden faster-whisper-Namen.
WHISPER_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
)

# Sprachvorschlaege der Oberflaeche ('auto' = erkennen lassen).
LANGUAGES: tuple[str, ...] = ("de", "en", "auto")

DEVICES: tuple[str, ...] = ("auto", "cuda", "cpu")

# Bildwechsel-Erkennung: die Namen stammen aus pipeline.screens (SENSITIVITIES/FORMATS),
# werden hier aber bewusst wiederholt - die Oberflaeche darf die Pipeline nicht importieren
# (das zoege torch & Co. in den Webserver-Prozess).
SENSITIVITIES: tuple[str, ...] = ("grob", "mittel", "fein")
FRAME_FORMATS: tuple[str, ...] = ("jpg-1600", "jpg-1280", "png")


@dataclass(frozen=True)
class JobOptions:
    """Die in der Oberflaeche einstellbaren Optionen eines Stapellaufs."""

    input_dir: Path
    output_dir: Path
    model: str = "large-v3"
    language: str = "de"
    device: str = "auto"
    diarize: bool = True
    frames: bool = False
    frame_sensitivity: str = "mittel"
    frame_format: str = "jpg-1600"


def scan_media(folder: Path) -> list[Path]:
    """Alle unterstuetzten Medien direkt in ``folder`` (nicht rekursiv), alphabetisch.

    Versteckte Dateien und die von der Pipeline erzeugten ``*.16k.wav``-Artefakte
    werden uebersprungen. Einzelne unlesbare Eintraege ebenfalls: unter ``/mnt/c``
    liegen Windows-Systemdateien (``DumpStack.log.tmp``, ``pagefile.sys``), auf die
    ``stat()`` mit "Permission denied" antwortet - der Ordner als Ganzes ist aber
    lesbar und darf deswegen nicht am ersten solchen Eintrag scheitern.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {folder}")

    found: list[Path] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name.lower().endswith(_ARTEFACT_SUFFIX):
                continue
            if Path(name).suffix.lower() not in MEDIA_SUFFIXES:
                continue
            try:
                if entry.is_file():
                    found.append(Path(entry.path))
            except OSError:  # keine Berechtigung / kaputter Symlink -> ueberspringen
                continue
    return sorted(found, key=lambda p: p.name.casefold())


def select_files(folder: Path, names: Sequence[str]) -> list[Path]:
    """Die angefragten Dateinamen, geschnitten mit dem tatsaechlichen Ordnerinhalt.

    ``scan_media`` bleibt die Autoritaet: ein manipulierter Request kann so nicht aus dem
    Eingangsordner ausbrechen (``../``, ``unter/x.mp3``, absolute Pfade), und die
    bestehende Filterung (versteckt, ``*.16k.wav``) samt Sortierung bleibt erhalten.
    """
    wanted = set(names)
    return [media for media in scan_media(folder) if media.name in wanted]


def transcript_path(media: Path, output_dir: Path) -> Path:
    """Wo das Transkript dieser Datei landet - Layout aus ``export.write_markdown``."""
    return Path(output_dir) / Path(media).stem / "transkript.md"


def is_done(media: Path, output_dir: Path) -> bool:
    """True, wenn im Ausgangsordner bereits ein Transkript dieser Datei liegt."""
    return transcript_path(media, output_dir).exists()


def cli_prefix(python: str | None = None) -> list[str]:
    """Kommando-Praefix fuer einen CLI-Aufruf im *selben* venv.

    Bevorzugt das Konsolen-Skript (exakt das, was der Nutzer von Hand aufruft; es
    ueberlebt auch den ``os.execv``-Neustart des cuDNN-Bootstraps unveraendert),
    faellt sonst auf ``python -m audioscribe.cli`` zurueck.

    Bewusst NICHT ueber ``uv run``: das wuerde die venv des laufenden Servers neu
    synchronisieren und dabei das Rechen-Backend austauschen koennen (s. README).
    """
    python = python or sys.executable
    script = Path(python).parent / "audioscribe"
    if script.exists():
        return [str(script)]
    return [python, "-m", "audioscribe.cli"]


def build_argv(media: Path, opts: JobOptions, *, prefix: Sequence[str] | None = None) -> list[str]:
    """Baut den vollstaendigen ``audioscribe run``-Aufruf fuer eine Datei."""
    argv = list(prefix if prefix is not None else cli_prefix())
    argv += [
        "run",
        str(Path(media)),
        "--output",
        str(Path(opts.output_dir)),
        "--model",
        opts.model,
        "--language",
        opts.language,
        "--device",
        opts.device,
    ]
    if not opts.diarize:
        argv.append("--no-diarize")
    if opts.frames:
        # Die Feinparameter (--frame-fps, --frame-min-gap) bleiben der Kommandozeile
        # vorbehalten; die Oberflaeche setzt nur die beiden Auswahlfelder.
        argv += [
            "--frames",
            "--frame-sensitivity",
            opts.frame_sensitivity,
            "--frame-format",
            opts.frame_format,
        ]
    return argv


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Umgebung des Subprozesses: ungepufferte Ausgabe, UTF-8.

    ``PYTHONUNBUFFERED`` statt ``-u``: Der cuDNN-Bootstrap baut die Kommandozeile per
    ``os.execv`` aus ``sys.argv`` neu und wuerde ein ``-u`` dabei verlieren - die
    Umgebung ueberlebt den Neustart dagegen.
    """
    env = dict(base if base is not None else os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Feinfortschritt anfordern (config.settings.emit_progress). Bewusst ueber die
    # Umgebung statt ueber ein CLI-Flag: das ueberlebt den os.execv-Neustart des
    # cuDNN-Bootstraps zuverlaessig, eine Kommandozeilen-Option nur zufaellig.
    env["AUDIOSCRIBE_PROGRESS"] = "1"
    return env


_STAGE_RE = re.compile(r"^\[Stufe (\d+)/(\d+)\]\s*(.*)$")
# Zwei Quellen, ein Ausdruck: WhisperX' eigenes "Progress: 42.50%..." und unser
# "[Fortschritt] 42.5%" aus progress.emit_progress. Beide VERANKERT, damit keine fremde
# Bibliotheksausgabe versehentlich als Fortschritt gedeutet wird.
_PROGRESS_RE = re.compile(r"^(?:Progress: (\d+(?:\.\d+)?)%\.\.\.|\[Fortschritt\] (\d+(?:\.\d+)?)%)$")
# Aus pipeline/audio.py: "   - meeting.16k.wav: 00:06:58 (419s)"
_DURATION_LINE_RE = re.compile(r"^\s*-\s.*:\s*\d+:\d\d:\d\d\s*\((\d+(?:\.\d+)?)s\)\s*$")


def parse_stage(line: str) -> tuple[int, int, str] | None:
    """Gegenstueck zu ``ConsoleReporter.stage``: ``"[Stufe 2/5] Transkription"``.

    Liefert ``(index, total, name)`` oder ``None`` fuer jede andere Zeile.
    """
    match = _STAGE_RE.match(line.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3).strip()


def parse_progress(line: str) -> float | None:
    """Feinfortschritt innerhalb der laufenden Stufe in Prozent, sonst ``None``."""
    match = _PROGRESS_RE.match(line.strip())
    if not match:
        return None
    return float(match.group(1) or match.group(2))


def parse_duration_line(line: str) -> float | None:
    """Laufzeit aus der Ladezeile von ``pipeline/audio.py``, sonst ``None``.

    Muss gegen die anderen ``   - ...:``-Zeilen (``Markdown: ...``, ``JSON: ...``)
    abgrenzen - daher wird der komplette Zeilenbau verlangt, nicht nur die Klammer.
    """
    match = _DURATION_LINE_RE.match(line)
    return float(match.group(1)) if match else None


def cuda_probe_argv(python: str | None = None) -> list[str]:
    """Kommando, das in einem Wegwerf-Prozess prueft, ob CUDA verfuegbar ist."""
    return [
        python or sys.executable,
        "-c",
        "import torch; print(int(torch.cuda.is_available()))",
    ]


def probe_cuda(*, timeout: float = 120.0) -> bool | None:
    """CUDA-Verfuegbarkeit in einem *separaten* Prozess pruefen.

    Nicht ``config.cuda_available()`` benutzen: das importiert torch im Server-Prozess
    und haelt dauerhaft einen CUDA-Kontext offen - VRAM, den der eigentliche
    Transkriptions-Prozess braucht. ``None`` = unbekannt (dann alle Geraete anbieten).
    """
    try:
        proc = subprocess.run(  # noqa: S603 - festes Kommando, keine Nutzereingabe
            cuda_probe_argv(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - kein torch / Timeout -> unbekannt
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().endswith("1")
