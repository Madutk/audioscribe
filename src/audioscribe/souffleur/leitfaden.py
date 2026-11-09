"""Leitfaden: die Meeting-Vorbereitung als Checkliste für den Souffleur.

Eine Vorbereitung ist eine Markdown-Datei des Menschen - üblich unter
``<wiki>/raw/vorbereitung/JJJJ-MM-TT_<thema>.md``. Sie ist **kein Wissen**: Sie belegt nichts,
wird nie in den Wiki-Index aufgenommen (``raw/`` liest der Souffleur nicht) und eine Abweichung
von ihr ist kein Widerspruch. Sie sagt dem Souffleur nur, was in diesem Meeting geklärt werden soll.

Format (tolerant gelesen)::

    ---
    titel: Abstimmung Freigabeprozess
    art: abstimmung
    ---
    # Ziel
    Ein bis drei Sätze.

    ## Muss geklärt werden
    - [ ] Wer gibt Änderungen frei? (Wiki: ENT-003)
      - eingerückt: Notiz zum Punkt
    ## Sollte angesprochen werden
    - [ ] Weiterer Punkt
    ## Hintergrund
    Freier Text.

Jedes ``- [ ]`` ist ein Punkt (P1, P2, … in Dateireihenfolge). Unter einer Überschrift mit
„Muss“/„Must“/„Pflicht“ ist er Pflicht, sonst „sollte“. ``- [x]`` gilt von Anfang an als geklärt.

Status je Punkt: ``offen`` → ``angesprochen`` → ``geklaert``; ``vertagt`` setzt nur der Mensch.
Die KI hebt den Status nur an (nie zurück), und nur mit wörtlichem Beleg aus dem Fenster
(geprüft in ``kern``). Was der Mensch setzt, gilt.

Wiki-Bezug je Punkt (``verknuepfe_wiki``): sobald das Wiki geladen ist, bekommt jeder Punkt bis zu
zwei Fundstellen - zuerst über Kennungen wie ``ENT-003`` (exakt), sonst über die Suche mit Text und
Notiz, nur bei deutlicher Überdeckung. So sieht der Moderator, was das Wiki zum Punkt schon festhält.

Ergebnis im Sitzungsordner: ``souffleur-leitfaden.json`` (Stand, auch für die Wiederaufnahme)
und ``souffleur-leitfaden.md`` (lesbar, mit ``[x]``/``[ ]``).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from audioscribe.i18n import tr
from audioscribe.models import format_timecode
from audioscribe.souffleur import wiki as wiki_modul

STAND_DATEI = "souffleur-leitfaden.json"
MD_DATEI = "souffleur-leitfaden.md"
VERSION = 1
VORBEREITUNG_ORDNER = "vorbereitung"  # unter <wiki>/raw/

OFFEN = "offen"
ANGESPROCHEN = "angesprochen"
GEKLAERT = "geklaert"
VERTAGT = "vertagt"
STATUS: tuple[str, ...] = (OFFEN, ANGESPROCHEN, GEKLAERT, VERTAGT)
KI_STATUS: tuple[str, ...] = (ANGESPROCHEN, GEKLAERT)  # mehr darf die KI nicht melden
_RANG = {OFFEN: 0, ANGESPROCHEN: 1, GEKLAERT: 2}

MUSS = "muss"
SOLLTE = "sollte"
ERGAENZT = "Im Meeting ergänzt"  # Abschnitt für Punkte, die der Moderator aus Hinweisen übernimmt

MAX_PUNKTE = 40
MAX_DATEI_BYTES = 256 * 1024
TEXT_MAX = 300
NOTIZ_MAX = 600
STAND_MAX = 200
PROMPT_MAX = 1500  # Zeichen für den Leitfaden im Prompt (Ollama: num_ctx 8192)
WIKI_JE_PUNKT = 2
WIKI_AUSZUG_MAX = 280
WIKI_UEBERDECKUNG = 0.5  # Suche ohne Kennung: Anteil der Suchwörter, die im Abschnitt stehen müssen
WIKI_KENNUNG = "kennung"
WIKI_SUCHE = "suche"

_CHECKBOX = re.compile(r"^(?P<einzug>[ \t]*)[-*+]\s+\[(?P<haken>[ xX])\]\s+(?P<text>.+?)\s*$")
_LISTE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])\s+")
_UEBERSCHRIFT = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_WIKI_ID = re.compile(r"\b[A-Z]{1,5}-\d{1,4}\b")
_MUSS = re.compile(r"\b(muss|müssen|pflicht|must|required|kritisch|critical)\b", re.I)
_ZIEL = re.compile(r"^(ziel|ziele|goal|goals|zweck|purpose)\b", re.I)
_HINTERGRUND = re.compile(r"^(hintergrund|kontext|background|context)\b", re.I)


class LeitfadenFehler(ValueError):
    """Die Datei ist kein brauchbarer Leitfaden (nicht lesbar, zu groß, ohne Punkte)."""


@dataclass
class Punkt:
    id: str
    text: str
    prioritaet: str = SOLLTE
    abschnitt: str = ""
    notiz: str = ""
    begriffe: list[str] = field(default_factory=list)  # Wiki-Kennungen, z. B. ENT-003
    status: str = OFFEN
    gesetzt_von: str | None = None  # None (Datei) | "ki" | "nutzer"
    stand: str = ""  # KI: was noch offen ist bzw. das Ergebnis in Kurzform
    segment_id: int | None = None  # Segment, das den Status zuletzt begründet hat
    aussage: str = ""  # wörtlich aus diesem Segment (bzw. aus dem Bildtext, siehe ``bild``)
    bild: dict | None = None  # Beleg vom Bildschirm statt Segment: {id, t, datei}
    t_angesprochen: float | None = None
    t_zuletzt: float | None = None  # letzte Erwähnung (Sitzungsuhr)
    t_geklaert: float | None = None
    angestossen: bool = False  # Hinweis "anknüpfen" schon gegeben
    # Was das Wiki zum Punkt festhält: [{datei, ueberschrift, zeile, auszug, art}], art = "kennung" | "suche"
    wiki: list[dict] = field(default_factory=list)
    # Ergebnis im Meeting weicht vom Wiki ab (KI-gemeldet, Zitat lokal geprüft): {datei, ueberschrift, zeile, zitat, t}
    abweichung: dict | None = None
    herkunft: str = ""  # "hinweis:<id>" - im Meeting aus einem Souffleur-Hinweis übernommen

    @property
    def erledigt(self) -> bool:
        return self.status in (GEKLAERT, VERTAGT)

    def als_dict(self) -> dict:
        return asdict(self)


@dataclass
class Leitfaden:
    punkte: list[Punkt]
    quelle: str = ""
    titel: str = ""
    art: str = ""
    datum: str = ""
    ziel: str = ""
    hintergrund: str = ""
    version: int = VERSION

    def punkt(self, punkt_id: str) -> Punkt | None:
        return next((p for p in self.punkte if p.id == punkt_id), None)

    def offene(self) -> list[Punkt]:
        """Noch nicht erledigte Punkte - Pflicht zuerst, sonst in Dateireihenfolge."""
        return sorted((p for p in self.punkte if not p.erledigt), key=lambda p: p.prioritaet != MUSS)

    # --- Status ---------------------------------------------------------------------

    def melde_ki(self, punkt_id: str, status: str, *, segment_id: int | None, aussage: str, stand: str, t: float,
                 bild: dict | None = None, abweichung: dict | None = None) -> bool:
        """Befund der KI übernehmen - nur anheben, nie zurück, nichts an Vertagtem. ``True``,
        wenn sich etwas geändert hat (auch eine erneute Erwähnung zählt)."""
        p = self.punkt(punkt_id)
        if p is None or status not in KI_STATUS or p.status == VERTAGT:
            return False
        if p.status == GEKLAERT:
            return False
        if _RANG[status] < _RANG[p.status]:
            return False
        if p.angestossen and p.t_zuletzt is not None and t > p.t_zuletzt:
            p.angestossen = False  # wieder aufgegriffen: versandet es erneut, kommt ein neuer Anstoß
        p.t_zuletzt = t
        p.segment_id, p.aussage, p.bild = segment_id, aussage, bild
        if abweichung is not None:
            p.abweichung = {**abweichung, "t": t}
        if stand.strip():
            p.stand = stand.strip()[:STAND_MAX]
        if p.t_angesprochen is None:
            p.t_angesprochen = t
        if status == GEKLAERT:
            p.t_geklaert = t
        p.status, p.gesetzt_von = status, "ki"
        return True

    def ergaenze(self, text: str, *, herkunft: str, segment_id: int | None, aussage: str, t: float,
                 notiz: str = "") -> Punkt:
        """Ein im Meeting aufgekommener offener Punkt wird Teil des Leitfadens: angesprochen, nicht
        geklärt - er wird ab jetzt verfolgt und landet sonst in „Für das Folgemeeting“. Je Herkunft
        nur einmal."""
        vorhanden = next((p for p in self.punkte if herkunft and p.herkunft == herkunft), None)
        if vorhanden is not None:
            return vorhanden
        nummern = [int(p.id[1:]) for p in self.punkte if p.id[1:].isdigit()]
        p = Punkt(id=f"P{max(nummern, default=0) + 1}", text=text.strip()[:TEXT_MAX], abschnitt=ERGAENZT,
                  notiz=notiz[:NOTIZ_MAX], begriffe=list(dict.fromkeys(_WIKI_ID.findall(text))), status=ANGESPROCHEN,
                  gesetzt_von="nutzer", segment_id=segment_id, aussage=aussage, t_angesprochen=t, t_zuletzt=t,
                  angestossen=True, herkunft=herkunft)
        self.punkte.append(p)
        return p

    def setze(self, punkt_id: str, status: str) -> Punkt:
        """Der Mensch setzt den Status - jeder Wert ist erlaubt, auch zurück auf offen."""
        p = self.punkt(punkt_id)
        if p is None:
            raise KeyError(punkt_id)
        if status not in STATUS:
            raise ValueError(status)
        p.status, p.gesetzt_von = status, "nutzer"
        if status == OFFEN:
            p.angestossen = False
            p.t_angesprochen = p.t_zuletzt = p.t_geklaert = None
        return p

    def faellige_anstoesse(self, jetzt: float, nach_s: float) -> list[Punkt]:
        """Punkte, die angesprochen, aber seit ``nach_s`` nicht mehr erwähnt und nicht geklärt
        wurden - einmal je Versanden (eine neue Erwähnung macht den Punkt wieder anstoßbar).
        Markiert sie als angestoßen."""
        faellig = []
        for p in self.punkte:
            if p.status != ANGESPROCHEN or p.angestossen or p.t_zuletzt is None:
                continue
            if jetzt - p.t_zuletzt >= nach_s:
                p.angestossen = True
                faellig.append(p)
        return faellig

    def wiki_im_gespraech(self, text: str, *, max_punkte: int = 3) -> dict[str, list[dict]]:
        """Wiki-Bezüge der Punkte, um die es im Fenster gehen dürfte: angesprochene, und offene,
        deren Text mindestens zwei Inhaltswörter mit dem Fenster teilt. Damit kann die KI ein
        Ergebnis gegen das Wiki halten."""
        fenster = set(wiki_modul.tokenisiere(text))
        out: dict[str, list[dict]] = {}
        for p in self.offene():
            if not p.wiki:
                continue
            if p.status == ANGESPROCHEN or len(fenster & set(wiki_modul.tokenisiere(f"{p.text} {' '.join(p.begriffe)}"))) >= 2:
                out[p.id] = p.wiki
            if len(out) >= max_punkte:
                break
        return out

    def im_fenster(self, text: str) -> set[str]:
        """Offene Punkte, deren Text oder Kennungen mit dem Fenster ein Inhaltswort teilen."""
        fenster = {t for t in wiki_modul.tokenisiere(text) if len(t) >= 4}
        return {p.id for p in self.punkte if not p.erledigt
                and fenster & set(wiki_modul.tokenisiere(f"{p.text} {p.notiz} {' '.join(p.begriffe)}"))}

    def suchbegriffe(self) -> list[str]:
        """Wiki-Kennungen der gerade angesprochenen Punkte - schärfen die Wiki-Suche."""
        out: list[str] = []
        for p in self.punkte:
            if p.status == ANGESPROCHEN:
                out += [b for b in p.begriffe if b not in out]
        return out[:8]

    def bilanz(self) -> dict:
        z = {s: sum(1 for p in self.punkte if p.status == s) for s in STATUS}
        muss_offen = sum(1 for p in self.punkte if p.prioritaet == MUSS and not p.erledigt)
        return {"punkte": len(self.punkte), **z, "muss_offen": muss_offen}

    def als_dict(self) -> dict:
        return {
            "version": self.version, "quelle": self.quelle, "titel": self.titel, "art": self.art,
            "datum": self.datum, "ziel": self.ziel, "hintergrund": self.hintergrund,
            "punkte": [p.als_dict() for p in self.punkte], "bilanz": self.bilanz(),
        }


# --- Wiki-Bezug ---------------------------------------------------------------------------


def _wiki_eintrag(f, art: str) -> dict:
    return {"datei": f.datei, "ueberschrift": f.ueberschrift, "zeile": f.zeile,
            "auszug": f.auszug[:WIKI_AUSZUG_MAX], "art": art}


def wiki_zu_punkt(p: Punkt, index: wiki_modul.WikiIndex) -> list[dict]:
    """Bis zu ``WIKI_JE_PUNKT`` Fundstellen: Kennungen exakt, danach die Suche über Text und Notiz -
    die nur, wenn der Abschnitt mindestens die Hälfte der Suchwörter enthält (sonst Rauschen)."""
    out: list[dict] = []
    gesehen: set[tuple[str, int]] = set()
    for kennung in p.begriffe:
        for f in index.finde_kennung(kennung, top_k=WIKI_JE_PUNKT):
            if (f.datei, f.zeile) not in gesehen and len(out) < WIKI_JE_PUNKT:
                gesehen.add((f.datei, f.zeile))
                out.append(_wiki_eintrag(f, WIKI_KENNUNG))
    if out:
        return out
    anfrage = f"{p.text} {p.notiz}"
    woerter = {t for t in wiki_modul.tokenisiere(index.glossar.korrigiere(anfrage)) if not t.isdigit()}
    if len(woerter) < 2:
        return []
    for f in index.suche(anfrage, top_k=3, je_datei=1):
        treffer = woerter & set(wiki_modul.tokenisiere(f"{f.ueberschrift} {f.auszug}"))
        if len(treffer) / len(woerter) >= WIKI_UEBERDECKUNG and (f.datei, f.zeile) not in gesehen:
            gesehen.add((f.datei, f.zeile))
            out.append(_wiki_eintrag(f, WIKI_SUCHE))
            if len(out) >= WIKI_JE_PUNKT:
                break
    return out


def verknuepfe_wiki(lf: Leitfaden, index: wiki_modul.WikiIndex | None) -> int:
    """Jedem Punkt seine Wiki-Fundstellen zuordnen (ohne Wiki: alle leeren). Anzahl Punkte mit Bezug."""
    for p in lf.punkte:
        p.wiki = wiki_zu_punkt(p, index) if index is not None else []
    return sum(1 for p in lf.punkte if p.wiki)


# --- Lesen ------------------------------------------------------------------------------


def _frontmatter(zeilen: list[str]) -> tuple[dict[str, str], list[str]]:
    if not zeilen or zeilen[0].strip() != "---":
        return {}, zeilen
    for i in range(1, min(len(zeilen), 60)):
        if zeilen[i].strip() in ("---", "..."):
            felder = {}
            for z in zeilen[1:i]:
                if ":" in z and not z.startswith((" ", "\t")):
                    k, v = z.split(":", 1)
                    felder[k.strip().lower()] = v.strip().strip("\"'")
            return felder, zeilen[i + 1 :]
    return {}, zeilen


def _einzug(text: str) -> int:
    return len(text.expandtabs(4)) - len(text.expandtabs(4).lstrip())


def parse(text: str, *, quelle: str = "") -> Leitfaden:
    """Markdown → Leitfaden. Wirft ``LeitfadenFehler``, wenn kein einziger Punkt darin steht."""
    felder, zeilen = _frontmatter(text.replace("\r\n", "\n").split("\n"))
    punkte: list[Punkt] = []
    abschnitt, prio = "", SOLLTE
    bereich = ""  # "ziel" | "hintergrund" | ""
    ziel: list[str] = []
    hintergrund: list[str] = []
    h1 = ""
    offen: Punkt | None = None
    offen_einzug = 0
    im_code = False
    for zeile in zeilen:
        if zeile.lstrip().startswith(("```", "~~~")):
            im_code = not im_code
            offen = None
            continue
        if im_code:
            continue
        m = _UEBERSCHRIFT.match(zeile)
        if m:
            offen = None
            titel = m.group(2).strip()
            if len(m.group(1)) == 1 and not h1 and not _ZIEL.match(titel) and not _HINTERGRUND.match(titel):
                h1 = titel
            abschnitt = titel
            prio = MUSS if _MUSS.search(titel) else SOLLTE
            bereich = "ziel" if _ZIEL.match(titel) else ("hintergrund" if _HINTERGRUND.match(titel) else "")
            continue
        m = _CHECKBOX.match(zeile)
        if m and (offen is None or _einzug(m.group("einzug")) <= offen_einzug) and bereich != "hintergrund":
            if len(punkte) >= MAX_PUNKTE:
                offen = None
                continue
            text_p = m.group("text").strip()[:TEXT_MAX]
            offen = Punkt(id=f"P{len(punkte) + 1}", text=text_p, prioritaet=prio, abschnitt=abschnitt,
                          begriffe=list(dict.fromkeys(_WIKI_ID.findall(text_p))))
            if m.group("haken") in "xX":
                offen.status, offen.gesetzt_von = GEKLAERT, None
            offen_einzug = _einzug(m.group("einzug"))
            punkte.append(offen)
            continue
        if offen is not None:
            if not zeile.strip():
                continue
            if _einzug(zeile) > offen_einzug:
                notiz = _LISTE.sub("", zeile).strip()
                notiz = re.sub(r"^\[[ xX]\]\s*", "", notiz)
                offen.notiz = (f"{offen.notiz} · {notiz}" if offen.notiz else notiz)[:NOTIZ_MAX]
                offen.begriffe = list(dict.fromkeys(offen.begriffe + _WIKI_ID.findall(notiz)))
                continue
            offen = None
        if bereich == "ziel" and zeile.strip():
            ziel.append(zeile.strip())
        elif bereich == "hintergrund" and zeile.strip():
            hintergrund.append(zeile.strip())
    if not punkte:
        raise LeitfadenFehler(tr("Keine Punkte gefunden – jeder Punkt beginnt mit „- [ ]“."))
    return Leitfaden(
        punkte=punkte, quelle=quelle, titel=felder.get("titel") or felder.get("title") or h1,
        art=felder.get("art") or felder.get("type") or "", datum=felder.get("datum") or felder.get("date") or "",
        ziel=" ".join(ziel)[:NOTIZ_MAX], hintergrund="\n".join(hintergrund)[:4000],
    )


def lade_datei(pfad: Path) -> Leitfaden:
    pfad = Path(pfad)
    if pfad.suffix.lower() not in (".md", ".markdown", ".txt"):
        raise LeitfadenFehler(tr("Der Leitfaden muss eine Markdown-Datei sein (.md)."))
    try:
        if pfad.stat().st_size > MAX_DATEI_BYTES:
            raise LeitfadenFehler(tr("Die Datei ist zu groß für einen Leitfaden."))
        text = pfad.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LeitfadenFehler(tr("Die Datei ist kein UTF-8-Text.")) from exc
    except OSError as exc:
        raise LeitfadenFehler(tr("Datei nicht lesbar: {fehler}", fehler=exc)) from exc
    return parse(text, quelle=str(pfad))


def vorbereitungen(wiki_dir: Path | None) -> list[dict]:
    """Die Vorbereitungen unter ``<wiki>/raw/vorbereitung/`` - neueste zuerst (Name und mtime)."""
    if wiki_dir is None:
        return []
    ordner = Path(wiki_dir) / "raw" / VORBEREITUNG_ORDNER
    if not ordner.is_dir():
        return []
    out = []
    for p in ordner.glob("*.md"):
        if p.name.lower() == "readme.md" or p.name.startswith("."):
            continue
        try:
            out.append({"pfad": str(p), "name": p.name, "mtime": p.stat().st_mtime})
        except OSError:
            continue
    return sorted(out, key=lambda d: (d["name"], d["mtime"]), reverse=True)


# --- Prompt -----------------------------------------------------------------------------


def prompt_abschnitt(lf: Leitfaden, *, englisch: bool = False, wiki_ids: dict[str, list[str]] | None = None,
                     vorrang: set[str] | None = None) -> str:
    return prompt_abschnitt_mit_rest(lf, englisch=englisch, wiki_ids=wiki_ids, vorrang=vorrang)[0]


def prompt_abschnitt_mit_rest(lf: Leitfaden, *, englisch: bool = False, wiki_ids: dict[str, list[str]] | None = None,
                              vorrang: set[str] | None = None) -> tuple[str, int]:
    """Die nicht erledigten Punkte, kompakt und gedeckelt (``PROMPT_MAX``), dazu die Zahl der
    Punkte, die nicht mehr hineinpassten. Reihenfolge: angesprochene, dann die ``vorrang``-Punkte
    (worum es im Fenster gerade geht), dann Pflicht, dann der Rest - je in Dateireihenfolge. So
    fällt bei einer langen Vorbereitung nie ausgerechnet der Punkt weg, der gerade besprochen wird.
    ``wiki_ids``: je Punkt die IDs (F1, ...) seiner Wiki-Auszüge im Prompt."""
    w = {
        MUSS: "must" if englisch else "muss", SOLLTE: "should" if englisch else "sollte",
        OFFEN: "open" if englisch else "offen", ANGESPROCHEN: "raised" if englisch else "angesprochen",
        "notiz": "Note" if englisch else "Notiz", "stand": "Still open" if englisch else "Noch offen",
    }
    vorrang = vorrang or set()
    zeilen: list[str] = []
    laenge = 0
    if lf.ziel:
        z = f"{'Goal' if englisch else 'Ziel'}: {lf.ziel[:200]}"
        zeilen.append(z)
        laenge += len(z)
    offen = [p for p in lf.punkte if not p.erledigt]
    reihenfolge = sorted(range(len(offen)), key=lambda i: (
        0 if offen[i].status == ANGESPROCHEN else 1 if offen[i].id in vorrang else 2,
        offen[i].prioritaet != MUSS, i))
    ausgelassen = 0
    for i in reihenfolge:
        p = offen[i]
        z = f"[{p.id}] ({w[p.prioritaet]}, {w[p.status]}) {p.text[:200]}"
        if p.notiz:
            z += f" — {w['notiz']}: {p.notiz[:120]}"
        if p.status == ANGESPROCHEN and p.stand:
            z += f" — {w['stand']}: {p.stand[:120]}"
        if wiki_ids and wiki_ids.get(p.id):
            z += f" — Wiki: {', '.join(wiki_ids[p.id])}"
        if laenge + len(z) > PROMPT_MAX and zeilen:
            ausgelassen += 1
            continue
        zeilen.append(z)
        laenge += len(z) + 1
    return "\n".join(zeilen), ausgelassen


# --- Ablage im Sitzungsordner ---------------------------------------------------------------


def _atomar(pfad: Path, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, pfad)


def schreibe(session_dir: Path, lf: Leitfaden) -> None:
    session_dir = Path(session_dir)
    _atomar(session_dir / STAND_DATEI, json.dumps(lf.als_dict(), ensure_ascii=False, indent=2) + "\n")
    _atomar(session_dir / MD_DATEI, render_md(lf))


def lade_stand(session_dir: Path) -> Leitfaden | None:
    try:
        data = json.loads((Path(session_dir) / STAND_DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("punkte"), list):
        return None
    punkte = []
    for roh in data["punkte"]:
        if isinstance(roh, dict) and roh.get("id") and roh.get("text"):
            punkte.append(Punkt(**{k: v for k, v in roh.items() if k in Punkt.__dataclass_fields__}))
    if not punkte:
        return None
    felder = {k: str(data.get(k) or "") for k in ("quelle", "titel", "art", "datum", "ziel", "hintergrund")}
    return Leitfaden(punkte=punkte, **felder)


_HAKEN = {OFFEN: "[ ]", ANGESPROCHEN: "[~]", GEKLAERT: "[x]", VERTAGT: "[-]"}
_WORT = {OFFEN: "offen", ANGESPROCHEN: "angesprochen, nicht geklärt", GEKLAERT: "geklärt", VERTAGT: "vertagt"}


def _zeit(t: float | None) -> str:
    return f" ({format_timecode(t)})" if t is not None else ""


def render_md(lf: Leitfaden) -> str:
    """Ergebnis des Leitfadens, lesbar - auch als Begleitdatei fürs Wiki (``<stamm>.leitfaden.md``).
    Status und „Stand“ sind KI-eingeschätzt, sofern nicht vom Moderator gesetzt; die Belege
    sind wörtliche Transkriptstellen."""
    b = lf.bilanz()
    zeilen = [
        f"# Leitfaden: {lf.titel or Path(lf.quelle).stem or 'Meeting'}",
        "",
        f"Vorbereitung: `{lf.quelle}`" if lf.quelle else "Vorbereitung: –",
        "",
        "Status je Punkt aus dem Meeting. „KI“ = vom Souffleur eingeschätzt, „Moderator“ = von Hand gesetzt.",
        ("Belege sind wörtliche Stellen aus dem Transkript oder - als solche gekennzeichnet - aus dem Text eines"
         " Standbilds. Dies ist ein Hinweis zum Nachgehen, kein Wissen."),
        "",
        f"Geklärt {b[GEKLAERT]} · angesprochen {b[ANGESPROCHEN]} · offen {b[OFFEN]} · vertagt {b[VERTAGT]}"
        f" · davon Pflicht noch offen {b['muss_offen']}",
        "",
    ]
    if lf.ziel:
        zeilen += [f"**Ziel:** {lf.ziel}", ""]
    abschnitt = None
    for p in lf.punkte:
        if p.abschnitt != abschnitt:
            abschnitt = p.abschnitt
            zeilen += [f"## {abschnitt or 'Punkte'}", ""]
        quelle = {"ki": "KI", "nutzer": "Moderator"}.get(p.gesetzt_von or "", "")
        kopf = f"- {_HAKEN[p.status]} **{p.id}** {p.text} — {_WORT[p.status]}"
        kopf += _zeit(p.t_geklaert if p.status == GEKLAERT else p.t_angesprochen)
        zeilen.append(kopf + (f" · {quelle}" if quelle else ""))
        if p.stand:
            zeilen.append(f"  - {'Ergebnis' if p.status == GEKLAERT else 'Noch offen'} (KI): {p.stand}")
        if p.aussage and p.bild:
            zeilen.append(f"  - Beleg vom Bildschirm{_zeit(p.t_zuletzt)}, `frames/{p.bild.get('datei')}`: „{p.aussage}“")
        elif p.aussage:
            zeilen.append(f"  - Beleg{_zeit(p.t_zuletzt)}: „{p.aussage}“")
        if p.notiz:
            zeilen.append(f"  - Vorbereitung: {p.notiz}")
        if p.abweichung:
            a = p.abweichung
            ort = f"{a['datei']} › {a['ueberschrift']}" if a.get("ueberschrift") else a["datei"]
            zeilen.append(f"  - **Weicht vom Wiki ab** (KI){_zeit(a.get('t'))}: `{ort}`: „{a.get('zitat')}“")
        for w in p.wiki:
            ort = f"{w['datei']} › {w['ueberschrift']}" if w.get("ueberschrift") else w["datei"]
            art = "" if w.get("art") == WIKI_KENNUNG else " (per Suche, ungeprüft)"
            zeilen.append(f"  - Im Wiki{art}: `{ort}` (Zeile {w.get('zeile')})")
    offen = [p for p in lf.punkte if not p.erledigt]
    zeilen += ["", f"## Für das Folgemeeting ({len(offen)})", ""]
    zeilen += [f"- [ ] {p.text}" + (f" — noch offen: {p.stand}" if p.stand else "") for p in offen] or ["- nichts offen"]
    return "\n".join(zeilen) + "\n"
