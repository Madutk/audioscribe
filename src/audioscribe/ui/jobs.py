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

import json
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
    "large-v3-turbo",
)

# Sprachvorschlaege der Oberflaeche ('auto' = erkennen lassen).
LANGUAGES: tuple[str, ...] = ("de", "en", "auto")

# 'mps' = Apple Silicon (PRD §19, FR-53); nicht verfuegbare Geraete deaktiviert die Oberflaeche.
DEVICES: tuple[str, ...] = ("auto", "cuda", "mps", "cpu")

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
# Aus progress.emit_download: "[Download] <geladen> <gesamt>" in Bytes.
_DOWNLOAD_RE = re.compile(r"^\[Download\] (\d+) (\d+)$")
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


def parse_download(line: str) -> tuple[int, int] | None:
    """``(geladen, gesamt)`` eines Modell-Downloads in Bytes, sonst ``None``."""
    match = _DOWNLOAD_RE.match(line.strip())
    if not match or not int(match.group(2)):
        return None
    return int(match.group(1)), int(match.group(2))


def parse_duration_line(line: str) -> float | None:
    """Laufzeit aus der Ladezeile von ``pipeline/audio.py``, sonst ``None``.

    Muss gegen die anderen ``   - ...:``-Zeilen (``Markdown: ...``, ``JSON: ...``)
    abgrenzen - daher wird der komplette Zeilenbau verlangt, nicht nur die Klammer.
    """
    match = _DURATION_LINE_RE.match(line)
    return float(match.group(1)) if match else None


_ACCELERATOR_PROBE = (
    "import json, sys, torch\n"
    "mps = getattr(torch.backends, 'mps', None)\n"
    "mps_ok = bool(mps is not None and mps.is_available())\n"
    "try:\n"
    "    import mlx_whisper\n"
    "    mlx_ok = sys.platform == 'darwin'\n"
    "except Exception:\n"
    "    mlx_ok = False\n"
    "print(json.dumps({'cuda': bool(torch.cuda.is_available()), 'mps': mps_ok, 'mlx': mlx_ok}))\n"
)


def accelerator_probe_argv(python: str | None = None) -> list[str]:
    """Kommando, das in einem Wegwerf-Prozess CUDA, MPS und mlx-whisper prueft (JSON-Zeile)."""
    return [python or sys.executable, "-c", _ACCELERATOR_PROBE]


def cuda_probe_argv(python: str | None = None) -> list[str]:
    """Kommando, das in einem Wegwerf-Prozess prueft, ob CUDA verfuegbar ist."""
    return [
        python or sys.executable,
        "-c",
        "import torch; print(int(torch.cuda.is_available()))",
    ]


def parse_accelerator(stdout: str, backend_raw: str = "auto") -> dict | None:
    """Letzte JSON-Zeile der Probe -> ``{"cuda", "mps", "backend"}``; ``None`` = unbekannt."""
    zeilen = [z for z in (stdout or "").splitlines() if z.strip()]
    if not zeilen:
        return None
    try:
        daten = json.loads(zeilen[-1])
    except ValueError:
        return None
    if not isinstance(daten, dict):
        return None
    raw = (backend_raw or "auto").strip().lower()
    mlx = bool(daten.get("mlx")) and raw != "faster-whisper" and not bool(daten.get("cuda"))
    return {"cuda": bool(daten.get("cuda")), "mps": bool(daten.get("mps")), "backend": "mlx" if mlx else "faster-whisper"}


