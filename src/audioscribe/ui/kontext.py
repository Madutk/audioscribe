"""Aktiver Kontext der Oberfläche (PRD §21): Startseite, Projekt, einzelne Aufnahme oder Demo.

Der Server hält genau einen Kontext - wie er genau eine Live-Sitzung, einen Stapel und eine
Analyse zur Zeit hält. Ein Neuladen der Seite ändert daran nichts; nach einem Neustart des
Servers beginnt die Oberfläche wieder auf der Startseite.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path

from audioscribe.config import settings
from audioscribe.projekt import einstellungen, modell
from audioscribe.projekt.modell import Projekt

MODUS_START = "start"
MODUS_PROJEKT = "projekt"
MODUS_DATEI = "datei"
MODUS_DEMO = "demo"
MODI: tuple[str, ...] = (MODUS_START, MODUS_PROJEKT, MODUS_DATEI, MODUS_DEMO)

# Demo (zu reinen Vorführzwecken, leicht entfernbar): Wiki und Test-Meeting aus dem Repository.
DEMO_ORDNER = Path("demo") / "llm-wiki"
DEMO_TRANSKRIPT = Path("live_bahn_test") / "transkript.md"
DEMO_NAME = "Demo: Bahnbuchung"
DEMO_TEMPO = 1.0


class Kontext:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._modus = MODUS_START
        self._projekt: Projekt | None = None

    @property
    def modus(self) -> str:
        with self._lock:
            return self._modus

    @property
    def projekt(self) -> Projekt | None:
        with self._lock:
            return self._projekt

    def setze(self, modus: str, projekt: Projekt | None = None) -> None:
        if modus not in MODI:
            raise ValueError(f"Unbekannter Modus: {modus}")
        with self._lock:
            self._modus = modus
            self._projekt = projekt if modus in (MODUS_PROJEKT, MODUS_DEMO) else None


def demo_wurzel() -> Path:
    return settings.project_root / DEMO_ORDNER


def demo_verfuegbar() -> bool:
    try:
        return (demo_wurzel() / DEMO_TRANSKRIPT).is_file()
    except OSError:
        return False


def demo_projekt() -> Projekt:
    """Das Demo-Wiki als Projekt: Sitzungen landen im Cache, ins Wiki wird nie gespeichert."""
    ablage = settings.cache_dir / "demo"
    return Projekt(
        wurzel=demo_wurzel(), name=DEMO_NAME, sitzungen_dir=ablage, assets_dir=ablage / "assets",
        wiki_speichern=modell.WIKI_NIE, wiki_bilder=False, demo=True,
    )


def projekt_dict(projekt: Projekt, state: Mapping[str, object], *, mit_wiki: bool = True) -> dict:
    """Projekt für die Oberfläche: eigene Werte, wirksame Werte samt Herkunft, Wiki-Zustand."""
    eff = einstellungen.effektiv(state, projekt)
    out = {
        "name": projekt.name,
        "wurzel": str(projekt.wurzel),
        "sitzungen_dir": str(projekt.sitzungen_dir),
        "assets_dir": str(projekt.assets_dir),
        "raw_dir": str(projekt.raw_dir),
        "analysen_dir": str(projekt.analysen_dir),
        "wiki_speichern": projekt.wiki_speichern,
        "wiki_bilder": projekt.wiki_bilder,
        "demo": projekt.demo,
        "hinweis": projekt.hinweis,
        "eigen": {k: getattr(projekt, k) for k in modell.UEBERSCHREIBBAR},
        "effektiv": eff.werte,
        "herkunft": eff.herkunft,
    }
    if mit_wiki:
        from audioscribe.souffleur.wiki import pruefe_wiki

        out["wiki"] = pruefe_wiki(projekt.wurzel).als_dict()
    return out


def zuletzt(state: Mapping[str, object]) -> list[dict]:
    """Zuletzt geöffnete Projekte; ``vorhanden`` sagt, ob die Projektdatei erreichbar ist."""
    out = []
    for e in state.get("zuletzt_projekte") or []:
        if not isinstance(e, dict) or not e.get("pfad"):
            continue
        out.append({**e, "vorhanden": modell.ist_projekt(Path(e["pfad"]))})
    return out


def unterbrochene(state: Mapping[str, object], aktiv: Projekt | None = None) -> list[dict]:
    """Nicht sauber beendete Live-Sitzungen der bekannten Projekte (für das Banner)."""
    try:
        from audioscribe.live.journal import offene_sitzungen
    except ImportError:
        return []
    gesehen: set[str] = set()
    out: list[dict] = []
    kandidaten: list[tuple[str, str, Path]] = []
    if aktiv is not None and not aktiv.demo:
        kandidaten.append((str(aktiv.wurzel), aktiv.name, aktiv.sitzungen_dir))
    for e in zuletzt(state):
        if not e["vorhanden"]:
            continue
        try:
            p = modell.lade(e["pfad"])
        except modell.ProjektFehler:
            continue
        kandidaten.append((str(p.wurzel), p.name, p.sitzungen_dir))
    for wurzel, name, ordner in kandidaten:
        if wurzel in gesehen:
            continue
        gesehen.add(wurzel)
        try:
            for s in offene_sitzungen(ordner):
                out.append({**s, "projekt": wurzel, "projekt_name": name})
        except OSError:
            continue
    return out
