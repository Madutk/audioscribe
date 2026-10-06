"""Markierungen des Souffleurs und ihre Ablage als Begleitdatei (Entscheidung 2).

Eine Markierung zeigt auf eine Stelle im Transkript (``segment_id``, ``t_start``/``t_end``)
und - wenn belegt - auf eine Stelle im Wiki (``fundstellen``, ``wiki_zitat``). Was die KI
selbst formuliert, steht in ``ki_text``. Der Wortlaut des Transkripts wird nie angefasst:
Markierungen liegen in ``souffleur.json`` neben dem Transkript, dazu die lesbare
Abnahmetabelle ``souffleur-protokoll.md`` (Zeitstempel, Art, Aussage, Fundstelle, Verzögerung).
"""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from audioscribe.models import format_timecode

STAND_DATEI = "souffleur.json"
PROTOKOLL_DATEI = "souffleur-protokoll.md"
STAND_VERSION = 1

# Erweiterbar: neue Arten brauchen keinen Umbau bestehender Markierungen (Anforderungen §7).
ART_WIDERSPRUCH = "widerspruch"
ART_OFFEN = "offener_punkt"
ART_FRAGE = "frage"
ARTEN: tuple[str, ...] = (ART_WIDERSPRUCH, ART_OFFEN, ART_FRAGE)
ART_LABEL = {ART_WIDERSPRUCH: "Widerspruch", ART_OFFEN: "Offener Punkt", ART_FRAGE: "Frage"}


@dataclass(frozen=True)
class Fundstelle:
    """Eine Stelle im Wiki: Datei (relativ zum Wiki, POSIX), Überschrift, Zeile, Auszug."""

    datei: str
    ueberschrift: str
    zeile: int
    auszug: str
    score: float = 0.0

    @property
    def kurz(self) -> str:
        return f"{self.datei} › {self.ueberschrift}" if self.ueberschrift else self.datei


@dataclass
class Markierung:
    id: int
    art: str
    segment_id: int
    t_start: float
    t_end: float
    sprecher: str | None
    aussage: str  # wörtlich aus dem Transkript
    fundstellen: list[Fundstelle] = field(default_factory=list)
    wiki_zitat: str | None = None  # wörtlich aus dem Wiki-Auszug
    ki_text: str = ""  # KI-erzeugt (Einschätzung, Antwortformulierung)
    ohne_befund: bool = False  # Frage/Punkt, zu dem das Wiki nichts hat
    sicherheit: str = "hoch"
    # Verzögerung (Anforderungen §7 "Geschwindigkeit"), alles in Sekunden
    verzoegerung_s: float | None = None  # Sprachende -> Hinweis (Sitzungsuhr)
    anteil_asr_s: float | None = None  # davon Spracherkennung (segment.delay)
    anteil_warten_s: float | None = None  # davon Warten im Fenster
    anteil_suche_s: float | None = None  # davon lokale Wiki-Suche (real)
    ki_start_s: float | None = None  # davon Prozessstart des KI-Dienstes (real)
    ki_antwort_s: float | None = None  # KI-Aufruf gesamt (real, enthält ki_start_s)
    verzoegerung_real_s: float | None = None  # Empfang des Segments -> Hinweis (Wanduhr)
    t_hinweis: float | None = None
    fenster_id: int = 0
    erstellt: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def ist_offener_punkt(self) -> bool:
        return self.art == ART_OFFEN or (self.art == ART_FRAGE and self.ohne_befund)

    def als_dict(self) -> dict:
        d = asdict(self)
        d["label"] = ART_LABEL.get(self.art, self.art)
        d["offener_punkt"] = self.ist_offener_punkt
        d["fundstelle"] = self.fundstellen[0].kurz if self.fundstellen else None
        return d


@dataclass
class SouffleurStand:
    sitzung: str
    speed: float = 1.0
    wiki: dict | None = None
    ki: dict | None = None
    markierungen: list[Markierung] = field(default_factory=list)
    bilanz: dict = field(default_factory=dict)
    version: int = STAND_VERSION

    @property
    def offene_punkte(self) -> list[Markierung]:
        return [m for m in self.markierungen if m.ist_offener_punkt]


# --- Bilanz -----------------------------------------------------------------------------


def _stat(werte: list[float]) -> dict:
    if not werte:
        return {"mittel": None, "median": None, "max": None}
    return {
        "mittel": round(statistics.fmean(werte), 2),
        "median": round(statistics.median(werte), 2),
        "max": round(max(werte), 2),
    }


def bilanz(markierungen: list[Markierung], *, ki_aufrufe: int = 0, ki_fehler: int = 0, fenster: int = 0) -> dict:
    hinweise = [m for m in markierungen]
    v = [m.verzoegerung_s for m in hinweise if m.verzoegerung_s is not None]
    r = [m.verzoegerung_real_s for m in hinweise if m.verzoegerung_real_s is not None]
    s = [m.ki_start_s for m in hinweise if m.ki_start_s is not None]
    return {
        "hinweise": len(hinweise),
        "je_art": {art: sum(1 for m in hinweise if m.art == art) for art in ARTEN},
        "offene_punkte": sum(1 for m in hinweise if m.ist_offener_punkt),
        "ki_aufrufe": ki_aufrufe,
        "ki_fehler": ki_fehler,
        "fenster": fenster,
        "verzoegerung_s": _stat(v),
        "verzoegerung_real_s": _stat(r),
        "ki_start_s": _stat(s),
    }


