"""Gerüst für ein neues, leeres LLM-Wiki (Karpathy-Muster: ``raw/`` + ``wiki/``).

Dieselbe Ordnerstruktur wie das Demo-Wiki. Angelegt wird nur, was fehlt - ein Ordner, in dem
schon etwas liegt, behält seinen Inhalt. Die Startseiten sorgen dafür, dass der Souffleur das
frische Wiki sofort lesen kann (ein leeres ``wiki/`` gälte als „kein Wiki gefunden“).
"""

from __future__ import annotations

from pathlib import Path

ORDNER: tuple[str, ...] = (
    "raw",
    "wiki/quellen",
    "wiki/prozesse",
    "wiki/anforderungen",
    "wiki/systeme",
    "wiki/rollen",
    "wiki/entscheidungen",
    "wiki/offene-punkte",
    "wiki/widersprueche",
    "wiki/analysen",
    "wiki/lint",
)


def _startseiten(name: str) -> dict[str, str]:
    return {
        "wiki/index.md": (
            f"# {name}\n\n"
            "Höchste vergebene Nummern: Q-000 · PRO-000 · ANF-000 · SYS-000 · ROL-000 · "
            "ENT-000 · OP-000 · WID-000 · AN-000\n\n"
            "## Übergreifend\n\n"
            "- [[uebersicht]]: Lagebild der Domäne\n"
            "- [[glossar]]: Begriffe und Fehlerkennungen\n\n"
            "## Quellen\n\n## Prozesse\n\n## Anforderungen\n\n## Systeme\n\n## Rollen\n\n"
            "## Entscheidungen\n\n## Offene Punkte\n\n## Widersprüche\n\n## Analysen\n"
        ),
        "wiki/log.md": "# Log\n\nChronik aller Vorgänge, nur anhängend.\n",
        "wiki/uebersicht.md": (
            f"# Übersicht {name}\n\n"
            "> KI-erzeugtes Lagebild auf Basis des Wiki-Stands.\n\n"
            "Noch keine Quellen eingearbeitet.\n"
        ),
        "wiki/glossar.md": (
            "# Glossar\n\n"
            "| Begriff | Bedeutung in der Domäne | Synonyme | Fehlerkennungen | Beleg |\n"
            "|---|---|---|---|---|\n"
        ),
        "README.md": (
            f"# LLM-Wiki: {name}\n\n"
            "- `raw/` – Rohquellen (Transkripte, Bilder). AudioScribe legt hier beendete Sitzungen ab;\n"
            "  bestehende Quellen werden nie verändert.\n"
            "- `wiki/` – die Wiki-Seiten. AudioScribe liest sie nur (Souffleur).\n"
        ),
    }


def lege_wiki_an(wurzel: Path, name: str) -> list[str]:
    """Ordner und Startseiten anlegen; liefert die neu geschriebenen Dateien (relativ)."""
    wurzel = Path(wurzel)
    for ordner in ORDNER:
        (wurzel / ordner).mkdir(parents=True, exist_ok=True)
    neu: list[str] = []
    for pfad, inhalt in _startseiten(name).items():
        datei = wurzel / pfad
        if not datei.exists():
            datei.write_text(inhalt, encoding="utf-8")
            neu.append(pfad)
    return neu
