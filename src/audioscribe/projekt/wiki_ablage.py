"""Wiki-Ablage: eine beendete Sitzung als neue Quelle ins LLM-Wiki des Projekts legen.

Ziel ist ``<wiki>/raw/<JJJJ-MM-TT>_<kurzname>/`` - der Ort, an dem das Wiki seine Rohquellen
erwartet. Bilder wandern in den Assets-Ordner des Projekts; die Zuordnung Zeitstempel ↔ Bild
bleibt erhalten: ``marks.json`` und ``transkript.annotiert.md`` der Ablage verweisen relativ
auf die Bilder dort.

Regeln (PRD §21):

- Die Seiten unter ``wiki/`` werden nie angefasst; geschrieben wird nur nach ``raw/`` und in
  den Assets-Ordner.
- Rein anhängend: nichts Bestehendes wird überschrieben (Kollision → ``-2``, ``-3`` …).
- ``transkript.md`` ist eine byte-gleiche Kopie - der Wortlaut bleibt unverändert.
- Die Ablage ist ein Export. KI-Analyse und Review arbeiten weiter auf dem Sitzungsordner.
- KI-erzeugte Nachbereitungen liegen getrennt unter ``nachbereitung-ki/`` und sind als
  KI-erzeugt gekennzeichnet - sie sind keine Quelle.

Meetings-Format (Projekteinstellung ``wiki_format``, ``speichere_meeting``): statt eines Ordners
eine Datei ``raw/meetings/<JJJJ-MM-TT>_<art>_<thema>.md`` - das Transkript mit den Bildlinks -,
daneben auf Wunsch ``<stamm>.souffleur.md``/``.json`` und die Bilder unter ``<assets>/<stamm>/``.
Alle teilen denselben Namensstamm; so verlangt es die ``CLAUDE.md`` des Wikis.

„Speichern unter …“ (``speichere_nach``) ist dieselbe Ablage an frei gewählte Ordner für
Transkript und Bilder - auch ohne Projekt. Nie unter die Wiki-Seiten, rein anhängend, die
Bildlinks bleiben relativ; nur die Wiki-Konventionen (``raw/``, Assets im Wiki) entfallen.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from audioscribe.projekt.modell import FORMAT_MEETINGS, MEETING_ARTEN, Projekt, gleich, ist_unter

VERMERK = "wiki-ablage.json"
NACHBEREITUNG_ORDNER = "nachbereitung-ki"
MEETINGS_ORDNER = "meetings"  # unter raw/ - Meetings-Format
SOUFFLEUR_ENDUNG = ".souffleur"  # Begleitdatei der Markierungen: <stamm>.souffleur.md/.json
# Aus dem Analyse-Ordner nicht mitgenommen: Materialkopie, Kontext, Skills, Protokoll, Manifest.
_ANALYSE_AUSGELASSEN = {"material", "kontext", "agent-log.txt", "analyse.json", VERMERK}

_DATUM = re.compile(r"(\d{4}-\d{2}-\d{2})")
_LIVE_NAME = re.compile(r"^live-\d{4}-\d{2}-\d{2}_(\d{2}-\d{2}-\d{2})$")
_BILD_LINK = re.compile(r"!\[([^\]]*)\]\((?:\./)?material/frames/([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FRAME_PFAD = re.compile(r"(?:\./)?material/frames/([^)\s\"'<>]+)")
# Namensstamm im Meetings-Format, wie ihn die CLAUDE.md des Wikis vorgibt.
STAMM_MUSTER = re.compile(r"^\d{4}-\d{2}-\d{2}_(" + "|".join(MEETING_ARTEN) + r")_[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Ablage:
    ordner: str  # Ziel unter raw/ (Meetings-Format: die Transkript-Datei)
    assets: str | None  # Bilder-Ordner dieser Sitzung (None = ohne Bilder gespeichert)
    bilder: int
    markierungen: int
    titel: str
    zeit: str
    art: str = "sitzung"  # sitzung | nachbereitung
    frei: bool = False  # Ziele vom Nutzer gewählt („Speichern unter …“) statt raw/ und Assets des Projekts

    def als_dict(self) -> dict:
        return asdict(self)


# --- Hilfen ----------------------------------------------------------------------------------


_ist_unter = ist_unter


def _pruefe_ziele(projekt: Projekt) -> None:
    """Geschrieben wird nur nach raw/ und in den Assets-Ordner - nie unter die Wiki-Seiten."""
    if projekt.wiki_dir is None or projekt.raw_dir is None or projekt.assets_dir is None:
        raise RuntimeError("Dieses Projekt hat kein Wiki – in den Projekteinstellungen anlegen oder verknüpfen.")
    if not projekt.wiki_dir.is_dir():
        raise RuntimeError(f"LLM-Wiki nicht erreichbar: {projekt.wiki_dir}")
    for ziel in (projekt.raw_dir, projekt.assets_dir):
        if _ist_unter(ziel, projekt.seiten_dir):
            raise RuntimeError(f"Ablage darf nicht unter den Wiki-Seiten liegen: {ziel}")
    if not _ist_unter(projekt.assets_dir, projekt.wiki_dir):
        raise RuntimeError(f"Der Bilder-Ordner muss im LLM-Wiki liegen: {projekt.assets_dir}")
    if projekt.assets_dir.resolve() == projekt.raw_dir.resolve():
        raise RuntimeError("Der Bilder-Ordner darf nicht raw/ selbst sein - bitte z. B. raw/assets wählen.")


def _pruefe_freie_ziele(
    session_dir: Path, raw_basis: Path | None, assets_basis: Path | None, seiten_dir: Path | None
) -> None:
    """Regeln für frei gewählte Ziele: nie unter die Wiki-Seiten, nicht in den Sitzungsordner
    selbst (Kopie in sich hinein), Bilder nicht in den Transkript-Ordner."""
    if raw_basis is None or str(raw_basis) in ("", "."):
        raise RuntimeError("Bitte einen Ordner für das Transkript wählen.")
    if raw_basis.is_file() or (assets_basis is not None and assets_basis.is_file()):
        raise RuntimeError("Das Ziel muss ein Ordner sein, keine Datei.")
    for ziel in (raw_basis, assets_basis):
        if ziel is None:
            continue
        if seiten_dir is not None and _ist_unter(ziel, seiten_dir):
            raise RuntimeError(f"Ablage darf nicht unter den Wiki-Seiten liegen: {ziel}")
        if _ist_unter(ziel, session_dir):
            raise RuntimeError("Die Ablage darf nicht im Sitzungsordner selbst liegen.")
    if assets_basis is not None and gleich(assets_basis, raw_basis):
        raise RuntimeError("Der Bilder-Ordner darf nicht der Transkript-Ordner selbst sein - bitte einen Unterordner wählen.")


def _datum(session_dir: Path) -> str:
    """Datum der Sitzung: aus dem Ordnernamen, sonst aus dem Transkript, sonst heute."""
    m = _DATUM.search(session_dir.name)
    if m:
        return m.group(1)
    try:
        data = json.loads((session_dir / "transcript.json").read_text(encoding="utf-8"))
        m = _DATUM.search(str(data.get("created") or ""))
        if m:
            return m.group(1)
    except (OSError, ValueError):
        pass
    return datetime.now().strftime("%Y-%m-%d")


def ordnername(session_dir: Path, titel: str = "") -> str:
    """``<JJJJ-MM-TT>_<kurzname>`` - das Namensschema der Rohquellen im Wiki."""
    from audioscribe.agent.material import slugify

    session_dir = Path(session_dir)
    if titel.strip():
        kurz = slugify(titel)
    else:
        live = _LIVE_NAME.match(session_dir.name)
        kurz = f"live-{live.group(1)}" if live else slugify(_DATUM.sub("", session_dir.name) or session_dir.name)
    return f"{_datum(session_dir)}_{kurz}"


def _freier_name(name: str, *basen: Path) -> str:
    """Erster Name, der in keinem der Ordner belegt ist (``name``, ``name-2``, …)."""
    kandidat, n = name, 2
    while any((b / kandidat).exists() for b in basen):
        kandidat = f"{name}-{n}"
        n += 1
    return kandidat


def _rel_posix(ziel: Path, von: Path) -> str:
    return Path(os.path.relpath(ziel, von)).as_posix()


def _link(pfad: str) -> str:
    """Pfad für einen Markdown-Link: Leerzeichen und Klammern maskiert, ``../`` bleibt."""
    return quote(pfad, safe="/.-_~")


def _atomar(pfad: Path, text: str) -> None:
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, pfad)


def _aus_sitzung(session_dir: Path, feld: str) -> str:
    try:
        data = json.loads((session_dir / "sitzung.json").read_text(encoding="utf-8"))
        return str(data.get(feld) or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def _titel_der_sitzung(session_dir: Path) -> str:
    return _aus_sitzung(session_dir, "titel")


def art_der_sitzung(session_dir: Path) -> str:
    """Die beim Start gewählte Art des Meetings (leer = keine)."""
    art = _aus_sitzung(Path(session_dir), "art").lower()
    return art if art in MEETING_ARTEN else ""


# --- Vermerk im Sitzungs- bzw. Analyse-Ordner ------------------------------------------------


def ablagen(ordner: Path) -> list[dict]:
    """Was aus diesem Ordner schon ins Wiki gelegt wurde (älteste zuerst)."""
    try:
        data = json.loads((Path(ordner) / VERMERK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def _vermerke(ordner: Path, ablage: Ablage) -> None:
    try:
        _atomar(Path(ordner) / VERMERK, json.dumps([*ablagen(ordner), ablage.als_dict()], ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass  # der Vermerk ist Komfort - die Ablage selbst ist geschrieben


def letzte_ablage(session_dir: Path, projekt: Projekt | None = None, *, auch_freie: bool = True) -> dict | None:
    """Jüngste noch vorhandene Ablage der Sitzung. Mit ``projekt`` zählen nur Ablagen in dessen
    ``raw/`` - der Vermerk ist nur eine Notiz im Sitzungsordner und kann aus einem anderen
    Projekt oder einem kopierten Wiki stammen - und, wenn ``auch_freie``, die per „Speichern
    unter …“ an frei gewählte Ordner gelegten."""
    for a in reversed(ablagen(session_dir)):
        ordner = str(a.get("ordner") or "")
        # Meetings-Format: "ordner" ist die Transkript-Datei.
        if a.get("art", "sitzung") != "sitzung" or not ordner or not Path(ordner).exists():
            continue
        frei = bool(a.get("frei"))
        if frei and not auch_freie:
            continue
        if projekt is not None and not frei:
            if projekt.raw_dir is None or not _ist_unter(Path(ordner), projekt.raw_dir):
                continue
            if a.get("assets") and (
                projekt.assets_dir is None or not _ist_unter(Path(str(a["assets"])), projekt.assets_dir)
            ):
                a = {**a, "assets": None}
        if frei and a.get("assets") and not Path(str(a["assets"])).is_dir():
            a = {**a, "assets": None}
        return a
    return None


# --- Sitzung ---------------------------------------------------------------------------------


def speichere_sitzung(
    session_dir: Path, projekt: Projekt, *, titel: str = "", art: str = "", bilder: bool = True,
    markierungen: bool = False,
) -> Ablage:
    """Das Transkript der Sitzung ins Wiki legen - auf Wunsch mit Bildern und mit den
    Markierungen des Souffleurs. Die Markierungen sind KI-erzeugt und zitieren das Wiki; unter
    ``raw/`` könnte der Ingest sie als Quelle lesen, deshalb gehen sie nur auf Wunsch mit.
    Das Ablageformat bestimmt das Projekt (``wiki_format``)."""
    _pruefe_ziele(projekt)
    if projekt.wiki_format == FORMAT_MEETINGS:
        return speichere_meeting(
            session_dir, projekt, titel=titel, art=art, bilder=bilder, markierungen=markierungen
        )
    return speichere_nach(
        session_dir, raw_basis=projekt.raw_dir, assets_basis=projekt.assets_dir, seiten_dir=projekt.seiten_dir,
        titel=titel, bilder=bilder, markierungen=markierungen, frei=False,
    )


def speichere_nach(
    session_dir: Path,
    *,
    raw_basis: Path,
    assets_basis: Path | None,
    seiten_dir: Path | None = None,
    titel: str = "",
    bilder: bool = True,
    markierungen: bool = False,
    frei: bool = True,
) -> Ablage:
    """Die Sitzung an zwei Ziele legen: ``<raw_basis>/<JJJJ-MM-TT>_<kurzname>/`` bekommt das
    Transkript, ``<assets_basis>/<derselbe Name>/`` die Bilder (``None`` = ohne Bilder). Die
    Bildlinks sind relativ - beide Ordner lassen sich zusammen verschieben. ``seiten_dir`` sind
    die Wiki-Seiten, unter die nie geschrieben wird."""
    from audioscribe.review.marks import load_marks, save_marks
    from audioscribe.review.merge import render_markdown_with_marks
    from audioscribe.souffleur import markierung, uebergabe

    session_dir = Path(session_dir)
    quelle = session_dir / "transkript.md"
    if not quelle.is_file():
        raise FileNotFoundError(f"Kein Transkript in {session_dir}")
    raw = Path(raw_basis) if raw_basis is not None else None
    assets_basis = Path(assets_basis) if assets_basis is not None else None
    _pruefe_freie_ziele(session_dir, raw, assets_basis, seiten_dir)
    bilder = bilder and assets_basis is not None
    titel = titel.strip() or _titel_der_sitzung(session_dir)

    raw.mkdir(parents=True, exist_ok=True)
    name = _freier_name(ordnername(session_dir, titel), raw, *([assets_basis] if assets_basis is not None else []))
    ziel = raw / name
    ziel.mkdir()

    # Scheitert die Ablage unterwegs (Platte voll, Rechte), verschwindet das selbst Angelegte
    # wieder - eine halbe Quelle unter raw/ würde der Ingest des Wikis für bare Münze nehmen.
    angelegt: list[Path] = [ziel]
    try:
        shutil.copyfile(quelle, ziel / "transkript.md")  # byte-gleich
        data: dict | None = None
        try:
            data = json.loads((session_dir / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            # Der absolute lokale Pfad zum Mitschnitt gehört nicht ins Wiki.
            ohne_pfad = {k: v for k, v in data.items() if k != "source_path"}
            _atomar(ziel / "transcript.json", json.dumps(ohne_pfad, ensure_ascii=False, indent=2) + "\n")

        anzahl_bilder = 0
        assets: Path | None = None
        if bilder:
            try:
                marks = load_marks(session_dir)
            except (OSError, ValueError, KeyError, TypeError):
                marks = []
            vorhandene = [m for m in marks if (session_dir / m.png).is_file()]
            if vorhandene:
                assets = assets_basis / name
                assets.mkdir(parents=True)
                angelegt.append(assets)
                neue = []
                for m in vorhandene:
                    bild = assets / Path(m.png).name
                    shutil.copyfile(session_dir / m.png, bild)
                    neue.append(replace(m, png=_rel_posix(bild, ziel)))
                anzahl_bilder = len(neue)
                # Maschinenlesbar: Zeitstempel -> Bild im Assets-Ordner (relativ zur Ablage).
                save_marks(ziel, neue)
                if isinstance(data, dict):
                    verlinkt = [replace(m, png=_link(m.png)) for m in neue]
                    _atomar(ziel / "transkript.annotiert.md", render_markdown_with_marks(data, verlinkt))

        anzahl_markierungen = 0
        stand = markierung.lade(session_dir) if markierungen else None
        if stand is not None:
            fassung = uebergabe.fassung(session_dir)
            sitzung = stand.sitzung or session_dir.name
            inhalt = uebergabe.daten(stand, sitzung=sitzung, transkript_fassung=fassung)
            _atomar(ziel / uebergabe.MARKIERUNGEN_JSON, json.dumps(inhalt, ensure_ascii=False, indent=2) + "\n")
            _atomar(ziel / uebergabe.MARKIERUNGEN_MD, uebergabe.render_md(sitzung, stand, fassung))
            anzahl_markierungen = len(stand.markierungen)

        _atomar(ziel / "README.md", _readme(titel or session_dir.name, session_dir.name, assets, ziel, stand is not None))
        ablage = Ablage(
            ordner=str(ziel), assets=str(assets) if assets else None, bilder=anzahl_bilder,
            markierungen=anzahl_markierungen, titel=titel, zeit=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            frei=frei,
        )
        _vermerke(session_dir, ablage)
        return ablage
    except BaseException:
        for ordner in reversed(angelegt):
            shutil.rmtree(ordner, ignore_errors=True)
        raise


# --- Meetings-Format ---------------------------------------------------------------------------


def meeting_stamm(session_dir: Path, art: str, titel: str = "") -> str:
    """``<JJJJ-MM-TT>_<art>_<thema>`` - Thema aus dem Titel wie beim Ordnernamen (kebab-case)."""
    datum, thema = ordnername(session_dir, titel).split("_", 1)
    return f"{datum}_{art}_{thema}"


def _meeting_dateien(meetings: Path, stamm: str) -> list[Path]:
    """Was unter einem Namensstamm neben dem Transkript liegen kann."""
    return [
        meetings / f"{stamm}.md",
        meetings / f"{stamm}{SOUFFLEUR_ENDUNG}.md",
        meetings / f"{stamm}{SOUFFLEUR_ENDUNG}.json",
        meetings / f"{stamm}.{NACHBEREITUNG_ORDNER}",
    ]


def _freier_stamm(stamm: str, meetings: Path, assets_basis: Path | None) -> str:
    """Erster Stamm, unter dem weder eine der Dateien noch der Bilder-Ordner existiert - ein
    Konflikt in einem der Ziele verschiebt alle (``-2``, ``-3`` …), damit sie zusammenpassen."""
    kandidat, n = stamm, 2
    while any(p.exists() for p in _meeting_dateien(meetings, kandidat)) or (
        assets_basis is not None and (assets_basis / kandidat).exists()
    ):
        kandidat = f"{stamm}-{n}"
        n += 1
    return kandidat


def _neu(pfad: Path, text: str) -> None:
    """Neue Datei schreiben - nie über eine bestehende."""
    with open(pfad, "x", encoding="utf-8") as f:
        f.write(text)


def _mit_meeting_kopf(markdown: str, datum: str, art: str, titel: str, sprecher: list[str]) -> str:
    """Datum, Anlass und Teilnehmende (als Rollen) oben in die Kopftabelle des Transkripts."""
    zeilen = [f"| Datum | {datum} |", f"| Anlass | {art.capitalize()}{': ' + titel if titel else ''} |"]
    if sprecher:
        zeilen.append(f"| Teilnehmende | {', '.join(sprecher)} |")
    trenner = "|---|---|\n"
    if trenner not in markdown:
        return markdown
    return markdown.replace(trenner, trenner + "\n".join(zeilen) + "\n", 1)


def speichere_meeting(
    session_dir: Path, projekt: Projekt, *, titel: str = "", art: str = "", bilder: bool = True,
    markierungen: bool = False,
) -> Ablage:
    """Die Sitzung als eine Datei ``raw/meetings/<stamm>.md`` ins Wiki legen: das Transkript mit
    erweitertem Kopf und relativen Bildlinks; Bilder unter ``<assets>/<stamm>/``, Markierungen
    auf Wunsch in ``<stamm>.souffleur.md``/``.json``. Der Wortlaut bleibt unverändert."""
    from audioscribe.review.marks import load_marks
    from audioscribe.review.merge import render_markdown_with_marks
    from audioscribe.souffleur import markierung, uebergabe

    _pruefe_ziele(projekt)
    session_dir = Path(session_dir)
    quelle = session_dir / "transkript.md"
    if not quelle.is_file():
        raise FileNotFoundError(f"Kein Transkript in {session_dir}")
    art = (art.strip().lower() or art_der_sitzung(session_dir))
    if art not in MEETING_ARTEN:
        raise RuntimeError(
            "Bitte die Art des Meetings wählen (" + ", ".join(MEETING_ARTEN) + ") – sie ist Teil des Dateinamens im Wiki."
        )
    titel = titel.strip() or _titel_der_sitzung(session_dir)
    try:
        data = json.loads((session_dir / "transcript.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = None

    meetings = projekt.raw_dir / MEETINGS_ORDNER
    meetings.mkdir(parents=True, exist_ok=True)
    stamm = _freier_stamm(meeting_stamm(session_dir, art, titel), meetings, projekt.assets_dir)
    datei = meetings / f"{stamm}.md"

    # Scheitert die Ablage unterwegs, verschwindet das selbst Angelegte wieder (wie beim Ordner).
    angelegt: list[Path] = []
    try:
        verlinkt = []
        assets: Path | None = None
        if bilder and data is not None:
            try:
                marks = load_marks(session_dir)
            except (OSError, ValueError, KeyError, TypeError):
                marks = []
            vorhandene = [m for m in marks if (session_dir / m.png).is_file()]
            if vorhandene:
                assets = projekt.assets_dir / stamm
                assets.mkdir(parents=True)
                angelegt.append(assets)
                for m in vorhandene:
                    bild = assets / Path(m.png).name
                    shutil.copyfile(session_dir / m.png, bild)
                    verlinkt.append(replace(m, png=_link(_rel_posix(bild, meetings))))

        if data is not None:
            sprecher = list(dict.fromkeys(str(p.get("speaker") or "") for p in data.get("paragraphs", [])))
            text = _mit_meeting_kopf(
                render_markdown_with_marks(data, verlinkt), _datum(session_dir), art, titel, [s for s in sprecher if s]
            )
        else:  # ohne transcript.json: das Transkript, wie es ist
            text = quelle.read_text(encoding="utf-8")
        _neu(datei, text)
        angelegt.append(datei)

        anzahl_markierungen = 0
        stand = markierung.lade(session_dir) if markierungen else None
        if stand is not None:
            fassung = uebergabe.fassung(session_dir)
            sitzung = stand.sitzung or session_dir.name
            inhalt = uebergabe.daten(stand, sitzung=sitzung, transkript_fassung=fassung)
            for endung, text in (
                (".json", json.dumps(inhalt, ensure_ascii=False, indent=2) + "\n"),
                (".md", uebergabe.render_md(sitzung, stand, fassung)),
            ):
                begleit = meetings / f"{stamm}{SOUFFLEUR_ENDUNG}{endung}"
                _neu(begleit, text)
                angelegt.append(begleit)
            anzahl_markierungen = len(stand.markierungen)

        ablage = Ablage(
            ordner=str(datei), assets=str(assets) if assets else None, bilder=len(verlinkt),
            markierungen=anzahl_markierungen, titel=titel, zeit=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        _vermerke(session_dir, ablage)
        return ablage
    except BaseException:
        for pfad in reversed(angelegt):
            if pfad.is_dir():
                shutil.rmtree(pfad, ignore_errors=True)
            else:
                pfad.unlink(missing_ok=True)
        raise


def _readme(titel: str, sitzung: str, assets: Path | None, ziel: Path, mit_markierungen: bool) -> str:
    zeilen = [
        f"# Quelle aus AudioScribe: {titel}",
        "",
        f"Sitzung `{sitzung}`. Dieser Ordner ist eine neue Rohquelle für das Wiki. Er wurde nur",
        "angehängt, nichts Bestehendes wurde verändert.",
        "",
        "- `transkript.md`: das Transkript der Sitzung, Wortlaut unverändert.",
        "- `transcript.json`: dasselbe maschinenlesbar (Absätze mit Zeitstempeln).",
    ]
    if assets is not None:
        zeilen += [
            f"- `transkript.annotiert.md`: das Transkript mit den Bildschirmbildern an der passenden Stelle;"
            f" die Bilder liegen unter `{_rel_posix(assets, ziel)}/`.",
            "- `marks.json`: Zuordnung Zeitstempel (`t`, Sekunden) → Bild (`png`, relativ zu diesem Ordner).",
        ]
    if mit_markierungen:
        zeilen += [
            "- `markierungen.json`: Markierungen des Souffleurs (format_version 1). Je Markierung: Art",
            "  (`widerspruch`, `offener_punkt`, `frage`; erweiterbar), Zeitbezug (`zeitstempel`, `t_start`,",
            "  `t_end`, `segment_id`), die wörtliche `aussage`, belegtes Wiki-Wissen unter `wiki`",
            "  (Fundstellen mit Datei, Überschrift, Zeile; Zitat) und getrennt davon `ki_erzeugt`.",
            "- `markierungen.md`: dieselben Markierungen lesbar.",
        ]
    zeilen += ["", "Was aus der Quelle im Wiki wird, entscheidet der Ingest- bzw. Lint-Prozess des Wikis.", ""]
    return "\n".join(zeilen)


# --- Nachbereitung (KI-Analyse) --------------------------------------------------------------


def speichere_nachbereitung(
    workspace: Path, projekt: Projekt, session_dir: Path, *, bilder: bool = True, markierungen: bool = False
) -> Ablage:
    """Dokumente einer KI-Analyse zur Sitzung ins Wiki legen - getrennt und als KI-erzeugt
    gekennzeichnet. Liegt die Sitzung noch nicht im Wiki, wird sie zuerst gespeichert.

    Mit Bildern verweisen die Dokumente auf die Bilder im Assets-Ordner der Sitzung (keine
    zweite Kopie); ohne Bilder werden Bildzeilen zu Textverweisen.
    """
    workspace, session_dir = Path(workspace), Path(session_dir)
    if not workspace.is_dir():
        raise FileNotFoundError(f"Analyse-Ordner nicht gefunden: {workspace}")
    _pruefe_ziele(projekt)

    # Eine freie Ablage („Speichern unter …“) zählt hier nicht: die Nachbereitung gehört ins Wiki.
    sitzung = letzte_ablage(session_dir, projekt, auch_freie=False) or speichere_sitzung(
        session_dir, projekt, bilder=bilder, markierungen=markierungen
    ).als_dict()
    basis = Path(sitzung["ordner"])
    # Meetings-Format: die Sitzung ist eine Datei - die Nachbereitung liegt daneben unter demselben Stamm.
    name = basis.stem if basis.is_file() else basis.name
    # Liegt die Sitzung ohne Bilder im Wiki, bekommt die Nachbereitung ihren eigenen Bilder-Ordner
    # unter demselben Namen - die Sitzung wird dafuer nicht ein zweites Mal abgelegt.
    if sitzung.get("assets"):
        assets: Path | None = Path(sitzung["assets"])
    else:
        assets = projekt.assets_dir / name if bilder else None

    eltern = basis.parent / f"{name}.{NACHBEREITUNG_ORDNER}" if basis.is_file() else basis / NACHBEREITUNG_ORDNER
    eltern.mkdir(exist_ok=True)
    ziel = eltern / _freier_name(workspace.name, eltern)
    ziel.mkdir()

    frames = workspace / "material" / "frames"
    genutzt: set[str] = set()

    def bildpfad(name: str, von: Path) -> str | None:
        """Relativer Link vom Dokument zum Bild in den Assets; fehlt es dort, wird es ergänzt."""
        # Nur ein Dateiname aus material/frames - nie ein Pfad, der aus dem Bilder-Ordner hinausführt.
        if assets is None or Path(name).name != name or name in ("", ".", ".."):
            return None
        bild = assets / name
        if not bild.is_file():
            if not (frames / name).is_file():
                return None
            assets.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(frames / name, bild)
        genutzt.add(name)
        return _link(_rel_posix(bild, von))

    try:
        for quelle in sorted(workspace.rglob("*")):
            rel = quelle.relative_to(workspace)
            # Arbeitsmaterial liegt auf der obersten Ebene; Punktordner (Skills) bleiben ueberall draussen.
            if rel.parts[0] in _ANALYSE_AUSGELASSEN or any(t.startswith(".") for t in rel.parts):
                continue
            neu = ziel / rel
            if quelle.is_dir():
                neu.mkdir(parents=True, exist_ok=True)
                continue
            neu.parent.mkdir(parents=True, exist_ok=True)
            if quelle.suffix.lower() != ".md":
                shutil.copyfile(quelle, neu)
                continue
            text = quelle.read_text(encoding="utf-8", errors="replace")
            if bilder and assets is not None:
                text = _FRAME_PFAD.sub(lambda m: bildpfad(m.group(1), neu.parent) or m.group(0), text)
            else:
                text = _BILD_LINK.sub(lambda m: f"_[{m.group(1) or m.group(2)}]_", text)
            neu.write_text(text, encoding="utf-8")

        # Ein README des Agenten bleibt stehen - der Hinweis bekommt dann einen eigenen Namen.
        _atomar(
            ziel / ("KI-ERZEUGT.md" if (ziel / "README.md").exists() else "README.md"),
            f"# KI-Nachbereitung: {workspace.name}\n\n"
            "**KI-erzeugt – keine Quelle.** Diese Dokumente hat der Analyse-Agent von AudioScribe aus dem\n"
            "Transkript (und den Bildern) dieser Sitzung erstellt. Beleg ist allein das Transkript "
            + (f"`{basis.name}` daneben.\n" if basis.is_file() else "im\nübergeordneten Ordner.\n"),
        )
    except BaseException:
        shutil.rmtree(ziel, ignore_errors=True)
        raise
    ablage = Ablage(
        ordner=str(ziel), assets=str(assets) if assets and genutzt else None, bilder=len(genutzt),
        markierungen=0, titel=workspace.name, zeit=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        art="nachbereitung",
    )
    _vermerke(workspace, ablage)
    return ablage
