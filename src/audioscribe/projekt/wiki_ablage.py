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

from audioscribe.projekt.modell import Projekt, ist_unter

VERMERK = "wiki-ablage.json"
NACHBEREITUNG_ORDNER = "nachbereitung-ki"
# Aus dem Analyse-Ordner nicht mitgenommen: Materialkopie, Kontext, Skills, Protokoll, Manifest.
_ANALYSE_AUSGELASSEN = {"material", "kontext", "agent-log.txt", "analyse.json", VERMERK}

_DATUM = re.compile(r"(\d{4}-\d{2}-\d{2})")
_LIVE_NAME = re.compile(r"^live-\d{4}-\d{2}-\d{2}_(\d{2}-\d{2}-\d{2})$")
_BILD_LINK = re.compile(r"!\[([^\]]*)\]\((?:\./)?material/frames/([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FRAME_PFAD = re.compile(r"(?:\./)?material/frames/([^)\s\"'<>]+)")


@dataclass(frozen=True)
class Ablage:
    ordner: str  # Ziel unter raw/
    assets: str | None  # Bilder-Ordner dieser Sitzung (None = ohne Bilder gespeichert)
    bilder: int
    markierungen: int
    titel: str
    zeit: str
    art: str = "sitzung"  # sitzung | nachbereitung

    def als_dict(self) -> dict:
        return asdict(self)


# --- Hilfen ----------------------------------------------------------------------------------


_ist_unter = ist_unter


def _pruefe_ziele(projekt: Projekt) -> None:
    """Geschrieben wird nur nach raw/ und in den Assets-Ordner - nie unter die Wiki-Seiten."""
    if not projekt.wurzel.is_dir():
        raise RuntimeError(f"LLM-Wiki nicht erreichbar: {projekt.wurzel}")
    for ziel in (projekt.raw_dir, projekt.assets_dir):
        if _ist_unter(ziel, projekt.seiten_dir):
            raise RuntimeError(f"Ablage darf nicht unter den Wiki-Seiten liegen: {ziel}")
    if not _ist_unter(projekt.assets_dir, projekt.wurzel):
        raise RuntimeError(f"Der Bilder-Ordner muss im LLM-Wiki liegen: {projekt.assets_dir}")
    if projekt.assets_dir.resolve() == projekt.raw_dir.resolve():
        raise RuntimeError("Der Bilder-Ordner darf nicht raw/ selbst sein - bitte z. B. raw/assets wählen.")


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


def _titel_der_sitzung(session_dir: Path) -> str:
    try:
        data = json.loads((session_dir / "sitzung.json").read_text(encoding="utf-8"))
        return str(data.get("titel") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


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


def letzte_ablage(session_dir: Path, projekt: Projekt | None = None) -> dict | None:
    """Jüngste noch vorhandene Ablage der Sitzung. Mit ``projekt`` zählen nur Ablagen in dessen
    ``raw/`` - der Vermerk ist nur eine Notiz im Sitzungsordner und kann aus einem anderen
    Projekt oder einem kopierten Wiki stammen."""
    for a in reversed(ablagen(session_dir)):
        ordner = str(a.get("ordner") or "")
        if a.get("art", "sitzung") != "sitzung" or not ordner or not Path(ordner).is_dir():
            continue
        if projekt is not None:
            if not _ist_unter(Path(ordner), projekt.raw_dir):
                continue
            if a.get("assets") and not _ist_unter(Path(str(a["assets"])), projekt.assets_dir):
                a = {**a, "assets": None}
        return a
    return None


# --- Sitzung ---------------------------------------------------------------------------------


def speichere_sitzung(
    session_dir: Path, projekt: Projekt, *, titel: str = "", bilder: bool = True, markierungen: bool = False
) -> Ablage:
    """Das Transkript der Sitzung ins Wiki legen - auf Wunsch mit Bildern und mit den
    Markierungen des Souffleurs. Die Markierungen sind KI-erzeugt und zitieren das Wiki; unter
    ``raw/`` könnte der Ingest sie als Quelle lesen, deshalb gehen sie nur auf Wunsch mit."""
    from audioscribe.review.marks import load_marks, save_marks
    from audioscribe.review.merge import render_markdown_with_marks
    from audioscribe.souffleur import markierung, uebergabe

    session_dir = Path(session_dir)
    quelle = session_dir / "transkript.md"
    if not quelle.is_file():
        raise FileNotFoundError(f"Kein Transkript in {session_dir}")
    _pruefe_ziele(projekt)
    titel = titel.strip() or _titel_der_sitzung(session_dir)

    raw, assets_basis = projekt.raw_dir, projekt.assets_dir
    raw.mkdir(parents=True, exist_ok=True)
    name = _freier_name(ordnername(session_dir, titel), raw, assets_basis)
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
        )
        _vermerke(session_dir, ablage)
        return ablage
    except BaseException:
        for ordner in reversed(angelegt):
            shutil.rmtree(ordner, ignore_errors=True)
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

    sitzung = letzte_ablage(session_dir, projekt) or speichere_sitzung(
        session_dir, projekt, bilder=bilder, markierungen=markierungen
    ).als_dict()
    basis = Path(sitzung["ordner"])
    # Liegt die Sitzung ohne Bilder im Wiki, bekommt die Nachbereitung ihren eigenen Bilder-Ordner
    # unter demselben Namen - die Sitzung wird dafuer nicht ein zweites Mal abgelegt.
    if sitzung.get("assets"):
        assets: Path | None = Path(sitzung["assets"])
    else:
        assets = projekt.assets_dir / basis.name if bilder else None

    eltern = basis / NACHBEREITUNG_ORDNER
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
            "Transkript (und den Bildern) dieser Sitzung erstellt. Beleg ist allein das Transkript im\n"
            "übergeordneten Ordner.\n",
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
