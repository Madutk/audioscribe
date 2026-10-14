"""Nativer Ordnerdialog (Finder, Explorer, GTK/Tk) aus dem Server heraus.

Der Browser kennt keinen Ordnerdialog, der einen Pfad liefert - der Server läuft aber auf
demselben Rechner (127.0.0.1) und kann den Dialog des Betriebssystems selbst öffnen. Immer
in einem Kindprozess: auf dem Mac ``osascript`` (nie tkinter im Serverprozess - ein
GUI-Toolkit im langlebigen Python-Prozess stört dort die Bildschirmaufnahme), unter Windows
PowerShell mit dem Ordnerdialog von WinForms, sonst tkinter in einem eigenen Python.

Ohne Desktop (WSL, Server ohne DISPLAY) gilt ``verfuegbar() == False`` - die Oberfläche nimmt
dann ihren eingebauten, serverseitig geblätterten Dialog (``/api/browse``).
"""

from __future__ import annotations

import base64
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from audioscribe.ui import browse

PLATTFORM = browse.PLATFORM  # "mac" | "windows" | "posix" - in Tests umschaltbar
TIMEOUT_S = 600.0
TITEL_MAX = 120
# Nur ein Dialog zur Zeit: ein zweiter Klick, solange der erste offen ist, bekommt 409.
sperre = threading.Lock()


class DialogFehler(RuntimeError):
    """Dialog nicht startbar, abgelaufen oder mit unerwarteter Antwort beendet."""


def verfuegbar() -> bool:
    if PLATTFORM == "mac":
        return shutil.which("osascript") is not None
    if PLATTFORM == "windows":
        return shutil.which("powershell") is not None
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return importlib.util.find_spec("tkinter") is not None


def _titel(titel: str) -> str:
    return "".join(c for c in titel if c.isprintable())[:TITEL_MAX] or "Ordner wählen"


def _start(start: Path | None) -> str:
    try:
        return str(start) if start is not None and start.is_dir() else ""
    except OSError:
        return ""


def _applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


_TK_SKRIPT = (
    "import sys, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
    "print(filedialog.askdirectory(initialdir=sys.argv[1] or None, title=sys.argv[2], mustexist=True) or '')\n"
)


def kommando(start: Path | None, titel: str) -> list[str]:
    """Aufruf des Dialogs je Plattform - rein, ohne Seiteneffekt."""
    titel = _titel(titel)
    anfang = _start(start)
    if PLATTFORM == "mac":
        wahl = f'set f to choose folder with prompt "{_applescript(titel)}"'
        if anfang:
            wahl += f' default location (POSIX file "{_applescript(anfang)}")'
        # "activate" holt den Dialog vor den Browser.
        return ["osascript", "-e", 'tell application "System Events"', "-e", "activate", "-e", wahl,
                "-e", "POSIX path of f", "-e", "end tell"]
    if PLATTFORM == "windows":
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$d.Description = '{titel.replace(chr(39), chr(39) * 2)}'; "
            "$d.ShowNewFolderButton = $true; "
            "if ($d.PSObject.Properties['UseDescriptionForTitle']) { $d.UseDescriptionForTitle = $true }; "
            + (f"$d.SelectedPath = '{anfang.replace(chr(39), chr(39) * 2)}'; " if anfang else "")
            + "$o = New-Object System.Windows.Forms.Form -Property @{TopMost=$true}; "
            "if ($d.ShowDialog($o) -eq 'OK') { [Console]::Out.Write($d.SelectedPath) } else { exit 2 }"
        )
        kodiert = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        return ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", kodiert]
    return [sys.executable, "-I", "-c", _TK_SKRIPT, anfang, titel]


def ergebnis(proc: subprocess.CompletedProcess) -> Path | None:
    """Antwort des Kindprozesses: Pfad, ``None`` bei Abbruch, sonst ``DialogFehler``."""
    out = (proc.stdout or "").strip()
    err = proc.stderr or ""
    if PLATTFORM == "mac":
        if proc.returncode != 0:
            if "-128" in err or "canceled" in err.lower():
                return None
            raise DialogFehler(err.strip() or f"osascript endete mit Code {proc.returncode}")
        out = out.rstrip("/") or "/"
        return Path(out)
    if PLATTFORM == "windows":
        if proc.returncode == 2:
            return None
        if proc.returncode != 0 or not out:
            raise DialogFehler(err.strip() or f"PowerShell endete mit Code {proc.returncode}")
        return Path(out)
    if proc.returncode != 0:
        raise DialogFehler(err.strip() or f"Dialog endete mit Code {proc.returncode}")
    return Path(out) if out else None


def waehle_ordner(start: Path | None, titel: str) -> Path | None:
    """Ordnerdialog zeigen und warten. ``None`` = abgebrochen."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if PLATTFORM == "windows" else 0
    try:
        proc = subprocess.run(
            kommando(start, titel), capture_output=True, text=True, timeout=TIMEOUT_S, creationflags=flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise DialogFehler("Der Ordnerdialog blieb zu lange offen.") from exc
    except OSError as exc:
        raise DialogFehler(f"Ordnerdialog nicht startbar: {exc}") from exc
    return ergebnis(proc)
