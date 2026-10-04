"""Kompatibilitäts-Fassade: die Aufnahme liegt jetzt in ``live.capture`` (je Plattform).

``pick`` und ``list_devices`` sind plattformneutral, ``AudioCapture`` ist die
WASAPI-Aufnahme unter Windows (``capture.wasapi``). Neue Aufrufer importieren direkt aus
``audioscribe.live.capture``.
"""

from __future__ import annotations

from audioscribe.live.capture import INSTALL_HINT, list_devices, open_capture, pick

__all__ = ["INSTALL_HINT", "AudioCapture", "list_devices", "open_capture", "pick"]


def AudioCapture(clock):  # noqa: N802 - historischer Klassenname
    """Die Aufnahme der laufenden Plattform (historisch: nur WASAPI)."""
    return open_capture(clock)
