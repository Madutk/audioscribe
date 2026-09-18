"""Zuletzt benutzte Ordner und Optionen der Oberflaeche - serverseitig gemerkt.

Bewusst NICHT im ``localStorage`` des Browsers: der ist an die Herkunft gebunden, und
``http://localhost:8766`` und ``http://127.0.0.1:8766`` sind fuer den Browser zwei
verschiedene Herkuenfte mit getrennten Speichern. Unter WSL ruft man die Oberflaeche mal
so und mal so auf - die Einstellungen waren dann scheinbar weg. Serverseitig gibt es
genau einen Zustand, unabhaengig von Browser und Adresse.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from audioscribe.config import settings

# Nur diese Schluessel werden gespeichert - niemals beliebiges JSON vom Client.
STATE_KEYS: tuple[str, ...] = (
    "input_dir",
    "output_dir",
    "model",
    "language",
    "device",
    "diarize",
    "frames",
    "frame_sensitivity",
    "frame_format",
    # KI-Analyse
    "agent_output_dir",
    "agent_model",
    "agent_skills",
    "agent_bash",
)

_STATE_NAME = "ui-state.json"


def state_path(cache_dir: Path | None = None) -> Path:
    """Ablageort der Zustandsdatei (Default: WSL-natives Cache-Verzeichnis)."""
    return Path(cache_dir if cache_dir is not None else settings.cache_dir) / _STATE_NAME


def load_state(cache_dir: Path | None = None) -> dict:
    """Gemerkten Zustand lesen; ``{}`` wenn nichts da oder die Datei kaputt ist.

    Eine beschaedigte Zustandsdatei darf die Oberflaeche nie lahmlegen.
    """
    path = state_path(cache_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return _clean(data) if isinstance(data, dict) else {}


def save_state(values: Mapping[str, object], cache_dir: Path | None = None) -> Path:
    """Zustand schreiben (nur bekannte Schluessel, atomar ueber eine temporaere Datei)."""
    path = state_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**load_state(cache_dir), **_clean(values)}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def merge_defaults(defaults: Mapping[str, object], saved: Mapping[str, object]) -> dict:
    """Gespeicherte Werte gewinnen ueber die Config-Defaults; Rest bleibt unveraendert."""
    return {**dict(defaults), **_clean(saved)}


def _clean(values: Mapping[str, object]) -> dict:
    """Auf ``STATE_KEYS`` filtern und die Typen erzwingen."""
    out: dict[str, object] = {}
    for key in STATE_KEYS:
        if key not in values:
            continue
        value = values[key]
        if key in ("diarize", "frames", "agent_bash"):
            out[key] = bool(value)
        elif key == "agent_skills":
            # Liste von Skill-Namen; eine leere Liste ist eine gueltige, bewusste Wahl.
            if isinstance(value, (list, tuple)):
                out[key] = [v.strip() for v in value if isinstance(v, str) and v.strip()]
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out
