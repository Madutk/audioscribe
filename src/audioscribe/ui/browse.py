"""Ordner-Auswahl im Browser: Pfad-Umsetzung Windows<->WSL, Verzeichnis-Listing.

Ein Browser kennt keinen nativen Ordner-Dialog, der einen *Pfad* zurueckgibt - deshalb
blaettert die Oberflaeche serverseitig durch das Dateisystem.

Der Server laeuft nativ unter Windows, unter WSL/Linux oder unter macOS. Eingefuegte Pfade
werden zwischen Windows und WSL in BEIDE Richtungen umgesetzt: unter WSL wird
``C:\\Users\\...`` zu ``/mnt/c/Users/...``, nativ unter Windows umgekehrt
``/mnt/c/Users/...`` zu ``C:\\Users\\...``. Derselbe kopierte Explorer-Pfad funktioniert
damit ueberall, und ein Ordner, den ein frueherer WSL-Lauf gemerkt hat, oeffnet sich auch
unter Windows. Auf dem Mac gibt es kein ``/mnt/c`` - Pfade bleiben, wie der Finder sie liefert.

Sicherheit: Das Blaettern ist absichtlich nicht auf ein Wurzelverzeichnis beschraenkt -
genau das ist das Feature. Abgesichert wird es dadurch, dass der Server ausschliesslich
an ``127.0.0.1`` bindet (NFR-8), das Listing rein lesend ist und - anders als die
Review-Oberflaeche - **keinerlei Dateiinhalte** ausliefert.
"""

from __future__ import annotations

import os
import re
import string
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
# Steuert Hinweistexte und Pfad-Umsetzung der Oberflaeche.
PLATFORM = "windows" if IS_WINDOWS else ("mac" if IS_MAC else "posix")

# "C:\Users\user" / "c:/Users/user" -> Laufwerksbuchstabe + Rest
_DRIVE_RE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
# "\\wsl$\Ubuntu\home\user" bzw. "\\wsl.localhost\Ubuntu\home\user" -> Rest
_UNC_WSL_RE = re.compile(r"^\\\\wsl(?:\$|\.localhost)\\[^\\]+(?:\\(.*))?$", re.IGNORECASE)
# "/mnt/c/Users/user" -> Laufwerksbuchstabe + Rest
_MNT_DRIVE_RE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")

# FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_HIDDEN_ATTRS = 0x2 | 0x4


def _clean(text: str) -> str:
    """Nutzereingabe entzwirbeln: Leerraum und die Anfuehrungszeichen aus dem Explorer weg."""
    return (text or "").strip().strip('"').strip("'")


def windows_to_wsl(text: str) -> str:
    """Setzt einen Windows-Pfad auf seine WSL-Entsprechung um; POSIX bleibt unveraendert.

    ``C:\\Users\\user`` -> ``/mnt/c/Users/user``,
    ``\\\\wsl$\\Ubuntu\\home\\user`` -> ``/home/user``.
    """
    raw = _clean(text)
    if not raw:
        return raw

    unc = _UNC_WSL_RE.match(raw)
    if unc:
        rest = (unc.group(1) or "").replace("\\", "/")
        return "/" + rest.lstrip("/")

    drive = _DRIVE_RE.match(raw)
    if drive:
        rest = (drive.group(2) or "").replace("\\", "/")
        return f"/mnt/{drive.group(1).lower()}/{rest}".rstrip("/") or "/"

    return raw


def wsl_to_windows(text: str) -> str:
    """Setzt einen WSL-Pfad auf seine Windows-Entsprechung um; Windows bleibt Windows.

    ``/mnt/c/Users/user`` -> ``C:\\Users\\user``, ``C:/Users/user`` -> ``C:\\Users\\user``.
    Reine Linux-Pfade (``/home/user``) bleiben stehen - sie sind unter Windows hoechstens
    ueber ``\\\\wsl$\\...`` erreichbar, und welche Distribution gemeint ist, weiss nur der Nutzer.
    """
    raw = _clean(text)
    if not raw:
        return raw

    mnt = _MNT_DRIVE_RE.match(raw.replace("\\", "/"))
    if mnt:
        rest = (mnt.group(2) or "").replace("/", "\\")
        return f"{mnt.group(1).upper()}:\\{rest}"

    drive = _DRIVE_RE.match(raw)
    if drive:
        # Trenner IMMER setzen: "C:" allein meint unter Windows das *aktuelle*
        # Verzeichnis auf C:, nicht die Wurzel.
        rest = (drive.group(2) or "").replace("/", "\\")
        return f"{drive.group(1).upper()}:\\{rest}"

    return raw


def to_native(text: str, *, windows: bool | None = None, mac: bool | None = None) -> str:
    """Nutzereingabe -> Schreibweise des Systems, auf dem der Server laeuft.

    Auf dem Mac wird nichts umgesetzt: ein eingefuegtes ``C:\\...`` ergaebe ein nicht
    existierendes ``/mnt/c/...`` statt einer klaren Fehlermeldung.
    """
    windows = IS_WINDOWS if windows is None else windows
    mac = (IS_MAC and not windows) if mac is None else mac
    if mac and not windows:
        return _clean(text)
    return wsl_to_windows(text) if windows else windows_to_wsl(text)


def normalize_path(
    text: str, *, default: Path | None = None, windows: bool | None = None, mac: bool | None = None
) -> Path:
    """Nutzereingabe -> absoluter Pfad (Pfad-Umsetzung, ``~``, ``..`` aufgeloest)."""
    raw = to_native(text or "", windows=windows, mac=mac)
    if not raw:
        return Path(default) if default is not None else Path.home()
    return Path(raw).expanduser().resolve()


