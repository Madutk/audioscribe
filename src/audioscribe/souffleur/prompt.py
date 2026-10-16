"""Prompt und Antwortschema für den Abgleich eines Fensters (A1–A3, B1, B2).

Der System-Prompt bleibt kurz, weil er als Argument an den KI-Prozess geht; Fenster, Kontext,
Wiki-Auszüge und Glossar stehen im Nutzer-Prompt. Fundstellen bekommen IDs ``F1..Fk``, damit
die KI nur auf Geliefertes zeigen kann und nichts frei zitieren muss.

Ist die Oberfläche englisch (``i18n.sprache()``), gelten ``system.en.md`` und englische
Überschriften im Nutzer-Prompt - die KI antwortet dann englisch. Schlüssel und Enum-Werte des
Antwortschemas bleiben in beiden Sprachen gleich, der Code wertet sie aus.
"""

from __future__ import annotations

from pathlib import Path

from audioscribe.i18n import sprache
from audioscribe.models import format_timecode
from audioscribe.souffleur.markierung import ARTEN, Fundstelle

_PROMPT_DIR = Path(__file__).parent / "prompts"
AUSZUG_MAX = 700
GLOSSAR_MAX = 60

SCHEMA = {
    "type": "object",
    "required": ["befunde", "uebergangen"],
    "properties": {
        "befunde": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["segment_id", "art", "aussage", "fundstelle_id", "wiki_zitat", "ki_text", "sicherheit"],
                "properties": {
                    "segment_id": {"type": "integer"},
                    "art": {"type": "string", "enum": list(ARTEN)},
                    "aussage": {"type": "string"},
                    "fundstelle_id": {"type": ["string", "null"]},
                    "wiki_zitat": {"type": ["string", "null"]},
                    "ki_text": {"type": "string", "maxLength": 240},
                    "suchbegriffe": {"type": "array", "items": {"type": "string"}},
                    "sicherheit": {"type": "string", "enum": ["hoch", "mittel"]},
                },
            },
        },
        "uebergangen": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["segment_id", "grund"],
                "properties": {
                    "segment_id": {"type": "integer"},
                    "grund": {
                        "type": "string",
                        "enum": ["smalltalk", "organisatorisch", "passt_zum_wiki", "rhetorische_frage", "unverstaendlich"],
                    },
                },
            },
        },
    },
}


# Feste Teile des Nutzer-Prompts je Sprache der Oberfläche (Sprache der KI-Antworten).
_TEXTE: dict[str, dict[str, str]] = {
    "de": {
        "unbekannt": "Unbekannt",
        "fenster": "## Fenster (zu beurteilende Segmente)",
        "kontext": "## Kontext davor (nur zum Verstehen, nicht bewerten)",
        "wiki": "## Wiki-Auszüge",
        "kein_wiki": "Kein Wiki verknüpft. Melde nur Fragen und offene Punkte; Widersprüche sind nicht möglich.",
        "nichts": "Die Suche im Wiki hat zu diesem Fenster nichts gefunden. Fragen gelten dann als ohne Befund.",
        "zeile": "Zeile",
        "glossar": "## Glossar (Fehlerkennung → richtig)",
    },
    "en": {
        "unbekannt": "Unknown",
        "fenster": "## Window (segments to assess)",
        "kontext": "## Preceding context (for understanding only, do not assess)",
        "wiki": "## Wiki excerpts",
        "kein_wiki": "No wiki linked. Report only questions and open items; contradictions are not possible.",
        "nichts": "The wiki search found nothing for this window. Questions then count as having no finding in the wiki.",
        "zeile": "line",
        "glossar": "## Glossary (misrecognition → correct)",
    },
}


def prompt_datei(name: str) -> Path:
    """``name.md`` - bei englischer Oberfläche ``name.en.md``, falls vorhanden."""
    if sprache() == "en" and (_PROMPT_DIR / f"{name}.en.md").is_file():
        return _PROMPT_DIR / f"{name}.en.md"
    return _PROMPT_DIR / f"{name}.md"


def _texte() -> dict[str, str]:
    return _TEXTE["en" if sprache() == "en" else "de"]


def system_prompt() -> str:
    return prompt_datei("system").read_text(encoding="utf-8").strip()


def _zeile(seg: dict, unbekannt: str = "Unbekannt") -> str:
    return f"[{seg['id']}] ({format_timecode(float(seg['start']))}) {seg.get('speaker') or unbekannt}: {seg['text']}"


def fundstellen_mit_ids(fundstellen: list[Fundstelle]) -> list[dict]:
    """Fundstellen als Dicts mit IDs F1..Fk - so gehen sie in Prompt und KiAuftrag.kontext."""
    out = []
    for i, f in enumerate(fundstellen, start=1):
        out.append({"id": f"F{i}", "datei": f.datei, "ueberschrift": f.ueberschrift, "zeile": f.zeile,
                    "auszug": f.auszug[:AUSZUG_MAX]})
    return out


def baue_prompt(
    fenster: list[dict],
    *,
    kontext: list[dict],
    fundstellen: list[dict],
    glossar: list[tuple[str, str]] | None = None,
    wiki_verknuepft: bool = True,
) -> str:
    t = _texte()
    teile = [t["fenster"], ""]
    teile += [_zeile(s, t["unbekannt"]) for s in fenster]
    if kontext:
        teile += ["", t["kontext"], ""]
        teile += [_zeile(s, t["unbekannt"]) for s in kontext]
    teile += ["", t["wiki"], ""]
    if not wiki_verknuepft:
        teile.append(t["kein_wiki"])
    elif not fundstellen:
        teile.append(t["nichts"])
    for f in fundstellen:
        ort = f"{f['datei']} › {f['ueberschrift']}" if f["ueberschrift"] else f["datei"]
        teile += [f"[{f['id']}] {ort} ({t['zeile']} {f['zeile']})", f["auszug"], ""]
    if glossar:
        teile += [t["glossar"], ""]
        teile += [f"- {falsch} → {richtig}" for falsch, richtig in glossar[:GLOSSAR_MAX]]
    return "\n".join(teile).rstrip() + "\n"
