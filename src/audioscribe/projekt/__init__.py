"""Projekte (PRD §21): ein Projekt gehört zu genau einem LLM-Wiki und trägt eigene Einstellungen.

- ``modell``: das Projekt und seine Datei ``<wiki>/.audioscribe/projekt.json``.
- ``einstellungen``: globale Vorgaben (KI, Sprache) und was ein Projekt davon überschreibt.
- ``wiki_ablage``: beendete Sitzungen und Nachbereitungen als neue Quelle nach ``raw/`` legen,
  Bilder in den Assets-Ordner. Die Seiten unter ``wiki/`` werden nie angefasst.
- ``vorlage``: Gerüst für ein neues, leeres LLM-Wiki.
"""

from __future__ import annotations

from audioscribe.projekt.modell import Projekt, ProjektFehler

__all__ = ["Projekt", "ProjektFehler"]
