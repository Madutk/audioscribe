"""``analyse.json``: Protokoll eines Analyse-Laufs im Ergebnisordner.

Haelt neben Name, Quelle, Skills und Modell die ``session_id`` fest - ueber sie laesst
sich die Sitzung spaeter fortsetzen (``audioscribe analyze … --resume``, Grundlage des
geplanten Dialogmodus).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST_NAME = "analyse.json"
MANIFEST_VERSION = 1


@dataclass
class Manifest:
    name: str
    quelle: str
    skills: list[str] = field(default_factory=list)
    model: str | None = None
    status: str = "laeuft"  # laeuft | fertig | fehler | abgebrochen
    gestartet: str = ""
    beendet: str | None = None
    session_id: str | None = None
    sitzungen: list[str] = field(default_factory=list)  # alle Session-IDs, aelteste zuerst
    turns: int | None = None
    dauer_s: float | None = None
    kosten_usd: float | None = None  # Preis zu API-Tarifen; bei Abo-Anmeldung nur ein Gegenwert
    tokens: dict | None = None  # eingabe/ausgabe/cache_lesen/cache_schreiben, über alle Läufe
    fehler: str | None = None
    version: int = MANIFEST_VERSION


def manifest_path(workspace: Path) -> Path:
    return Path(workspace) / MANIFEST_NAME


def save_manifest(workspace: Path, manifest: Manifest) -> Path:
    """Atomar schreiben - ein Abbruch mitten im Lauf hinterlaesst nie halbes JSON."""
    path = manifest_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_manifest(workspace: Path) -> Manifest | None:
    """Vorhandenes Manifest lesen; ``None`` wenn keins da oder unlesbar."""
    try:
        data = json.loads(manifest_path(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    known = {k: v for k, v in data.items() if k in Manifest.__dataclass_fields__}
    try:
        return Manifest(**known)
    except TypeError:
        return None
