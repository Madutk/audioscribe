"""Transkript-Replay: eine gespeicherte Transkriptdatei als Live-Sitzung abspielen (FR-64).

Testfunktion für den Souffleur (PRD §20): Die Absätze einer ``transcript.json`` oder eines
``transkript.md`` werden auf der Sitzungsuhr zu ihrem Zeitstempel als ``segment``-Ereignisse
ausgegeben, als kämen sie gerade aus der Spracherkennung. Es läuft kein Audio-Backend, kein
Modell, keine Aufnahme; Phasen, Messwerte, Fazit und Sitzungsordner entsprechen aber einer
echten Sitzung, damit Oberfläche und Souffleur denselben Weg nehmen wie im Betrieb.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from audioscribe.live import events
from audioscribe.live.bilanz import TEIL_LIVE, LiveBilanz, beschreibe_live, save_bilanz
from audioscribe.live.store import keep_live_copy, session_name, write_transcript
from audioscribe.models import Segment

MODE_REPLAY = "replay"
MODELL_REPLAY = "transkript-replay"
_TICK_S = 0.25
_PERSIST_S = 30.0
# Nach dem letzten Segment: kurz warten, damit die Oberfläche das Ende noch mitbekommt.
_NACHLAUF_S = 1.0
# Letzter Absatz ohne Folgeabsatz: angenommene Sprechdauer.
_LETZTE_DAUER_S = 3.0

# ``**[HH:MM:SS] Sprecher:** Text`` - die Zeilenform von export.render_markdown; von Hand
# geschriebene Transkripte kommen oft ohne Fettdruck (``[HH:MM:SS] Sprecher: Text``).
_ZEILE = re.compile(r"^(?:\*\*)?\[(\d{1,2}):(\d\d):(\d\d)\]\s+([^:*]+?):(?:\*\*)?\s+(.*)$")
# Dateien eines Sitzungsordners in der Reihenfolge, in der sie bevorzugt werden: die
# Live-Fassung ist das, was der Souffleur im Betrieb gesehen hätte.
_ORDNER_KANDIDATEN = ("transcript.live.json", "transcript.json", "transkript.live.md", "transkript.md")


@dataclass(frozen=True)
class ReplayOptions:
    output_dir: Path
    quelle: Path  # transcript.json, transkript.md oder ein Sitzungsordner
    speed: float = 1.0
    # Konstante Verzögerung je Segment (Sekunden Sitzungsuhr) - simuliert die Latenz der
    # Spracherkennung, die im Replay sonst 0 wäre.
    delay_s: float = 0.0
    sentences_per_timestamp: int = 2


# --- Transkript lesen ------------------------------------------------------------------


def finde_transkript(quelle: Path) -> Path:
    """Die Transkriptdatei zu einer Angabe: Datei oder Sitzungsordner."""
    quelle = Path(quelle)
    if quelle.is_dir():
        for name in _ORDNER_KANDIDATEN:
            if (quelle / name).is_file():
                return quelle / name
        raise FileNotFoundError(f"Kein Transkript im Ordner: {quelle}")
    if not quelle.is_file():
        raise FileNotFoundError(f"Transkript nicht gefunden: {quelle}")
    return quelle


def lade_transkript(quelle: Path) -> list[Segment]:
    """Segmente aus ``transcript.json`` (Absätze) oder ``transkript.md`` (Zeilen), nach Start sortiert."""
    pfad = finde_transkript(quelle)
    text = pfad.read_text(encoding="utf-8")
    segmente = _aus_json(text) if pfad.suffix.lower() == ".json" else _aus_markdown(text)
    if not segmente:
        raise ValueError(f"Keine Absätze mit Zeitstempel in {pfad}")
    return sorted(segmente, key=lambda s: (s.start, s.end))


def _aus_json(text: str) -> list[Segment]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"transcript.json nicht lesbar: {exc}") from exc
    absaetze = data.get("paragraphs") if isinstance(data, dict) else None
    if not isinstance(absaetze, list):
        raise ValueError("transcript.json ohne 'paragraphs'")
    out: list[Segment] = []
    for p in absaetze:
        if not isinstance(p, dict) or not str(p.get("text", "")).strip():
            continue
        start = float(p.get("start", 0.0))
        end = float(p.get("end", start))
        out.append(Segment(start, max(end, start), str(p["text"]).strip(), str(p.get("speaker") or "Unbekannt")))
    return out


def _aus_markdown(text: str) -> list[Segment]:
    treffer = []
    for line in text.splitlines():
        m = _ZEILE.match(line.strip())
        if m and m.group(5).strip():
            h, mi, s = (int(m.group(i)) for i in (1, 2, 3))
            treffer.append((h * 3600 + mi * 60 + s, m.group(4), m.group(5).strip()))
    out: list[Segment] = []
    for i, (start, sprecher, inhalt) in enumerate(treffer):
        # Markdown kennt nur den Anfang; das Ende ist der nächste Anfang (mindestens 1 s).
        end = treffer[i + 1][0] if i + 1 < len(treffer) else start + _LETZTE_DAUER_S
        out.append(Segment(float(start), float(max(end, start + 1)), inhalt, sprecher))
    return out


# --- Sitzung -------------------------------------------------------------------------


class TranskriptReplaySession:
    """Spielt ein Transkript als Live-Sitzung ab; ``stop`` über stdin beendet vorzeitig."""

    def __init__(self, opts: ReplayOptions) -> None:
        self.opts = opts
        self.dir = Path(opts.output_dir) / session_name()
        self._stop = threading.Event()
        self._t0 = 0.0
        self._segments: list[Segment] = []  # bereits ausgegebene, für die Ablage

    def clock(self) -> float:
        return (time.monotonic() - self._t0) * self.opts.speed

    def run(self) -> int:
        o = self.opts
        t_start = time.monotonic()
        self._state("laden", step="Transkript lesen")
        try:
            alle = lade_transkript(o.quelle)
        except (OSError, ValueError) as exc:
            events.log(str(exc))
            return 1
        events.log(
            f"Replay von {finde_transkript(o.quelle)}: {len(alle)} Absätze, "
            f"{alle[-1].end:.0f} s, Tempo {o.speed:g}×, Verzögerung {o.delay_s:g} s"
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._watch_stdin, daemon=True).start()

        self._t0 = time.monotonic()
        self._state("laeuft")
        naechste = 0
        last_persist = time.monotonic()
        last_stats = -1.0
        ende_bei: float | None = None
        try:
            while not self._stop.wait(_TICK_S / o.speed):
                jetzt = self.clock()
                while naechste < len(alle) and alle[naechste].end + o.delay_s <= jetzt:
                    self._emit(naechste + 1, alle[naechste])
                    naechste += 1
                if naechste >= len(alle) and ende_bei is None:
                    ende_bei = jetzt + _NACHLAUF_S
                if ende_bei is not None and jetzt >= ende_bei:
                    break
                if jetzt - last_stats >= 1.0:
                    last_stats = jetzt
                    events.emit(
                        events.STATS, elapsed=round(jetzt, 1), backlog=0.0, delay=o.delay_s,
                        level_mic=None, level_sys=None, partials_paused=False, rtf=None, catchup=False,
                    )
                if time.monotonic() - last_persist >= _PERSIST_S:
                    self._persist()
                    last_persist = time.monotonic()
        except KeyboardInterrupt:
            events.log("Strg+C - Replay wird abgeschlossen ...")
        aufnahme_s = self.clock()
        self._state("stoppt")
        self._finish(laden_s=self._t0 - t_start, aufnahme_s=aufnahme_s, gesamt_s=time.monotonic() - t_start)
        return 0

    # --- Hilfen -------------------------------------------------------------

    def _emit(self, nummer: int, seg: Segment) -> None:
        self._segments.append(seg)
        events.emit(
            events.SEGMENT,
            id=nummer,
            track="mic" if seg.speaker == "Ich" else "system",
            speaker=seg.speaker,
            start=round(seg.start, 2),
            end=round(seg.end, 2),
            text=seg.text,
            delay=self.opts.delay_s,
        )

    def _persist(self) -> None:
        if not self._segments:
            return
        write_transcript(
            self.dir,
            list(self._segments),
            duration_s=self._segments[-1].end,
            language="de",
            model=MODELL_REPLAY,
            mode=MODE_REPLAY,
            sentences_per_timestamp=self.opts.sentences_per_timestamp,
        )

    def _finish(self, *, laden_s: float, aufnahme_s: float, gesamt_s: float) -> None:
        self._persist()
        audio_s = sum(s.end - s.start for s in self._segments)
        bilanz = LiveBilanz(
            laden_s=laden_s, aufnahme_s=aufnahme_s, abschluss_s=0.0, gesamt_s=gesamt_s,
            abschnitte=len(self._segments), audio_s=audio_s,
            verzoegerung_mittel_s=self.opts.delay_s, verzoegerung_median_s=self.opts.delay_s,
            verzoegerung_max_s=self.opts.delay_s, backend=MODE_REPLAY, geraet="-", modell=MODELL_REPLAY,
        )
        keep_live_copy(self.dir, overwrite=True)
        save_bilanz(self.dir, TEIL_LIVE, bilanz)
        events.log(beschreibe_live(bilanz))
        events.emit(events.FAZIT, teil=TEIL_LIVE, **asdict(bilanz))
        self._state("fertig")
        events.log(f"Sitzung gespeichert: {self.dir}")

    def _state(self, phase: str, **extra: object) -> None:
        # Den Ordner erst nennen, wenn es ihn gibt - scheitert schon das Lesen, verwiese die
        # Oberfläche sonst auf einen Sitzungsordner, der nie angelegt wurde.
        ordner = {"session": self.dir.name, "dir": str(self.dir)} if self.dir.is_dir() else {}
        events.emit(events.STATE, phase=phase, model=MODELL_REPLAY, device="-", replay=True, **ordner, **extra)

    def _watch_stdin(self) -> None:
        if sys.stdin is None:
            return
        try:
            for line in sys.stdin:
                if line.strip().lower() == "stop":
                    self._stop.set()
                    return
        except (OSError, ValueError):
            return
