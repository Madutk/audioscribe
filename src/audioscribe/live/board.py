"""Auftragsbrett des Transkriptions-Threads: fertige Abschnitte zuerst, Vorschau zuletzt.

Vorschau-Aufträge sind Wegwerfware - je Spur zählt nur der neueste, und sie kommen erst
dran, wenn kein fertiger Abschnitt wartet. So kann die Vorschau den Rückstand nie
vergrößern, nur freie Rechenzeit nutzen.

Aufholmodus: Warten mehrere fertige Abschnitte derselben Spur, gehen sie zusammengelegt
als ein Stück (bis ``coalesce_s``) an den Transkriptions-Thread. Whisper polstert jede
Eingabe auf 30 s, ein Stück kostet also fast so viel wie ein einzelner Abschnitt - so
holt die CPU auf. Bei leerem Brett ändert sich nichts.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from audioscribe.live.chunker import Utterance, merge_utterances


@dataclass
class Job:
    track: str
    utterance: Utterance
    final: bool
    parts: int = 1  # zusammengelegte Abschnitte (Aufholmodus)


class JobBoard:
    def __init__(self, coalesce_s: float = 0.0, max_gap_s: float = 3.0) -> None:
        self._cond = threading.Condition()
        self._finals: deque[Job] = deque()
        self._partials: dict[str, Job] = {}
        self._active_s = 0.0
        self._coalesce_s = coalesce_s  # 0 = nie zusammenlegen
        self._max_gap_s = max_gap_s

    def put_final(self, job: Job) -> None:
        with self._cond:
            self._finals.append(job)
            self._partials.pop(job.track, None)
            self._cond.notify()

    def put_partial(self, job: Job) -> None:
        with self._cond:
            self._partials[job.track] = job
            self._cond.notify()

    def drop_partial(self, track: str) -> None:
        with self._cond:
            self._partials.pop(track, None)

    def get(self, timeout: float) -> Job | None:
        with self._cond:
            if not self._finals and not self._partials:
                self._cond.wait(timeout)
            if self._finals:
                job = self._take_final()
                self._active_s = job.utterance.duration_s
                return job
            if self._partials:
                return self._partials.pop(next(iter(self._partials)))
            return None

    def _take_final(self) -> Job:
        """Nächster fertiger Abschnitt - im Aufholmodus samt seinen direkten Nachfolgern."""
        first = self._finals.popleft()
        parts = [first.utterance]
        while self._finals and self._coalesce_s > 0:
            nxt = self._finals[0]
            gap_s = nxt.utterance.start_s - parts[-1].end_s
            total_s = nxt.utterance.end_s - parts[0].start_s
            if nxt.track != first.track or gap_s > self._max_gap_s or total_s > self._coalesce_s:
                break
            parts.append(self._finals.popleft().utterance)
        if len(parts) == 1:
            return first
        return Job(first.track, merge_utterances(parts), final=True, parts=len(parts))

    def done(self, job: Job) -> None:
        if job.final:
            with self._cond:
                self._active_s = 0.0
                self._cond.notify_all()

    def backlog_s(self) -> float:
        """Sekunden fertig gesprochenes, noch nicht transkribiertes Audio."""
        with self._cond:
            return self._active_s + sum(j.utterance.duration_s for j in self._finals)

    def wait_idle(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait_for(
                lambda: not self._finals and self._active_s == 0.0, timeout
            )
