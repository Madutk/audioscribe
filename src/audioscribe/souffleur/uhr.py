"""Schätzer für die Sitzungsuhr des Live-Kindprozesses.

Der Kindprozess meldet ``stats.elapsed`` einmal je Sitzungssekunde (bei ``speed`` ≠ 1 alle
``1/speed`` realen Sekunden). Dazwischen rechnet der Server mit der eigenen Monotonuhr weiter.
Der Fehler bleibt unter der Rundung von ``elapsed`` (0,1 s) plus Pipe-Latenz.
"""

from __future__ import annotations

import threading
import time


class SitzungsUhr:
    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed if speed > 0 else 1.0
        self._lock = threading.Lock()
        self._elapsed: float | None = None
        self._t_sync = 0.0

    def sync(self, elapsed: float, *, mono: float | None = None) -> None:
        with self._lock:
            self._elapsed = float(elapsed)
            self._t_sync = time.monotonic() if mono is None else mono

    def jetzt(self, *, mono: float | None = None) -> float | None:
        """Geschätzte Sitzungszeit; ``None`` bis zur ersten Meldung."""
        with self._lock:
            if self._elapsed is None:
                return None
            now = time.monotonic() if mono is None else mono
            return self._elapsed + (now - self._t_sync) * self.speed

    def sitzungszeit_von(self, mono: float) -> float | None:
        """Sitzungszeit zu einem früheren Monotonwert (z. B. Empfang eines Segments)."""
        return self.jetzt(mono=mono)
