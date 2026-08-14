"""Stapel-Runner: arbeitet die gewaehlten Dateien nacheinander als Subprozesse ab.

Laeuft in einem Hintergrund-Thread, damit der Webserver antwortbereit bleibt. Die
Ausgabe der Kind-Prozesse landet zeilenweise in einem Ringpuffer, den die Oberflaeche
per Offset abholt (siehe ``snapshot``). Zur Begruendung des Subprozess-Ansatzes siehe
den Modul-Docstring von ``audioscribe.ui.jobs``.

Fortschritt und Restzeit werden hier berechnet, nicht im Browser: die Rechnung braucht
die Wanduhrzeiten der bereits fertigen Dateien, die ohnehin nur der Runner kennt.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from audioscribe.ui.jobs import (
    JobOptions,
    build_argv,
    child_env,
    parse_duration_line,
    parse_progress,
    parse_stage,
)

# Zustaende einer Datei im Stapel (Anzeige in der Oberflaeche).
WAITING = "wartet"
RUNNING = "laeuft"
DONE = "fertig"
FAILED = "fehler"
CANCELLED = "abgebrochen"

# Fortschrittszeilen kommen im Sekundentakt; nur jeder volle Zehnerschritt wandert in den
# Log. So bleibt die Spur im Fehlerfall lesbar, ohne die Anzeige zu fluten (eine
# Zweistundendatei erzeugt sonst ~240 Zeilen).
_LOG_PROGRESS_STEP = 10.0

# Erst ab einer fertigen Datei ist eine Restzeit serioes: der erste Lauf enthaelt
# Modell-Downloads, CUDA-Initialisierung und den os.execv-Neustart des cuDNN-Bootstraps.
_ETA_MIN_DONE = 1


@dataclass
class FileState:
    name: str
    path: str
    state: str = WAITING
    returncode: int | None = None
    seconds: float | None = None
    duration: float | None = None
    percent: float | None = None
    fraction: float = 0.0


@dataclass
class _Stage:
    index: int
    total: int
    name: str


@dataclass
class _State:
    """Alles, was hinter dem Lock liegt."""

    running: bool = False
    files: list[FileState] = field(default_factory=list)
    current: int | None = None
    stage: _Stage | None = None
    summary: str | None = None
    cancelled: bool = False
    started: float | None = None
    file_started: float | None = None


def file_fraction(stage: _Stage | None, percent: float | None) -> float:
    """Fortschritt einer Datei als 0..1 aus Stufe und Feinfortschritt.

    Bewusst gleichgewichtete Stufen: ``orchestrator`` rechnet die Gesamtzahl exakt aus,
    und der Wert ist an der Anzeige ablesbar ("Stufe 3/5 - Transkription 62 %"). Eine
    Gewichtstabelle nach Stufennamen waere auf CPU und GPU in entgegengesetzte Richtungen
    falsch und wuerde per String-Vergleich an Anzeigetexte eines anderen Moduls koppeln.
    """
    if stage is None or stage.total <= 0:
        return 0.0
    inner = 0.0 if percent is None else max(0.0, min(100.0, percent)) / 100.0
    return max(0.0, min(1.0, (stage.index - 1 + inner) / stage.total))


def _fit_cost(samples: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """Kleinste Quadrate ``sekunden = a + b * dauer`` ueber fertige Dateien.

    ``a`` faengt den festen Aufwand je Datei ab - jeder Kindprozess laedt Whisper,
    wav2vec2 und pyannote neu, was bei vielen kurzen Dateien dominiert. Mit nur einem
    Messpunkt bleibt nur der reine Durchsatz (``a = 0``).
    """
    if not samples:
        return None
    if len(samples) == 1:
        duration, seconds = samples[0]
        return (0.0, seconds / duration) if duration > 0 else None

    n = len(samples)
    sx = sum(d for d, _ in samples)
    sy = sum(s for _, s in samples)
    sxx = sum(d * d for d, _ in samples)
    sxy = sum(d * s for d, s in samples)
    denom = n * sxx - sx * sx
    if denom <= 0:  # alle Dateien gleich lang -> keine Steigung bestimmbar
        return (0.0, sy / sx) if sx > 0 else None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    # Negative Werte sind physikalisch unsinnig und entstehen bei verrauschten Messungen.
    return max(0.0, intercept), max(0.0, slope)


def batch_eta(
    files: Sequence[FileState],
    current: int | None,
    elapsed_current: float,
) -> dict:
    """Audio-Bilanz des Stapels und - sofern schaetzbar - die Restzeit.

    ``eta_s`` ist ``None``, solange keine Datei fertig ist: der erste Lauf enthaelt
    Modell-Downloads, CUDA-Initialisierung und den ``os.execv``-Neustart und waere um
    Groessenordnungen daneben. Nur **fertige** Dateien speisen die Schaetzung -
    fehlgeschlagene und abgebrochene verbrennen Wanduhrzeit ohne Audio und wuerden die
    Rechnung sprengen. Dateien ohne messbare Laufzeit fallen aus der Zahl heraus und
    werden getrennt gezaehlt.
    """
    total_audio = sum(f.duration for f in files if f.duration)
    # Erledigtes Audio inklusive des angebrochenen Anteils der laufenden Datei - das
    # macht den Gesamtbalken fluessig. Fuer die Restzeit unten wird bewusst NICHT damit
    # gerechnet (dort zaehlt die Wanduhr), um nicht zwei Schaetzungen zu multiplizieren.
    done_audio = sum(f.duration for f in files if f.duration and f.state in (DONE, FAILED))
    if current is not None and 0 <= current < len(files):
        running = files[current]
        if running.duration and running.state == RUNNING:
            done_audio += running.duration * running.fraction

    balance = {
        "eta_s": None,
        "audio_total_s": round(total_audio),
        "audio_done_s": round(min(done_audio, total_audio)),
        "unknown_count": sum(1 for f in files if not f.duration and f.state in (WAITING, RUNNING)),
    }

    samples = [
        (f.duration, f.seconds)
        for f in files
        if f.state == DONE and f.duration and f.seconds is not None
    ]
    if len(samples) < _ETA_MIN_DONE:
        return balance
    fit = _fit_cost(samples)
    if fit is None:
        return balance
    overhead, rate = fit

    remaining = 0.0
    for index, entry in enumerate(files):
        if entry.state != WAITING and index != current:
            continue
        if not entry.duration:
            continue  # unbekannte Laenge: zaehlt separat, nicht in der Zahl
        cost = overhead + rate * entry.duration
        if index == current:
            cost = max(0.0, cost - elapsed_current)
        remaining += cost

    balance["eta_s"] = round(remaining)
    return balance


class BatchRunner:
    """Ein Stapellauf zur Zeit; Status und Log sind jederzeit abfragbar."""

    def __init__(self, *, max_lines: int = 5000) -> None:
        self._lock = threading.Lock()
        self._state = _State()
        self._log: deque[str] = deque(maxlen=max_lines)
        # Zahl der bereits aus dem Ringpuffer verdraengten Zeilen: haelt den vom
        # Client mitgefuehrten Offset auch nach dem Ueberlauf konsistent.
        self._dropped = 0
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    # --- oeffentliche API -------------------------------------------------

    def start(
        self,
        opts: JobOptions,
        files: Sequence[Path],
        *,
        durations: Mapping[str, float | None] | None = None,
        argv_builder: Callable[[Path, JobOptions], list[str]] = build_argv,
    ) -> None:
        """Startet den Stapellauf. ``RuntimeError``, wenn schon einer laeuft.

        ``durations`` (Dateiname -> Sekunden) wird VOR dem Start ermittelt und hier nur
        entgegengenommen - im Runner selbst darf nie gemessen werden, das wuerde den
        Lesethread hinter dem Lock blockieren.
        """
        durations = durations or {}
        with self._lock:
            if self._state.running:
                raise RuntimeError("Es laeuft bereits ein Durchlauf.")
            self._state = _State(
                running=True,
                started=time.monotonic(),
                files=[
                    FileState(
                        name=Path(f).name,
                        path=str(f),
                        duration=durations.get(Path(f).name),
                    )
                    for f in files
                ],
            )
            self._log.clear()
            self._dropped = 0

        self._append(f"Starte Stapellauf: {len(files)} Datei(en) -> {opts.output_dir}")
        self._append(
            f"Modell: {opts.model} | Sprache: {opts.language} | Geraet: {opts.device} | "
            f"Diarisierung: {'an' if opts.diarize else 'aus'}"
        )

        self._thread = threading.Thread(
            target=self._run_batch,
            args=(opts, [Path(f) for f in files], argv_builder),
            name="audioscribe-batch",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Bricht den laufenden Stapel ab (aktueller Prozess inkl. seiner Kinder)."""
        with self._lock:
            if not self._state.running:
                return
            self._state.cancelled = True
            proc = self._proc
        if proc and proc.poll() is None:
            self._append("Abbruch angefordert - beende laufenden Prozess ...")
            _terminate(proc)

    def snapshot(self, offset: int = 0) -> dict:
        """Status + alle Log-Zeilen ab ``offset``; ``offset`` der Antwort weiterreichen."""
        with self._lock:
            state = self._state
            start = max(0, min(len(self._log), offset - self._dropped))
            lines = list(self._log)[start:]
            new_offset = self._dropped + len(self._log)
            current = state.current

            elapsed_current = (
                time.monotonic() - state.file_started if state.file_started is not None else 0.0
            )
            eta = (
                batch_eta(state.files, current, elapsed_current)
                if state.running
                else None
            )
            return {
                "running": state.running,
                "cancelled": state.cancelled,
                "total": len(state.files),
                "done": sum(1 for f in state.files if f.state not in (WAITING, RUNNING)),
                "current": (
                    {"index": current + 1, "name": state.files[current].name}
                    if current is not None and current < len(state.files)
                    else None
                ),
                "stage": asdict(state.stage) if state.stage else None,
                "files": [asdict(f) for f in state.files],
                "summary": state.summary,
                "eta": eta,
                "offset": new_offset,
                "lines": lines,
            }

    # --- Innenleben -------------------------------------------------------

    def _append(self, line: str) -> None:
        with self._lock:
            if len(self._log) == self._log.maxlen:
                self._dropped += 1
            self._log.append(line)

    def _set_file(self, index: int, **changes: object) -> None:
        with self._lock:
            entry = self._state.files[index]
            for key, value in changes.items():
                setattr(entry, key, value)

    def _run_batch(
        self,
        opts: JobOptions,
        files: list[Path],
        argv_builder: Callable[[Path, JobOptions], list[str]],
    ) -> None:
        try:
            for index, media in enumerate(files):
                with self._lock:
                    if self._state.cancelled:
                        break
                    self._state.current = index
                    self._state.stage = None
                    self._state.file_started = time.monotonic()
                    self._state.files[index].percent = None
                    self._state.files[index].fraction = 0.0

                self._set_file(index, state=RUNNING)
                self._append(f"\n[{index + 1}/{len(files)}] {media.name}")
                started = time.monotonic()
                code = self._run_one(argv_builder(media, opts), index)
                elapsed = round(time.monotonic() - started, 1)

                with self._lock:
                    cancelled = self._state.cancelled
                if cancelled:
                    self._set_file(index, state=CANCELLED, returncode=code, seconds=elapsed)
                    break
                if code == 0:
                    self._set_file(
                        index, state=DONE, returncode=0, seconds=elapsed, fraction=1.0
                    )
                    self._append(f"   -> fertig in {elapsed}s")
                else:
                    self._set_file(index, state=FAILED, returncode=code, seconds=elapsed)
                    self._append(f"   -> FEHLER (Exit-Code {code}) - weiter mit der naechsten Datei")
        finally:
            self._finish()

    def _run_one(self, argv: list[str], index: int) -> int:
        """Startet einen Kind-Prozess und wertet seine Ausgabe zeilenweise aus."""
        try:
            proc = subprocess.Popen(  # noqa: S603 - Kommando kommt aus build_argv
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=child_env(),
                # eigene Prozessgruppe: der Abbruch erreicht auch ffmpeg-Enkelprozesse
                start_new_session=True,
            )
        except OSError as exc:
            self._append(f"   Prozessstart fehlgeschlagen: {exc}")
            return -1

        with self._lock:
            self._proc = proc

        assert proc.stdout is not None
        logged_progress = -_LOG_PROGRESS_STEP
        for raw in proc.stdout:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue

            # Zuerst ausserhalb des Locks deuten, dann genau einmal sperren.
            percent = parse_progress(line)
            if percent is not None:
                self._update_progress(index, percent)
                if percent < logged_progress + _LOG_PROGRESS_STEP:
                    continue  # Flutschutz: nur volle Zehnerschritte in den Log
                logged_progress = percent - percent % _LOG_PROGRESS_STEP
                self._append(f"   {percent:.0f}%")
                continue

            stage = parse_stage(line)
            if stage:
                logged_progress = -_LOG_PROGRESS_STEP
                with self._lock:
                    self._state.stage = _Stage(*stage)
                    # Prozent MUSS auch hier zurueck - sonst schleppt die Transkription
                    # ihre 100 % in die naechste Stufe und der Balken laeuft rueckwaerts.
                    self._state.files[index].percent = None
                    self._state.files[index].fraction = file_fraction(self._state.stage, None)
                self._append(line)
                continue

            duration = parse_duration_line(line)
            if duration is not None:
                self._set_file(index, duration=duration)
            self._append(line)

        code = proc.wait()
        with self._lock:
            self._proc = None
        return code

    def _update_progress(self, index: int, percent: float) -> None:
        with self._lock:
            entry = self._state.files[index]
            entry.percent = percent
            entry.fraction = file_fraction(self._state.stage, percent)

    def _finish(self) -> None:
        with self._lock:
            files = self._state.files
            cancelled = self._state.cancelled
            for entry in files:
                if entry.state in (WAITING, RUNNING):
                    entry.state = CANCELLED if cancelled else WAITING
            ok = sum(1 for f in files if f.state == DONE)
            failed = [f.name for f in files if f.state == FAILED]

            parts = [f"{ok} von {len(files)} transkribiert"]
            if failed:
                parts.append(f"{len(failed)} fehlgeschlagen: {', '.join(failed)}")
            if cancelled:
                parts.append("abgebrochen")
            summary = " | ".join(parts)

            self._state.summary = summary
            self._state.running = False
            self._state.current = None
            self._state.stage = None
            self._state.file_started = None
        self._append(f"\nZusammenfassung: {summary}")


def _terminate(proc: subprocess.Popen[str]) -> None:
    """Beendet die Prozessgruppe des Kindes, notfalls hart."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()