def _is_hidden(entry: os.DirEntry) -> bool:
    """Versteckt: Punktordner (POSIX) bzw. Hidden-/System-Attribut (Windows).

    Ohne die Attribut-Pruefung staenden in ``C:\\`` Eintraege wie ``$Recycle.Bin`` oder
    ``System Volume Information`` mitten in der Ordnerliste.
    """
    if entry.name.startswith("."):
        return True
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & _HIDDEN_ATTRS)
    except (AttributeError, OSError):  # st_file_attributes gibt es nur unter Windows
        return False


def list_dirs(folder: Path, *, show_hidden: bool = False) -> list[Path]:
    """Unterverzeichnisse von ``folder``, alphabetisch; unlesbare Eintraege ausgelassen."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {folder}")

    out: list[Path] = []
    # scandir statt iterdir: spart je Eintrag einen stat-Aufruf (spuerbar auf Netzlaufwerken).
    with os.scandir(folder) as entries:
        for entry in entries:
            if not show_hidden and _is_hidden(entry):
                continue
            try:
                if entry.is_dir():
                    out.append(Path(entry.path))
            except OSError:  # kaputter Symlink / keine Berechtigung -> ueberspringen
                continue
    return sorted(out, key=lambda p: p.name.casefold())


def breadcrumbs(folder: Path) -> list[tuple[str, str]]:
    """Pfadkette als ``(Anzeigename, Pfad)`` von der Wurzel bzw. dem Laufwerk bis ``folder``.

    Erwartet einen absoluten Pfad (so, wie ``normalize_path`` ihn liefert): die Wurzel ist
    ``/`` unter POSIX und ``C:\\`` unter Windows.
    """
    folder = Path(folder)
    anchor = folder.anchor or "/"
    # Anzeigename ohne den Trenner am Ende ("C:" statt "C:\"), damit die Oberflaeche
    # ihn wie zwischen allen anderen Krumen selbst setzen kann; "/" bleibt "/".
    crumbs = [(anchor if anchor == "/" else anchor.rstrip("\\/") or anchor, anchor)]
    current = Path(anchor)
    for part in folder.parts[1:]:
        current = current / part
        crumbs.append((part, str(current)))
    return crumbs


def windows_drives() -> list[Path]:
    """Vorhandene Laufwerke des laufenden Windows-Systems (``C:\\``, ``D:\\``, ...).

    Die Bitmaske von ``GetLogicalDrives`` kostet keinen Datentraeger-Zugriff; erst danach
    wird geprueft, ob das Laufwerk lesbar ist - ein leeres DVD-Laufwerk faellt so raus.
    """
    if not IS_WINDOWS:
        return []
    try:
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    except (AttributeError, OSError, ImportError):
        return []

    out: list[Path] = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask >> index & 1:
            continue
        drive = Path(f"{letter}:\\")
        try:
            if drive.is_dir():
                out.append(drive)
        except OSError:
            continue
    return out


def quick_links(
    *,
    project_root: Path,
    input_dir: Path,
    output_dir: Path,
    home: Path | None = None,
    mnt_root: Path = Path("/mnt"),
    volumes_root: Path = Path("/Volumes"),
    windows: bool | None = None,
    mac: bool | None = None,
) -> list[tuple[str, str]]:
    """Sprungziele fuer den Ordner-Dialog (Projektordner, Home, Laufwerke, Nutzer-Ordner)."""
    windows = IS_WINDOWS if windows is None else windows
    mac = (IS_MAC and not windows) if mac is None else mac
    home = Path.home() if home is None else Path(home)
    candidates: list[tuple[str, Path]] = [
        ("Projekt", Path(project_root)),
        ("input/", Path(input_dir)),
        ("output/", Path(output_dir)),
        ("Home", home),
    ]

    if windows:
        # Nativ unter Windows sind die Laufwerke die Wurzeln - ein "/" gibt es nicht,
        # ohne diese Sprungziele kaeme man aus dem Projektordner nie heraus.
        candidates += [(drive.drive, drive) for drive in windows_drives()]
        # Die uebersetzten Namen kommen mit: ein deutsches Windows hat "Dokumente",
        # ein englisches "Documents" - vorhanden ist immer nur einer davon.
        candidates += [
            (name, home / name)
            for name in ("Desktop", "Downloads", "Videos", "Dokumente", "Documents")
        ]
    elif mac:
        # Finder zeigt die Nutzerordner lokalisiert ("Schreibtisch"), auf der Platte heissen
        # sie englisch - darum deutsche Labels auf englische Pfade.
        candidates += [
            ("Schreibtisch", home / "Desktop"),
            ("Dokumente", home / "Documents"),
            ("Downloads", home / "Downloads"),
            ("Filme", home / "Movies"),
            ("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"),
        ]
        # Externe Platten und Sticks haengen unter /Volumes; "Macintosh HD" ist nur ein Link auf /.
        try:
            volumes = sorted(p for p in Path(volumes_root).iterdir() if p.is_dir())
        except OSError:
            volumes = []
        for vol in volumes:
            try:
                if vol.resolve() == Path("/"):
                    continue
            except OSError:
                continue
            candidates.append((f"Volume {vol.name}", vol))
    else:
        # Unter WSL haengen die Windows-Laufwerke in /mnt/<buchstabe>; /mnt/wsl & Co. raus.
        try:
            drives = sorted(p for p in Path(mnt_root).iterdir() if len(p.name) == 1 and p.is_dir())
        except OSError:
            drives = []
        candidates += [(f"Windows {d.name.upper()}:", d) for d in drives]

    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for label, path in candidates:
        try:
            if not path.is_dir():
                continue
        except OSError:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        links.append((label, key))
    return links
