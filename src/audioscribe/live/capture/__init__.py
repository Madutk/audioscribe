"""Audio-Aufnahme je Plattform hinter einer kleinen Schnittstelle (PRD §17.2, §19).

Jede Aufnahme bietet ``mics`` und ``loopbacks`` (Geräteeinträge ``{index, name, rate,
channels, default}``), ``open(name, device, wav_path) -> Track`` und ``close()``. Dahinter
steckt unter Windows WASAPI (``wasapi``), unter macOS CoreAudio fürs Mikrofon plus
ScreenCaptureKit fürs System-Audio (``mac``) und zum Messen überall das WAV-Replay
(``live.replay``). Alles hinter der Aufnahme (Schnitt, Warteschlange, ASR) sieht nur
``Track``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from audioscribe.live.track import Track

INSTALL_HINT = "uv sync --extra <cu124|cpu> --extra review --extra live"
INSTALL_HINT_MAC = "uv sync --extra cpu --extra mac --extra review --extra live"


class Capture(Protocol):
    mics: list[dict]
    loopbacks: list[dict]

    def open(self, name: str, device: dict, wav_path: Path) -> Track: ...

    def close(self) -> None: ...


def pick(devices: list[dict], wahl: str) -> dict | None:
    """``"default"`` | ``"none"`` | Geräteindex -> Geräteeintrag (rein, testbar)."""
    wahl = (wahl or "default").strip().lower()
    if wahl == "none" or not devices:
        return None
    if wahl == "default":
        return next((d for d in devices if d.get("default")), devices[0])
    try:
        return next(d for d in devices if str(d["index"]) == wahl or d["index"] == int(wahl))
    except (ValueError, StopIteration):
        raise RuntimeError(f"Audio-Gerät '{wahl}' nicht gefunden") from None


def open_capture(clock: Callable[[], float], platform: str | None = None) -> Capture:
    """Die Aufnahme der laufenden Plattform; außerhalb von Windows/macOS bleibt nur das Replay."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        from audioscribe.live.capture.wasapi import AudioCapture

        return AudioCapture(clock)
    if platform == "darwin":
        from audioscribe.live.capture.mac import MacCapture

        return MacCapture(clock)
    raise RuntimeError(
        "Live-Aufnahme braucht Windows (WASAPI) oder macOS (ScreenCaptureKit); unter Linux/WSL "
        "geht nur das Replay: audioscribe live --wav DATEI"
    )


def list_devices(platform: str | None = None) -> dict:
    """``{"mics": [...], "loopbacks": [...]}`` der laufenden Plattform (für CLI, doctor, UI)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        from audioscribe.live.capture.wasapi import list_devices as win

        return win()
    if platform == "darwin":
        from audioscribe.live.capture.mac import list_devices as mac

        return mac()
    raise RuntimeError(
        "Live-Aufnahme braucht Windows (WASAPI) oder macOS (ScreenCaptureKit); unter WSL/Linux "
        "nicht verfügbar."
    )


def ensure_permissions(
    *, mic: bool, system: bool, log: Callable[[str], None], platform: str | None = None
) -> None:
    """macOS fragt die TCC-Berechtigungen VOR dem Start der Sitzungsuhr ab.

    Die Dialoge können Sekunden dauern; fielen sie in die Aufnahme, würde die Zeitleiste
    mit Stille aufgefüllt und die Ladezeit im Fazit stimmte nicht. Andere Plattformen
    kennen keine solchen Abfragen.
    """
    platform = sys.platform if platform is None else platform
    if platform != "darwin":
        return
    from audioscribe.live import berechtigungen

    if mic:
        status = berechtigungen.mikrofon_status()
        if status == berechtigungen.NICHT_GEFRAGT:
            log("macOS fragt nach der Mikrofon-Berechtigung ...")
            status = berechtigungen.mikrofon_anfragen()
        if status != berechtigungen.ERTEILT:
            raise RuntimeError(
                "Mikrofon nicht erlaubt - Systemeinstellungen > Datenschutz & Sicherheit > "
                f"Mikrofon: '{berechtigungen.host_app()}' freigeben (oder '--mic none')."
            )
    if system and not berechtigungen.bildschirm_erlaubt():
        berechtigungen.bildschirm_anfragen()  # öffnet den Dialog; wirkt erst nach Neustart
        raise RuntimeError(
            "Bildschirmaufnahme nicht erlaubt - das System-Audio läuft über ScreenCaptureKit. "
            "Systemeinstellungen > Datenschutz & Sicherheit > Bildschirmaufnahme: "
            f"'{berechtigungen.host_app()}' freigeben, die App neu starten und 'audioscribe live' "
            "erneut aufrufen (oder '--loopback none')."
        )
