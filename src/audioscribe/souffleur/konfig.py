"""Konfiguration des Souffleurs - und die EINE Stelle, die den Wiki-Pfad liest (K1).

„Projekt“ ist in dieser Stufe die Audioscribe-Installation mit ihrem Einstellungsstand.
Sollen Projekte später je ein eigenes Wiki bekommen, bekommt ``lade_konfig`` den
Projektschlüssel und liest den Pfad aus dem Projekt statt aus dem globalen Stand - der Rest
des Souffleurs merkt davon nichts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from audioscribe.config import settings
from audioscribe.souffleur.ki import DEFAULT_MODEL

# Schluessel im Einstellungsstand der Oberflaeche (ui/state.py)
KEY_WIKI = "wiki_dir"
KEY_UEBERGABE = "uebergabe_dir"
KEY_MODELL = "souffleur_model"
KEY_BACKEND = "souffleur_backend"
KEY_AKTIV = "souffleur_aktiv"
KEY_SENSIBEL = "souffleur_sensibel"

UEBERGABE_ORDNER = "wiki-uebergabe"


@dataclass(frozen=True)
class SouffleurKonfig:
    wiki_dir: Path | None
    uebergabe_dir: Path
    modell: str = DEFAULT_MODEL
    backend: str = "claude-agent"
    aktiv: bool = True
    sensibel: bool = False  # auch Befunde mit Sicherheit "mittel" zeigen
    speed: float = 1.0
    # Fensterung (Anforderungen §7 "Wenig Störung", "Geschwindigkeit")
    fenster_max_s: float = 20.0
    fenster_max_segmente: int = 4
    fenster_leerlauf_s: float = 5.0
    kontext_s: float = 60.0
    top_k: int = 6
    max_befunde: int = 3
    ki_timeout_s: float = 45.0
    # Die Essenz wartet der Moderator bewusst ab; ein langsamer Aufruf darf länger dauern.
    essenz_timeout_s: float = 90.0


def _pfad(raw: object) -> Path | None:
    if isinstance(raw, str) and raw.strip():
        from audioscribe.ui.browse import normalize_path

        return normalize_path(raw.strip(), default=Path(raw.strip()))
    return None


def wiki_pfad(state: Mapping[str, object], projekt: str | None = None) -> Path | None:
    """Der Wiki-Pfad des Projekts. ``projekt`` ist für die spätere Stufe mit mehreren
    Projekten vorgesehen; jetzt gilt der Pfad der Installation (Einstellungen, sonst Umgebung)."""
    del projekt  # Stufe 1: ein Wiki je Installation
    return _pfad(state.get(KEY_WIKI)) or _pfad(settings.wiki_dir)


def lade_konfig(
    state: Mapping[str, object],
    *,
    projekt: str | None = None,
    output_dir: Path | None = None,
    speed: float = 1.0,
) -> SouffleurKonfig:
    """Konfiguration aus dem Einstellungsstand der Oberfläche; Umgebungswerte sind Vorgaben."""
    ausgabe = Path(output_dir) if output_dir is not None else settings.output_dir
    uebergabe = _pfad(state.get(KEY_UEBERGABE)) or _pfad(settings.uebergabe_dir) or ausgabe / UEBERGABE_ORDNER
    modell = state.get(KEY_MODELL)
    backend = state.get(KEY_BACKEND)
    return SouffleurKonfig(
        wiki_dir=wiki_pfad(state, projekt),
        uebergabe_dir=uebergabe,
        modell=modell.strip() if isinstance(modell, str) and modell.strip() else settings.souffleur_model,
        backend=backend.strip() if isinstance(backend, str) and backend.strip() else settings.souffleur_backend,
        aktiv=bool(state.get(KEY_AKTIV, True)),
        sensibel=bool(state.get(KEY_SENSIBEL, False)),
        speed=speed,
    )
