"""Anwendungsfenster unter macOS auflisten und aufnehmen - rein über PyObjC/Quartz (FR-51).

Gleiches Dict-Schema wie ``fenster.list_windows`` (``hwnd`` ist hier die Quartz-Fenster-
nummer ``kCGWindowNumber``). Aufgenommen wird mit ``CGWindowListCreateImage``: liefert den
Inhalt des Fensters auch hinter anderen Fenstern, braucht aber die Berechtigung
"Bildschirmaufnahme" (ohne sie kommt nur der Rahmen). Importe der Frameworks stehen in
den Funktionen; das Modul ist überall importierbar.
"""

from __future__ import annotations

import os
from collections.abc import Callable

Rect = tuple[int, int, int, int]  # left, top, right, bottom

# Fenster dieser Prozesse sind Teile der Shell, nie eine Anwendung.
_SHELL_OWNERS = frozenset({"Window Server", "Dock", "Control Center", "Notification Center", "Spotlight", "SystemUIServer"})


SCREENCAPTURE = "/usr/sbin/screencapture"


def screencapture_image(args: list[str], timeout_s: float = 5.0):
    """Bildschirmfoto über das Systemwerkzeug ``screencapture`` in einem EIGENEN Prozess.

    Für Vorschaubilder im langlebigen Server-Prozess. Jede In-Prozess-Aufnahme
    (``mss``, ``CGWindowListCreateImage``) macht den Prozess dauerhaft zum
    ScreenCaptureKit-Client; solange er lebt, bekommt kein weiterer Prozess mit
    demselben Programmpfad (der Aufnahme-Subprozess!) einen Audio-Stream gestartet -
    "ScreenCaptureKit antwortet nicht (Zeitüberschreitung)". ``screencapture`` ist ein
    anderes Programm und endet sofort. ``None``, wenn nichts aufgenommen wurde
    (Fenster minimiert, Monitor unbekannt).
    """
    import subprocess
    import tempfile

    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "shot.png")
        try:
            proc = subprocess.run(  # noqa: S603 - festes Systemwerkzeug, Argumente sind Zahlen
                [SCREENCAPTURE, "-x", "-t", "png", *args, out],
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) == 0:
            return None
        with Image.open(out) as img:
            return img.convert("RGB")


def _quartz():
    try:
        import Quartz
    except ImportError as exc:
        raise RuntimeError("Fensteraufnahme braucht PyObjC (Quartz) -> 'uv sync --extra cpu --extra mac --extra live'") from exc
    return Quartz


def _wanted(*, title: str, owner: str, layer: int, width: int, height: int, alpha: float, on_screen: bool) -> bool:
    """Welches Fenster der Liste ist eine Anwendung? (rein, testbar)"""
    if not title.strip() or layer != 0 or width <= 0 or height <= 0 or alpha <= 0.0 or not on_screen:
        return False
    return owner not in _SHELL_OWNERS


def eintraege(infos: list[dict], eigene_pid: int) -> list[dict]:
    """Rohe ``CGWindowListCopyWindowInfo``-Dicts -> unsere Fenstereinträge (rein, testbar)."""
    out: list[dict] = []
    for w in infos:
        bounds = w.get("kCGWindowBounds") or {}
        width, height = int(bounds.get("Width", 0)), int(bounds.get("Height", 0))
        pid = int(w.get("kCGWindowOwnerPID", 0))
        owner = str(w.get("kCGWindowOwnerName", "") or "")
        if pid == eigene_pid:
            continue
        if not _wanted(
            title=str(w.get("kCGWindowName", "") or ""),
            owner=owner,
            layer=int(w.get("kCGWindowLayer", 0)),
            width=width,
            height=height,
            alpha=float(w.get("kCGWindowAlpha", 1.0)),
            on_screen=bool(w.get("kCGWindowIsOnscreen", True)),
        ):
            continue
        out.append(
            {
                "hwnd": int(w["kCGWindowNumber"]),
                "title": str(w.get("kCGWindowName")),
                "process": owner or "?",
                "pid": pid,
                "width": width,
                "height": height,
            }
        )
    return out


def _infos(Q, option=None, window: int = 0) -> list[dict]:
    opt = option if option is not None else (Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements)
    raw = Q.CGWindowListCopyWindowInfo(opt, window or Q.kCGNullWindowID)
    return [dict(w) for w in (raw or [])]


def list_windows() -> list[dict]:
    """Sichtbare Anwendungsfenster in Z-Order (vorderstes zuerst)."""
    Q = _quartz()
    return eintraege(_infos(Q), os.getpid())


def _info(hwnd: int) -> dict | None:
    Q = _quartz()
    infos = _infos(Q, Q.kCGWindowListOptionIncludingWindow, hwnd)
    return infos[0] if infos else None


def is_window(hwnd: int) -> bool:
    try:
        return _info(hwnd) is not None
    except RuntimeError:
        return False


def is_iconic(hwnd: int) -> bool:
    """Minimiert = nicht mehr auf dem Bildschirm."""
    info = _info(hwnd)
    return info is None or not bool(info.get("kCGWindowIsOnscreen", False))


def window_title(hwnd: int) -> str:
    info = _info(hwnd)
    return str((info or {}).get("kCGWindowName", "") or "")


def window_rect(hwnd: int) -> Rect:
    from audioscribe.live.fenster import WindowGone

    info = _info(hwnd)
    if info is None:
        raise WindowGone(f"Fenster {hwnd} existiert nicht mehr")
    b = info.get("kCGWindowBounds") or {}
    x, y = int(b.get("X", 0)), int(b.get("Y", 0))
    return (x, y, x + int(b.get("Width", 0)), y + int(b.get("Height", 0)))


def grab_window(hwnd: int, fallback: Callable[[Rect], object] | None = None):
    """Fensterinhalt als PIL-Bild; ``None`` wenn minimiert/ausgeblendet."""
    from PIL import Image

    from audioscribe.live.fenster import WindowGone

    Q = _quartz()
    info = _info(hwnd)
    if info is None:
        raise WindowGone(f"Fenster {hwnd} existiert nicht mehr")
    if not bool(info.get("kCGWindowIsOnscreen", False)):
        return None
    image = Q.CGWindowListCreateImage(
        Q.CGRectNull,
        Q.kCGWindowListOptionIncludingWindow,
        hwnd,
        Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageNominalResolution,
    )
    img = None
    if image is not None:
        w, h = Q.CGImageGetWidth(image), Q.CGImageGetHeight(image)
        stride = Q.CGImageGetBytesPerRow(image)
        data = bytes(Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(image)))
        if w > 0 and h > 0 and len(data) >= stride * h:
            img = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", stride, 1).convert("RGB")
    einfarbig = img is not None and all(lo == hi for lo, hi in img.getextrema())
    if (img is None or einfarbig) and fallback is not None:
        ersatz = fallback(window_rect(hwnd))
        if ersatz is not None:
            return ersatz
    return img
