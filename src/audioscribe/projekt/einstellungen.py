"""Globale Einstellungen (KI, Sprache) und was ein Projekt davon überschreibt.

Global heißt: je Installation, gespeichert im Einstellungsstand der Oberfläche
(``ui/state.py``). Ein Projekt kann jeden dieser Werte für sich festlegen; fehlt der Wert im
Projekt, gilt der globale. ``effektiv`` ist die eine Stelle, die das zusammenführt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from audioscribe import variante
from audioscribe.config import settings
from audioscribe.projekt.modell import UEBERSCHREIBBAR, Projekt

# KI-Dienste zur Auswahl; weitere Dienste kommen hier dazu (Factory: souffleur/ki.make_ki).
KI_DIENSTE: tuple[tuple[str, str], ...] = (
    ("claude-agent", "Claude (Agent SDK)"),
    ("ollama", "Lokal (Ollama auf diesem Rechner)"),
)


def ki_dienste() -> tuple[tuple[str, str], ...]:
    """Die in dieser Programmvariante wählbaren Dienste (``variante.py``)."""
    if variante.aktiv():
        return ((variante.DIENST_LOKAL, "Lokale KI (auf diesem Rechner)"),)
    return KI_DIENSTE


def _zulaessig(dienst: str) -> str:
    """Unzulässiger Dienst (z. B. ``claude-agent`` aus einer alten Datei) -> lokale KI."""
    return dienst if variante.dienst_zulaessig(dienst) else variante.DIENST_LOKAL

# Schlüssel im Einstellungsstand je globalem Wert.
_STATE_KEY = {
    "ki_dienst": "souffleur_backend",
    "souffleur_model": "souffleur_model",
    "agent_model": "agent_model",
    "sprache": "sprache",
}


@dataclass(frozen=True)
class Effektiv:
    werte: dict[str, str]
    herkunft: dict[str, str]  # je Wert "global" | "projekt"

    def __getitem__(self, key: str) -> str:
        return self.werte[key]


def _text(wert: object) -> str | None:
    return wert.strip() if isinstance(wert, str) and wert.strip() else None


def globale(state: Mapping[str, object]) -> dict[str, str]:
    """Die globalen Werte: gespeicherter Stand, sonst die Vorgaben aus der Umgebung."""
    return {
        "ki_dienst": _zulaessig(_text(state.get("souffleur_backend")) or settings.souffleur_backend),
        "souffleur_model": _text(state.get("souffleur_model")) or settings.souffleur_model,
        "agent_model": _text(state.get("agent_model")) or settings.agent_model,
        "sprache": _text(state.get("sprache")) or settings.whisper_language,
    }


def als_state(werte: Mapping[str, object]) -> dict[str, str]:
    """Globale Werte auf die Schlüssel des Einstellungsstands umsetzen (nur gesetzte)."""
    return {_STATE_KEY[k]: v for k in UEBERSCHREIBBAR if (v := _text(werte.get(k))) is not None}


def effektiv(state: Mapping[str, object], projekt: Projekt | None = None) -> Effektiv:
    werte = globale(state)
    herkunft = dict.fromkeys(werte, "global")
    if projekt is not None:
        for key in UEBERSCHREIBBAR:
            eigen = _text(getattr(projekt, key))
            if key == "ki_dienst" and eigen is not None:
                eigen = _zulaessig(eigen)
            if eigen is not None:
                werte[key] = eigen
                herkunft[key] = "projekt"
    return Effektiv(werte, herkunft)


def hinweis(state: Mapping[str, object], projekt: Projekt | None = None) -> str | None:
    """Text für die Oberfläche, wenn ein gespeicherter Dienst in dieser Variante abgelehnt
    und durch die lokale KI ersetzt wurde - sonst ``None``."""
    kandidaten = [_text(state.get("souffleur_backend")) or settings.souffleur_backend]
    if projekt is not None:
        kandidaten.append(_text(projekt.ki_dienst))
    for dienst in kandidaten:
        if dienst and (text := variante.pruefe_dienst(dienst)):
            return text
    return None


def modelle(dienst: str, zweck: str) -> tuple[str, ...]:
    """Vorschlagsliste je Dienst: ``zweck`` ist ``souffleur`` oder ``agent``. Bei der lokalen KI
    gilt dieselbe Liste für beide - welches Modell passt, entscheidet der Rechner."""
    from audioscribe.souffleur.ki import SOUFFLEUR_MODELS
    from audioscribe.souffleur.ki_ollama import OLLAMA_MODELLE
    from audioscribe.ui import jobs

    if dienst == "ollama":
        return OLLAMA_MODELLE
    return SOUFFLEUR_MODELS if zweck == "souffleur" else jobs.AGENT_MODELS


def optionen(state: Mapping[str, object]) -> dict:
    """Auswahllisten für die Einstellungsseiten. Ein per Umgebung gesetzter Wert außerhalb der
    Listen (z. B. der Test-Dienst) bleibt wählbar, statt stillschweigend zu verschwinden.
    Modelle tragen den Dienst, zu dem sie gehören - die Oberfläche filtert danach."""
    from audioscribe.ui import jobs

    g = globale(state)

    dienste = ki_dienste()

    def mit(liste: list[dict], wert: str, **extra: str) -> list[dict]:
        return liste if any(e["id"] == wert for e in liste) else [{"id": wert, "label": wert, **extra}, *liste]

    def je_dienst(zweck: str) -> list[dict]:
        return [{"id": m, "label": m, "dienst": d} for d, _ in dienste for m in modelle(d, zweck)]

    return {
        "ki_dienste": mit([{"id": i, "label": l} for i, l in dienste], g["ki_dienst"]),
        "souffleur_models": mit(je_dienst("souffleur"), g["souffleur_model"], dienst=g["ki_dienst"]),
        "agent_models": mit(je_dienst("agent"), g["agent_model"], dienst=g["ki_dienst"]),
        "sprachen": mit([{"id": s, "label": _SPRACHEN.get(s, s)} for s in jobs.LANGUAGES], g["sprache"]),
    }


_SPRACHEN = {"de": "Deutsch", "en": "Englisch", "auto": "Automatisch erkennen"}
