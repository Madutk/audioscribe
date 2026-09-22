"""Einzelne Anwendungsfenster auflisten und aufnehmen - nur Windows, nur ``ctypes``.

Aufgenommen wird per ``PrintWindow(PW_RENDERFULLCONTENT)``: das liefert den Inhalt des
gewählten Fensters auch dann, wenn andere Fenster davor liegen. Manche Anwendungen
(erhöhte Prozesse, exklusive DirectX-Vollbilder) liefern damit nur Schwarz - dafür gibt
es den ``fallback`` auf einen Bildschirmausschnitt.

Außerhalb von Windows ist die Fensterliste leer; importierbar bleibt das Modul überall.
"""

from __future__ import annotations

import functools
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

# Fensterstile und DWM-Attribute (winuser.h / dwmapi.h)
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
WS_EX_APPWINDOW = 0x40000
GW_OWNER = 4
PW_RENDERFULLCONTENT = 0x2
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DIB_RGB_COLORS = 0

# Fensterklassen der Shell, die nie als Anwendung gemeint sind.
_SHELL_CLASSES = frozenset(
    {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}
)
_UWP_HOST = "ApplicationFrameHost"

Rect = tuple[int, int, int, int]  # left, top, right, bottom


class WindowGone(RuntimeError):
    """Das Fenster existiert nicht mehr."""


# --- Reine Logik (testbar ohne WinAPI) -------------------------------------------


def _wanted(
    *,
    title: str,
    class_name: str,
    style_ex: int,
    cloaked: int,
    has_owner: bool,
    width: int,
    height: int,
) -> bool:
    """Alt-Tab-Logik: welches sichtbare Top-Level-Fenster ist eine Anwendung?"""
    if not title.strip() or cloaked or width <= 0 or height <= 0:
        return False
    if class_name in _SHELL_CLASSES:
        return False
    app = bool(style_ex & WS_EX_APPWINDOW)
    if style_ex & WS_EX_TOOLWINDOW and not app:
        return False
    return app or not has_owner


def group_by_process(windows: list[dict]) -> list[dict]:
    """Fenster nach Anwendung bündeln; Reihenfolge = erstes Auftreten (Z-Order)."""
    gruppen: dict[str, list[dict]] = {}
    for w in windows:
        gruppen.setdefault(w["process"], []).append(w)
    return [{"process": p, "windows": ws} for p, ws in gruppen.items()]


def window_label(window: dict) -> str:
    """Merkbarer Name statt des flüchtigen HWND: ``prozess – Titel``."""
    return f"{window['process']} – {window['title']}"


# --- WinAPI --------------------------------------------------------------------


