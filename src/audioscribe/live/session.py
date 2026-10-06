"""Eine Live-Sitzung: Aufnahme, Schnitt, Transkription, Standbilder, Ablage (PRD §17).

Threads: Audio-Callbacks (PortAudio, ScreenCaptureKit) füllen die Spuren, der Schnitt-Thread zerlegt sie an
Sprechpausen, EIN Transkriptions-Thread arbeitet das Auftragsbrett ab (ein Modell, eine
GPU), der Bildschirm-Thread sichert Standbilder. Der Hauptthread meldet den Stand und
schreibt alle 30 s das Transkript.

Absturzsicherung (PRD §21): jedes Segment und jedes Standbild steht sofort im Journal
(``live/journal.py``), der Zustand in ``sitzung.json``. ``resume_dir`` setzt eine
unterbrochene Sitzung fort - erst laden, dann schreiben: Transkript, ``marks.json`` und
Mitschnitt entstehen sonst komplett aus dem Speicher und würden den Bestand überschreiben.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from audioscribe.live import events, journal
from audioscribe.live.asr import Ergebnis
from audioscribe.live.bilanz import TEIL_LIVE, beschreibe_live, save_bilanz
from audioscribe.live.board import Job, JobBoard
from audioscribe.live.chunker import Chunker
from audioscribe.live.diagnose import DIAGNOSE_NAME, Abschnitt, Diagnose, Vorschau, lies_diagnose
from audioscribe.live.speakers import SPRECHER_DATEI
from audioscribe.live.store import (
    SPUR_WAV,
    keep_live_copy,
    session_name,
    teil_wav,
    verbinde_teile,
    wav_frames,
    write_transcript,
)
from audioscribe.live.track import SAMPLE_RATE
from audioscribe.models import Segment, format_timecode
from audioscribe.review.marks import Mark, load_marks, save_marks

_TICK_S = 0.25
_PERSIST_S = 30.0
# Takt-Zeile im Journal: so alt ist die bekannte Sitzungszeit nach einem Absturz höchstens.
_TAKT_S = 5.0
# Ab diesem Rückstand pausiert die Vorschau: fertige Abschnitte gehen vor.
_PARTIAL_MAX_BACKLOG_S = 3.0
# Tempo (Rechenzeit je Audiosekunde) über die letzten fertigen Abschnitte gemittelt.
_RTF_WINDOW = 10


@dataclass(frozen=True)
class LiveOptions:
    output_dir: Path
    model: str
    device: str
    compute_type: str
    backend: str = "faster-whisper"  # faster-whisper | mlx (Apple Silicon)
    language: str = "de"
    monitor: int = 1  # 0 = ohne Bildschirm
    window: int = 0  # HWND eines Anwendungsfensters; hat Vorrang vor monitor
    mic: str = "default"  # "default" | "none" | Geräteindex
    loopback: str = "default"
    sensitivity: str = "mittel"
    bildformat: str = "jpg-1600"
    partials: bool = True
    speakers: bool = True
    hf_token: str | None = None
    sentences_per_timestamp: int = 2
    cpu_threads: int = 0  # 0 = Bibliotheks-Default
    # Schnitt: Abschnitt zu nach pause_s Sprechpause, spätestens nach max_chunk_s.
    pause_s: float = 0.6
    max_chunk_s: float = 12.0
    # Vorschau: ab partial_min_s offenem Audio, höchstens alle partial_interval_s.
    partial_min_s: float = 1.0
    partial_interval_s: float = 2.0
    # VAD jeden Takt (0,25 s) statt jeden zweiten: ~0,25 s weniger Verzögerung.
    vad_every_tick: bool = False
    # Aufholmodus (PRD §17, NFR-15): ab catchup_s WARTENDEM Rückstand billig dekodieren,
    # wartende Abschnitte derselben Spur bis coalesce_s zusammenlegen (0 = nie).
    catchup_s: float = 5.0
    coalesce_s: float = 25.0
    force_eco: bool = False  # Messläufe: jeden Abschnitt sparsam dekodieren (--eco)
    # WAV-Replay statt Audio-Geräten (FR-49); speed > 1 lässt die Sitzungsuhr schneller
    # laufen (nur für Funktionstests - Latenzen sind dann nicht mehr vergleichbar).
    replay_system: Path | None = None
    replay_mic: Path | None = None
    speed: float = 1.0
    # Wiederaufnahme (PRD §21): diesen Sitzungsordner fortsetzen statt einen neuen anzulegen.
    resume_dir: Path | None = None
    titel: str = ""


class LiveSession:
    def __init__(self, opts: LiveOptions) -> None:
        self.opts = opts
        self._resume = opts.resume_dir is not None
        self.dir = Path(opts.resume_dir) if self._resume else Path(opts.output_dir) / session_name()
        self._stop = threading.Event()
        self._threads_stop = threading.Event()
        self._lock = threading.Lock()  # Segmente, offene Abschnitte
        self._io_lock = threading.Lock()  # Dateien im Sitzungsordner
        self._segments: list[Segment] = []
        self._marks: list[Mark] = []
        self._open: dict[str, int | None] = {}
        self._last_delay: float | None = None
        self._board = JobBoard(coalesce_s=opts.coalesce_s)
        self._catchup = False
        self._t0 = 0.0
        self._chunk_index = 0  # nur im Transkriptions-Thread
        # Diagnose-Log (FR-47); daraus entsteht am Ende das Fazit (FR-46).
        self._diagnose = Diagnose(self.dir / DIAGNOSE_NAME)
        # Absturzsicherung (PRD §21). Die Segment-ID ist ein eigener Zähler und steht im
        # Journal: Souffleur-Markierungen und die Anker im Browser hängen an ihr.
        self._seg_id = 0
        self._bestand: list[dict] = []  # wiederhergestellte Segmentzeilen des Journals
        self._start_sample = 0  # Startversatz dieses Aufnahme-Teils auf der Zeitleiste
        self._basis_s = 0.0
        self._teil_nr = 1
        self._sitzung_id = uuid.uuid4().hex
        self._titel = opts.titel.strip()
        self._journal = journal.Journal(self.dir)
        self._sperre: journal.Sperre | None = None
        self._status_offen = False  # sitzung.json steht auf "laeuft" und gehört diesem Lauf
        self._notfall = threading.Event()  # stdout tot: der Server ist weg
        if self._resume:
            self._lade_bestand()

    def clock(self) -> float:
        """Sitzungsuhr in Sekunden seit Aufnahmestart; beim Replay ggf. beschleunigt.

        Nach einer Wiederaufnahme läuft sie ab dem Startversatz weiter - die Zeitleiste der
        Sitzung bleibt lückenlos, und Sample-Position im Mitschnitt = Sitzungszeit."""
        return self._basis_s + (time.monotonic() - self._t0) * self.opts.speed

    # --- Wiederaufnahme ------------------------------------------------------

    def _lade_bestand(self) -> None:
        """Erst laden, dann schreiben: Segmente, Standbilder, Diagnose und Startversatz."""
        status = journal.lies_status(self.dir)
        if status is None:
            raise RuntimeError(f"Keine fortsetzbare Sitzung ({journal.STATUS_DATEI} fehlt): {self.dir}")
        if status.get("replay"):
            raise RuntimeError("Ein Transkript-Replay lässt sich nicht fortsetzen.")
        if status.get("status") in (journal.BEENDET, journal.VERWORFEN):
            raise RuntimeError(f"Die Sitzung ist {status.get('status')} und wird nicht fortgesetzt: {self.dir}")
        bestand = journal.lies_journal(self.dir)
        self._bestand = sorted(bestand.segmente, key=lambda s: int(s["id"]))
        self._segments = [
            Segment(float(s["start"]), float(s["end"]), str(s["text"]), s.get("speaker")) for s in self._bestand
        ]
        self._seg_id = bestand.letzte_id
        self._marks = lade_marks(self.dir, bestand.shots)
        self._chunk_index = self._diagnose.uebernehme(lies_diagnose(self.dir))
        self._sitzung_id = str(status.get("sitzung_id") or self._sitzung_id)
        self._titel = self._titel or str(status.get("titel") or "")
        teile = _teile(status)
        self._teil_nr = max((int(t.get("nr") or 0) for t in teile), default=0) + 1
        # Reste eines gescheiterten Fortsetzungsversuchs (Spur geöffnet, dann Abbruch vor dem
        # Eintrag in sitzung.json) blockieren die Nummer nicht - Track öffnet nie Vorhandenes.
        while any((self.dir / teil_wav(spur, self._teil_nr)).exists() for spur in SPUR_WAV):
            self._teil_nr += 1
        # Der Takt ist Sekunden älter als der Mitschnitt, der bis zum Absturz weiterlief:
        # läge der Versatz unter der Länge eines Teils, überlappten die Teile.
        samples = math.ceil(max([bestand.ende_s] + [m.t for m in self._marks]) * SAMPLE_RATE)
        for teil in teile:
            for rel in (teil.get("spuren") or {}).values():
                samples = max(samples, int(teil.get("start_sample") or 0) + wav_frames(self.dir / rel))
        self._start_sample = samples
        self._basis_s = samples / SAMPLE_RATE

    def _sichere_alte_teile(self) -> None:
        """Mitschnitte früherer Teile, die noch den Endnamen tragen, zu ``…teilN.wav`` machen.

        Der Endname (``mikrofon.wav``) entsteht erst wieder beim sauberen Abschluss, und zwar
        nur aus Teilen (``store.verbinde_teile``) - so hängt nie ein Teil doppelt an."""
        status = journal.lies_status(self.dir) or {}
        teile = _teile(status)
        geaendert = False
        for teil in teile:
            spuren = dict(teil.get("spuren") or {})
            for spur, rel in list(spuren.items()):
                if spur in SPUR_WAV and rel == SPUR_WAV[spur] and (self.dir / rel).is_file():
                    neu = teil_wav(spur, int(teil.get("nr") or 1))
                    os.replace(self.dir / rel, self.dir / neu)
                    spuren[spur] = neu
                    geaendert = True
            teil["spuren"] = spuren
        if geaendert:
            journal.schreibe_status(self.dir, teile=teile)

    def _melde_bestand(self) -> None:
        """Das bisherige Transkript sofort an Runner und Browser - als ``restored``."""
        for s in self._bestand:
            events.emit(
                events.SEGMENT,
                id=int(s["id"]),
                track=s.get("track") or "system",
                speaker=s.get("speaker"),
                start=round(float(s["start"]), 2),
                end=round(float(s["end"]), 2),
                text=str(s["text"]),
                delay=s.get("delay"),
                restored=True,
            )
        for mark in self._marks:
            if mark.id is not None:
                events.emit(events.SHOT, id=mark.id, t=mark.t, file=Path(mark.png).name, restored=True)
        events.log(
            f"Sitzung wird fortgesetzt: {len(self._bestand)} Abschnitte, {len(self._marks)} Standbilder, "
            f"weiter bei {format_timecode(self._basis_s)} (Teil {self._teil_nr})"
        )

    def _wav_name(self, spur: str) -> str:
        return SPUR_WAV[spur] if self._teil_nr == 1 else teil_wav(spur, self._teil_nr)

    def _beginne_teil(self, spuren: dict[str, str]) -> None:
        """Zustand ``laeuft`` samt diesem Aufnahme-Teil eintragen - ab hier ist die Sitzung
        nach einem Absturz fortsetzbar."""
        status = journal.lies_status(self.dir) or {}
        teile = [t for t in _teile(status) if int(t.get("nr") or 0) < self._teil_nr]
        teile.append({"nr": self._teil_nr, "start_sample": self._start_sample, "spuren": spuren})
        journal.schreibe_status(
            self.dir,
            sitzung_id=self._sitzung_id,
            status=journal.LAEUFT,
            titel=self._titel,
            sprache=self.opts.language,
            modell=self.opts.model,
            replay=False,
            pid=os.getpid(),
            teile=teile,
        )
        self._status_offen = True
        if self._resume:
            self._journal.zeile(journal.ART_TEIL, nr=self._teil_nr, start_sample=self._start_sample)

    def _setze_status(self, status: str) -> None:
        """Zustand ändern - nur, wenn die Sitzung eine Zustandsdatei hat."""
        if journal.lies_status(self.dir) is not None:
            journal.schreibe_status(self.dir, status=status)
        self._status_offen = False

    def _server_weg(self) -> None:
        """stdout ist tot (der Server ist gestorben): geordnet anhalten statt abzureißen."""
        self._notfall.set()
        self._stop.set()

    def _notabschluss(self) -> int:
        """Audio ist geschlossen: sichern, was da ist, und die Sitzung fortsetzbar lassen.
        Wartende Abschnitte werden nicht mehr gerechnet - sie stehen im Mitschnitt."""
        self._threads_stop.set()
        try:
            self._persist()
        except Exception:  # noqa: BLE001 - der Notabschluss sichert, so viel geht
            pass
        self._diagnose.close()
        self._setze_status(journal.UNTERBROCHEN)
        return 1

    # --- Ablauf -------------------------------------------------------------

    def run(self) -> int:
        events.bei_stdout_tot(self._server_weg)
        try:
            return self._run()
        finally:
            self._journal.close()
            if self._status_offen:
                # Ausnahme mitten in der Aufnahme: die Sitzung bleibt fortsetzbar.
                self._setze_status(journal.UNTERBROCHEN)
            if self._sperre is not None:
                self._sperre.gib_frei()
                self._sperre = None

    def _run(self) -> int:
        from audioscribe.live.capture import ensure_permissions, pick
        from audioscribe.live.speakers import SpeakerLabeler

        o = self.opts
        t_start = time.monotonic()
        if self._resume:
            # Vor allem anderen: kein zweiter Prozess auf demselben Ordner, und das bisherige
            # Transkript steht sofort in der Oberfläche - nicht erst nach dem Modellladen.
            self._sperre = journal.sperre(self.dir)
            self._state("laden", step="Sitzung wiederherstellen")
            self._melde_bestand()
            self._sichere_alte_teile()
        self._state("laden", step=f"Whisper {o.model}")
        wie = "Metal" if o.backend == "mlx" else o.compute_type
        events.log(f"Lade Modell {o.model} ({o.backend}, {o.device}, {wie}) ...")
        started = time.monotonic()
        self._asr = self._load_asr()
        events.log(f"Whisper {o.model} geladen ({_took(started)})")
        # Vor dem Hintergrund-Thread: torch.set_num_threads wirkt prozessweit.
        self._limit_torch_threads()
        self._labeler = SpeakerLabeler(self._load_embedder(), pfad=self.dir / SPRECHER_DATEI)
        self._state("laden", step="Sprachaktivität (VAD)")
        started = time.monotonic()
        vad = self._load_vad()
        events.log(f"Sprachaktivität bereit ({_took(started)})")

        self.dir.mkdir(parents=True, exist_ok=True)
        if self._sperre is None:
            self._sperre = journal.sperre(self.dir)  # Lebenszeichen für die Dauer des Prozesses
        if o.replay_system is None and o.replay_mic is None:
            # Vor der Sitzungsuhr: die macOS-Dialoge dürfen nicht in die Aufnahme fallen.
            self._state("laden", step="Berechtigungen")
            ensure_permissions(
                mic=o.mic.strip().lower() != "none", system=o.loopback.strip().lower() != "none", log=events.log
            )
        self._state("laden", step="Audio-Geräte")
        self._t0 = time.monotonic()
        audio = self._open_capture()
        tracks: dict = {}
        screen = None
        try:
            spuren: dict[str, str] = {}
            for name, wahl, geraete in (
                ("mic", o.mic, audio.mics),
                ("system", o.loopback, audio.loopbacks),
            ):
                device = pick(geraete, wahl)
                if device is None:
                    events.log(f"Spur '{name}': aus")
                    continue
                spuren[name] = self._wav_name(name)
                tracks[name] = audio.open(name, device, self.dir / spuren[name])
                events.log(f"Spur '{name}': {device['name']} ({device['rate']} Hz)")
            if not tracks and not (o.monitor or o.window):
                events.log("Weder Audio noch Bildquelle gewählt - nichts aufzunehmen.")
                return 1

            self._beginne_teil(spuren)
            chunkers = {
                name: Chunker(vad, pause_s=o.pause_s, max_s=o.max_chunk_s, start=self._start_sample)
                for name in tracks
            }
            threads = [
                threading.Thread(target=self._cut_loop, args=(tracks, chunkers), daemon=True),
                threading.Thread(target=self._asr_loop, daemon=True),
                threading.Thread(target=self._watch_stdin, daemon=True),
            ]
            screen = self._start_screen()
            for thread in threads:
                thread.start()

            self._state("laeuft")  # Maschinenwert wie ui.runner.RUNNING, darum ohne Umlaut
            self._main_loop(tracks)
        finally:
            aufnahme_s = self.clock()
            self._state("stoppt")
            audio.close()
        if screen is not None:
            screen.stop()
            screen.join(timeout=5)

        # Nach dem Schließen der Streams: Rest einlesen, offene Abschnitte abschließen.
        threads[0].join(timeout=5)
        if self._notfall.is_set():
            return self._notabschluss()
        for name, track in tracks.items():
            chunkers[name].feed(*track.take(self.clock()))
            for utt in chunkers[name].poll(flush=True):
                self._board.put_final(Job(name, utt, final=True, t_abgeschlossen=self.clock()))
        stopped = time.monotonic()
        self._drain()
        self._threads_stop.set()
        self._finish(
            laden_s=self._t0 - t_start, aufnahme_s=aufnahme_s, abschluss_s=time.monotonic() - stopped,
            gesamt_s=time.monotonic() - t_start,
        )
        return 0

    def _finish(self, *, laden_s: float, aufnahme_s: float, abschluss_s: float, gesamt_s: float) -> None:
        """Transkript und Live-Fassung sichern, Fazit ablegen und melden (FR-46)."""
        self._persist()
        bilanz = self._diagnose.bilanz(
            laden_s=laden_s, aufnahme_s=aufnahme_s, abschluss_s=abschluss_s, gesamt_s=gesamt_s,
            schwelle_s=self.opts.max_chunk_s,
        )
        bilanz = replace(bilanz, backend=self.opts.backend, geraet=self.opts.device, modell=self.opts.model)
        self._diagnose.close()
        with self._io_lock:
            keep_live_copy(self.dir, overwrite=True)
            save_bilanz(self.dir, TEIL_LIVE, bilanz)
        # Hat niemand mehr zugehört (Server weg), bleibt die Sitzung fortsetzbar und die
        # Teile bleiben getrennt; sonst entsteht jetzt wieder EINE WAV je Spur.
        allein = events.stdout_tot()
        if not allein:
            try:
                verbinde_teile(self.dir)
            except OSError as exc:
                events.log(f"Mitschnitt-Teile nicht verbunden: {exc}")
        self._setze_status(journal.UNTERBROCHEN if allein else journal.BEENDET)
        events.log(beschreibe_live(bilanz))
        # Vor "fertig": der Runner muss das Fazit haben, bevor er das Nachschärfen anstößt.
        events.emit(events.FAZIT, teil=TEIL_LIVE, **asdict(bilanz))
        self._state("fertig")
        events.log(f"Sitzung gespeichert: {self.dir}")

    def _main_loop(self, tracks: dict) -> None:
        last_persist = last_takt = time.monotonic()
        try:
            while not self._stop.wait(1.0 / self.opts.speed):
                backlog = self._board.backlog_s()
                self._diagnose.rueckstand(self.clock(), backlog)
                events.emit(
                    events.STATS,
                    elapsed=round(self.clock(), 1),
                    backlog=round(backlog, 1),
                    delay=self._last_delay,
                    level_mic=round(tracks["mic"].level, 3) if "mic" in tracks else None,
                    level_sys=round(tracks["system"].level, 3) if "system" in tracks else None,
                    partials_paused=self.opts.partials and backlog > _PARTIAL_MAX_BACKLOG_S,
                    rtf=self.rtf(),
                    catchup=self._catchup,
                )
                if time.monotonic() - last_takt >= _TAKT_S:
                    self._journal.takt(self.clock())
                    last_takt = time.monotonic()
                if time.monotonic() - last_persist >= _PERSIST_S:
                    self._persist()
                    last_persist = time.monotonic()
        except KeyboardInterrupt:
            events.log("Strg+C - Sitzung wird abgeschlossen ...")
        self._stop.set()

    def _drain(self) -> None:
        """Wartet auf die letzten Abschnitte; ein zweites Strg+C bricht das Warten ab."""
        backlog = self._board.backlog_s()
        if backlog:
            events.log(f"Transkribiere die letzten {backlog:.0f} s ...")
        try:
            while not self._board.wait_idle(1.0):
                pass
        except KeyboardInterrupt:
            events.log("Warten abgebrochen - der Rest steht nur im Mitschnitt.")

    # --- Threads ------------------------------------------------------------

    def _cut_loop(self, tracks: dict, chunkers: dict[str, Chunker]) -> None:
        last_partial = dict.fromkeys(tracks, 0.0)
        tick = 0
        while not self._stop.wait(_TICK_S / self.opts.speed):
            tick += 1
            now = self.clock()
            for name, track in tracks.items():
                chunker = chunkers[name]
                chunker.feed(*track.take(now))
                if tick % 2 and not self.opts.vad_every_tick:
                    continue  # VAD nur jeden zweiten Takt - sie ist der teure Teil
                done = chunker.poll()
                for utt in done:
                    self._board.put_final(Job(name, utt, final=True, t_abgeschlossen=now))
                self._offer_partial(name, chunker, bool(done), now, last_partial)

    def _offer_partial(
        self, name: str, chunker: Chunker, finalized: bool, now: float, last_partial: dict
    ) -> None:
        utt = chunker.open_utterance()
        with self._lock:
            was_open = self._open.get(name) is not None
            self._open[name] = utt.start if utt else None
        if utt is None:
            self._board.drop_partial(name)
            if was_open and not finalized:
                events.emit(events.PARTIAL, track=name, text="")  # VAD hat zurückgezogen
            return
        if (
            self.opts.partials
            and utt.duration_s >= self.opts.partial_min_s
            and now - last_partial[name] >= self.opts.partial_interval_s
            and self._board.backlog_s() <= _PARTIAL_MAX_BACKLOG_S
        ):
            last_partial[name] = now
            self._board.put_partial(Job(name, utt, final=False))

    def _asr_loop(self) -> None:
        while not self._threads_stop.is_set():
            job = self._board.get(0.5)
            if job is None:
                continue
            try:
                if job.final:
                    self._do_final(job)
                else:
                    self._do_partial(job)
            except Exception as exc:  # noqa: BLE001 - ein Abschnitt darf die Sitzung nie kippen
                events.log(f"Transkription fehlgeschlagen: {exc}")
            finally:
                self._board.done(job)

    def _still_open(self, job: Job) -> bool:
        with self._lock:
            return self._open.get(job.track) == job.utterance.start

    def _do_partial(self, job: Job) -> None:
        if not self._still_open(job):
            return
        t_start = self.clock()
        started = time.monotonic()
        erg = Ergebnis.von(self._asr.transcribe(job.utterance.audio, final=False))
        self._diagnose.vorschau(
            Vorschau(
                track=job.track,
                t_start=round(t_start, 2),
                fenster_s=round(job.utterance.duration_s, 2),
                rechenzeit_s=round(time.monotonic() - started, 3),
                modell=self.opts.model,
            )
        )
        if erg.text and self._still_open(job):
            events.emit(
                events.PARTIAL, track=job.track, start=round(job.utterance.start_s, 2), text=erg.text
            )

    def _do_final(self, job: Job) -> None:
        utt = job.utterance
        # Der Rückstand zählt nur wartende Abschnitte - dieser hier ist keiner mehr.
        eco = self._enter_catchup(self._board.backlog_s()) or self.opts.force_eco
        t_start = self.clock()
        started = time.monotonic()
        erg = Ergebnis.von(self._asr.transcribe(utt.audio, final=True, eco=eco))
        text = erg.text
        rechenzeit = time.monotonic() - started
        started = time.monotonic()
        speaker = self._labeler.label(job.track, utt.audio) if text else None
        sprecher = time.monotonic() - started
        t_ende = self.clock()
        self._chunk_index += 1
        self._diagnose.abschnitt(
            Abschnitt(
                chunk_index=self._chunk_index,
                track=job.track,
                audio_start_s=round(utt.start_s, 2),
                audio_end_s=round(utt.end_s, 2),
                audio_dauer_s=round(utt.duration_s, 2),
                t_abgeschlossen=round(job.t_abgeschlossen, 2),
                t_start=round(t_start, 2),
                t_ende=round(t_ende, 2),
                wartezeit_s=round(t_start - job.t_abgeschlossen, 2),
                rechenzeit_s=round(rechenzeit, 3),
                sprecher_s=round(sprecher, 3),
                latenz_s=round(t_ende - utt.end_s, 2),
                latenz_max_s=round(t_ende - utt.erster_teil_end_s, 2),
                modell=self.opts.model,
                eco=eco,
                parts=job.parts,
                anzahl_woerter=len(text.split()),
                schluss=utt.schluss,
                segmente=[asdict(s) for s in erg.segmente],
            )
        )
        if not text:
            events.emit(events.PARTIAL, track=job.track, text="")
            return
        with self._lock:
            self._segments.append(Segment(utt.start_s, utt.end_s, text, speaker))
            self._seg_id += 1
            number = self._seg_id
            self._last_delay = round(t_ende - utt.end_s, 1)
        # Vor der Meldung: was die Oberfläche gesehen hat, übersteht auch einen Absturz.
        self._journal.segment(
            id=number, track=job.track, speaker=speaker, start=utt.start_s, end=utt.end_s, text=text,
            delay=self._last_delay,
        )
        events.emit(
            events.SEGMENT,
            id=number,
            track=job.track,
            speaker=speaker,
            start=round(utt.start_s, 2),
            end=round(utt.end_s, 2),
            text=text,
            delay=self._last_delay,
        )

    def _watch_stdin(self) -> None:
        """``stop`` über stdin beendet die Sitzung sauber; ein Dateiende bedeutet nichts."""
        if sys.stdin is None:
            return
        for line in sys.stdin:
            if line.strip().lower() == "stop":
                self._stop.set()
                return

    # --- Hilfen -------------------------------------------------------------

    def _load_asr(self):
        from audioscribe.live.asr import make_transcriber

        o = self.opts
        return make_transcriber(
            o.backend,
            o.model,
            o.device,
            o.compute_type,
            o.language,
            on_progress=lambda done, total: events.emit(
                events.DOWNLOAD, model=o.model, done=done, total=total
            ),
            cpu_threads=o.cpu_threads,
        )

    def _load_vad(self):
        from audioscribe.live.chunker import silero_vad

        return silero_vad()

    def _open_capture(self):
        """Audio-Geräte - oder beim Replay die WAV-Dateien (FR-49)."""
        o = self.opts
        if o.replay_system is not None or o.replay_mic is not None:
            from audioscribe.live.replay import ReplayCapture

            events.log(f"Replay statt Aufnahme (Tempo {o.speed:g}×)")
            return ReplayCapture(
                self.clock, system=o.replay_system, mic=o.replay_mic, speed=o.speed, on_end=self._stop.set,
                start_sample=self._start_sample,
            )
        from audioscribe.live.capture import open_capture

        if self._start_sample:
            return open_capture(self.clock, start_sample=self._start_sample)
        return open_capture(self.clock)

    def _enter_catchup(self, backlog_s: float) -> bool:
        """Sparmodus an/aus je nach Rückstand; der Wechsel wird einmal protokolliert."""
        catchup = backlog_s > self.opts.catchup_s
        if catchup != self._catchup:
            self._catchup = catchup
            if catchup:
                events.log(
                    f"Rückstand {backlog_s:.0f} s - Aufholmodus: Abschnitte zusammenlegen, Beam 1"
                )
            else:
                events.log("Rückstand abgebaut - wieder volle Qualität")
        return catchup

    def rtf(self) -> float | None:
        """Rechenzeit je Audiosekunde über die letzten Abschnitte (None ohne Messung)."""
        return self._diagnose.tempo_letzte(_RTF_WINDOW)

    def _limit_torch_threads(self) -> None:
        """torch (Sprecher-Embedding) auf dieselbe Threadzahl wie ctranslate2 begrenzen."""
        if self.opts.cpu_threads <= 0 or self.opts.device != "cpu":
            return
        try:
            import torch

            torch.set_num_threads(self.opts.cpu_threads)
        except Exception:  # noqa: BLE001 - ohne torch (kein Embedder) gibt es nichts zu begrenzen
            pass

    def _load_embedder(self):
        """Sprecher-Modell im Hintergrund; der erste System-Abschnitt wartet darauf."""
        o = self.opts
        if not o.speakers or o.loopback.strip().lower() == "none":
            return None
        if not o.hf_token:
            events.log("HF_TOKEN fehlt - System-Spur heißt 'Gegenseite' statt 'Sprecher N'")
            return None
        from audioscribe.live.speakers import BackgroundEmbedder

        def load():
            from audioscribe.live.speakers import SpeakerEmbedder

            return SpeakerEmbedder(o.device, o.hf_token)

        events.log("Sprecher-Modell lädt im Hintergrund ...")
        return BackgroundEmbedder(load, log=events.log)

    def _start_screen(self):
        if not (self.opts.monitor or self.opts.window):
            return None
        try:
            from audioscribe.live.screen import ScreenWatcher

            watcher = ScreenWatcher(
                self.opts.monitor,
                self.dir,
                self.clock,
                self._on_shot,
                window=self.opts.window,
                sensitivity=self.opts.sensitivity,
                bildformat=self.opts.bildformat,
                log=events.log,
                start_id=max((m.id or 0 for m in self._marks), default=0),
            )
            watcher.start()
            return watcher
        except ImportError:
            events.log("mss fehlt - keine Standbilder (uv sync ... --extra live)")
            return None

    def _on_shot(self, mark: Mark) -> None:
        with self._io_lock:
            self._marks.append(mark)
            save_marks(self.dir, self._marks)
        self._journal.shot(id=mark.id, t=mark.t, png=mark.png, created=mark.created, kind=mark.kind)
        events.emit(events.SHOT, id=mark.id, t=mark.t, file=Path(mark.png).name)

    def _persist(self) -> None:
        with self._lock:
            segments = list(self._segments)
        with self._io_lock:
            write_transcript(
                self.dir,
                segments,
                duration_s=self.clock(),
                language=self._asr.detected or self.opts.language,
                model=self.opts.model,
                mode="live",
                sentences_per_timestamp=self.opts.sentences_per_timestamp,
            )
        labeler = getattr(self, "_labeler", None)
        if labeler is not None:
            labeler.sichere()

    def _state(self, phase: str, **extra: object) -> None:
        if self._resume:
            extra = {"fortgesetzt": True, **extra}
        events.emit(
            events.STATE,
            phase=phase,
            session=self.dir.name,
            dir=str(self.dir),
            model=self.opts.model,
            device=self.opts.device,
            backend=self.opts.backend,
            sitzung_id=self._sitzung_id,
            titel=self._titel,
            **extra,
        )


def _took(started: float) -> str:
    return f"{time.monotonic() - started:.1f} s"


# --- Wiederaufnahme: Hilfen und Abschluss ohne Modelle (PRD §21) ------------------------


def _teile(status: dict) -> list[dict]:
    return [dict(t) for t in status.get("teile") or [] if isinstance(t, dict)]


def lade_marks(session_dir: Path, shots: list[dict]) -> list[Mark]:
    """Standbilder aus ``marks.json``, ergänzt um die Journalzeilen.

    Eine beim Absturz halb geschriebene ``marks.json`` (ältere Stände schrieben nicht atomar)
    darf die Wiederaufnahme nicht kippen - dann trägt das Journal allein."""
    try:
        marks = load_marks(session_dir)
    except (OSError, ValueError, KeyError, TypeError):
        marks = []
    bekannt = {m.png for m in marks}
    for shot in shots:
        png = str(shot.get("png") or "")
        if not png or png in bekannt:
            continue
        bekannt.add(png)
        marks.append(
            Mark(
                t=float(shot["t"]),
                png=png,
                created=shot.get("created"),
                id=int(shot["id"]) if shot.get("id") is not None else None,
                kind=shot.get("kind"),
            )
        )
    marks.sort(key=lambda m: m.t)
    return marks


def finalisiere_sitzung(session_dir: str | Path, *, sentences_per_timestamp: int = 2) -> int:
    """``live --finalize``: eine unterbrochene Sitzung ohne Modelle sauber abschließen.

    Transkript aus dem Journal, Mitschnitt-Teile zu einer WAV je Spur (mit repariertem
    Kopf), Live-Fassung sichern, Zustand ``beendet``. Am Ende steht wie bei einer echten
    Sitzung ``state fertig`` mit dem Ordner - der Runner kann danach nachschärfen."""
    session_dir = Path(session_dir)
    status = journal.lies_status(session_dir)
    if status is None:
        events.log(f"Keine Sitzung zum Abschließen ({journal.STATUS_DATEI} fehlt): {session_dir}")
        return 1
    if status.get("replay"):
        events.log("Ein Transkript-Replay braucht keinen Abschluss.")
        return 1
    if status.get("status") in (journal.BEENDET, journal.VERWORFEN):
        events.log(f"Die Sitzung ist bereits {status.get('status')}: {session_dir}")
        return 1
    try:
        sperre = journal.sperre(session_dir)
    except RuntimeError as exc:
        events.log(str(exc))
        return 1
    t_start = time.monotonic()
    modell = str(status.get("modell") or "")
    zustand = dict(
        session=session_dir.name, dir=str(session_dir), model=modell, device="-",
        sitzung_id=str(status.get("sitzung_id") or ""), titel=str(status.get("titel") or ""),
    )
    try:
        events.emit(events.STATE, phase="laden", step="Sitzung abschließen", **zustand)
        bestand = journal.lies_journal(session_dir)
        segments = [
            Segment(float(s["start"]), float(s["end"]), str(s["text"]), s.get("speaker"))
            for s in sorted(bestand.segmente, key=lambda s: int(s["id"]))
        ]
        marks = lade_marks(session_dir, bestand.shots)
        if marks:
            save_marks(session_dir, marks)
        # Das Gesicherte auch an Runner und Browser - die Oberflaeche zeigt, was abgeschlossen wird.
        for s in sorted(bestand.segmente, key=lambda s: int(s["id"])):
            events.emit(
                events.SEGMENT, id=int(s["id"]), track=s.get("track") or "system", speaker=s.get("speaker"),
                start=round(float(s["start"]), 2), end=round(float(s["end"]), 2), text=str(s["text"]),
                delay=s.get("delay"), restored=True,
            )
        for mark in marks:
            if mark.id is not None:
                events.emit(events.SHOT, id=mark.id, t=mark.t, file=Path(mark.png).name, restored=True)
        verbinde_teile(session_dir)
        dauer = max(
            [bestand.ende_s]
            + [m.t for m in marks]
            + [wav_frames(session_dir / rel) / SAMPLE_RATE for rel in SPUR_WAV.values()]
        )
        write_transcript(
            session_dir,
            segments,
            duration_s=dauer,
            language=str(status.get("sprache") or "de"),
            model=modell,
            mode="live",
            sentences_per_timestamp=sentences_per_timestamp,
        )
        keep_live_copy(session_dir, overwrite=True)
        diagnose = Diagnose(session_dir / DIAGNOSE_NAME)
        diagnose.uebernehme(lies_diagnose(session_dir))
        bilanz = diagnose.bilanz(
            laden_s=0.0, aufnahme_s=dauer, abschluss_s=0.0, gesamt_s=time.monotonic() - t_start, schwelle_s=12.0
        )
        bilanz = replace(bilanz, modell=modell)
        diagnose.close()
        save_bilanz(session_dir, TEIL_LIVE, bilanz)
        journal.schreibe_status(session_dir, status=journal.BEENDET)
        events.log(f"Abgeschlossen aus dem Journal: {len(segments)} Abschnitte, {len(marks)} Standbilder")
        events.log(beschreibe_live(bilanz))
        events.emit(events.FAZIT, teil=TEIL_LIVE, **asdict(bilanz))
        events.emit(events.STATE, phase="fertig", **zustand)
        events.log(f"Sitzung gespeichert: {session_dir}")
        return 0
    finally:
        sperre.gib_frei()
