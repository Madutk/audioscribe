"""Auftragsbrett des Transkriptions-Threads: fertige Abschnitte zuerst, Vorschau zuletzt.

Vorschau-Aufträge sind Wegwerfware - je Spur zählt nur der neueste, und sie kommen erst
dran, wenn kein fertiger Abschnitt wartet. So kann die Vorschau den Rückstand nie
vergrößern, nur freie Rechenzeit nutzen.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from audioscribe.live.chunker import Utterance


@dataclass
class Job:
    track: str
    utterance: Utterance
    final: bool


class JobBoard:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._finals: deque[Job] = deque()
        self._partials: dict[str, Job] = {}
        self._active_s = 0.0

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
                job = self._finals.popleft()
                self._active_s = job.utterance.duration_s
                return job
            if self._partials:
                return self._partials.pop(next(iter(self._partials)))
            return None

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