@functools.cache
def _api() -> SimpleNamespace | None:
    """DLL-Handles mit gesetzten Signaturen; ``None`` außerhalb von Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        shcore = None

    enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def sig(fn, restype, argtypes):
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    sig(user32.EnumWindows, wt.BOOL, [enum_proc, wt.LPARAM])
    for name in ("IsWindow", "IsWindowVisible", "IsIconic"):
        sig(getattr(user32, name), wt.BOOL, [wt.HWND])
    sig(user32.GetWindowTextLengthW, ctypes.c_int, [wt.HWND])
    sig(user32.GetWindowTextW, ctypes.c_int, [wt.HWND, wt.LPWSTR, ctypes.c_int])
    sig(user32.GetClassNameW, ctypes.c_int, [wt.HWND, wt.LPWSTR, ctypes.c_int])
    # 64-bit: GetWindowLongPtrW; auf 32-bit gibt es nur GetWindowLongW.
    long_ptr = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    sig(long_ptr, ctypes.c_ssize_t, [wt.HWND, ctypes.c_int])
    sig(user32.GetWindow, wt.HWND, [wt.HWND, wt.UINT])
    sig(user32.GetWindowRect, wt.BOOL, [wt.HWND, ctypes.POINTER(wt.RECT)])
    sig(user32.GetWindowThreadProcessId, wt.DWORD, [wt.HWND, ctypes.POINTER(wt.DWORD)])
    sig(user32.GetDC, wt.HDC, [wt.HWND])
    sig(user32.ReleaseDC, ctypes.c_int, [wt.HWND, wt.HDC])
    sig(user32.PrintWindow, wt.BOOL, [wt.HWND, wt.HDC, wt.UINT])
    sig(user32.FindWindowExW, wt.HWND, [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR])
    sig(user32.SetProcessDPIAware, wt.BOOL, [])
    if hasattr(user32, "SetProcessDpiAwarenessContext"):
        sig(user32.SetProcessDpiAwarenessContext, wt.BOOL, [ctypes.c_void_p])
    if shcore is not None:
        sig(shcore.SetProcessDpiAwareness, ctypes.c_long, [ctypes.c_int])

    sig(gdi32.CreateCompatibleDC, wt.HDC, [wt.HDC])
    sig(gdi32.CreateCompatibleBitmap, wt.HBITMAP, [wt.HDC, ctypes.c_int, ctypes.c_int])
    sig(gdi32.SelectObject, ctypes.c_void_p, [wt.HDC, ctypes.c_void_p])
    sig(gdi32.DeleteObject, wt.BOOL, [ctypes.c_void_p])
    sig(gdi32.DeleteDC, wt.BOOL, [wt.HDC])
    sig(
        gdi32.GetDIBits,
        ctypes.c_int,
        [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT],
    )

    sig(dwmapi.DwmGetWindowAttribute, ctypes.c_long, [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD])

    sig(kernel32.OpenProcess, wt.HANDLE, [wt.DWORD, wt.BOOL, wt.DWORD])
    sig(
        kernel32.QueryFullProcessImageNameW,
        wt.BOOL,
        [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)],
    )
    sig(kernel32.CloseHandle, wt.BOOL, [wt.HANDLE])
    sig(kernel32.GetConsoleWindow, wt.HWND, [])

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD),
            ("biWidth", wt.LONG),
            ("biHeight", wt.LONG),
            ("biPlanes", wt.WORD),
            ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD),
            ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", wt.LONG),
            ("biYPelsPerMeter", wt.LONG),
            ("biClrUsed", wt.DWORD),
            ("biClrImportant", wt.DWORD),
        ]

    return SimpleNamespace(
        ctypes=ctypes,
        wt=wt,
        user32=user32,
        gdi32=gdi32,
        dwmapi=dwmapi,
        kernel32=kernel32,
        shcore=shcore,
        enum_proc=enum_proc,
        long_ptr=long_ptr,
        BITMAPINFOHEADER=BITMAPINFOHEADER,
    )


def _need_api() -> SimpleNamespace:
    api = _api()
    if api is None:
        raise RuntimeError("Fensteraufnahme gibt es nur unter Windows")
    return api


@functools.cache
def dpi_aware() -> None:
    """Prozess per-monitor-DPI-aware machen, damit Fensterrechtecke in physischen Pixeln
    kommen. Nur einmal pro Prozess setzbar - Fehler (schon gesetzt, z. B. durch mss) sind
    egal, das Ergebnis ist dasselbe."""
    api = _api()
    if api is None:
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if hasattr(api.user32, "SetProcessDpiAwarenessContext") and api.user32.SetProcessDpiAwarenessContext(
            api.ctypes.c_void_p(-4)
        ):
            return
        if api.shcore is not None and api.shcore.SetProcessDpiAwareness(2) == 0:
            return
        api.user32.SetProcessDPIAware()
    except OSError:
        pass


def is_window(hwnd: int) -> bool:
    api = _api()
    return bool(api and api.user32.IsWindow(hwnd))


def is_iconic(hwnd: int) -> bool:
    return bool(_need_api().user32.IsIconic(hwnd))


def window_title(hwnd: int) -> str:
    api = _need_api()
    n = api.user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = api.ctypes.create_unicode_buffer(n + 1)
    api.user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class_name(api, hwnd: int) -> str:
    buf = api.ctypes.create_unicode_buffer(256)
    api.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _dwm_attr(api, hwnd: int, attr: int, ctype):
    """DWM-Attribut lesen; ``None`` wenn DWM nichts dazu sagt."""
    out = ctype()
    hr = api.dwmapi.DwmGetWindowAttribute(hwnd, attr, api.ctypes.byref(out), api.ctypes.sizeof(out))
    return out if hr == 0 else None


def _get_window_rect(api, hwnd: int) -> Rect:
    r = api.wt.RECT()
    if not api.user32.GetWindowRect(hwnd, api.ctypes.byref(r)):
        raise WindowGone(f"Fenster {hwnd} nicht mehr lesbar")
    return (r.left, r.top, r.right, r.bottom)


def window_rect(hwnd: int) -> Rect:
    """Sichtbarer Rahmen (ohne die unsichtbaren Resize-Ränder), sonst ``GetWindowRect``."""
    api = _need_api()
    r = _dwm_attr(api, hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, api.wt.RECT)
    if r is not None and r.right > r.left and r.bottom > r.top:
        return (r.left, r.top, r.right, r.bottom)
    return _get_window_rect(api, hwnd)


def _pid_of(api, hwnd: int) -> int:
    pid = api.wt.DWORD()
    api.user32.GetWindowThreadProcessId(hwnd, api.ctypes.byref(pid))
    return pid.value


def process_name(pid: int) -> str:
    """Basisname der Exe (ohne ``.exe``); ``?`` wenn der Prozess nicht abfragbar ist."""
    api = _need_api()
    handle = api.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "?"
    try:
        size = api.wt.DWORD(1024)
        buf = api.ctypes.create_unicode_buffer(size.value)
        if not api.kernel32.QueryFullProcessImageNameW(handle, 0, buf, api.ctypes.byref(size)):
            return "?"
        return Path(buf.value).stem or "?"
    finally:
        api.kernel32.CloseHandle(handle)


def _app_pid(api, hwnd: int, pid: int) -> int:
    """UWP-Apps stecken in einem ApplicationFrameHost - der Inhalt gehört einem Kindfenster."""
    if process_name(pid) != _UWP_HOST:
        return pid
    core = api.user32.FindWindowExW(hwnd, None, "Windows.UI.Core.CoreWindow", None)
    return _pid_of(api, core) if core else pid


def list_windows() -> list[dict]:
    """Sichtbare Anwendungsfenster in Z-Order (vorderstes zuerst); leer außerhalb Windows."""
    api = _api()
    if api is None:
        return []
    dpi_aware()
    handles: list[int] = []

    # Im ctypes-Callback nur sammeln: Ausnahmen darin würden stumm verschluckt.
    @api.enum_proc
    def collect(hwnd, _lparam):
        handles.append(hwnd)
        return True

    api.user32.EnumWindows(collect, 0)
    eigene = os.getpid()
    konsole = api.kernel32.GetConsoleWindow()
    out: list[dict] = []
    for hwnd in handles:
        if hwnd == konsole or not api.user32.IsWindowVisible(hwnd):
            continue
        try:
            title = window_title(hwnd)
            if not title.strip():
                continue
            cloaked = _dwm_attr(api, hwnd, DWMWA_CLOAKED, api.wt.DWORD)
            left, top, right, bottom = window_rect(hwnd)
            if not _wanted(
                title=title,
                class_name=_class_name(api, hwnd),
                style_ex=api.long_ptr(hwnd, GWL_EXSTYLE),
                cloaked=cloaked.value if cloaked is not None else 0,
                has_owner=bool(api.user32.GetWindow(hwnd, GW_OWNER)),
                width=right - left,
                height=bottom - top,
            ):
                continue
            pid = _app_pid(api, hwnd, _pid_of(api, hwnd))
            if pid == eigene:
                continue
            out.append(
                {
                    "hwnd": hwnd,
                    "title": title,
                    "process": process_name(pid),
                    "pid": pid,
                    "width": right - left,
                    "height": bottom - top,
                }
            )
        except WindowGone:
            continue  # zwischen EnumWindows und jetzt geschlossen
    return out


def grab_window(hwnd: int, fallback: Callable[[Rect], object] | None = None):
    """Fensterinhalt als PIL-Bild; ``None`` wenn minimiert/ausgeblendet.

    ``fallback(rect)`` wird gerufen, wenn PrintWindow scheitert oder nur eine Farbe liefert
    (typisch: Schwarz bei erhöhten Prozessen und exklusiven DirectX-Vollbildern).
    """
    from PIL import Image

    api = _need_api()
    if not api.user32.IsWindow(hwnd):
        raise WindowGone(f"Fenster {hwnd} existiert nicht mehr")
    # Auch "in den Tray geschlossene" Fenster (Teams, Spotify) sind nur unsichtbar.
    if api.user32.IsIconic(hwnd) or not api.user32.IsWindowVisible(hwnd):
        return None

    # PrintWindow zeichnet das ganze Fenster inkl. unsichtbarer Ränder (GetWindowRect);
    # gezeigt werden soll nur der sichtbare Rahmen (DWM). Darum groß rendern, dann schneiden.
    wl, wt_, wr, wb = _get_window_rect(api, hwnd)
    el, et, er, eb = window_rect(hwnd)
    w, h = wr - wl, wb - wt_
    if w <= 0 or h <= 0:
        return None

    ct = api.ctypes
    hdc = api.user32.GetDC(None)
    mem = bmp = old = None
    try:
        mem = api.gdi32.CreateCompatibleDC(hdc)
        # Mit dem Bildschirm-DC, nicht dem Memory-DC: sonst entsteht eine 1-bpp-Bitmap.
        bmp = api.gdi32.CreateCompatibleBitmap(hdc, w, h)
        old = api.gdi32.SelectObject(mem, bmp)
        ok = api.user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)

        bmi = api.BITMAPINFOHEADER()
        bmi.biSize = ct.sizeof(api.BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # negativ = Zeilen von oben nach unten
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        buf = ct.create_string_buffer(w * h * 4)
        lines = api.gdi32.GetDIBits(mem, bmp, 0, h, buf, ct.byref(bmi), DIB_RGB_COLORS)
    finally:
        if old is not None:
            api.gdi32.SelectObject(mem, old)
        if bmp:
            api.gdi32.DeleteObject(bmp)
        if mem:
            api.gdi32.DeleteDC(mem)
        api.user32.ReleaseDC(None, hdc)

    img = None
    if ok and lines == h:
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        img = img.crop((max(el - wl, 0), max(et - wt_, 0), min(er - wl, w), min(eb - wt_, h)))
    einfarbig = img is not None and all(lo == hi for lo, hi in img.getextrema())
    if (img is None or einfarbig) and fallback is not None:
        ersatz = fallback((el, et, er, eb))
        if ersatz is not None:
            return ersatz
    return img


def preview_window_jpeg(hwnd: int, width: int = 480) -> bytes | None:
    """Verkleinertes Vorschaubild für die Fensterwahl; ``None`` wenn minimiert."""
    import io

    img = grab_window(hwnd)
    if img is None:
        return None
    img.thumbnail((width, width))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return out.getvalue()
