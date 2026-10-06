"""C1: Essenz der letzten Minuten auf Knopfdruck - KI-erzeugt und so gekennzeichnet.

Die Zusammenfassung bezieht sich genau auf das Zeitfenster ``[jetzt - minuten, jetzt]`` der
Sitzungsuhr. Sie wird in ``souffleur-essenz.jsonl`` abgelegt (Entscheidung 7), getrennt vom
Transkript, und ist nie Teil der Übergabe ans Wiki (Leitplanke 6).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from audioscribe.models import format_timecode
from audioscribe.souffleur.ki import KiAntwort, KiAuftrag, KiDienst, KiFehler

ESSENZ_DATEI = "souffleur-essenz.jsonl"
MINUTEN: tuple[int, ...] = (2, 5)
_PROMPT_DIR = Path(__file__).parent / "prompts"

SCHEMA = {
    "type": "object",
    "required": ["essenz", "offen"],
    "properties": {
        "essenz": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "object", "required": ["punkt"], "properties": {"punkt": {"type": "string"}}},
        },
        "offen": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(frozen=True)
class Essenz:
    minuten: int
    t_von: float
    t_bis: float
    segment_ids: list[int]
    punkte: list[str]
    offen: list[str]
    ki_s: float
    ki_start_s: float
    modell: str
    erstellt: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ki_erzeugt: bool = True  # Kennzeichnung setzt der Code, nie das Modell

    @property
    def fenster(self) -> str:
        return f"{format_timecode(self.t_von)}–{format_timecode(self.t_bis)}"


def system_prompt() -> str:
    return (_PROMPT_DIR / "essenz.md").read_text(encoding="utf-8").strip()


def im_fenster(segmente: list[dict], *, jetzt: float, minuten: int) -> list[dict]:
    """Segmente, deren Ende im Fenster ``[jetzt - minuten·60, jetzt]`` liegt, nach Start sortiert."""
    von = max(0.0, jetzt - minuten * 60)
    return sorted((s for s in segmente if von <= float(s["end"]) <= jetzt), key=lambda s: float(s["start"]))


def prompt(segmente: list[dict], *, minuten: int, t_von: float, t_bis: float) -> str:
    zeilen = [f"## Ausschnitt ({minuten} Minuten, {format_timecode(t_von)} bis {format_timecode(t_bis)})", ""]
    for s in segmente:
        zeilen.append(f"[{format_timecode(float(s['start']))}] {s.get('speaker') or 'Unbekannt'}: {s['text']}")
    return "\n".join(zeilen)


def erzeuge(ki: KiDienst, segmente: list[dict], *, jetzt: float, minuten: int, timeout_s: float = 45.0) -> Essenz:
    """Essenz des Fensters erzeugen. Leeres Fenster oder KI-Fehler → ``KiFehler``."""
    if minuten not in MINUTEN:
        raise ValueError(f"Fenster muss {MINUTEN} Minuten sein, nicht {minuten}")
    auswahl = im_fenster(segmente, jetzt=jetzt, minuten=minuten)
    t_von, t_bis = max(0.0, jetzt - minuten * 60), jetzt
    if not auswahl:
        raise KiFehler(f"In den letzten {minuten} Minuten wurde nichts transkribiert.")
    auftrag = KiAuftrag(
        system=system_prompt(),
        prompt=prompt(auswahl, minuten=minuten, t_von=t_von, t_bis=t_bis),
        schema=SCHEMA,
        kontext={"art": "essenz", "segmente": auswahl, "minuten": minuten},
        timeout_s=timeout_s,
    )
    antwort: KiAntwort = ki.antworte(auftrag)
    punkte = [str(p.get("punkt", "")).strip() for p in antwort.daten.get("essenz", []) if isinstance(p, dict)]
    offen = [str(o).strip() for o in antwort.daten.get("offen", []) if str(o).strip()]
    return Essenz(
        minuten=minuten, t_von=round(t_von, 1), t_bis=round(t_bis, 1),
        segment_ids=[int(s["id"]) for s in auswahl], punkte=[p for p in punkte if p][:5], offen=offen,
        ki_s=round(antwort.antwort_s, 2), ki_start_s=round(antwort.start_s, 2), modell=antwort.modell,
    )


def anhaengen(session_dir: Path, essenz: Essenz) -> Path:
    """Eine Zeile an ``souffleur-essenz.jsonl`` anhängen (nur anhängend, nie überschreiben)."""
    pfad = Path(session_dir) / ESSENZ_DATEI
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(essenz), ensure_ascii=False) + "\n")
    return pfad
