"""LLM-Wiki-Ordner einer beendeten Sitzung: ``<sitzung>/LLM-Wiki/``.

Nach Stopp und Nachbereitung liegt im Sitzungsordner ein kleiner, für ein LLM-Wiki fertiger
Ordner - das Transkript als ``<Titel>.md`` und die Standbilder daneben unter ``<Titel>/``:

    LLM-Wiki/
      Workshop Reisebuchung.md      (Transkript, Bildlinks relativ auf den Ordner daneben)
      Workshop Reisebuchung/
        0001_00-00-03.jpg

Der Ordner ist rein abgeleitet: ``erzeuge`` baut ihn jedes Mal vollständig neu. Ein
nachträglich geänderter Titel braucht darum keine eigene Umbenennung - neu erzeugen genügt.
Gebaut wird neben dem alten Stand; erst ein fertiger Ordner ersetzt ihn.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from audioscribe.i18n import tr
from audioscribe.live import journal

ORDNER = "LLM-Wiki"
_NEU = ".LLM-Wiki.neu"
_ALT = ".LLM-Wiki.alt"
_MAX_NAME = 120
# In Dateinamen unter Windows/macOS verboten oder heikel; Steuerzeichen ohnehin.
_VERBOTEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def dateiname(titel: str, session_dir: Path) -> str:
    """Lesbarer Dateiname aus dem Titel (Leerzeichen und Umlaute bleiben); leer → Sitzungsname."""
    name = _VERBOTEN.sub("-", titel or "")
    name = re.sub(r"\s+", " ", name).strip().lstrip(".").strip()[:_MAX_NAME].rstrip(" .")
    return name or Path(session_dir).name


def ordner(session_dir: Path) -> Path:
    return Path(session_dir) / ORDNER


def erzeuge(session_dir: Path) -> Path:
    """``LLM-Wiki/`` aus Transkript, Standbildern und Titel (``sitzung.json``) neu bauen."""
    from audioscribe.review.marks import load_marks
    from audioscribe.review.merge import render_markdown_with_marks

    session_dir = Path(session_dir)
    quelle = session_dir / "transkript.md"
    if not quelle.is_file():
        raise FileNotFoundError(tr("Kein Transkript in {ordner}", ordner=session_dir))
    name = dateiname(str((journal.lies_status(session_dir) or {}).get("titel") or ""), session_dir)
    try:
        data = json.loads((session_dir / "transcript.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    try:
        marks = load_marks(session_dir) if isinstance(data, dict) else []
    except (OSError, ValueError, KeyError, TypeError):
        marks = []
    vorhandene = [m for m in marks if (session_dir / m.png).is_file()]

    neu, alt, ziel = session_dir / _NEU, session_dir / _ALT, ordner(session_dir)
    for rest in (neu, alt):  # Reste eines abgebrochenen Laufs
        shutil.rmtree(rest, ignore_errors=True)
    try:
        neu.mkdir()
        if vorhandene:
            bilder = neu / name
            bilder.mkdir()
            verlinkt = []
            for m in vorhandene:
                shutil.copy2(session_dir / m.png, bilder / Path(m.png).name)
                verlinkt.append(replace(m, png=quote(f"{name}/{Path(m.png).name}", safe="/.-_~")))
            (neu / f"{name}.md").write_text(render_markdown_with_marks(data, verlinkt), encoding="utf-8")
        else:  # ohne Bilder: das Transkript, wie es ist
            shutil.copy2(quelle, neu / f"{name}.md")
        if ziel.exists():
            ziel.rename(alt)
        neu.rename(ziel)
    except BaseException:
        if alt.exists() and not ziel.exists():
            alt.rename(ziel)
        shutil.rmtree(neu, ignore_errors=True)
        raise
    shutil.rmtree(alt, ignore_errors=True)
    return ziel / f"{name}.md"
