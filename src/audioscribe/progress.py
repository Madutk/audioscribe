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
