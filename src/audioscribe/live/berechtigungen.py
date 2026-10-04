"""macOS-Berechtigungen (TCC) für Mikrofon und Bildschirmaufnahme - reine PyObjC-Aufrufe.

Beide Berechtigungen hängen an der App, die den Prozess gestartet hat (Terminal, iTerm,
VS Code), nicht an "Python". Die Bildschirmaufnahme wirkt erst, nachdem diese App neu
gestartet wurde. Gebraucht werden sie vom System-Audio (ScreenCaptureKit) und von den
Standbildern (``mss``); das Mikrofon fragt macOS beim ersten Öffnen des Streams ab.

Alle Funktionen sind außerhalb von macOS oder ohne PyObjC ungefährlich und liefern
``None`` bzw. ``UNBEKANNT``; die Importe stehen in den Funktionen (Projektmuster).
"""

from __future__ import annotations

import os
import sys
import threading

ERTEILT = "erteilt"
NICHT_GEFRAGT = "nicht gefragt"
VERWEIGERT = "verweigert"
GESPERRT = "gesperrt"  # durch Richtlinie (MDM) blockiert
UNBEKANNT = "unbekannt"  # kein macOS oder PyObjC fehlt

# AVAuthorizationStatus
_AV_STATUS = {0: NICHT_GEFRAGT, 1: GESPERRT, 2: VERWEIGERT, 3: ERTEILT}

_HOSTS = {
    "Apple_Terminal": "Terminal",
    "iTerm.app": "iTerm",
    "vscode": "Visual Studio Code",
    "WarpTerminal": "Warp",
    "Hyper": "Hyper",
    "WezTerm": "WezTerm",
    "ghostty": "Ghostty",
}


def host_app(env: dict | None = None) -> str:
    """Name der Terminal-App, der die Berechtigungen gehören (aus ``TERM_PROGRAM``)."""
    env = os.environ if env is None else env
    raw = env.get("TERM_PROGRAM", "").strip()
    return _HOSTS.get(raw, raw or "Terminal")


def ist_mac(platform: str | None = None) -> bool:
    return (sys.platform if platform is None else platform) == "darwin"


def mikrofon_status() -> str:
    """Stand der Mikrofon-Berechtigung ohne Dialog."""
    if not ist_mac():
        return UNBEKANNT
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except ImportError:
        return UNBEKANNT
    try:
        return _AV_STATUS.get(int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)), UNBEKANNT)
    except Exception:  # noqa: BLE001
        return UNBEKANNT


def mikrofon_anfragen(timeout_s: float = 120.0) -> str:
    """Zeigt den Mikrofon-Dialog und wartet auf die Antwort; liefert den neuen Stand."""
    if not ist_mac():
        return UNBEKANNT
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except ImportError:
        return UNBEKANNT
    fertig = threading.Event()
    antwort: list[bool] = []

    def handler(granted: bool) -> None:
        antwort.append(bool(granted))
        fertig.set()

    try:
        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, handler)
    except Exception:  # noqa: BLE001
        return mikrofon_status()
    fertig.wait(timeout_s)
    if antwort:
        return ERTEILT if antwort[0] else VERWEIGERT
    return mikrofon_status()


def bildschirm_erlaubt() -> bool | None:
    """Bildschirmaufnahme erteilt? ``None`` ohne macOS/PyObjC. Zeigt keinen Dialog."""
    if not ist_mac():
        return None
    try:
        from Quartz import CGPreflightScreenCaptureAccess
    except ImportError:
        return None
    try:
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001
        return None


def bildschirm_anfragen() -> bool | None:
    """Öffnet den Dialog für die Bildschirmaufnahme; die Freigabe greift erst nach Neustart."""
    if not ist_mac():
        return None
    try:
        from Quartz import CGRequestScreenCaptureAccess
    except ImportError:
        return None
    try:
        return bool(CGRequestScreenCaptureAccess())
    except Exception:  # noqa: BLE001
        return None


def pyobjc_fehlt() -> bool:
    """PyObjC-Brücken (Quartz, AVFoundation) nicht installiert? Nur auf macOS relevant."""
    if not ist_mac():
        return False
    try:
        import AVFoundation  # noqa: F401
        import Quartz  # noqa: F401
    except ImportError:
        return True
    return False


def bewerte(
    *, bildschirm: bool | None, mikrofon: str, host: str, pyobjc_fehlt: bool = False
) -> tuple[str, list[str]]:
    """Deutsche Hinweise für doctor und Oberfläche (rein, testbar).

    Liefert ``(status, teile)`` mit Status ``OK`` | ``WARN``.
    """
    if pyobjc_fehlt:
        return "WARN", [f"PyObjC fehlt -> 'uv sync --extra cpu --extra mac --extra live'"]
    teile: list[str] = []
    status = "OK"
    if bildschirm is True:
        teile.append("Bildschirmaufnahme: erteilt")
    elif bildschirm is False:
        status = "WARN"
        teile.append(
            "Bildschirmaufnahme FEHLT -> Systemeinstellungen > Datenschutz & Sicherheit > "
            f"Bildschirmaufnahme: '{host}' erlauben und die App neu starten "
            "(System-Audio und Standbilder brauchen sie)"
        )
    if mikrofon == ERTEILT:
        teile.append("Mikrofon: erteilt")
    elif mikrofon == NICHT_GEFRAGT:
        teile.append("Mikrofon: noch nicht abgefragt (Dialog beim ersten Start)")
    elif mikrofon == VERWEIGERT:
        status = "WARN"
        teile.append(
            "Mikrofon: verweigert -> Systemeinstellungen > Datenschutz & Sicherheit > "
            f"Mikrofon: '{host}' erlauben"
        )
    elif mikrofon == GESPERRT:
        status = "WARN"
        teile.append("Mikrofon: durch Richtlinie gesperrt")
    return status, teile


def hinweis() -> str:
    """Einzeiliger Hinweis für die Oberfläche; leer, wenn alles erteilt ist oder kein Mac."""
    if not ist_mac():
        return ""
    status, teile = bewerte(
        bildschirm=bildschirm_erlaubt(), mikrofon=mikrofon_status(), host=host_app(), pyobjc_fehlt=pyobjc_fehlt()
    )
    return "" if status == "OK" else "; ".join(t for t in teile if "FEHLT" in t or "verweigert" in t or "gesperrt" in t or "fehlt" in t)
