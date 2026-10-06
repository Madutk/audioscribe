"""Konfiguration des Souffleurs - und die EINE Stelle, die den Wiki-Pfad liest (K1).

Mit einem geöffneten Projekt (PRD §21) kommt der Wiki-Pfad aus dem Projekt, KI-Dienst und
Modell aus den Projekteinstellungen bzw. den globalen Vorgaben (``projekt/einstellungen``).
Ohne Projekt gilt der Einstellungsstand der Installation, sonst die Umgebung - so arbeiten
Kommandozeile und Tests weiter wie bisher. Der Rest des Souffleurs merkt davon nichts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from audioscribe.config import settings
from audioscribe.souffleur.ki import DEFAULT_MODEL

if TYPE_CHECKING:
    from audioscribe.projekt.modell import Projekt

# Schluessel im Einstellungsstand der Oberflaeche (ui/state.py)
KEY_WIKI = "wiki_dir"
KEY_MODELL = "souffleur_model"
KEY_BACKEND = "souffleur_backend"
KEY_AKTIV = "souffleur_aktiv"
KEY_SENSIBEL = "souffleur_sensibel"


@dataclass(frozen=True)
class SouffleurKonfig:
    wiki_dir: Path | None
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


def wiki_pfad(state: Mapping[str, object], projekt: Projekt | None = None) -> Path | None:
    """Der Wiki-Pfad: der Wiki-Ordner des Projekts, ohne Projekt der Pfad der Installation
    (Einstellungen, sonst Umgebung)."""
    if projekt is not None:
        return Path(projekt.wurzel)
    return _pfad(state.get(KEY_WIKI)) or _pfad(settings.wiki_dir)


def lade_konfig(
    state: Mapping[str, object],
    *,
    projekt: Projekt | None = None,
    speed: float = 1.0,
) -> SouffleurKonfig:
    """Konfiguration aus Projekt und Einstellungsstand; Umgebungswerte sind Vorgaben."""
    from audioscribe.projekt.einstellungen import effektiv

    eff = effektiv(state, projekt)
    return SouffleurKonfig(
        wiki_dir=wiki_pfad(state, projekt),
        modell=eff["souffleur_model"],
        backend=eff["ki_dienst"],
        aktiv=bool(state.get(KEY_AKTIV, True)),
        sensibel=bool(state.get(KEY_SENSIBEL, False)),
        speed=speed,
    )
