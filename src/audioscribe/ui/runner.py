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

from audioscribe.agent.fortschritt import parse_status_line
from audioscribe.live.events import parse_event
from audioscribe.ui.jobs import (
    AnalyseOptions,
    JobOptions,
    LiveJobOptions,
    build_analyze_argv,
    build_argv,
    build_live_argv,
    build_refine_argv,
    child_env,
    parse_duration_line,
    parse_progress,
    parse_stage,
)
from audioscribe.verbrauch import QUELLE_ANALYSE, Verbrauch, Zaehler

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
    output_dir: str = ""  # Zielordner des Laufs - fuer die Ergebniskarte
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


class _ProcessRunner:
    """Gemeinsame Basis: Lock, Log-Ringpuffer mit Offset, Start eines Kind-Prozesses."""

    def __init__(self, *, max_lines: int = 5000) -> None:
        self._lock = threading.Lock()
        self._log: deque[str] = deque(maxlen=max_lines)
        # Zahl der bereits aus dem Ringpuffer verdraengten Zeilen: haelt den vom
        # Client mitgefuehrten Offset auch nach dem Ueberlauf konsistent.
        self._dropped = 0
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    def _append(self, line: str) -> None:
        with self._lock:
            if len(self._log) == self._log.maxlen:
                self._dropped += 1
            self._log.append(line)

    def _lines_since(self, offset: int) -> tuple[list[str], int]:
        """Log-Zeilen ab ``offset`` und der neue Offset. Aufrufer haelt den Lock."""
        start = max(0, min(len(self._log), offset - self._dropped))
        return list(self._log)[start:], self._dropped + len(self._log)

    def _reset_log(self) -> None:
        """Aufrufer haelt den Lock."""
        self._log.clear()
        self._dropped = 0

    def _spawn(self, argv: list[str], *, stdin: int = subprocess.DEVNULL) -> subprocess.Popen[str] | None:
        try:
            proc = subprocess.Popen(  # noqa: S603 - Kommando kommt aus build_*argv
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # Kein Terminal erben: ein Kind, das nachfragt, bekaeme sonst die
                # Tastatur des Server-Fensters und bliebe haengen. Nur die Live-Sitzung
                # bekommt eine Pipe - ueber sie kommt das saubere "stop".
                stdin=stdin,
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
            return None
        with self._lock:
            self._proc = proc
        return proc


class BatchRunner(_ProcessRunner):
    """Ein Stapellauf zur Zeit; Status und Log sind jederzeit abfragbar."""

    def __init__(self, *, max_lines: int = 5000) -> None:
        super().__init__(max_lines=max_lines)
        self._state = _State()

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
                output_dir=str(opts.output_dir),
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
            self._reset_log()

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

    def laeuft(self) -> bool:
        with self._lock:
            return self._state.running

    def leeren(self) -> None:
        """Stand und Protokoll des letzten Laufs vergessen (Kontextwechsel); nie im Lauf."""
        with self._lock:
            if not self._state.running:
                self._state = _State()
                self._reset_log()

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
            lines, new_offset = self._lines_since(offset)
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
                "output_dir": state.output_dir,
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
        proc = self._spawn(argv)
        if proc is None:
            return -1

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


class AnalyseRunner(_ProcessRunner):
    """Ein Analyse-Lauf (``audioscribe analyze``) zur Zeit - Log per Polling wie beim Stapel."""

    def __init__(self, *, max_lines: int = 5000, zaehler: Zaehler | None = None) -> None:
        super().__init__(max_lines=max_lines)
        self._info: dict = {"running": False}
        self._zaehler = zaehler  # KI-Verbrauch seit Programmstart (Kopfzeile der Oberflaeche)

    def start(
        self,
        opts: AnalyseOptions,
        *,
        argv_builder: Callable[[AnalyseOptions], list[str]] = build_analyze_argv,
    ) -> Path:
        """Startet die Analyse; gibt den Ergebnisordner zurueck. ``RuntimeError`` bei Doppelstart."""
        from audioscribe.agent.material import slugify

        workspace = Path(opts.output_dir) / slugify(opts.name)
        with self._lock:
            if self._info.get("running"):
                raise RuntimeError("Es laeuft bereits eine Analyse.")
            self._info = {
                "running": True,
                "cancelled": False,
                "name": opts.name,
                "workspace": str(workspace),
                "source": str(opts.source),
                "started": time.time(),
                "returncode": None,
                "result": None,
                "progress": None,
            }
            self._reset_log()
        if self._zaehler is not None:
            self._zaehler.beginne(QUELLE_ANALYSE)
        self._thread = threading.Thread(
            target=self._run,
            args=(argv_builder(opts), workspace),
            name="audioscribe-analyse",
            daemon=True,
        )
        self._thread.start()
        return workspace

    def laeuft(self) -> bool:
        with self._lock:
            return bool(self._info.get("running"))

    def leeren(self) -> None:
        """Ergebnis und Protokoll der letzten Analyse vergessen (Kontextwechsel); nie im Lauf."""
        with self._lock:
            if not self._info.get("running"):
                self._info = {"running": False}
                self._reset_log()

    def cancel(self) -> None:
        with self._lock:
            if not self._info.get("running"):
                return
            self._info["cancelled"] = True
            proc = self._proc
        if proc and proc.poll() is None:
            self._append("Abbruch angefordert - beende den Agenten ...")
            _terminate(proc)

    def snapshot(self, offset: int = 0) -> dict:
        with self._lock:
            lines, new_offset = self._lines_since(offset)
            info = dict(self._info)
        if info.get("started") and info.get("running"):
            info["elapsed_s"] = round(time.time() - info["started"], 1)
        return {**info, "offset": new_offset, "lines": lines}

    def _run(self, argv: list[str], workspace: Path) -> None:
        code = -1
        try:
            proc = self._spawn(argv)
            if proc is not None:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.rstrip("\n").rstrip("\r")
                    if not line.strip():
                        continue
                    progress = parse_status_line(line)
                    if progress is not None:
                        # Fortschritt ersetzt den vorigen Stand; nicht ins Protokoll.
                        with self._lock:
                            self._info["progress"] = progress
                        if self._zaehler is not None and progress.get("verbrauch"):
                            self._zaehler.setze(QUELLE_ANALYSE, Verbrauch.aus_dict(progress["verbrauch"]))
                        continue
                    self._append(line)
                code = proc.wait()
        finally:
            self._finish(code, workspace)

    def _finish(self, code: int, workspace: Path) -> None:
        from audioscribe.agent.manifest import load_manifest

        manifest = load_manifest(workspace)
        result = None
        if manifest is not None:
            index = workspace / "INDEX.md"
            result = {
                "status": manifest.status,
                "session_id": manifest.session_id,
                "index": str(index) if index.exists() else None,
                "fehler": manifest.fehler,
            }
        with self._lock:
            if result is not None:
                # Verbrauch dieses Laufs (nicht die Summe aller Laeufe aus analyse.json); der
                # Preis ist ein Gegenwert zu API-Preisen und heisst in der Oberflaeche auch so.
                result["verbrauch"] = (self._info.get("progress") or {}).get("verbrauch")
            self._proc = None
            self._info.update(running=False, returncode=code, result=result)
            cancelled = self._info.get("cancelled")
        if cancelled:
            self._append("\nAnalyse abgebrochen.")
        elif code == 0:
            self._append(f"\nAnalyse fertig: {workspace}")
        else:
            self._append(f"\nAnalyse mit Fehler beendet (Exit-Code {code}).")


class LiveRunner(_ProcessRunner):
    """Eine Live-Sitzung (``audioscribe live``) zur Zeit, danach optional ``refine``.

    Anders als Stapel und Analyse liefert das Kind neben dem Protokoll strukturierte
    Ereignisse (``[Live] {json}``): Segmente und Standbilder werden gesammelt und per
    eigenem Offset abgeholt, Vorschautext und Messwerte ersetzen jeweils den Vorstand.
    """

    def __init__(self, *, max_lines: int = 5000) -> None:
        super().__init__(max_lines=max_lines)
        self._info: dict = {"running": False}
        self._events: list[dict] = []
        self._discard = False  # Reset unterwegs: kein Nachschaerfen mehr anstossen
        self._last_line: str | None = None  # letzte Protokollzeile - Fehlertext fuer die Oberflaeche
        # Souffleur (PRD §20): hoert die Segmente mit und haengt "hinweis"-Ereignisse an.
        self._souffleur = None
        # Nachlauf (PRD §21): laeuft nach dem Ende einer Sitzung, z. B. die Wiki-Ablage "immer".
        self._on_ende: Callable[[Path], dict | None] | None = None
        # Zaehlt Starts und Resets: ein Reset, der einen Start noch beim Aufbau des Souffleurs
        # erwischt, macht diesen Start ungueltig (sonst liefe das Kind ohne Runner weiter).
        self._gen = 0

    def laeuft(self) -> bool:
        with self._lock:
            return bool(self._info.get("running"))

    def start(
        self,
        opts: LiveJobOptions,
        *,
        argv_builder: Callable[[LiveJobOptions], list[str]] = build_live_argv,
        refine_builder: Callable[[Path, LiveJobOptions], list[str]] = build_refine_argv,
        souffleur_factory: Callable[[LiveJobOptions], object | None] | None = None,
        on_ende: Callable[[Path], dict | None] | None = None,
        finalize_builder: Callable[[Path], list[str]] | None = None,
    ) -> None:
        """``on_ende`` bekommt nach einem sauberen Ende den Sitzungsordner; sein Ergebnis steht
        als ``nachlauf`` im Status. ``finalize_builder`` schliesst eine unterbrochene Sitzung
        ab, statt aufzunehmen (``opts.resume_dir`` nennt den Ordner)."""
        with self._lock:
            if self._info.get("running"):
                raise RuntimeError("Es laeuft bereits eine Live-Sitzung.")
            self._on_ende = on_ende
            self._info = {
                "running": True,
                "phase": "startet",
                "stopping": False,
                "session": None,
                "dir": None,
                "model": None,
                "device": None,
                "step": None,  # Ladeschritt waehrend "laden"
                "stats": None,
                "download": None,
                "partials": {},
                "refine": None,
                "fazit": None,  # {"live": {...}, "nachschaerfen": {...}} nach dem jeweiligen Ende
                "returncode": None,
                "error": None,  # letzte Protokollzeile, wenn die Sitzung mit Fehler endet
                "replay": opts.replay_transcript is not None,  # Testmodus: Transkript abspielen (FR-64)
                "replay_speed": opts.replay_speed if opts.replay_transcript is not None else None,
                "titel": getattr(opts, "titel", "") or "",
                "fortgesetzt": getattr(opts, "resume_dir", None) is not None,  # Wiederaufnahme (PRD §21)
                "pausiert": False,  # Abspielen angehalten (nur Transkript-Replay, z. B. die Demo)
                "nachlauf": None,  # Ergebnis von on_ende, z. B. {"wiki_ablage": {...}}
            }
            self._events = []
            self._discard = False
            self._last_line = None
            self._reset_log()
            self._souffleur = None
            self._gen += 1
            gen = self._gen
        souffleur = None
        if souffleur_factory is not None:
            try:
                souffleur = souffleur_factory(opts)
            except Exception as exc:  # noqa: BLE001 - der Souffleur darf die Sitzung nie verhindern
                souffleur = None
                self._append(f"Souffleur nicht gestartet: {exc}")
            if souffleur is not None:
                souffleur.on_hinweis = self._on_hinweis
                with self._lock:
                    self._souffleur = souffleur
        resume_dir = getattr(opts, "resume_dir", None)
        if souffleur is not None and resume_dir is not None:
            # Wiederaufnahme: der Ordner steht fest - die bisherigen Hinweise sofort zeigen,
            # nicht erst nach dem Laden der Modelle.
            try:
                souffleur.starte(Path(resume_dir))
            except Exception as exc:  # noqa: BLE001
                self._append(f"Souffleur-Fehler: {exc}")
        if finalize_builder is not None and resume_dir is not None:
            argv = finalize_builder(Path(resume_dir))
        else:
            argv = argv_builder(opts)
        with self._lock:
            ueberholt = self._gen != gen
        if ueberholt:
            # Inzwischen zurueckgesetzt (z. B. "Demo beenden" direkt nach dem Start): nichts starten.
            if souffleur is not None:
                souffleur.stop()
                with self._lock:
                    if self._souffleur is souffleur:
                        self._souffleur = None
            return
        self._thread = threading.Thread(
            target=self._run,
            args=(argv, opts, refine_builder),
            name="audioscribe-live",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Erster Aufruf: sauberes ``stop`` ueber stdin. Zweiter Aufruf oder waehrend des
        Nachschaerfens: Prozess beenden (die Live-Fassung liegt dann schon auf der Platte)."""
        with self._lock:
            if not self._info.get("running"):
                return
            hard = self._info["stopping"] or self._info["phase"] == "nachschaerfen"
            self._info["stopping"] = True
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        if hard:
            self._append("Abbruch - beende den Prozess ...")
            _terminate(proc)
            return
        self._append("Stopp angefordert - Sitzung wird abgeschlossen ...")
        try:
            assert proc.stdin is not None
            proc.stdin.write("stop\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            _terminate(proc)

    def pause(self, an: bool) -> None:
        """Abspielen eines Transkripts anhalten bzw. fortsetzen (``pause``/``weiter`` ueber stdin).
        Eine echte Aufnahme laesst sich nicht pausieren - ``RuntimeError``."""
        with self._lock:
            laeuft = self._info.get("running") and self._info.get("phase") == "laeuft"
            replay = self._info.get("replay")
            proc = self._proc
        if not laeuft or proc is None or proc.poll() is not None:
            raise RuntimeError("Es läuft gerade nichts, das sich anhalten ließe.")
        if not replay:
            raise RuntimeError("Eine Aufnahme lässt sich nicht pausieren – nur das Abspielen eines Transkripts.")
        try:
            assert proc.stdin is not None
            proc.stdin.write("pause\n" if an else "weiter\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Pause nicht möglich: {exc}") from exc

    def reset(self, *, timeout: float = 15.0) -> Path | None:
        """Alles auf Anfang: eine laufende Sitzung wird hart beendet (ohne Nachschaerfen),
        danach sind Zustand, Ereignisse und Protokoll leer wie vor dem ersten Start.

        Die Dateien der verworfenen Sitzung bleiben auf der Platte; ihr Ordner wird
        zurueckgegeben, damit die Oberflaeche ihn nennen kann.
        """
        with self._lock:
            old_dir = self._info.get("dir")
            running = self._info.get("running")
            if running:
                self._discard = True
                self._info["stopping"] = True
            proc, thread, souffleur = self._proc, self._thread, self._souffleur
        if souffleur is not None:
            souffleur.stop()
        if running:
            if proc is not None and proc.poll() is None:
                _terminate(proc)
            if thread is not None:
                thread.join(timeout)
                if thread.is_alive():
                    raise RuntimeError("Die Live-Sitzung liess sich nicht beenden.")
        with self._lock:
            self._info = {"running": False}
            self._events = []
            self._discard = False
            self._souffleur = None
            self._on_ende = None
            self._gen += 1
            self._reset_log()
        return Path(old_dir) if old_dir else None

    def session_dir(self) -> Path | None:
        with self._lock:
            raw = self._info.get("dir")
        return Path(raw) if raw else None

    def souffleur(self):
        """Der Souffleur der laufenden bzw. letzten Sitzung (``None`` ohne Sitzung)."""
        with self._lock:
            return self._souffleur

    def snapshot(self, offset: int = 0, ev_offset: int = 0) -> dict:
        with self._lock:
            lines, new_offset = self._lines_since(offset)
            info = dict(self._info)
            info["partials"] = dict(info.get("partials") or {})
            new_events = self._events[max(0, ev_offset) :]
            total = len(self._events)
            souffleur = self._souffleur
        info["souffleur"] = souffleur.status() if souffleur is not None else None
        return {**info, "offset": new_offset, "lines": lines, "events": new_events, "ev_offset": total}

    def _on_hinweis(self, hinweis: dict) -> None:
        """Eine Markierung des Souffleurs - als Ereignis fuer den Browser (wie segment/shot)."""
        with self._lock:
            self._events.append({"type": "hinweis", **hinweis})

    def _run(
        self,
        argv: list[str],
        opts: LiveJobOptions,
        refine_builder: Callable[[Path, LiveJobOptions], list[str]],
    ) -> None:
        code = -1
        try:
            code = self._pump(self._spawn(argv, stdin=subprocess.PIPE), self._on_live_line)
            with self._lock:
                session = self._info.get("dir")
                aborted = self._discard or (self._info["stopping"] and self._info["phase"] != "fertig")
            if code == 0 and opts.refine and session and not aborted:
                with self._lock:
                    self._info.update(phase="nachschaerfen", stopping=False, partials={})
                self._append(f"\nNachschaerfen mit {opts.refine_model} ...")
                code = self._pump(self._spawn(refine_builder(Path(session), opts)), self._on_refine_line)
        finally:
            with self._lock:
                self._proc = None
                self._info.update(partials={})
                souffleur = self._souffleur
            if souffleur is not None:
                # Der Souffleur beurteilt noch die letzten Fenster und schreibt die Uebergabe -
                # solange gilt die Sitzung als laufend (Phase "abschluss"), sonst laese die
                # Oberflaeche ein unfertiges Protokoll.
                with self._lock:
                    self._info["phase"] = "abschluss"
                try:
                    souffleur.abschliessen()
                except Exception as exc:  # noqa: BLE001 - Abschluss des Souffleurs ist Zugabe
                    self._append(f"Souffleur-Abschluss fehlgeschlagen: {exc}")
            self._nachlauf(code)
            with self._lock:
                self._info.update(
                    running=False, returncode=code, phase="beendet" if code == 0 else "fehler", pausiert=False
                )
                if code != 0:
                    self._info["error"] = self._last_line
            self._append("\nSitzung beendet." if code == 0 else f"\nBeendet mit Exit-Code {code}.")

    def _nachlauf(self, code: int) -> None:
        """Nach einem sauberen Ende: ``on_ende`` ausfuehren (z. B. Wiki-Ablage "immer"). Solange
        gilt die Sitzung als laufend - sonst boete die Oberflaeche das Speichern doppelt an."""
        with self._lock:
            on_ende, session, verworfen = self._on_ende, self._info.get("dir"), self._discard
        if on_ende is None or code != 0 or verworfen or not session:
            return
        with self._lock:
            self._info["phase"] = "abschluss"
        try:
            ergebnis = on_ende(Path(session))
        except Exception as exc:  # noqa: BLE001 - der Nachlauf darf das Ende nie verhindern
            self._append(f"Nachlauf fehlgeschlagen: {exc}")
            ergebnis = {"fehler": str(exc)}
        if ergebnis:
            with self._lock:
                self._info["nachlauf"] = ergebnis

    def _pump(self, proc: subprocess.Popen[str] | None, on_line: Callable[[str], None]) -> int:
        if proc is None:
            return -1
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n").rstrip("\r")
            if line.strip():
                on_line(line)
        return proc.wait()

    def _on_live_line(self, line: str) -> None:
        event = parse_event(line)
        if event is None:
            self._append(line)
            with self._lock:
                self._last_line = line
            return
        typ = event.pop("type")
        empfangen = time.monotonic()
        with self._lock:
            souffleur = self._souffleur
            if typ == "state":
                self._info.update(
                    {k: event.get(k) for k in ("phase", "session", "dir", "model", "device", "step")}
                )
                for k in ("sitzung_id", "titel"):
                    if event.get(k):
                        self._info[k] = event[k]
                # Das Kind meldet, ob das Abspielen steht - jede andere Phase hebt die Pause auf.
                self._info["pausiert"] = bool(event.get("pausiert")) and event.get("phase") == "laeuft"
                if event.get("phase") != "laden":
                    self._info["download"] = None
            elif typ == "download":
                self._info["download"] = event
            elif typ == "stats":
                self._info["stats"] = event
            elif typ == "fazit":
                self._note_fazit(event)
            elif typ == "partial":
                if event.get("text"):
                    self._info["partials"][event["track"]] = event
                else:
                    self._info["partials"].pop(event.get("track"), None)
            elif typ in ("segment", "shot"):
                if typ == "segment":
                    self._info["partials"].pop(event.get("track"), None)
                self._events.append({"type": typ, **event})
        # Ausserhalb des Locks: der Souffleur ruft ueber _on_hinweis selbst wieder hinein.
        if souffleur is None:
            return
        try:
            if typ == "stats" and event.get("elapsed") is not None:
                souffleur.uhr_sync(float(event["elapsed"]))
            elif typ == "state" and event.get("phase") == "laeuft" and event.get("dir"):
                souffleur.starte(Path(event["dir"]))
            elif typ == "segment" and event.get("restored"):
                souffleur.uebernehme(event)  # Wiederaufnahme: nur Kontext, nicht neu beurteilen
            elif typ == "segment":
                souffleur.beobachte(event, empfangen_mono=empfangen)
        except Exception as exc:  # noqa: BLE001 - der Souffleur darf die Sitzung nie stoeren
            self._append(f"Souffleur-Fehler: {exc}")

    def _note_fazit(self, event: dict) -> None:
        """Fazit eines Teils (live | nachschaerfen) ablegen; Aufruf unter ``_lock``."""
        fazit = dict(self._info.get("fazit") or {})
        fazit[str(event.pop("teil", "live"))] = event
        self._info["fazit"] = fazit

    def _on_refine_line(self, line: str) -> None:
        event = parse_event(line)
        if event is not None:
            if event.pop("type") == "fazit":
                with self._lock:
                    self._note_fazit(event)
            return
        percent = parse_progress(line)
        stage = parse_stage(line)
        with self._lock:
            refine = dict(self._info.get("refine") or {})
            if stage:
                refine.update(index=stage[0], total=stage[1], name=stage[2], percent=None)
            elif percent is not None:
                refine["percent"] = percent
            self._info["refine"] = refine or None
            if percent is None:
                self._last_line = line
        if percent is None:
            self._append(line)


def _terminate(proc: subprocess.Popen[str]) -> None:
    """Beendet die Prozessgruppe des Kindes, notfalls hart."""
    if os.name == "nt":
        # os.killpg/getpgid gibt es unter Windows nicht. taskkill /T nimmt die Enkel
        # (ffmpeg) mit; ein sanftes Signal kennt ein Konsolenprozess ohne Fenster nicht.
        subprocess.run(  # noqa: S603, S607 - festes Kommando
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
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
