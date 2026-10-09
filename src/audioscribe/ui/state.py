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
    # Live-Transkription; Geraete nach NAME gemerkt - die Indizes wechseln mit jedem
    # an- oder abgesteckten Headset. Fenster ebenso nach "Prozess – Titel", weil ein
    # HWND den naechsten Start der Anwendung nicht ueberlebt.
    "live_source",
    "live_monitor",
    "live_window",
    "live_mic",
    "live_loopback",
    "live_model",
    "live_language",
    "live_device",
    "live_sensitivity",
    "live_format",
    "live_partials",
    "live_speakers",
    "live_refine",
    "live_refine_model",
    # Testmodus: zuletzt abgespieltes Transkript und Tempo (FR-64).
    "replay_transcript",
    "replay_speed",
    # Souffleur (PRD §20): KI-Dienst, Modell, Schalter. "wiki_dir" gilt nur ohne Projekt
    # (Kommandozeile, Uebernahme alter Installationen) - sonst traegt das Projekt den Pfad.
    "wiki_dir",
    "souffleur_model",
    "souffleur_backend",
    "souffleur_aktiv",
    "souffleur_sensibel",
    # Globale Vorgabe fuer die Transkriptionssprache (PRD §21); Projekte koennen sie ueberschreiben.
    "sprache",
    # Projekte (PRD §21): zuletzt geoeffnete, juengstes zuerst - je {"pfad", "name", "geoeffnet"}.
    "zuletzt_projekte",
    # Aufnahmen ohne Projekt ("Sofort aufnehmen") - leer heisst: Vorgabe im Dokumente-Ordner.
    "eingang_dir",
    # Darstellung der Oberflaeche: "system" folgt der Betriebssystem-Einstellung.
    "theme",
)

THEMES: tuple[str, ...] = ("system", "light", "dark")
LIVE_SOURCES: tuple[str, ...] = ("monitor", "window", "none", "transcript")

_BOOL_KEYS = (
    "diarize", "frames", "agent_bash", "live_partials", "live_speakers", "live_refine",
    "souffleur_aktiv", "souffleur_sensibel",
)

_LOESCHBAR = ("wiki_dir", "eingang_dir")

MAX_ZULETZT = 12

_STATE_NAME = "einstellungen.json"
# Bis 2026-10: Zustand lag als Cache-Datei unter ~/.cache/audioscribe; beim ersten Lesen des
# neuen Orts wird sie uebernommen (kopiert, nicht geloescht).
_LEGACY_NAME = "ui-state.json"


def state_path(config_dir: Path | None = None) -> Path:
    """Ablageort der Einstellungsdatei (Default: Konfigurationsordner der Plattform)."""
    return Path(config_dir if config_dir is not None else settings.config_dir) / _STATE_NAME


def legacy_state_path() -> Path:
    return Path(settings.cache_dir) / _LEGACY_NAME


def _uebernehme_alte_datei(path: Path) -> None:
    alt = legacy_state_path()
    if path.exists() or not alt.is_file():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(alt.read_bytes())
        os.replace(tmp, path)
    except OSError:
        pass


def load_state(config_dir: Path | None = None) -> dict:
    """Gemerkten Zustand lesen; ``{}`` wenn nichts da oder die Datei kaputt ist.

    Eine beschaedigte Zustandsdatei darf die Oberflaeche nie lahmlegen.
    """
    path = state_path(config_dir)
    if config_dir is None:
        _uebernehme_alte_datei(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return _clean(data) if isinstance(data, dict) else {}


def save_state(values: Mapping[str, object], config_dir: Path | None = None) -> Path:
    """Zustand schreiben (nur bekannte Schluessel, atomar ueber eine temporaere Datei)."""
    path = state_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**load_state(config_dir), **_clean(values)}
    # Ein bewusst geleertes Pfadfeld loest die Verknuepfung (z. B. Wiki abhaengen, K1).
    for key in _LOESCHBAR:
        if key in values and isinstance(values[key], str) and not values[key].strip():
            merged.pop(key, None)
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
        if key in _BOOL_KEYS:
            out[key] = bool(value)
        elif key == "theme":
            # Landet unescaped im HTML-Attribut - darum nur die drei bekannten Werte.
            if value in THEMES:
                out[key] = value
        elif key == "live_source":
            if value in LIVE_SOURCES:
                out[key] = value
        elif key == "zuletzt_projekte":
            if isinstance(value, (list, tuple)):
                out[key] = [
                    {k: str(e[k]).strip() for k in ("pfad", "name", "geoeffnet") if isinstance(e.get(k), str)}
                    for e in value
                    if isinstance(e, dict) and isinstance(e.get("pfad"), str) and e["pfad"].strip()
                ][:MAX_ZULETZT]
        elif key == "agent_skills":
            # Liste von Skill-Namen; eine leere Liste ist eine gueltige, bewusste Wahl.
            if isinstance(value, (list, tuple)):
                out[key] = [v.strip() for v in value if isinstance(v, str) and v.strip()]
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def merke_projekt(pfad: Path | str, name: str, config_dir: Path | None = None) -> None:
    """Projekt an die Spitze der zuletzt geoeffneten setzen."""
    from datetime import datetime

    pfad = str(pfad)
    liste = [e for e in load_state(config_dir).get("zuletzt_projekte", []) if e.get("pfad") != pfad]
    eintrag = {"pfad": pfad, "name": name, "geoeffnet": datetime.now().strftime("%Y-%m-%d %H:%M")}
    save_state({"zuletzt_projekte": [eintrag, *liste]}, config_dir)


def vergiss_projekt(pfad: Path | str, config_dir: Path | None = None) -> None:
    """Projekt aus der Liste nehmen - die Projektdatei im Wiki bleibt unberuehrt."""
    pfad = str(pfad)
    liste = [e for e in load_state(config_dir).get("zuletzt_projekte", []) if e.get("pfad") != pfad]
    save_state({"zuletzt_projekte": liste}, config_dir)
