"""Ordner-Auswahl im Browser: Pfad-Umsetzung Windows<->WSL, Verzeichnis-Listing.

Ein Browser kennt keinen nativen Ordner-Dialog, der einen *Pfad* zurueckgibt - deshalb
blaettert die Oberflaeche serverseitig durch das Dateisystem. Fuer den WSL-Alltag setzt
``windows_to_wsl`` eingefuegte Explorer-Pfade (``C:\\Users\\...``, ``\\\\wsl$\\...``) auf
die passenden POSIX-Pfade um.

Sicherheit: Das Blaettern ist absichtlich nicht auf ein Wurzelverzeichnis beschraenkt -
genau das ist das Feature. Abgesichert wird es dadurch, dass der Server ausschliesslich
an ``127.0.0.1`` bindet (NFR-8), das Listing rein lesend ist und - anders als die
Review-Oberflaeche - **keinerlei Dateiinhalte** ausliefert.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# "C:\Users\marek" / "c:/Users/marek" -> Laufwerksbuchstabe + Rest
_DRIVE_RE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
# "\\wsl$\Ubuntu\home\marek" bzw. "\\wsl.localhost\Ubuntu\home\marek" -> Rest
_UNC_WSL_RE = re.compile(r"^\\\\wsl(?:\$|\.localhost)\\[^\\]+(?:\\(.*))?$", re.IGNORECASE)


def windows_to_wsl(text: str) -> str:
    """Setzt einen Windows-Pfad auf seine WSL-Entsprechung um; POSIX bleibt unveraendert.

    ``C:\\Users\\marek`` -> ``/mnt/c/Users/marek``,
    ``\\\\wsl$\\Ubuntu\\home\\marek`` -> ``/home/marek``.
    """
    raw = text.strip().strip('"').strip("'")
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


def normalize_path(text: str, *, default: Path | None = None) -> Path:
    """Nutzereingabe -> absoluter Pfad (Windows-Umsetzung, ``~``, ``..`` aufgeloest)."""
    raw = windows_to_wsl(text or "")
    if not raw:
        return Path(default) if default is not None else Path.home()
    return Path(raw).expanduser().resolve()


def list_dirs(folder: Path, *, show_hidden: bool = False) -> list[Path]:
    """Unterverzeichnisse von ``folder``, alphabetisch; unlesbare Eintraege ausgelassen."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {folder}")

    out: list[Path] = []
    # scandir statt iterdir: spart je Eintrag einen stat-Aufruf (spuerbar auf /mnt/c).
    with os.scandir(folder) as entries:
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    out.append(Path(entry.path))
            except OSError:  # kaputter Symlink / keine Berechtigung -> ueberspringen
                continue
    return sorted(out, key=lambda p: p.name.casefold())


def breadcrumbs(folder: Path) -> list[tuple[str, str]]:
    """Pfadkette als ``(Anzeigename, Pfad)`` von der Wurzel bis ``folder``."""
    folder = Path(folder)
    crumbs = [("/", "/")]
    current = Path("/")
    for part in folder.parts[1:]:
        current = current / part
        crumbs.append((part, str(current)))
    return crumbs


def quick_links(
    *,
    project_root: Path,
    input_dir: Path,
    output_dir: Path,
    home: Path | None = None,
    mnt_root: Path = Path("/mnt"),
) -> list[tuple[str, str]]:
    """Sprungziele fuer den Ordner-Dialog (Projektordner, Home, Windows-Laufwerke)."""
    home = Path.home() if home is None else Path(home)
    candidates: list[tuple[str, Path]] = [
        ("Projekt", Path(project_root)),
        ("input/", Path(input_dir)),
        ("output/", Path(output_dir)),
        ("Home", home),
    ]

    # Windows-Laufwerke haengen unter /mnt/<buchstabe>; /mnt/wsl & Co. ausblenden.
    try:
        drives = sorted(p for p in Path(mnt_root).iterdir() if len(p.name) == 1 and p.is_dir())
    except OSError:
        drives = []
    candidates += [(f"Windows {d.name.upper()}:", d) for d in drives]

    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for label, path in candidates:
        if not path.is_dir():
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        links.append((label, key))
    return links
