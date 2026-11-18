"""Mitdenker: die zweite, langsame Spur des Souffleurs (Stufe 2, Anforderungen §5).

Der Abgleich je Fenster (``kern.py``) meldet schnell, was vom Wiki abweicht oder offen ist. Der
Mitdenker liest alle ein bis zwei Minuten mehrere Minuten Gespräch, lässt die KI nachdenken und
liefert **Karten**: Bestätigungen aus dem Wiki, Erkenntnisse des Gesprächs und weitergedachte
Gedanken. Er ist zuschaltbar (Vorgabe aus) und läuft im eigenen Thread - die schnelle Spur wartet
nie auf ihn.

Bewusste Ausnahme von Leitplanke 7, nur hier: Die KI darf Wiki, Gespräch und eigenes
Allgemeinwissen verbinden. Leitplanke 6 gilt weiter - die Herkunft je Karte setzt der Code:
``wiki`` nur bei wörtlich geprüftem Zitat, ``gespraech`` nur bei wörtlich geprüfter Aussage.

Karten sind keine ``Markierung``: Sie stehen nur in ``souffleur-mitdenker.json``/``.md`` im
Sitzungsordner und gehen weder in Bilanz und Protokoll noch in die Übergabe ans Wiki.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from audioscribe.i18n import sprache, tr
from audioscribe.models import format_timecode
from audioscribe.souffleur import markierung as mk
from audioscribe.souffleur import prompt as prompt_modul
from audioscribe.souffleur import wiki as wiki_modul
from audioscribe.souffleur.ki import BACKEND_OLLAMA, KiAuftrag, KiDienst, KiFehler
from audioscribe.souffleur.konfig import SouffleurKonfig

STAND_DATEI = "souffleur-mitdenker.json"
MD_DATEI = "souffleur-mitdenker.md"
VERSION = 1

ART_BESTAETIGUNG = "bestaetigung"
ART_ERKENNTNIS = "erkenntnis"
ART_GEDANKE = "gedanke"
ARTEN: tuple[str, ...] = (ART_BESTAETIGUNG, ART_ERKENNTNIS, ART_GEDANKE)
ART_LABEL = {ART_BESTAETIGUNG: "Bestätigung", ART_ERKENNTNIS: "Erkenntnis", ART_GEDANKE: "Gedanke"}

HERKUNFT_WIKI = "wiki"
HERKUNFT_GESPRAECH = "gespraech"
HERKUNFT_KI = "allgemeinwissen"
HERKUNFT_LABEL = {HERKUNFT_WIKI: "Wiki", HERKUNFT_GESPRAECH: "Gespräch", HERKUNFT_KI: "KI-Wissen"}

EREIGNIS = "mitdenken"  # Typ des Ereignisses an den Browser - eigener Strom neben "hinweis"

KARTEN_JE_LAUF = 2
TITEL_MAX = 80
KI_TEXT_MAX = 400
AUSSAGE_MIN = 12  # kürzere "wörtliche" Ausschnitte belegen nichts
ZITAT_MIN = 20
TRANSKRIPT_MAX = 9000  # Zeichen Gespräch im Prompt
TOP_K = 8
SCHON_GESAGT_MAX = 12
LEITFADEN_MAX = 10
_DEDUP_AEHNLICH = 0.5
_TICK_S = 1.0
_LEERLAUF_S = 20.0  # so lange Stille: schon früher mitdenken ...
_LEERLAUF_TAKT_S = 45.0  # ... aber nicht dichter als so
_LEERLAUF_WOERTER = 15
_FEHLER_FOLGE_MAX = 2
_FEHLER_PAUSE_S = 180.0
_ABSCHLUSS_WARTEN_S = 15.0

SCHEMA = {
    "type": "object",
    "required": ["karten"],
    "properties": {
        "karten": {
            "type": "array",
            "maxItems": KARTEN_JE_LAUF,
            "items": {
                "type": "object",
                "required": [
                    "art",
                    "segment_id",
                    "aussage",
                    "titel",
                    "ki_text",
                    "fundstelle_id",
                    "wiki_zitat",
                    "allgemeinwissen",
                    "relevanz",
                ],
                "properties": {
                    "art": {"type": "string", "enum": list(ARTEN)},
                    "segment_id": {"type": "integer"},
                    "aussage": {"type": "string"},
                    "titel": {"type": "string", "maxLength": TITEL_MAX},
                    "ki_text": {"type": "string", "maxLength": KI_TEXT_MAX},
                    "fundstelle_id": {"type": ["string", "null"]},
                    "wiki_zitat": {"type": ["string", "null"]},
                    "bezug_segment_ids": {"type": "array", "maxItems": 3, "items": {"type": "integer"}},
                    "allgemeinwissen": {"type": "boolean"},
                    "relevanz": {"type": "string", "enum": ["hoch", "mittel"]},
                },
            },
        },
    },
}

_TEXTE: dict[str, dict[str, str]] = {
    "de": {
        "neu": "## Neu seit dem letzten Mitdenken (hierauf beziehen sich Karten)",
        "kontext": "## Bisheriges Gespräch (Kontext)",
        "gesagt": "## Schon gesagt (deine bisherigen Karten – nicht wiederholen)",
        "gemeldet": "## Schon gemeldet (Hinweise des Souffleurs – nicht wiederholen)",
        "leitfaden": "## Leitfaden (offene Punkte des Moderators – kein Wissen)",
        "kein_wiki": "Kein Wiki verknüpft. Bestätigungen sind nicht möglich.",
        "nichts": "Die Suche im Wiki hat zu diesem Abschnitt nichts gefunden. Bestätigungen sind dann nicht möglich.",
    },
    "en": {
        "neu": "## New since the last thinking run (cards refer to this)",
        "kontext": "## Earlier conversation (context)",
        "gesagt": "## Already said (your earlier cards – do not repeat)",
        "gemeldet": "## Already reported (the prompter's hints – do not repeat)",
        "leitfaden": "## Agenda (the moderator's open items – not knowledge)",
        "kein_wiki": "No wiki linked. Confirmations are not possible.",
        "nichts": "The wiki search found nothing for this section. Confirmations are then not possible.",
    },
}


def art_label(art: str) -> str:
    """Bezeichnung der Art in der Sprache der Oberfläche."""
    if art == ART_BESTAETIGUNG:
        return tr("Bestätigung")
    if art == ART_ERKENNTNIS:
        return tr("Erkenntnis")
    if art == ART_GEDANKE:
        return tr("Gedanke")
    return art


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _woerter(text: str) -> int:
    return len(wiki_modul.tokenisiere(text))


@dataclass
class Karte:
    id: str  # "M<n>" - eigener ID-Raum neben den Markierungen
    art: str
    segment_id: int
    t_start: float
    t_end: float
    sprecher: str | None
    aussage: str  # wörtlich aus dem Transkript, oder leer (Gedanke ohne belegbaren Ausschnitt)
    titel: str  # KI-erzeugt
    ki_text: str  # KI-erzeugt
    fundstellen: list[mk.Fundstelle] = field(default_factory=list)
    wiki_zitat: str | None = None  # wörtlich aus dem Wiki-Auszug
    bezug_segment_ids: list[int] = field(default_factory=list)
    herkunft: list[str] = field(default_factory=list)  # setzt der Code, nie das Modell
    relevanz: str = "hoch"
    t_hinweis: float | None = None
    ki_antwort_s: float | None = None
    lauf: int = 0
    erstellt: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ki_erzeugt: bool = True

    def als_dict(self) -> dict:
        d = asdict(self)
        d["label"] = art_label(self.art)
        d["fundstelle"] = self.fundstellen[0].kurz if self.fundstellen else None
        return d


# --- Prompt ------------------------------------------------------------------------------------


def system_prompt() -> str:
    return prompt_modul.prompt_datei("mitdenken").read_text(encoding="utf-8").strip()


def teile_transkript(segmente: list[dict], stand: float) -> tuple[list[dict], list[dict], int]:
    """Segmente des Fensters in (Kontext, Neu) teilen. Neu ist, was nach ``stand`` endet und live
    kam (wiederhergestellte Segmente sind nur Kontext). Über ``TRANSKRIPT_MAX`` Zeichen fällt das
    Älteste weg - erst vom Kontext, dann vom Neuen. Dritter Wert: Zahl der gekappten Segmente."""
    neu = [s for s in segmente if float(s["end"]) > stand and s.get("empfangen_mono") is not None]
    neu_ids = {int(s["id"]) for s in neu}
    alt = [s for s in segmente if int(s["id"]) not in neu_ids]
    gekappt = 0
    laenge = sum(len(str(s["text"])) for s in segmente)
    while laenge > TRANSKRIPT_MAX and (alt or len(neu) > 1):
        raus = alt.pop(0) if alt else neu.pop(0)
        laenge -= len(str(raus["text"]))
        gekappt += 1
    return alt, neu, gekappt


def baue_prompt(
    neu: list[dict],
    *,
    kontext: list[dict],
    fundstellen: list[dict],
    glossar: list[tuple[str, str]] | None = None,
    wiki_verknuepft: bool = True,
    karten: list[Karte] | None = None,
    markierungen: list[dict] | None = None,
    leitfaden: list[dict] | None = None,
) -> str:
    englisch = sprache() == "en"
    t, basis = _TEXTE["en" if englisch else "de"], prompt_modul._texte()
    teile: list[str] = []
    if kontext:
        teile += [t["kontext"], ""]
        teile += [prompt_modul._zeile(s, basis["unbekannt"]) for s in kontext]
        teile.append("")
    teile += [t["neu"], ""]
    teile += [prompt_modul._zeile(s, basis["unbekannt"]) for s in neu]
    teile += ["", basis["wiki"], ""]
    if not wiki_verknuepft:
        teile.append(t["kein_wiki"])
    elif not fundstellen:
        teile.append(t["nichts"])
    for f in fundstellen:
        ort = f"{f['datei']} › {f['ueberschrift']}" if f["ueberschrift"] else f["datei"]
        teile += [f"[{f['id']}] {ort} ({basis['zeile']} {f['zeile']})", f["auszug"], ""]
    if glossar:
        teile += [basis["glossar"], ""]
        teile += [f"- {falsch} → {richtig}" for falsch, richtig in glossar[: prompt_modul.GLOSSAR_MAX]]
    if karten:
        teile += ["", t["gesagt"], ""]
        teile += [
            f"[{k.id}] ({format_timecode(k.t_start)}) {art_label(k.art)}: {k.titel}" for k in karten[-SCHON_GESAGT_MAX:]
        ]
    if markierungen:
        teile += ["", t["gemeldet"], ""]
        teile += [
            f"({format_timecode(float(m['t_start']))}) {m.get('label') or m['art']}: {m['aussage']}"
            for m in markierungen
        ]
    if leitfaden:
        teile += ["", t["leitfaden"], ""]
        teile += [f"[{p['id']}] {p['text']}" for p in leitfaden[:LEITFADEN_MAX]]
    return "\n".join(teile).rstrip() + "\n"


# --- Prüfung -----------------------------------------------------------------------------------


def pruefe_karte(roh: Any, je_id: dict[int, dict], fund_je_id: dict, *, sensibel: bool = False) -> Karte | None:
    """Lokale Validierung wie beim Abgleich: Wo ein Zitat oder eine Aussage behauptet wird, muss
    sie wörtlich im Gelieferten stehen. Eine Bestätigung ohne beides wird verworfen; ein Gedanke
    darf ohne Beleg bleiben - dann trägt er auch keine Herkunft „Wiki“ oder „Gespräch“."""
    return pruefe_mit_grund(roh, je_id, fund_je_id, sensibel=sensibel)[0]


def pruefe_mit_grund(
    roh: Any, je_id: dict[int, dict], fund_je_id: dict, *, sensibel: bool = False
) -> tuple[Karte | None, str]:
    """Wie ``pruefe_karte``, dazu der Grund einer Ablehnung - er steht in der Diagnose, damit sich
    nach echten Sitzungen nachstellen lässt, was der Filter wegnimmt."""
    if not isinstance(roh, dict):
        return None, "ungueltig"
    try:
        segment_id = int(roh.get("segment_id"))
    except (TypeError, ValueError):
        return None, "ungueltig"
    seg = je_id.get(segment_id)
    art = str(roh.get("art") or "")
    if art not in ARTEN:
        return None, "unbekannte_art"
    if seg is None:
        return None, "unbekanntes_segment"
    titel = " ".join(str(roh.get("titel") or "").split())[:TITEL_MAX]
    ki_text = str(roh.get("ki_text") or "").strip()[:KI_TEXT_MAX]
    if not titel or not ki_text:
        return None, "ohne_text"
    relevanz = str(roh.get("relevanz") or "hoch")

    aussage = str(roh.get("aussage") or "").strip()
    if len(aussage) < AUSSAGE_MIN or _norm(aussage) not in _norm(str(seg["text"])):
        aussage = ""
    fundstellen: list[mk.Fundstelle] = []
    zitat: str | None = None
    treffer = fund_je_id.get(str(roh.get("fundstelle_id") or ""))
    if treffer is not None:
        fdict, fobj = treffer
        kandidat = str(roh.get("wiki_zitat") or "").strip()
        if len(kandidat) >= ZITAT_MIN and _norm(kandidat) in _norm(fdict["auszug"]):
            fundstellen, zitat = [fobj], kandidat
    if art == ART_BESTAETIGUNG and not zitat:
        return None, "ohne_zitat"  # ohne wörtliches Zitat bestätigt nichts
    if art in (ART_BESTAETIGUNG, ART_ERKENNTNIS) and not aussage:
        return None, "ohne_aussage"
    # "Lieber wenige": Unbelegtes mit mittlerer Relevanz bleibt weg. Eine Bestätigung ist dagegen
    # doppelt wörtlich geprüft - und das Modell stuft sie fast immer als "mittel" ein (gemessen).
    if relevanz == "mittel" and art != ART_BESTAETIGUNG and not sensibel:
        return None, "relevanz_mittel"

    herkunft: list[str] = []
    if zitat:
        herkunft.append(HERKUNFT_WIKI)
    if aussage:
        herkunft.append(HERKUNFT_GESPRAECH)
    # Ohne jeden Beleg kann der Text nur aus dem Modell stammen - gleich, was es dazu angibt.
    if roh.get("allgemeinwissen") is True or not herkunft:
        herkunft.append(HERKUNFT_KI)
    bezug: list[int] = []
    for wert in roh.get("bezug_segment_ids") or []:
        try:
            sid = int(wert)
        except (TypeError, ValueError):
            continue
        if sid in je_id and sid != segment_id and sid not in bezug:
            bezug.append(sid)
    return Karte(
        id="",
        art=art,
        segment_id=segment_id,
        t_start=float(seg["start"]),
        t_end=float(seg["end"]),
        sprecher=seg.get("speaker"),
        aussage=aussage,
        titel=titel,
        ki_text=ki_text,
        fundstellen=fundstellen,
        wiki_zitat=zitat,
        bezug_segment_ids=bezug[:3],
        herkunft=herkunft,
        relevanz=relevanz,
    ), ""


def ist_dublette(karte: Karte, alte: list[Karte], markierungen: list[dict] | None = None) -> bool:
    """Über die ganze Sitzung: gleiche Art mit ähnlichem Inhalt, derselbe Wiki-Beleg, oder eine
    Bestätigung zu einer Frage, die der Souffleur schon mit derselben Fundstelle beantwortet hat."""
    woerter = set(wiki_modul.tokenisiere(f"{karte.titel} {karte.ki_text}"))
    fund = karte.fundstellen[0].kurz if karte.fundstellen else ""
    for alt in alte:
        if (
            fund
            and karte.wiki_zitat
            and alt.fundstellen
            and alt.fundstellen[0].kurz == fund
            and _norm(alt.wiki_zitat or "") == _norm(karte.wiki_zitat)
        ):
            return True
        if alt.art != karte.art:
            continue
        alt_w = set(wiki_modul.tokenisiere(f"{alt.titel} {alt.ki_text}"))
        if woerter and alt_w and len(woerter & alt_w) / len(woerter | alt_w) >= _DEDUP_AEHNLICH:
            return True
    if karte.art == ART_BESTAETIGUNG and fund:
        for m in markierungen or []:
            if m.get("art") == mk.ART_FRAGE and m.get("segment_id") == karte.segment_id and m.get("fundstelle") == fund:
                return True
    return False


# --- Ablage (nur Sitzungsordner) -----------------------------------------------------------------


def schreibe(session_dir: Path, karten: list[Karte], *, bilanz: dict, modell: str = "") -> Path:
    """``souffleur-mitdenker.json`` und ``.md`` schreiben (atomar). Mehr nicht."""
    session_dir = Path(session_dir)
    daten = {
        "version": VERSION,
        "sitzung": session_dir.name,
        "modell": modell,
        "ki_erzeugt": True,
        "karten": [k.als_dict() for k in karten],
        "bilanz": bilanz,
    }
    mk._atomar(session_dir / STAND_DATEI, json.dumps(daten, ensure_ascii=False, indent=2) + "\n")
    mk._atomar(session_dir / MD_DATEI, render_md(session_dir.name, karten))
    return session_dir / STAND_DATEI


def lade(session_dir: Path) -> tuple[list[Karte], dict]:
    """Karten und Bilanz einer unterbrochenen Sitzung; ohne Datei beides leer."""
    try:
        daten = json.loads((Path(session_dir) / STAND_DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(daten, dict):
        return [], {}
    karten: list[Karte] = []
    for roh in daten.get("karten", []):
        if not isinstance(roh, dict):
            continue
        try:
            felder = {k: v for k, v in roh.items() if k in Karte.__dataclass_fields__}
            felder["fundstellen"] = [mk.Fundstelle(**f) for f in roh.get("fundstellen", [])]
            karten.append(Karte(**felder))
        except TypeError:
            continue
    bilanz = daten.get("bilanz")
    return karten, dict(bilanz) if isinstance(bilanz, dict) else {}


def render_md(sitzung: str, karten: list[Karte]) -> str:
    zeilen = [
        f"# Mitdenker: {sitzung}",
        "",
        "KI-erzeugt, keine Quelle. Der Mitdenker verbindet Gespräch, Wiki und Allgemeinwissen der KI.",
        "„Gesagt“ und „Wiki“ sind wörtlich und geprüft; alles unter „KI“ hat die KI formuliert.",
        "",
    ]
    if not karten:
        zeilen.append("Keine Karten.")
    for k in karten:
        herkunft = ", ".join(HERKUNFT_LABEL.get(h, h) for h in k.herkunft) or "–"
        zeilen += [
            f"## [{format_timecode(k.t_start)}] {ART_LABEL.get(k.art, k.art)}: {k.titel}",
            "",
            f"- Herkunft: {herkunft}",
        ]
        if k.aussage:
            zeilen.append(f"- Gesagt ({k.sprecher or 'Unbekannt'}): „{k.aussage}“")
        if k.fundstellen and k.wiki_zitat:
            zeilen.append(f"- Wiki ({k.fundstellen[0].kurz}, Zeile {k.fundstellen[0].zeile}): „{k.wiki_zitat}“")
        zeilen += [f"- KI: {k.ki_text}", ""]
    return "\n".join(zeilen).rstrip() + "\n"


# --- Die Spur ------------------------------------------------------------------------------------


class Mitdenker:
    """Ein Objekt je Sitzung, im Besitz des ``Souffleur``. ``quelle`` ist der Souffleur: Er liefert
    den Schnappschuss (kurz unter seiner Sperre), die Uhr, das Log und die Zustellung. Suche,
    KI-Aufruf und Schreiben laufen hier ohne jede Sperre des Souffleurs."""

    def __init__(self, quelle: Any, ki: KiDienst | None, konfig: SouffleurKonfig) -> None:
        self._quelle = quelle
        self.ki = ki
        self.konfig = konfig
        self._aktiv = bool(konfig.mitdenken)
        self._lock = threading.Lock()  # nur Karten, Zähler, Zustand
        self._lauf_sperre = threading.Lock()  # nie zwei Läufe gleichzeitig
        self._karten: list[Karte] = []
        self._stand = -1.0  # Sitzungszeit, bis zu der das Gespräch schon mitgedacht ist
        self._t_lauf: float | None = None  # Sitzungszeit beim Start des letzten Laufs
        self._laeufe = 0
        self._fehler = 0
        self._fehler_folge = 0
        self._pause_bis = 0.0
        self._meldung = ""
        self._denkt = False
        self._beendet = False
        self._verwerfen = False  # nach Abbruch: Spätresultate zählen nicht mehr
        self._thread: threading.Thread | None = None
        self._wecker = threading.Event()

    # --- Lebenszyklus -------------------------------------------------------------------

    @property
    def verfuegbar(self) -> bool:
        return self.ki is not None and getattr(self.ki, "backend", "") != BACKEND_OLLAMA

    def grund(self) -> str:
        """Warum der Mitdenker nicht läuft - leer, wenn er kann."""
        if self.ki is None:
            return tr("Mitdenken braucht einen KI-Dienst.")
        if not self.verfuegbar:
            return tr("Mitdenken läuft vorerst nicht mit der lokalen KI.")
        return ""

    def starte(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._arbeite, name="souffleur-mitdenker", daemon=True)
            self._thread.start()

    def uebernehme(self, session_dir: Path) -> list[Karte]:
        """Wiederaufnahme: Karten der unterbrochenen Sitzung übernehmen (der Aufrufer meldet sie)."""
        karten, bilanz = lade(session_dir)
        if karten or bilanz:
            with self._lock:
                self._karten = karten
                self._laeufe = int(bilanz.get("laeufe") or 0)
                self._fehler = int(bilanz.get("fehler") or 0)
                self._stand = float(bilanz.get("stand_t") or max((k.t_end for k in karten), default=-1.0))
        return karten

    def setze_aktiv(self, aktiv: bool) -> None:
        with self._lock:
            self._aktiv = bool(aktiv)
            if aktiv:
                self._t_lauf = None  # der Takt zählt ab dem Einschalten neu
        self._wecker.set()

    def abschliessen(self) -> None:
        """Kein Schlusslauf (das Sitzungsende wartet sonst darauf). Ein laufender Lauf bekommt kurz
        Zeit; danach wird sein Ergebnis verworfen. Dann der letzte Stand auf die Platte."""
        self._beende(_ABSCHLUSS_WARTEN_S)
        self._schreibe()

    def stop(self) -> None:
        """Harter Abbruch (Reset): nichts mehr nach außen, nicht lange warten."""
        self._verwerfen = True
        self._beende(1.0)

    def _beende(self, warten_s: float) -> None:
        with self._lock:
            self._beendet = True
        self._wecker.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=warten_s)
        self._verwerfen = True

    # --- Takt ---------------------------------------------------------------------------

    def _arbeite(self) -> None:
        while True:
            self._wecker.wait(_TICK_S)
            self._wecker.clear()
            with self._lock:
                if self._beendet:
                    return
                bereit = self._aktiv and self.verfuegbar and time.monotonic() >= self._pause_bis
            if not bereit:
                continue
            try:
                snap = self._quelle._mitdenk_schnappschuss(self.konfig.mitdenken_fenster_s)
                if self._faellig(snap) is not None:
                    self._laufe(snap)
            except Exception as exc:  # noqa: BLE001 - ein Lauf darf die Spur nicht beenden
                self._quelle._log(tr("Mitdenker: Lauf übersprungen: {fehler}", fehler=exc))
                self._quelle._diagnose({"spur": "mitdenker", "fehler": str(exc)})

    def _faellig(self, snap: dict) -> str | None:
        """Ob jetzt ein Lauf ansteht: nach dem Takt mit genug neuem Inhalt, oder früher, wenn das
        Gespräch gerade ruht. ``None`` heißt warten."""
        if not snap["aktiv"] or snap["beendet"] or snap["wiki_laedt"]:
            return None
        with self._lock:
            stand, t_lauf = self._stand, self._t_lauf
        _, neu, _ = teile_transkript(snap["segmente"], stand)
        if not neu:
            return None
        jetzt = float(snap["jetzt"])
        woerter = sum(_woerter(str(s["text"])) for s in neu)
        seit = jetzt - (t_lauf if t_lauf is not None else float(neu[0]["start"]))
        if seit >= self.konfig.mitdenken_takt_s and woerter >= self.konfig.mitdenken_min_woerter:
            return "takt"
        stille = jetzt - float(neu[-1]["end"])
        if (
            stille >= _LEERLAUF_S
            and seit >= min(_LEERLAUF_TAKT_S, self.konfig.mitdenken_takt_s)
            and woerter >= min(_LEERLAUF_WOERTER, self.konfig.mitdenken_min_woerter)
        ):
            return "leerlauf"
        return None

    # --- Ein Lauf -----------------------------------------------------------------------

    def laufe_jetzt(self) -> list[Karte]:
        """Ein Lauf sofort, ohne Takt - synchron. Läuft schon einer, passiert nichts."""
        if not self.verfuegbar:
            return []
        return self._laufe(self._quelle._mitdenk_schnappschuss(self.konfig.mitdenken_fenster_s))

    def _laufe(self, snap: dict) -> list[Karte]:
        if not self._lauf_sperre.acquire(blocking=False):
            return []
        try:
            with self._lock:
                self._denkt = True
            return self._ein_lauf(snap)
        finally:
            with self._lock:
                self._denkt = False
            self._lauf_sperre.release()

    def _ein_lauf(self, snap: dict) -> list[Karte]:
        assert self.ki is not None  # noqa: S101 - Typ-Verengung fuer Optional
        jetzt = float(snap["jetzt"])
        with self._lock:
            stand = self._stand
        kontext, neu, gekappt = teile_transkript(snap["segmente"], stand)
        if not neu:
            return []
        with self._lock:
            alte = list(self._karten)
            self._t_lauf = jetzt
            self._laeufe += 1
            lauf = self._laeufe
        diag: dict = {
            "spur": "mitdenker",
            "lauf": lauf,
            "t_von": float(neu[0]["start"]),
            "t_bis": float(neu[-1]["end"]),
            "segmente_neu": len(neu),
            "segmente_kontext": len(kontext),
            **({"gekappt": gekappt} if gekappt else {}),
        }

        wiki: wiki_modul.WikiIndex | None = snap["wiki"]
        markierungen: list[dict] = snap["markierungen"]
        fundstellen: list[mk.Fundstelle] = []
        glossar: list[tuple[str, str]] = []
        if wiki is not None:
            text = " ".join(str(s["text"]) for s in neu)
            fundstellen = wiki.suche(" ".join([text, *snap["suchbegriffe"]]), top_k=TOP_K)
            # Worauf der Souffleur im Fenster schon gezeigt hat, gehört dazu - sonst kann die KI
            # einen Gedanken nicht an denselben Beleg hängen.
            vorhanden = {(f.datei, f.zeile) for f in fundstellen}
            for m in markierungen:
                for f in m.get("fundstellen") or []:
                    schluessel = (str(f.get("datei")), int(f.get("zeile") or 0))
                    if schluessel not in vorhanden and (obj := wiki.abschnitt(*schluessel)) is not None:
                        fundstellen.append(obj)
                        vorhanden.add(schluessel)
            glossar = wiki.glossar.eintraege
        fmit = prompt_modul.fundstellen_mit_ids(fundstellen)
        auftrag = KiAuftrag(
            system=system_prompt(),
            prompt=baue_prompt(
                neu,
                kontext=kontext,
                fundstellen=fmit,
                glossar=glossar,
                wiki_verknuepft=wiki is not None,
                karten=alte,
                markierungen=markierungen,
                leitfaden=snap["leitfaden"],
            ),
            schema=SCHEMA,
            kontext={"art": EREIGNIS, "segmente": neu, "kontext": kontext, "fundstellen": fmit, "glossar": glossar},
            timeout_s=self.konfig.mitdenken_timeout_s,
            denken=True,
            aufwand="medium",
        )
        try:
            antwort = self.ki.antworte(auftrag)
        except KiFehler as exc:
            with self._lock:
                self._fehler += 1
                self._fehler_folge += 1
                self._meldung = str(exc)
                if self._fehler_folge >= _FEHLER_FOLGE_MAX:
                    self._pause_bis = time.monotonic() + _FEHLER_PAUSE_S
                    self._meldung = tr(
                        "KI-Fehler ({anzahl} in Folge), Pause {pause} s: {fehler}",
                        anzahl=self._fehler_folge,
                        pause=f"{_FEHLER_PAUSE_S:.0f}",
                        fehler=exc,
                    )
                meldung = self._meldung
            self._quelle._log(f"Mitdenker: {meldung}")
            self._quelle._diagnose({**diag, "fehler": str(exc)})
            return []
        if self._verwerfen:
            return []  # Sitzung ist inzwischen zu Ende oder zurückgesetzt

        je_id = {int(s["id"]): s for s in [*kontext, *neu]}
        fund_je_id = {f["id"]: (f, fundstellen[i]) for i, f in enumerate(fmit)}
        t_hinweis = self._quelle.uhr.jetzt()
        neue: list[Karte] = []
        verworfen: list[dict] = []
        rohe = antwort.daten.get("karten")
        for roh in (rohe if isinstance(rohe, list) else [])[:KARTEN_JE_LAUF]:
            karte, grund = pruefe_mit_grund(roh, je_id, fund_je_id, sensibel=self.konfig.sensibel)
            if karte is None:
                # Mit Titel: so lässt sich nach echten Sitzungen beurteilen, was der Filter wegnimmt.
                verworfen.append(
                    {
                        "art": roh.get("art") if isinstance(roh, dict) else None,
                        "grund": grund,
                        **({"titel": str(roh.get("titel") or "")[:TITEL_MAX]} if isinstance(roh, dict) else {}),
                    }
                )
                continue
            if ist_dublette(karte, [*alte, *neue], markierungen):
                verworfen.append({"art": karte.art, "grund": "dublette"})
                continue
            karte.lauf = lauf
            karte.ki_antwort_s = round(antwort.antwort_s, 2)
            karte.t_hinweis = round(t_hinweis, 2) if t_hinweis is not None else None
            neue.append(karte)
        with self._lock:
            for karte in neue:
                karte.id = f"M{len(self._karten) + 1}"
                self._karten.append(karte)
            self._stand = float(neu[-1]["end"])
            self._fehler_folge = 0
            self._meldung = ""
        for karte in neue:
            self._quelle._log(
                tr(
                    "Mitdenker: {art} bei {t} s (KI {ki} s)",
                    art=art_label(karte.art),
                    t=f"{karte.t_start:.0f}",
                    ki=f"{antwort.antwort_s:.1f}",
                )
            )
            try:
                # Frisch lesen: der Runner hängt on_hinweis erst nach dem Bau ein, stop() ersetzt es.
                self._quelle.on_hinweis({**karte.als_dict(), "type": EREIGNIS})
            except Exception as exc:  # noqa: BLE001
                self._quelle._log(tr("Mitdenker: Karte nicht zugestellt: {fehler}", fehler=exc))
        self._quelle._diagnose(
            {
                **diag,
                "treffer": len(fundstellen),
                "ki_start_s": round(antwort.start_s, 3),
                "ki_antwort_s": round(antwort.antwort_s, 3),
                "karten": [k.id for k in neue],
                "verworfen": verworfen,
                **({"verbrauch": antwort.verbrauch.als_dict()} if antwort.verbrauch is not None else {}),
            }
        )
        if neue:
            self._schreibe()
        return neue

    # --- Ergebnisse ---------------------------------------------------------------------

    def karten(self) -> list[Karte]:
        with self._lock:
            return list(self._karten)

    def _schreibe(self) -> None:
        ziel = self._quelle.session_dir
        with self._lock:
            karten = list(self._karten)
            bilanz = {
                "karten": len(karten),
                "laeufe": self._laeufe,
                "fehler": self._fehler,
                "stand_t": self._stand,
                "je_art": {art: sum(1 for k in karten if k.art == art) for art in ARTEN},
            }
        if ziel is None or not (karten or bilanz["laeufe"]):
            return
        try:
            schreibe(ziel, karten, bilanz=bilanz, modell=getattr(self.ki, "modell", "") if self.ki else "")
        except OSError as exc:
            self._quelle._log(tr("Souffleur: Begleitdatei nicht schreibbar: {fehler}", fehler=exc))

    def status(self) -> dict:
        with self._lock:
            if not self.verfuegbar:
                zustand = "nicht_verfuegbar"
            elif not self._aktiv:
                zustand = "aus"
            elif self._denkt:
                zustand = "denkt"
            elif time.monotonic() < self._pause_bis:
                zustand = "pause"
            else:
                zustand = "wartet"
            return {
                "aktiv": self._aktiv,
                "verfuegbar": self.verfuegbar,
                "grund": self.grund(),
                "zustand": zustand,
                "meldung": self._meldung,
                "karten": len(self._karten),
                "laeufe": self._laeufe,
                "fehler": self._fehler,
            }
