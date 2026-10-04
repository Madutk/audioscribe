"""Bestandsaufnahme der Aufnahmequellen - für CLI, doctor und die Oberfläche."""

from __future__ import annotations

from audioscribe.live.fenster import group_by_process


def inventory() -> dict:
    """Audio-Geräte, Monitore und Fenster; fehlende Teile stehen als Klartext in ``problems``."""
    out: dict = {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": []}
    try:
        from audioscribe.live.capture import list_devices

        out.update(list_devices())
    except Exception as exc:  # noqa: BLE001 - Treiberfehler dürfen die Abfrage nie kippen
        out["problems"].append(str(exc))
    try:
        from audioscribe.live.screen import list_monitors

        out["monitors"] = list_monitors()
    except ImportError:
        from audioscribe.live.capture import INSTALL_HINT

        out["problems"].append(f"mss fehlt -> {INSTALL_HINT}")
    except Exception as exc:  # noqa: BLE001
        out["problems"].append(f"Monitore nicht lesbar: {exc}")
    try:
        from audioscribe.live.fenster import list_windows

        out["windows"] = list_windows()  # leer außerhalb von Windows und macOS
    except Exception as exc:  # noqa: BLE001
        out["problems"].append(f"Fenster nicht lesbar: {exc}")
    return out


def list_devices_text() -> str:
    inv = inventory()
    lines = []
    for titel, key in (("Mikrofone", "mics"), ("System-Audio (Loopback)", "loopbacks")):
        lines.append(f"{titel}:")
        lines += [
            f"  [{d['index']}] {d['name']}{'  (Standard)' if d.get('default') else ''}"
            for d in inv[key]
        ] or ["  -"]
    lines.append("Monitore:")
    lines += [f"  [{m['index']}] {m['width']}x{m['height']}" for m in inv["monitors"]] or ["  -"]
    lines.append("Fenster (--window ID):")
    for gruppe in group_by_process(inv["windows"]):
        lines.append(f"  {gruppe['process']}")
        lines += [
            f"    [{w['hwnd']}] {w['title']}  ({w['width']}x{w['height']})" for w in gruppe["windows"]
        ]
    if not inv["windows"]:
        lines.append("  -")
    lines += [f"! {p}" for p in inv["problems"]]
    return "\n".join(lines)
