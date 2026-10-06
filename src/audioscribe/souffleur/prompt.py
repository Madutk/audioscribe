"""Prompt und Antwortschema für den Abgleich eines Fensters (A1–A3, B1, B2).

Der System-Prompt bleibt kurz, weil er als Argument an den KI-Prozess geht; Fenster, Kontext,
Wiki-Auszüge und Glossar stehen im Nutzer-Prompt. Fundstellen bekommen IDs ``F1..Fk``, damit
die KI nur auf Geliefertes zeigen kann und nichts frei zitieren muss.
"""

from __future__ import annotations

from pathlib import Path

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


def system_prompt() -> str:
    return (_PROMPT_DIR / "system.md").read_text(encoding="utf-8").strip()


def _zeile(seg: dict) -> str:
    return f"[{seg['id']}] ({format_timecode(float(seg['start']))}) {seg.get('speaker') or 'Unbekannt'}: {seg['text']}"


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
    teile = ["## Fenster (zu beurteilende Segmente)", ""]
    teile += [_zeile(s) for s in fenster]
    if kontext:
        teile += ["", "## Kontext davor (nur zum Verstehen, nicht bewerten)", ""]
        teile += [_zeile(s) for s in kontext]
    teile += ["", "## Wiki-Auszüge", ""]
    if not wiki_verknuepft:
        teile.append("Kein Wiki verknüpft. Melde nur Fragen und offene Punkte; Widersprüche sind nicht möglich.")
    elif not fundstellen:
        teile.append("Die Suche im Wiki hat zu diesem Fenster nichts gefunden. Fragen gelten dann als ohne Befund.")
    for f in fundstellen:
        kopf = f"[{f['id']}] {f['datei']} › {f['ueberschrift']} (Zeile {f['zeile']})" if f["ueberschrift"] else f"[{f['id']}] {f['datei']} (Zeile {f['zeile']})"
        teile += [kopf, f["auszug"], ""]
    if glossar:
        teile += ["## Glossar (Fehlerkennung → richtig)", ""]
        teile += [f"- {falsch} → {richtig}" for falsch, richtig in glossar[:GLOSSAR_MAX]]
    return "\n".join(teile).rstrip() + "\n"
