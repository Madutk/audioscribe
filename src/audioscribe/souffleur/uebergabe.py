"""A4: Markierungen des Souffleurs im Übergabeformat fürs Wiki.

Dieses Modul baut nur die Inhalte (``markierungen.json`` als Daten, ``markierungen.md`` als
Text) und schreibt selbst nichts. Abgelegt werden sie zusammen mit dem Transkript von
``projekt/wiki_ablage.py`` - nach ``raw/`` des Projekt-Wikis, rein anhängend. Was der Lint
daraus macht, ist nicht unsere Sache (Leitplanke 5); das Format ist in ``FORMAT_VERSION``
gekapselt und lässt sich hier ändern, ohne den Rest anzufassen (Entscheidung 3).

Essenzen gehören nicht dazu (Leitplanke 6).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from audioscribe.models import format_timecode
from audioscribe.souffleur.markierung import ART_LABEL, SouffleurStand

FORMAT_VERSION = 1
MARKIERUNGEN_JSON = "markierungen.json"
MARKIERUNGEN_MD = "markierungen.md"


def fassung(session_dir: Path) -> str:
    """Fassung des Transkripts: ``live`` | ``refined`` | ``replay`` (aus ``transcript.json``)."""
    try:
        data = json.loads((Path(session_dir) / "transcript.json").read_text(encoding="utf-8"))
        return str(data.get("mode") or "live")
    except (OSError, ValueError):
        return "unbekannt"


def daten(stand: SouffleurStand, *, sitzung: str, transkript_fassung: str) -> dict:
    """Inhalt von ``markierungen.json``: jede Markierung mit Zeitbezug, belegtes Wiki-Wissen
    und KI-Erzeugtes in getrennten Feldern."""
    return {
        "format_version": FORMAT_VERSION,
        "uebergabe_id": uuid.uuid4().hex[:12],
        "erstellt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sitzung": sitzung,
        "transkript": "transkript.md",
        "transkript_fassung": transkript_fassung,
        "wiki": stand.wiki,
        "markierungsarten": list(ART_LABEL),
        "markierungen": [
            {
                "id": m.id, "art": m.art, "label": ART_LABEL.get(m.art, m.art),
                "zeitstempel": format_timecode(m.t_start), "t_start": m.t_start, "t_end": m.t_end,
                "segment_id": m.segment_id, "sprecher": m.sprecher,
                "aussage": m.aussage,
                "wiki": {"fundstellen": [vars(f) for f in m.fundstellen], "zitat": m.wiki_zitat},
                "ki_erzeugt": {"text": m.ki_text},
                "ohne_befund": m.ohne_befund, "offener_punkt": m.ist_offener_punkt,
                "verzoegerung_s": m.verzoegerung_s,
            }
            for m in stand.markierungen
        ],
    }


def render_md(sitzung: str, stand: SouffleurStand, transkript_fassung: str) -> str:
    """Inhalt von ``markierungen.md``: dieselben Markierungen lesbar."""
    zeilen = [
        f"# Markierungen des Souffleurs: {sitzung}",
        "",
        f"Transkript: `transkript.md` (Fassung: {transkript_fassung}, Wortlaut unverändert). Jede Markierung ist über den",
        "Zeitstempel einer Stelle im Transkript zugeordnet. Spalten „Wiki“ sind belegt (Fundstelle und Zitat),",
        "Spalte „KI“ ist KI-erzeugt und keine Quelle.",
        "",
        "| Zeit | Art | Aussage | Wiki-Fundstelle | Wiki-Zitat | KI |",
        "|---|---|---|---|---|---|",
    ]
    for m in stand.markierungen:
        fund = m.fundstellen[0].kurz if m.fundstellen else ("nichts im Wiki" if m.ohne_befund else "–")
        z = lambda t: (t or "–").replace("|", "¦").replace("\n", " ")  # noqa: E731
        zeilen.append(f"| {format_timecode(m.t_start)} | {ART_LABEL.get(m.art, m.art)} | {z(m.aussage)} | {z(fund)} | {z(m.wiki_zitat)} | {z(m.ki_text)} |")
    if not stand.markierungen:
        zeilen.append("| – | – | keine Markierungen | – | – | – |")
    offen = stand.offene_punkte
    zeilen += ["", f"## Offene Punkte ({len(offen)})", ""] + ([f"- [{format_timecode(m.t_start)}] {m.aussage}" for m in offen] or ["- keine"])
    return "\n".join(zeilen) + "\n"
