"""A4: Übergabe ans Wiki - Transkript samt Markierungen als neue Quelle bereitstellen.

Rein anhängend: Je Sitzung entsteht ein Ordner ``<uebergabe_dir>/<sitzung>/`` (bei Kollision
``-2``, ``-3`` …). Nichts Bestehendes wird überschrieben, und das Ziel liegt nie im Wiki-Pfad
aus K1 - der ist ein Lesepfad (Leitplanke 2). Was der Lint daraus macht, ist nicht unsere
Sache (Leitplanke 5); das Format ist in ``FORMAT_VERSION`` gekapselt und lässt sich hier
ändern, ohne den Rest anzufassen (Entscheidung 3).

Inhalt: ``transkript.md`` (byte-gleiche Kopie), ``markierungen.json`` (Markierungen mit
Zeitbezug, Fundstellen, KI-Felder getrennt), ``markierungen.md`` (lesbar), ``README.md``.
Essenzen gehören nicht dazu (Leitplanke 6).
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from audioscribe.models import format_timecode
from audioscribe.souffleur.markierung import ART_LABEL, SouffleurStand

FORMAT_VERSION = 1
TRANSKRIPT_DATEIEN = ("transkript.md", "transcript.json")


@dataclass(frozen=True)
class Uebergabe:
    ordner: Path
    uebergabe_id: str
    markierungen: int
    transkript_fassung: str  # "live" | "refined" | "replay" (aus transcript.json)


def _freier_ordner(basis: Path, name: str) -> Path:
    ziel = basis / name
    n = 2
    while ziel.exists():
        ziel = basis / f"{name}-{n}"
        n += 1
    return ziel


def _ist_unter(ziel: Path, wiki: Path | None) -> bool:
    if wiki is None:
        return False
    try:
        return ziel.resolve().is_relative_to(wiki.resolve())
    except OSError:
        return False


def _fassung(session_dir: Path) -> str:
    try:
        data = json.loads((session_dir / "transcript.json").read_text(encoding="utf-8"))
        return str(data.get("mode") or "live")
    except (OSError, ValueError):
        return "unbekannt"


def schreibe(session_dir: Path, stand: SouffleurStand, *, uebergabe_dir: Path, wiki_dir: Path | None) -> Uebergabe:
    session_dir, uebergabe_dir = Path(session_dir), Path(uebergabe_dir)
    if _ist_unter(uebergabe_dir, wiki_dir):
        raise RuntimeError(f"Übergabeordner darf nicht im Wiki liegen: {uebergabe_dir}")
    quelle = session_dir / "transkript.md"
    if not quelle.is_file():
        raise FileNotFoundError(f"Kein Transkript in {session_dir}")
    uebergabe_dir.mkdir(parents=True, exist_ok=True)
    ziel = _freier_ordner(uebergabe_dir, session_dir.name or "sitzung")
    ziel.mkdir()
    for name in TRANSKRIPT_DATEIEN:
        if (session_dir / name).is_file():
            shutil.copyfile(session_dir / name, ziel / name)
    uebergabe_id = uuid.uuid4().hex[:12]
    fassung = _fassung(session_dir)
    daten = {
        "format_version": FORMAT_VERSION,
        "uebergabe_id": uebergabe_id,
        "erstellt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sitzung": session_dir.name,
        "transkript": "transkript.md",
        "transkript_fassung": fassung,
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
    (ziel / "markierungen.json").write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ziel / "markierungen.md").write_text(_render_md(session_dir.name, stand, fassung), encoding="utf-8")
    (ziel / "README.md").write_text(_README, encoding="utf-8")
    return Uebergabe(ordner=ziel, uebergabe_id=uebergabe_id, markierungen=len(stand.markierungen), transkript_fassung=fassung)


def _render_md(sitzung: str, stand: SouffleurStand, fassung: str) -> str:
    zeilen = [
        f"# Markierungen des Souffleurs: {sitzung}",
        "",
        f"Transkript: `transkript.md` (Fassung: {fassung}, Wortlaut unverändert). Jede Markierung ist über den",
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


_README = """# Übergabe aus Audioscribe (Souffleur)

Dieser Ordner ist eine neue Quelle für das Wiki. Er wurde nur angehängt, nichts Bestehendes
wurde verändert.

- `transkript.md`: das Transkript der Sitzung, Wortlaut unverändert.
- `transcript.json`: dasselbe maschinenlesbar (Absätze mit Zeitstempeln), falls vorhanden.
- `markierungen.json`: Markierungen des Souffleurs (format_version 1). Je Markierung: Art
  (`widerspruch`, `offener_punkt`, `frage`; erweiterbar), Zeitbezug (`zeitstempel`, `t_start`,
  `t_end`, `segment_id`), die wörtliche `aussage`, belegtes Wiki-Wissen unter `wiki`
  (Fundstellen mit Datei, Überschrift, Zeile; Zitat) und getrennt davon `ki_erzeugt`.
- `markierungen.md`: dieselben Markierungen lesbar.

Was aus den Markierungen im Wiki wird, entscheidet der Lint-Prozess des Wikis.
"""