def probe_accelerator(*, timeout: float = 120.0) -> dict | None:
    """Beschleuniger in einem *separaten* Prozess pruefen: CUDA, MPS (Apple Silicon), MLX.

    Nicht ``config.cuda_available()`` benutzen: das importiert torch im Server-Prozess
    und haelt dauerhaft einen CUDA-Kontext offen - VRAM, den der eigentliche
    Transkriptions-Prozess braucht. ``None`` = unbekannt (dann alle Geraete anbieten).
    """
    try:
        proc = subprocess.run(  # noqa: S603 - festes Kommando, keine Nutzereingabe
            accelerator_probe_argv(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - kein torch / Timeout -> unbekannt
        return None
    if proc.returncode != 0:
        return None
    return parse_accelerator(proc.stdout, os.environ.get("AUDIOSCRIBE_ASR_BACKEND", "auto"))


def probe_cuda(*, timeout: float = 120.0) -> bool | None:
    """CUDA-Verfuegbarkeit (``None`` = unbekannt) - Huelle um ``probe_accelerator``."""
    acc = probe_accelerator(timeout=timeout)
    return None if acc is None else acc["cuda"]


def doctor_argv(python: str | None = None) -> list[str]:
    """Kommando fuer den Umgebungs-Check als Wegwerf-Prozess (``audioscribe doctor --json``)."""
    return [python or sys.executable, "-m", "audioscribe.cli", "doctor", "--json"]


def probe_environment(*, timeout: float = 300.0) -> list[dict] | None:
    """``audioscribe doctor --json`` in einem *separaten* Prozess ausfuehren.

    Gleiche Begruendung wie ``probe_cuda``: die Checks importieren torch und pyannote
    und fragen Hugging Face an - nichts davon gehoert in den Server-Prozess. ``None``
    heisst: Check nicht ausfuehrbar (Timeout, kaputte Installation); die Oberflaeche
    zeigt dann einen Hinweis statt einer Liste. Exit-Code 1 ist dagegen normal - er
    meldet nur, dass mindestens ein Check FAIL ist.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - festes Kommando, keine Nutzereingabe
            doctor_argv(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=child_env(),
        )
        # Die letzte nicht-leere Zeile ist das JSON; davor koennen Warnungen stehen.
        zeilen = [z for z in proc.stdout.splitlines() if z.strip()]
        daten = json.loads(zeilen[-1]) if zeilen else None
    except Exception:  # noqa: BLE001 - Timeout, kein JSON -> unbekannt
        return None
    if not isinstance(daten, list):
        return None
    return [
        {"status": str(d.get("status", "WARN")), "name": str(d.get("name", "?")), "detail": str(d.get("detail", ""))}
        for d in daten
        if isinstance(d, dict)
    ]


# --- KI-Analyse (PRD §16) ----------------------------------------------------------
#
# Auch der Agent laeuft als Subprozess ('audioscribe analyze'): gleiche Gruende wie oben
# (Config pro Lauf, Abbruch per Prozessgruppe, Absturz-Isolation), und der Webserver
# braucht das Agent SDK nicht selbst zu importieren.

# Vorschlaege der Oberflaeche; die CLI akzeptiert jeden Namen, den Claude Code kennt.
AGENT_MODELS: tuple[str, ...] = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5-1")


@dataclass(frozen=True)
class AnalyseOptions:
    """Die in der Oberflaeche einstellbaren Optionen eines Analyse-Laufs."""

    source: Path  # Ergebnisordner eines 'run' (output/<stem>)
    name: str
    output_dir: Path
    context_text: str = ""
    context_files: tuple[Path, ...] = ()
    skills: tuple[str, ...] = ()
    skills_dir: Path | None = None
    model: str = "claude-opus-5"
    bash: bool = True


def build_analyze_argv(opts: AnalyseOptions, *, prefix: Sequence[str] | None = None) -> list[str]:
    """Baut den vollstaendigen ``audioscribe analyze``-Aufruf."""
    argv = list(prefix if prefix is not None else cli_prefix())
    # Werte in der '--option=wert'-Form: ein Prozessname wie "-Test" oder ein Kontext,
    # der mit "--" beginnt, wuerde sonst von argparse als Option gelesen.
    argv += [
        "analyze",
        str(Path(opts.source)),
        f"--name={opts.name}",
        f"--out={Path(opts.output_dir)}",
        f"--model={opts.model}",
    ]
    if opts.context_text.strip():
        argv.append(f"--context-text={opts.context_text}")
    for path in opts.context_files:
        argv.append(f"--context={Path(path)}")
    if opts.skills_dir is not None:
        argv.append(f"--skills-dir={Path(opts.skills_dir)}")
    # Die Auswahl der Oberflaeche gilt exakt: ohne '--skill' griffe in der CLI die
    # Config-Vorauswahl - eine bewusst leere Auswahl heisst darum '--no-skills'.
    argv += [f"--skill={name}" for name in opts.skills]
    if not opts.skills:
        argv.append("--no-skills")
    if not opts.bash:
        argv.append("--no-bash")
    return argv


def scan_results(output_dir: Path) -> list[dict]:
    """Fertige Transkriptionen unter ``output_dir`` - die moeglichen Analyse-Quellen.

    Ein Unterordner zaehlt, wenn er ``transkript.md`` enthaelt. Juengste zuerst.
    """
    folder = Path(output_dir)
    if not folder.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {folder}")
    out: list[tuple[float, dict]] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if not entry.is_dir():
                    continue
                transcript = Path(entry.path) / "transkript.md"
                if not transcript.is_file():
                    continue
                mtime = transcript.stat().st_mtime
                frames_dir = Path(entry.path) / "frames"
                frames = (
                    sum(1 for p in frames_dir.iterdir() if p.is_file())
                    if frames_dir.is_dir()
                    else 0
                )
            except OSError:
                continue
            annotated = (Path(entry.path) / "transkript.annotiert.md").is_file()
            out.append(
                (
                    mtime,
                    {"name": entry.name, "path": entry.path, "frames": frames, "annotated": annotated},
                )
            )
    return [item for _, item in sorted(out, key=lambda t: t[0], reverse=True)]


# --- Live-Transkription (PRD §17) --------------------------------------------------

# 'auto' waehlt nach Geraet und Backend: large-v3-turbo auf CUDA und MLX, small auf CPU
# (live/asr.default_model).
LIVE_WHISPER_MODELS: tuple[str, ...] = ("auto", *WHISPER_MODELS)


@dataclass(frozen=True)
class LiveJobOptions:
    """Die in der Oberflaeche einstellbaren Optionen einer Live-Sitzung."""

    output_dir: Path
    monitor: int = 1  # 0 = ohne Bildschirm
    window: int = 0  # HWND eines Anwendungsfensters; hat Vorrang vor monitor
    mic: str = "default"  # "default" | "none" | Geraeteindex
    loopback: str = "default"
    model: str = "auto"
    language: str = "de"
    device: str = "auto"
    frame_sensitivity: str = "mittel"
    frame_format: str = "jpg-1600"
    partials: bool = True
    speakers: bool = True
    refine: bool = True
    # Unabhaengig vom Live-Modell: live zaehlt Tempo, beim Nachschaerfen Genauigkeit.
    refine_model: str = "large-v3"
    # Testmodus (FR-64): ein gespeichertes Transkript abspielen statt aufzunehmen. Dann
    # gibt es weder Audio noch Bild noch Nachschaerfen - nur die Ereignisse der Absaetze.
    replay_transcript: Path | None = None
    replay_speed: float = 1.0


REPLAY_SPEEDS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0)


def build_live_argv(opts: LiveJobOptions, *, prefix: Sequence[str] | None = None) -> list[str]:
    """Baut den vollstaendigen ``audioscribe live``-Aufruf."""
    argv = list(prefix if prefix is not None else cli_prefix())
    if opts.replay_transcript is not None:
        return [
            *argv,
            "live",
            f"--output={Path(opts.output_dir)}",
            f"--transcript={Path(opts.replay_transcript)}",
            f"--speed={opts.replay_speed:g}",
        ]
    argv += [
        "live",
        f"--output={Path(opts.output_dir)}",
        f"--monitor={opts.monitor}",
        f"--mic={opts.mic}",
        f"--loopback={opts.loopback}",
        f"--model={opts.model}",
        f"--language={opts.language}",
        f"--device={opts.device}",
        f"--frame-sensitivity={opts.frame_sensitivity}",
        f"--frame-format={opts.frame_format}",
    ]
    if opts.window:
        argv.append(f"--window={opts.window}")
    if not opts.partials:
        argv.append("--no-partials")
    if not opts.speakers:
        argv.append("--no-speakers")
    return argv


def build_refine_argv(
    session_dir: Path, opts: LiveJobOptions, *, prefix: Sequence[str] | None = None
) -> list[str]:
    """Baut den ``audioscribe refine``-Aufruf fuer eine beendete Sitzung."""
    argv = list(prefix if prefix is not None else cli_prefix())
    return [
        *argv,
        "refine",
        str(Path(session_dir)),
        f"--model={opts.refine_model}",
        f"--language={opts.language}",
        f"--device={opts.device}",
    ]