# --- Ablage (nur Begleitdateien) -------------------------------------------------------------


def _atomar(pfad: Path, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, pfad)


def schreibe(session_dir: Path, stand: SouffleurStand) -> Path:
    """``souffleur.json`` und ``souffleur-protokoll.md`` schreiben (atomar). Mehr nicht."""
    session_dir = Path(session_dir)
    data = {
        "version": stand.version,
        "sitzung": stand.sitzung,
        "speed": stand.speed,
        "wiki": stand.wiki,
        "ki": stand.ki,
        "markierungen": [m.als_dict() for m in stand.markierungen],
        "bilanz": stand.bilanz,
    }
    _atomar(session_dir / STAND_DATEI, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _atomar(session_dir / PROTOKOLL_DATEI, render_protokoll(stand))
    return session_dir / STAND_DATEI


def lade(session_dir: Path) -> SouffleurStand | None:
    try:
        data = json.loads((Path(session_dir) / STAND_DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    markierungen = []
    for roh in data.get("markierungen", []):
        felder = {k: v for k, v in roh.items() if k in Markierung.__dataclass_fields__}
        felder["fundstellen"] = [Fundstelle(**f) for f in roh.get("fundstellen", [])]
        markierungen.append(Markierung(**felder))
    return SouffleurStand(
        sitzung=str(data.get("sitzung", "")), speed=float(data.get("speed", 1.0)), wiki=data.get("wiki"),
        ki=data.get("ki"), markierungen=markierungen, bilanz=dict(data.get("bilanz") or {}),
        version=int(data.get("version", STAND_VERSION)),
    )


# --- Protokoll (Abnahmetabelle) ---------------------------------------------------------------


def _s(wert: float | None) -> str:
    return "–" if wert is None else f"{wert:.1f} s".replace(".", ",")


def _zelle(text: str | None) -> str:
    return (text or "–").replace("|", "¦").replace("\n", " ").strip()


def render_protokoll(stand: SouffleurStand) -> str:
    zeilen = [
        f"# Souffleur-Protokoll: {stand.sitzung}",
        "",
        "Je Markierung: Zeitstempel der Aussage, Art, betroffene Aussage (wörtlich), Fundstelle im Wiki,",
        "gemessene Verzögerung (Sprachende bis Hinweis auf der Sitzungsuhr; in Klammern der Anteil des",
        "KI-Prozessstarts) und die reale Verzögerung ab Empfang des Segments. Spalte „KI“ ist KI-erzeugt.",
        "",
    ]
    if stand.speed != 1.0:
        zeilen += [f"Abspieltempo {stand.speed:g}×: Sitzungs-Verzögerungen sind entsprechend gestreckt, die reale Spalte nicht.", ""]
    if stand.wiki:
        zeilen += [f"Wiki: {stand.wiki.get('name') or stand.wiki.get('pfad')} ({stand.wiki.get('zustand')}), Stand {stand.wiki.get('stand') or '–'}", ""]
    zeilen += [
        "| Zeit | Art | Aussage | Fundstelle | Wiki-Zitat | KI | Hinweis nach | real |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m in stand.markierungen:
        fund = m.fundstellen[0].kurz if m.fundstellen else ("nichts im Wiki" if m.ohne_befund else "–")
        start = f"davon KI-Start {_s(m.ki_start_s)}" if m.ki_start_s is not None else ""
        zeilen.append(
            f"| {format_timecode(m.t_start)} | {ART_LABEL.get(m.art, m.art)} | {_zelle(m.aussage)} | {_zelle(fund)} "
            f"| {_zelle(m.wiki_zitat)} | {_zelle(m.ki_text)} | {_s(m.verzoegerung_s)}{f' ({start})' if start else ''} "
            f"| {_s(m.verzoegerung_real_s)} |"
        )
    if not stand.markierungen:
        zeilen.append("| – | – | keine Markierungen | – | – | – | – | – |")
    offen = stand.offene_punkte
    zeilen += ["", f"## Offene Punkte ({len(offen)})", ""]
    zeilen += [f"- [{format_timecode(m.t_start)}] {m.aussage}" for m in offen] or ["- keine"]
    b = stand.bilanz
    if b:
        v, r, s = b.get("verzoegerung_s", {}), b.get("verzoegerung_real_s", {}), b.get("ki_start_s", {})
        zeilen += [
            "", "## Bilanz", "",
            f"- Hinweise: {b.get('hinweise', 0)} (Widerspruch {b.get('je_art', {}).get(ART_WIDERSPRUCH, 0)}, "
            f"offener Punkt {b.get('je_art', {}).get(ART_OFFEN, 0)}, Frage {b.get('je_art', {}).get(ART_FRAGE, 0)}), "
            f"offene Punkte gesamt {b.get('offene_punkte', 0)}",
            f"- KI-Aufrufe: {b.get('ki_aufrufe', 0)}, davon Fehler {b.get('ki_fehler', 0)}, Fenster {b.get('fenster', 0)}",
            f"- Verzögerung Sitzung: Ø {_s(v.get('mittel'))} · Median {_s(v.get('median'))} · max {_s(v.get('max'))}",
            f"- Verzögerung real: Ø {_s(r.get('mittel'))} · Median {_s(r.get('median'))} · max {_s(r.get('max'))}",
            f"- KI-Prozessstart: Ø {_s(s.get('mittel'))} · max {_s(s.get('max'))}",
        ]
    return "\n".join(zeilen) + "\n"
