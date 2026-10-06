"""Nur-Lese-Zugriff auf das LLM-Wiki (K1, Entscheidung 1).

Annahme Karpathy-Muster: ein Ordner mit Markdown. Liegt ein Unterordner ``wiki/`` vor, sind
das die Seiten; sonst alle ``*.md`` unter der Wurzel. Nicht gelesen werden ``log.md``,
``raw/`` (unveränderliche Quellen), Punktordner und ``node_modules``. Der Name des Wikis ist
die H1 der ``index.md`` oder der Ordnername.

Jede Seite wird an ihren Überschriften in Abschnitte geteilt; ein Abschnitt ist eine
Fundstelle (Datei, Überschrift, Zeile, Auszug). Gesucht wird lexikalisch (BM25 über
Abschnitte, Überschriften doppelt gewichtet) - ohne neue Abhängigkeit, ohne Netz.

Das Glossar ist Teil des Wikis: eine Datei ``glossar.md`` oder eine Seite mit „Glossar“ in
der H1. Tabellen mit Kopf ``Fehlerkennung | Korrekt`` liefern bestätigte Fehlerkennungen der
Spracherkennung (Format des Skills transkript-normalisierung); übrige zweispaltige Tabellen
gelten als Fachbegriffe.

Dieses Modul öffnet Dateien ausschließlich zum Lesen.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from audioscribe.souffleur.markierung import Fundstelle

ZUSTAND_KEINS = "keins"
ZUSTAND_OK = "ok"
ZUSTAND_FEHLER = "fehler"

SEITEN_ORDNER = "wiki"
AUSGESCHLOSSEN_ORDNER = {"raw", "node_modules", "__pycache__"}
AUSGESCHLOSSEN_DATEIEN = {"log.md"}
MAX_DATEI_BYTES = 2 * 1024 * 1024
MAX_ABSCHNITTE = 20_000
AUSZUG_MAX = 700

_HEADING = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")
_TABELLE_TRENNER = re.compile(r"^\s*\|?\s*:?-{2,}")
_TOKEN = re.compile(r"[a-zäöüß0-9]+")
_TAUSENDER = re.compile(r"(?<=\d)[.  ](?=\d{3}\b)")

_STOPP = set(
    """
    aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes auch auf aus bei bin bis
    bist da damit dann das dass dasselbe dazu dein deine dem den denn der deren derselbe des dessen die dies diese dieselbe
    diesem diesen dieser dieses doch dort du durch ein eine einem einen einer eines einig einige einigem einigen einiger
    einiges einmal er es etwas euch euer eure für gegen gewesen hab habe haben hat hatte hatten hier hin hinter ich ihm ihn
    ihnen ihr ihre im in indem ins ist ja jede jedem jeden jeder jedes jene jenem jenen jener jenes jetzt kann kein keine
    keinem keinen keiner keines können könnte machen man manche manchem manchen mancher manches mein meine mich mir mit muss
    musste nach nicht nichts noch nun nur ob oder ohne sehr sein seine sich sie sind so solche solchem solchen solcher solches
    soll sollte sondern sonst um und uns unser unsere unter viel vom von vor während war waren warst was weg weil weiter welche
    welchem welchen welcher welches wenn werde werden wie wieder will wir wird wirst wo wollen wollte würde würden zu zum zur
    zwar zwischen eigentlich halt mal gut okay ok genau ne bei uns ab denen dafür darum dies gibt geht macht machen wer wann
    """.split()
)


def tokenisiere(text: str) -> list[str]:
    """Kleinbuchstaben, NFC, Tausenderpunkte entfernt, Stoppwörter raus, grobe Endungen gekappt."""
    text = unicodedata.normalize("NFC", text.lower())
    text = _TAUSENDER.sub("", text)
    out = []
    for tok in _TOKEN.findall(text):
        if len(tok) < 2 or tok in _STOPP:
            continue
        out.append(_stamm(tok))
    return out


def _stamm(tok: str) -> str:
    if tok.isdigit() or len(tok) < 6:
        return tok
    for endung in ("ungen", "ung", "en", "er", "es", "em", "et", "st", "e", "t", "n", "s"):
        if tok.endswith(endung) and len(tok) - len(endung) >= 4:
            return tok[: -len(endung)]
    return tok


# --- Status --------------------------------------------------------------------------------


@dataclass(frozen=True)
class WikiStatus:
    zustand: str  # keins | ok | fehler
    pfad: str = ""
    name: str = ""
    seiten: int = 0
    abschnitte: int = 0
    glossar_eintraege: int = 0
    glossar_datei: str = ""
    stand: str = ""  # jüngste Änderung einer Seite
    gelesen: str = ""  # wann der Index geladen wurde
    meldung: str = ""
    warnungen: tuple[str, ...] = ()

    def als_dict(self) -> dict:
        d = asdict(self)
        d["warnungen"] = list(self.warnungen)
        return d


def status_keins() -> WikiStatus:
    return WikiStatus(ZUSTAND_KEINS, meldung="Kein Wiki verknüpft. Der Souffleur erkennt nur Fragen und liefert Essenzen.")


# --- Glossar -------------------------------------------------------------------------------


@dataclass
class Glossar:
    datei: str = ""
    eintraege: list[tuple[str, str]] = field(default_factory=list)  # (Fehlerkennung, Korrekt)
    fachbegriffe: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._muster = [
            (re.compile(r"(?<!\w)" + re.escape(falsch) + r"(?!\w)", re.IGNORECASE), richtig)
            for falsch, richtig in self.eintraege
            if falsch.strip()
        ]

    def korrigiere(self, text: str) -> str:
        """Bestätigte Fehlerkennungen ersetzen - nur für die Suche, nie im Transkript."""
        for muster, richtig in self._muster:
            text = muster.sub(richtig, text)
        return text


def _tabellen(text: str) -> list[list[list[str]]]:
    """Alle Markdown-Tabellen als Zeilen von Zellen (Kopf zuerst)."""
    tabellen: list[list[list[str]]] = []
    aktuell: list[list[str]] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            if _TABELLE_TRENNER.match(line.strip().strip("|").strip() + "--"):
                if set(line.replace("|", "").replace(":", "").strip()) <= {"-", " "}:
                    continue
            zellen = [z.strip() for z in line.strip().strip("|").split("|")]
            aktuell.append(zellen)
        elif aktuell:
            tabellen.append(aktuell)
            aktuell = []
    if aktuell:
        tabellen.append(aktuell)
    return tabellen


def parse_glossar(text: str, datei: str = "") -> Glossar:
    glossar = Glossar(datei=datei)
    for tabelle in _tabellen(text):
        if not tabelle or len(tabelle[0]) < 2:
            continue
        kopf = [z.lower() for z in tabelle[0]]
        zeilen = [z for z in tabelle[1:] if len(z) >= 2 and z[0] and z[1]]
        if "fehlerkennung" in kopf[0] and any(k in kopf[1] for k in ("korrekt", "richtig")):
            glossar.eintraege += [(z[0], z[1]) for z in zeilen]
        else:
            glossar.fachbegriffe += [(z[0], z[1]) for z in zeilen]
    for m in re.finditer(r"^\s*[-*]\s+(.+?)\s*(?:→|->)\s*(.+?)\s*$", text, re.MULTILINE):
        glossar.eintraege.append((m.group(1).strip("`* "), m.group(2).strip("`* ")))
    glossar.__post_init__()
    return glossar


def ist_glossar(datei: Path, text: str) -> bool:
    if datei.stem.lower() in ("glossar", "glossary"):
        return True
    for line in text.splitlines():
        m = _HEADING.match(line.strip())
        if m and len(m.group(1)) == 1:
            return "glossar" in m.group(2).lower()
    return False


# --- Index ---------------------------------------------------------------------------------


@dataclass
class Abschnitt:
    datei: str
    ueberschrift: str
    zeile: int
    text: str = ""
    tokens: Counter = field(default_factory=Counter)
    laenge: int = 0


def seiten_dateien(pfad: Path) -> list[Path]:
    wurzel = pfad / SEITEN_ORDNER if (pfad / SEITEN_ORDNER).is_dir() else pfad
    dateien = []
    for p in sorted(wurzel.rglob("*.md")):
        rel = p.relative_to(pfad)
        teile = rel.parts[:-1]
        if any(t.startswith(".") or t in AUSGESCHLOSSEN_ORDNER for t in teile):
            continue
        if p.name.startswith(".") or (len(rel.parts) == 1 and p.name in AUSGESCHLOSSEN_DATEIEN):
            continue
        dateien.append(p)
    return dateien


def abschnitte_aus(text: str, datei: str) -> list[Abschnitt]:
    """Seite an Überschriften (H1–H3) teilen; Text vor der ersten Unterüberschrift gehört zur H1."""
    out: list[Abschnitt] = []
    titel = ""
    aktuell: Abschnitt | None = None
    puffer: list[str] = []

    def abschliessen() -> None:
        nonlocal aktuell, puffer
        if aktuell is not None:
            inhalt = re.sub(r"\s+", " ", " ".join(p.strip() for p in puffer if p.strip())).strip()
            if inhalt or aktuell.ueberschrift:
                aktuell.text = inhalt
                out.append(aktuell)
        aktuell, puffer = None, []

    for nr, line in enumerate(text.splitlines(), start=1):
        m = _HEADING.match(line.strip())
        if m:
            abschliessen()
            ebene, ueberschrift = len(m.group(1)), m.group(2).strip()
            if ebene == 1 and not titel:
                titel = ueberschrift
            aktuell = Abschnitt(datei=datei, ueberschrift=ueberschrift, zeile=nr)
            continue
        if aktuell is None:
            aktuell = Abschnitt(datei=datei, ueberschrift=titel, zeile=1)
        puffer.append(line)
    abschliessen()
    return [a for a in out if a.text]


class WikiIndex:
    def __init__(self, pfad: Path, abschnitte: list[Abschnitt], glossar: Glossar, status: WikiStatus) -> None:
        self.pfad = pfad
        self.abschnitte = abschnitte
        self.glossar = glossar
        self.status = status
        self._df: Counter = Counter()
        for a in abschnitte:
            a.tokens = Counter(tokenisiere(a.ueberschrift)) + Counter(tokenisiere(a.ueberschrift)) + Counter(tokenisiere(a.text))
            a.laenge = sum(a.tokens.values())
            self._df.update(a.tokens.keys())
        self._n = len(abschnitte)
        self._avg = (sum(a.laenge for a in abschnitte) / self._n) if self._n else 1.0

    @classmethod
    def laden(cls, pfad: Path | str) -> WikiIndex:
        pfad = Path(pfad)
        gelesen = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not pfad.is_dir():
            raise FileNotFoundError(f"Ordner nicht gefunden: {pfad}")
        dateien = seiten_dateien(pfad)
        warnungen: list[str] = []
        abschnitte: list[Abschnitt] = []
        glossar = Glossar()
        stand = 0.0
        seiten = 0
        for datei in dateien:
            try:
                if datei.stat().st_size > MAX_DATEI_BYTES:
                    warnungen.append(f"übersprungen (zu groß): {datei.relative_to(pfad).as_posix()}")
                    continue
                text = datei.read_text(encoding="utf-8", errors="replace")
                stand = max(stand, datei.stat().st_mtime)
            except OSError as exc:
                warnungen.append(f"nicht lesbar: {datei.relative_to(pfad).as_posix()} ({exc.strerror or exc})")
                continue
            rel = datei.relative_to(pfad).as_posix()
            if ist_glossar(datei, text) and not glossar.datei:
                glossar = parse_glossar(text, rel)
            seiten += 1
            abschnitte += abschnitte_aus(text, rel)
            if len(abschnitte) > MAX_ABSCHNITTE:
                warnungen.append(f"Index bei {MAX_ABSCHNITTE} Abschnitten abgeschnitten")
                abschnitte = abschnitte[:MAX_ABSCHNITTE]
                break
        if not seiten:
            raise ValueError(f"Keine Markdown-Seiten gefunden unter {pfad}")
        name = _wiki_name(pfad)
        status = WikiStatus(
            ZUSTAND_OK, pfad=str(pfad), name=name, seiten=seiten, abschnitte=len(abschnitte),
            glossar_eintraege=len(glossar.eintraege), glossar_datei=glossar.datei,
            stand=datetime.fromtimestamp(stand).strftime("%Y-%m-%d %H:%M") if stand else "", gelesen=gelesen,
            meldung=_meldung_ok(name, seiten, glossar), warnungen=tuple(warnungen),
        )
        return cls(pfad, abschnitte, glossar, status)

    def suche(self, text: str, *, top_k: int = 6, je_datei: int = 2) -> list[Fundstelle]:
        """BM25 über Abschnitte; der Suchtext wird vorher über das Glossar korrigiert."""
        anfrage = Counter(tokenisiere(self.glossar.korrigiere(text)))
        if not anfrage or not self._n:
            return []
        k1, b = 1.5, 0.75
        bewertet: list[tuple[float, Abschnitt]] = []
        for a in self.abschnitte:
            score = 0.0
            for tok in anfrage:
                tf = a.tokens.get(tok)
                if not tf:
                    continue
                idf = math.log(1 + (self._n - self._df[tok] + 0.5) / (self._df[tok] + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * a.laenge / self._avg))
            if score > 0:
                bewertet.append((score, a))
        bewertet.sort(key=lambda t: -t[0])
        out: list[Fundstelle] = []
        je: Counter = Counter()
        for score, a in bewertet:
            if je[a.datei] >= je_datei:
                continue
            je[a.datei] += 1
            out.append(Fundstelle(a.datei, a.ueberschrift, a.zeile, a.text[:AUSZUG_MAX], round(score, 3)))
            if len(out) >= top_k:
                break
        return out


def _wiki_name(pfad: Path) -> str:
    index = pfad / "index.md"
    try:
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _HEADING.match(line.strip())
            if m and len(m.group(1)) == 1:
                return m.group(2).strip()
    except OSError:
        pass
    return pfad.name


def _meldung_ok(name: str, seiten: int, glossar: Glossar) -> str:
    g = f"Glossar: {len(glossar.eintraege)} Einträge ({glossar.datei})" if glossar.datei else "Glossar: keins im Wiki"
    return f"{name}: {seiten} Seiten gelesen. {g}."


def pruefe_wiki(pfad: Path | str | None) -> WikiStatus:
    """K1: Pfad prüfen - erreichbar, lesbar, ein Wiki? Verständliche Meldung für den Moderator."""
    if pfad is None or not str(pfad).strip():
        return status_keins()
    pfad = Path(pfad)
    try:
        return WikiIndex.laden(pfad).status
    except FileNotFoundError:
        return WikiStatus(ZUSTAND_FEHLER, pfad=str(pfad), meldung="Ordner nicht gefunden oder nicht erreichbar.")
    except PermissionError:
        return WikiStatus(ZUSTAND_FEHLER, pfad=str(pfad), meldung="Keine Leserechte für diesen Ordner.")
    except ValueError as exc:
        return WikiStatus(ZUSTAND_FEHLER, pfad=str(pfad), meldung=f"Kein Wiki gefunden: {exc}")
    except OSError as exc:
        return WikiStatus(ZUSTAND_FEHLER, pfad=str(pfad), meldung=f"Nicht lesbar: {exc.strerror or exc}")
