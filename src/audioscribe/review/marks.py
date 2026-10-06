"""Sidecar-Speicher fuer Bild-Markierungen (``marks.json``, FR-15).

Markierungen werden GETRENNT vom handeditierbaren Markdown gehalten; erneute
Transkriptionslaeufe oder Handedits am Transkript lassen sie unberuehrt (PRD §13).
Quelle der Wahrheit ist der (lag-korrigierte) Zeitstempel ``t`` – die Einfuege-Position
im Transkript wird beim Export aus ``t`` berechnet, nicht gespeichert (robust gegen
erneute Transkription).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Mark:
    t: float  # lag-korrigierter Zeitstempel in Sekunden
    png: str  # Pfad relativ zum Ausgabeordner, z.B. "frames/00-01-20.png"
    note: str | None = None
    created: str | None = None
    # Fortlaufende Nummer der automatischen Bildwechsel-Erkennung (FR-25). Sie steht im
    # Dateinamen UND im annotierten Transkript ("#0001") und ist damit die Klammer, an der
    # eine KI Bild und Textstelle zusammenbringt. Von Hand gesetzte Marks haben keine.
    id: int | None = None
    # Herkunft: "auto" (Bildwechsel-Erkennung) oder None (in der Review-Oberflaeche
    # gesetzt). Ein erneuter Lauf ersetzt nur die automatischen (s. screens.merge_marks).
    kind: str | None = None


def marks_path(out_dir: str | Path) -> Path:
    return Path(out_dir) / "marks.json"


def load_marks(out_dir: str | Path) -> list[Mark]:
    """Laedt die Markierungen (nach ``t`` sortiert); fehlende Datei -> leere Liste."""
    path = marks_path(out_dir)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    marks = [
        Mark(
            t=float(m["t"]),
            png=str(m["png"]),
            note=m.get("note"),
            created=m.get("created"),
            # .get(): aeltere marks.json kennen id/kind nicht - sie bleiben lesbar.
            id=int(m["id"]) if m.get("id") is not None else None,
            kind=m.get("kind"),
        )
        for m in raw
    ]
    marks.sort(key=lambda m: m.t)
    return marks


def save_marks(out_dir: str | Path, marks: list[Mark]) -> Path:
    """Schreibt ``<out_dir>/marks.json`` (nach ``t`` sortiert) und liefert den Pfad."""
    path = marks_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(marks, key=lambda m: m.t)
    # Atomar: die Live-Sitzung schreibt die Datei bei jedem Standbild neu, und eine beim
    # Absturz halb geschriebene marks.json kippte danach jeden Export (load_marks wirft).
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([asdict(m) for m in ordered], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path
