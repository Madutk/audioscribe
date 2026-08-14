"""Fortschritts-Reporting fuer die CLI (bewusst minimal gehalten)."""

from __future__ import annotations

from typing import Protocol


class Reporter(Protocol):
    def stage(self, index: int, name: str) -> None: ...
    def info(self, message: str) -> None: ...


class ConsoleReporter:
    """Einfacher Stufen-Tracker fuer die Kommandozeile."""

    def __init__(self, total: int) -> None:
        self.total = total

    def stage(self, index: int, name: str) -> None:
        print(f"\n[Stufe {index}/{self.total}] {name}", flush=True)

    def info(self, message: str) -> None:
        print(f"   - {message}", flush=True)


def emit_progress(percent: float) -> None:
    """Maschinenlesbarer Feinfortschritt innerhalb einer Stufe (0..100).

    Bewusst eine Modulfunktion und KEIN weiteres Mitglied von ``Reporter``: dieses
    Protokoll ist oeffentlich (``run_pipeline(reporter=...)``), ein zusaetzliches
    Mitglied wuerde fremde Reporter-Implementierungen mit AttributeError brechen.
    Das Format entspricht dem, was WhisperX selbst ausgibt ("Progress: 42.50%..."),
    damit die Oberflaeche beide Quellen mit einem Ausdruck lesen kann.
    """
    print(f"[Fortschritt] {max(0.0, min(100.0, percent)):.1f}%", flush=True)
