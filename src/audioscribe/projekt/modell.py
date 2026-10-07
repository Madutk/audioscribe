"""Das Projekt und seine Datei im Projektordner.

Der **Projektordner** ist die Identität des Projekts: ``<projekt>/.audioscribe/projekt.json``
(Version 2), darin als Vorgabe ``sitzungen/`` für die Live-Sitzungen und - nur wenn ein neues
Wiki angelegt wurde - ``llm-wiki/``. Ein vorhandenes LLM-Wiki wird per Pfad verknüpft
(``wiki_dir``); ein Projekt kann auch ganz ohne Wiki arbeiten.

Pfade stehen relativ zum Projektordner in der Datei, wo das geht - ein Projekt unter
``C:\\Users\\…`` öffnet sich so auch unter ``/Users/…``.

Kompatibilität: Projektdateien der Version 1 lagen im Wiki-Ordner selbst und kannten kein
``wiki_dir``. Sie öffnen sich unverändert - der Projektordner ist dort die Wiki-Wurzel
(``wiki_dir = "."``). Der Punktordner wird vom Wiki-Index übersprungen (``souffleur/wiki.py``).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

PROJEKT_ORDNER = ".audioscribe"
PROJEKT_DATEI = "projekt.json"
VERSION = 2

RAW_ORDNER = "raw"
SEITEN_ORDNER = "wiki"
ASSETS_VORSCHLAG = "raw/assets"
ANALYSEN_ORDNER = "analysen"
# Vorgaben im Projektordner: Sitzungen und - bei "Neues Wiki anlegen" - das Wiki.
SITZUNGEN_ORDNER = "sitzungen"
WIKI_ORDNER = "llm-wiki"

# Wie das Projekt zu seinem Wiki kommt: gar nicht, neu im Projektordner, vorhandenes verknüpfen.
WIKI_KEINS = "keins"
WIKI_NEU = "neu"
WIKI_VORHANDEN = "vorhanden"
WIKI_ARTEN: tuple[str, ...] = (WIKI_KEINS, WIKI_NEU, WIKI_VORHANDEN)

# Wiki-Ablage nach Sitzungsende: nachfragen, ohne Nachfrage speichern, nie anbieten.
WIKI_FRAGEN = "fragen"
WIKI_IMMER = "immer"
WIKI_NIE = "nie"
WIKI_SPEICHERN: tuple[str, ...] = (WIKI_FRAGEN, WIKI_IMMER, WIKI_NIE)

# Felder, die ein Projekt von den globalen Einstellungen überschreiben kann (None = global).
UEBERSCHREIBBAR: tuple[str, ...] = ("ki_dienst", "souffleur_model", "agent_model", "sprache")


class ProjektFehler(ValueError):
    """Projekt nicht lesbar oder Angaben unvollständig - die Meldung ist für den Nutzer."""


@dataclass(frozen=True)
class Projekt:
    wurzel: Path  # Projektordner (.audioscribe/, Vorgabe sitzungen/)
    name: str
    sitzungen_dir: Path  # Live-Mitschnitte und Analysen
    wiki_dir: Path | None = None  # LLM-Wiki-Wurzel (mit raw/ und wiki/) - oder kein Wiki
    assets_dir: Path | None = None  # Bilder der ins Wiki gespeicherten Sitzungen (nur mit Wiki)
    id: str = ""
    erstellt: str = ""
    ki_dienst: str | None = None
    souffleur_model: str | None = None
    agent_model: str | None = None
    sprache: str | None = None
    wiki_speichern: str = WIKI_FRAGEN
    wiki_bilder: bool = True
    # Markierungen des Souffleurs mit ablegen: KI-erzeugt, deshalb nur auf Wunsch (Vorgabe: nein).
    wiki_markierungen: bool = False
    # Demo-Projekt: liegt nicht auf der Platte, wird nie gespeichert (ui/kontext.py).
    demo: bool = False
    # Hinweis vom Laden (nicht gespeichert): z. B. ein Ordner aus der Projektdatei war auf
    # diesem Rechner nicht brauchbar und wurde durch den Vorschlag ersetzt.
    hinweis: str = ""

    @property
    def hat_wiki(self) -> bool:
        return self.wiki_dir is not None

    @property
    def raw_dir(self) -> Path | None:
        return self.wiki_dir / RAW_ORDNER if self.wiki_dir is not None else None

    @property
    def seiten_dir(self) -> Path | None:
        return self.wiki_dir / SEITEN_ORDNER if self.wiki_dir is not None else None

    @property
    def analysen_dir(self) -> Path:
        return self.sitzungen_dir / ANALYSEN_ORDNER

    @property
    def datei(self) -> Path:
        return projekt_datei(self.wurzel)


def projekt_datei(wurzel: Path) -> Path:
    return Path(wurzel) / PROJEKT_ORDNER / PROJEKT_DATEI


def ist_projekt(wurzel: Path) -> bool:
    try:
        return projekt_datei(wurzel).is_file()
    except OSError:
        return False


# --- Pfade in der Datei ----------------------------------------------------------------------


def ist_unter(pfad: Path, basis: Path) -> bool:
    """Liegt ``pfad`` in ``basis`` (oder ist er es selbst)? Verglichen wird ohne Rücksicht auf
    Groß- und Kleinschreibung: auf den üblichen Dateisystemen von Windows und macOS treffen
    ``wiki/`` und ``WIKI/`` denselben Ordner - im Zweifel gilt ein Pfad lieber als „darunter“."""
    try:
        p, b = Path(pfad).resolve(), Path(basis).resolve()
    except (OSError, ValueError):
        return False
    return p.is_relative_to(b) or Path(str(p).casefold()).is_relative_to(str(b).casefold())


_ist_unter = ist_unter


def _gleich(a: Path, b: Path) -> bool:
    """Derselbe Ordner (ohne Rücksicht auf Groß- und Kleinschreibung)."""
    return _ist_unter(a, b) and _ist_unter(b, a)


_WINDOWS_PFAD = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _systemfremd(text: str) -> bool:
    """Absoluter Pfad eines anderen Betriebssystems (Projekt per Git/Stick auf einen anderen
    Rechner gebracht): ``C:\\…`` unter macOS/Linux bzw. ``/Users/…`` unter Windows."""
    windows = bool(_WINDOWS_PFAD.match(text))
    return (windows and os.name != "nt") or (text.startswith("/") and os.name == "nt")


def _als_text(pfad: Path, wurzel: Path) -> str:
    """Relativ zum Projektordner (POSIX), wenn der Pfad darin oder daneben liegt - sonst absolut.
    Der Projektordner selbst wird zu ``"."``."""
    pfad, wurzel = Path(pfad), Path(wurzel)
    if _ist_unter(pfad, wurzel.parent):
        try:
            return Path(os.path.relpath(pfad.resolve(), wurzel.resolve())).as_posix()
        except ValueError:  # anderes Laufwerk
            pass
    return str(pfad)


def _aus_text(text: str, wurzel: Path) -> Path | None:
    """Pfad aus der Projektdatei; ``None``, wenn er von einem anderen Betriebssystem stammt."""
    if _systemfremd(text):
        return None
    roh = Path(text)
    if roh.is_absolute():
        return roh
    return Path(os.path.normpath(Path(wurzel) / roh))


# --- Lesen und Schreiben ---------------------------------------------------------------------


def lade(pfad: Path | str) -> Projekt:
    """Projekt aus dem Projektordner lesen; ``pfad`` darf auch die Projektdatei selbst sein.
    Projektdateien der Version 1 (im Wiki-Ordner, ohne ``wiki_dir``) gelten weiter: dort ist
    der Wiki-Ordner der Projektordner."""
    wurzel = Path(pfad)
    if wurzel.name == PROJEKT_DATEI:
        wurzel = wurzel.parent.parent
    elif wurzel.name == PROJEKT_ORDNER:
        wurzel = wurzel.parent
    datei = projekt_datei(wurzel)
    try:
        data = json.loads(datei.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjektFehler(f"In diesem Ordner liegt kein AudioScribe-Projekt: {wurzel}") from exc
    except (OSError, ValueError) as exc:
        raise ProjektFehler(f"Projektdatei nicht lesbar: {datei} ({exc})") from exc
    if not isinstance(data, dict):
        raise ProjektFehler(f"Projektdatei hat ein unbekanntes Format: {datei}")

    def text(key: str) -> str | None:
        wert = data.get(key)
        return wert.strip() if isinstance(wert, str) and wert.strip() else None

    version = data.get("version")
    if not isinstance(version, int):
        version = 1
    hinweise: list[str] = []

    # Wiki: Version 1 kennt kein wiki_dir - dort ist der Projektordner die Wiki-Wurzel. Ab
    # Version 2 heißt null "kein Wiki". Ein Wiki wird nie geraten: ein systemfremder Pfad
    # macht das Projekt bis zur Korrektur zu einem ohne Wiki.
    wiki_dir: Path | None
    if version < 2 or "wiki_dir" not in data:
        wiki_dir = wurzel
    elif text("wiki_dir") is None:
        wiki_dir = None
    else:
        wiki_dir = _aus_text(text("wiki_dir") or "", wurzel)
        if wiki_dir is None:
            hinweise.append(
                f"Der Wiki-Ordner aus der Projektdatei ({text('wiki_dir')}) ist auf diesem Rechner nicht "
                "erreichbar – das Projekt arbeitet bis zur Korrektur in den Projekteinstellungen ohne Wiki."
            )
    seiten = wiki_dir / SEITEN_ORDNER if wiki_dir is not None else None

    # Dieselben Regeln wie beim Anlegen - die Datei kann von Hand geändert oder von einem
    # anderen Rechner gekommen sein. Unbrauchbare Ordner ersetzt der Vorschlag; der Hinweis
    # sagt es dem Nutzer, statt dass Mitschnitte stillschweigend unter wiki/ landen.
    ersatz = vorschlag(wurzel, wiki_dir)
    sitzungen = _aus_text(text("sitzungen_dir") or "", wurzel) if text("sitzungen_dir") else None
    if sitzungen is None or _gleich(sitzungen, wurzel) or (
        wiki_dir is not None and (_gleich(sitzungen, wiki_dir) or _ist_unter(sitzungen, seiten))
    ):
        hinweise.append(
            f"Der Sitzungsordner aus der Projektdatei ({text('sitzungen_dir') or 'fehlt'}) ist auf diesem "
            f"Rechner nicht verwendbar – verwendet wird {ersatz['sitzungen_dir']}. Bitte in den "
            "Projekteinstellungen prüfen."
        )
        sitzungen = Path(ersatz["sitzungen_dir"])

    assets: Path | None = None
    if wiki_dir is not None:
        assets = _aus_text(text("assets_dir") or "", wurzel) if text("assets_dir") else wiki_dir / ASSETS_VORSCHLAG
        if (
            assets is None or not _ist_unter(assets, wiki_dir) or _ist_unter(assets, seiten)
            or _gleich(assets, wiki_dir) or _gleich(assets, wiki_dir / RAW_ORDNER)
        ):
            hinweise.append(
                f"Der Bilder-Ordner aus der Projektdatei ({text('assets_dir')}) ist nicht verwendbar – "
                f"verwendet wird {ersatz['assets_dir']}."
            )
            assets = Path(ersatz["assets_dir"])

    speichern = data.get("wiki_speichern")
    return Projekt(
        wurzel=wurzel,
        name=text("name") or wurzel.name,
        sitzungen_dir=sitzungen,
        wiki_dir=wiki_dir,
        assets_dir=assets,
        hinweis=" ".join(hinweise),
        id=text("id") or "",
        erstellt=text("erstellt") or "",
        ki_dienst=text("ki_dienst"),
        souffleur_model=text("souffleur_model"),
        agent_model=text("agent_model"),
        sprache=text("sprache"),
        wiki_speichern=speichern if speichern in WIKI_SPEICHERN else WIKI_FRAGEN,
        wiki_bilder=bool(data.get("wiki_bilder", True)),
        wiki_markierungen=data.get("wiki_markierungen") is True,
    )


def speichere(projekt: Projekt) -> Path:
    """Projektdatei schreiben (atomar, immer in der aktuellen Version). Das Demo-Projekt wird
    nie gespeichert."""
    if projekt.demo:
        return projekt.datei
    data = {
        "version": VERSION,
        "id": projekt.id,
        "name": projekt.name,
        "erstellt": projekt.erstellt,
        "wiki_dir": _als_text(projekt.wiki_dir, projekt.wurzel) if projekt.wiki_dir is not None else None,
        "sitzungen_dir": _als_text(projekt.sitzungen_dir, projekt.wurzel),
        "assets_dir": _als_text(projekt.assets_dir, projekt.wurzel) if projekt.assets_dir is not None else None,
        "ki_dienst": projekt.ki_dienst,
        "souffleur_model": projekt.souffleur_model,
        "agent_model": projekt.agent_model,
        "sprache": projekt.sprache,
        "wiki_speichern": projekt.wiki_speichern,
        "wiki_bilder": projekt.wiki_bilder,
        "wiki_markierungen": projekt.wiki_markierungen,
    }
    datei = projekt.datei
    datei.parent.mkdir(parents=True, exist_ok=True)
    tmp = datei.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, datei)
    return datei


# --- Prüfen und Anlegen ----------------------------------------------------------------------


def vorschlag(wurzel: Path, wiki_dir: Path | None = None) -> dict[str, str]:
    """Vorbelegung des Assistenten: Sitzungen im Projektordner, ein neues Wiki ebenfalls,
    Bilder im Wiki unter ``raw/assets`` (nur mit Wiki)."""
    wurzel = Path(wurzel)
    return {
        "sitzungen_dir": str(wurzel / SITZUNGEN_ORDNER),
        "wiki_dir_neu": str(wurzel / WIKI_ORDNER),
        "assets_dir": str(Path(wiki_dir) / ASSETS_VORSCHLAG) if wiki_dir is not None else "",
    }


def wiki_ordner(wiki_art: str, wurzel: Path | None, wiki_dir: Path | None) -> Path | None:
    """Der Wiki-Ordner, der sich aus der Wiki-Art ergibt: keiner, der feste Unterordner für ein
    neues Wiki oder der angegebene vorhandene."""
    if wiki_art == WIKI_NEU:
        return Path(wurzel) / WIKI_ORDNER if wurzel is not None else None
    if wiki_art == WIKI_VORHANDEN:
        return Path(wiki_dir) if wiki_dir is not None else None
    return None


def pruefe(
    *,
    name: str,
    wurzel: Path | None,
    sitzungen_dir: Path | None,
    wiki_art: str = WIKI_KEINS,
    wiki_dir: Path | None = None,
    assets_dir: Path | None = None,
    neu: bool = True,
) -> dict[str, str]:
    """Angaben prüfen; liefert ``{feld: Meldung}`` - leer heißt: alles in Ordnung.

    ``neu`` unterscheidet das Anlegen (hier darf noch kein Projekt liegen) vom Ändern eines
    geöffneten Projekts. Das Wiki wird über ``souffleur.wiki.pruefe_wiki`` gelesen, nie verändert.
    """
    from audioscribe.souffleur.wiki import ZUSTAND_OK, pruefe_wiki

    fehler: dict[str, str] = {}
    if not name.strip():
        fehler["name"] = "Bitte einen Projektnamen angeben."

    if wiki_art not in WIKI_ARTEN:
        fehler["wiki_dir"] = f"Unbekannte Wiki-Art: {wiki_art}"
        wiki_art = WIKI_KEINS
    wiki = wiki_ordner(wiki_art, wurzel, wiki_dir)
    seiten = wiki / SEITEN_ORDNER if wiki is not None else None

    if wurzel is None:
        fehler["wurzel"] = "Bitte den Projektordner angeben."
    else:
        wurzel = Path(wurzel)
        try:
            if neu and ist_projekt(wurzel):
                fehler["wurzel"] = "In diesem Ordner liegt schon ein Projekt – über „Projekt öffnen“ laden."
            elif wurzel.is_file():
                fehler["wurzel"] = "Das ist eine Datei, kein Ordner."
            elif not wurzel.exists() and not wurzel.parent.is_dir():
                # Nur eine Ebene wird angelegt - ein Tippfehler soll keine Ordnerkette erzeugen.
                fehler["wurzel"] = f"Der übergeordnete Ordner fehlt: {wurzel.parent}"
            elif wiki_art == WIKI_VORHANDEN and seiten is not None and _ist_unter(wurzel, seiten):
                fehler["wurzel"] = "Der Projektordner darf nicht unter den Wiki-Seiten (wiki/) liegen."
        except OSError as exc:
            fehler["wurzel"] = f"Ordner nicht erreichbar: {exc.strerror or exc}"

    if wiki_art == WIKI_NEU and wiki is not None:
        try:
            if wiki.is_file():
                fehler["wiki_dir"] = f"Im Projektordner liegt eine Datei namens {WIKI_ORDNER}."
            elif (wiki / SEITEN_ORDNER).exists():
                # Das Gerüst legt Dateien unter wiki/ an - in ein bestehendes Wiki nie.
                fehler["wiki_dir"] = (
                    f"Im Projektordner liegt schon ein Wiki ({WIKI_ORDNER}/) – bitte „Vorhandenes Wiki verknüpfen“ wählen."
                )
        except OSError as exc:
            fehler["wiki_dir"] = f"Ordner nicht erreichbar: {exc.strerror or exc}"
    elif wiki_art == WIKI_VORHANDEN:
        if wiki is None:
            fehler["wiki_dir"] = "Bitte den Ordner des LLM-Wikis angeben."
        else:
            status = pruefe_wiki(wiki)
            if status.zustand != ZUSTAND_OK:
                fehler["wiki_dir"] = status.meldung

    if sitzungen_dir is None:
        fehler["sitzungen_dir"] = "Bitte den Ordner für Sitzungen angeben."
    else:
        sitzungen_dir = Path(sitzungen_dir)
        if wurzel is not None and _gleich(sitzungen_dir, wurzel):
            fehler["sitzungen_dir"] = "Bitte einen eigenen Ordner wählen, nicht den Projektordner selbst."
        elif wiki is not None and _ist_unter(sitzungen_dir, seiten):
            fehler["sitzungen_dir"] = "Sitzungen dürfen nicht unter wiki/ liegen – dort stehen nur die Wiki-Seiten."
        elif wiki is not None and _gleich(sitzungen_dir, wiki):
            fehler["sitzungen_dir"] = "Bitte einen eigenen Ordner wählen, nicht den Wiki-Ordner selbst."
        elif not _anlegbar(sitzungen_dir):
            fehler["sitzungen_dir"] = f"Ordner nicht anlegbar: {sitzungen_dir}"

    if wiki is not None:
        if assets_dir is None:
            fehler["assets_dir"] = "Bitte den Ordner für Bilder angeben."
        else:
            assets_dir = Path(assets_dir)
            if not _ist_unter(assets_dir, wiki) or _gleich(assets_dir, wiki):
                fehler["assets_dir"] = "Der Bilder-Ordner muss im LLM-Wiki liegen, damit die Verweise beim Umzug gültig bleiben."
            elif _ist_unter(assets_dir, seiten):
                fehler["assets_dir"] = "Bilder dürfen nicht unter wiki/ liegen – dort stehen nur die Wiki-Seiten."
            elif _gleich(assets_dir, wiki / RAW_ORDNER):
                fehler["assets_dir"] = "Bitte einen eigenen Ordner wählen (z. B. raw/assets), nicht raw/ selbst."
    return fehler


def _anlegbar(pfad: Path) -> bool:
    """Existiert der Ordner oder ein Vorfahr, in dem er angelegt werden kann?"""
    try:
        if pfad.is_dir():
            return True
        if pfad.exists():
            return False
        for eltern in pfad.parents:
            if eltern.exists():
                return eltern.is_dir()
    except OSError:
        return False
    return False


def lege_an(
    *,
    name: str,
    wurzel: Path,
    sitzungen_dir: Path,
    wiki_art: str = WIKI_KEINS,
    wiki_dir: Path | None = None,
    assets_dir: Path | None = None,
    ki_dienst: str | None = None,
    souffleur_model: str | None = None,
    agent_model: str | None = None,
    sprache: str | None = None,
    wiki_speichern: str = WIKI_FRAGEN,
    wiki_bilder: bool = True,
    wiki_markierungen: bool = False,
) -> Projekt:
    """Projekt anlegen: Angaben prüfen, den Projektordner anlegen, bei Bedarf das Wiki-Gerüst
    schreiben, Ordner und Projektdatei erzeugen. Ein vorhandenes Wiki wird dabei nicht verändert."""
    wiki = wiki_ordner(wiki_art, wurzel, wiki_dir)
    if wiki is not None and assets_dir is None:
        assets_dir = wiki / ASSETS_VORSCHLAG
    fehler = pruefe(
        name=name, wurzel=wurzel, sitzungen_dir=sitzungen_dir, wiki_art=wiki_art, wiki_dir=wiki_dir,
        assets_dir=assets_dir,
    )
    if fehler:
        raise ProjektFehler(" ".join(fehler.values()))
    wurzel = Path(wurzel)
    try:
        wurzel.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjektFehler(f"Projektordner nicht anlegbar: {exc.strerror or exc}") from exc
    if wiki_art == WIKI_NEU and wiki is not None:
        from audioscribe.projekt.vorlage import lege_wiki_an

        try:
            lege_wiki_an(wiki, name.strip())
        except OSError as exc:
            raise ProjektFehler(f"Wiki nicht anlegbar: {exc.strerror or exc}") from exc
    projekt = Projekt(
        wurzel=wurzel,
        name=name.strip(),
        sitzungen_dir=Path(sitzungen_dir),
        wiki_dir=wiki,
        assets_dir=Path(assets_dir) if wiki is not None and assets_dir is not None else None,
        id=uuid.uuid4().hex[:12],
        erstellt=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ki_dienst=ki_dienst or None,
        souffleur_model=souffleur_model or None,
        agent_model=agent_model or None,
        sprache=sprache or None,
        wiki_speichern=wiki_speichern if wiki_speichern in WIKI_SPEICHERN else WIKI_FRAGEN,
        wiki_bilder=bool(wiki_bilder),
        wiki_markierungen=bool(wiki_markierungen),
    )
    try:
        projekt.sitzungen_dir.mkdir(parents=True, exist_ok=True)
        if projekt.raw_dir is not None:
            projekt.raw_dir.mkdir(parents=True, exist_ok=True)
        speichere(projekt)
    except OSError as exc:
        raise ProjektFehler(f"Projekt nicht anlegbar: {exc.strerror or exc}") from exc
    return projekt


def aendere(projekt: Projekt, felder: dict) -> Projekt:
    """Projekteinstellungen ändern und speichern. Bei den überschreibbaren Feldern heißt
    ``None`` bzw. leer: wieder die globale Einstellung verwenden. Über ``wiki_art`` (mit
    ``wiki_dir`` bei „vorhanden“) wird ein Wiki nachträglich angelegt, verknüpft oder gelöst -
    die Dateien bleiben in jedem Fall liegen."""
    neu: dict = {}
    for key in UEBERSCHREIBBAR:
        if key in felder:
            wert = felder[key]
            if wert is not None and not isinstance(wert, str):
                raise ProjektFehler(f"Ungültiger Wert für {key}.")
            wert = wert.strip() if wert else ""
            # Die Werte wandern als argv in Kindprozesse - nur harmlose Zeichen (wie global).
            if wert and (wert.startswith("-") or not all(c.isalnum() or c in "-_.:[]" for c in wert)):
                raise ProjektFehler(f"Ungültiger Wert für {key}: {wert}")
            neu[key] = wert or None
    if isinstance(felder.get("name"), str) and felder["name"].strip():
        neu["name"] = felder["name"].strip()
    for key in ("sitzungen_dir", "assets_dir", "wiki_dir"):
        if key in felder and felder[key] not in (None, ""):
            if not isinstance(felder[key], (str, Path)):
                raise ProjektFehler(f"Ungültiger Ordner für {key}.")
            neu[key] = Path(felder[key])
    if "wiki_speichern" in felder:
        if felder["wiki_speichern"] not in WIKI_SPEICHERN:
            raise ProjektFehler(f"Unbekannte Wiki-Ablage: {felder['wiki_speichern']}")
        neu["wiki_speichern"] = felder["wiki_speichern"]
    for key in ("wiki_bilder", "wiki_markierungen"):
        if key in felder and felder[key] is not None:
            if not isinstance(felder[key], bool):
                raise ProjektFehler(f"Ungültiger Wert für {key}.")
            neu[key] = felder[key]

    # Wiki anlegen, verknüpfen oder lösen
    wiki_art = felder.get("wiki_art")
    if wiki_art is None and "wiki_dir" in neu:
        wiki_art = WIKI_VORHANDEN
    geruest = False
    if wiki_art is not None:
        if wiki_art not in WIKI_ARTEN:
            raise ProjektFehler(f"Unbekannte Wiki-Art: {wiki_art}")
        if wiki_art == WIKI_KEINS:
            neu["wiki_dir"] = None
            neu["assets_dir"] = None
        elif wiki_art == WIKI_NEU:
            neu["wiki_dir"] = projekt.wurzel / WIKI_ORDNER
            geruest = True
        elif "wiki_dir" not in neu:
            raise ProjektFehler("Bitte den Ordner des LLM-Wikis angeben.")
        wiki = neu.get("wiki_dir")
        if wiki is not None and "assets_dir" not in neu:
            # Der bisherige Bilder-Ordner gilt weiter, wenn er im neuen Wiki liegt - sonst der Vorschlag.
            bisher = projekt.assets_dir
            neu["assets_dir"] = bisher if bisher is not None and _ist_unter(bisher, wiki) else wiki / ASSETS_VORSCHLAG
    wiki_geaendert = wiki_art is not None

    geaendert = replace(projekt, **neu, hinweis="")
    if geaendert.wiki_dir is None and geaendert.assets_dir is not None:
        raise ProjektFehler("Dieses Projekt hat kein Wiki – ein Bilder-Ordner braucht ein Wiki.")
    art = WIKI_KEINS if geaendert.wiki_dir is None else (WIKI_NEU if geruest else WIKI_VORHANDEN)
    fehler = pruefe(
        name=geaendert.name, wurzel=geaendert.wurzel, sitzungen_dir=geaendert.sitzungen_dir,
        wiki_art=art, wiki_dir=geaendert.wiki_dir, assets_dir=geaendert.assets_dir, neu=False,
    )
    # Ein Wiki, das gerade nicht lesbar ist, darf das Ändern der übrigen Einstellungen nicht sperren.
    fehler.pop("wurzel", None)
    if not wiki_geaendert:
        fehler.pop("wiki_dir", None)
    if fehler:
        raise ProjektFehler(" ".join(fehler.values()))
    try:
        if geruest and geaendert.wiki_dir is not None:
            from audioscribe.projekt.vorlage import lege_wiki_an

            lege_wiki_an(geaendert.wiki_dir, geaendert.name)
        geaendert.sitzungen_dir.mkdir(parents=True, exist_ok=True)
        if geaendert.raw_dir is not None:
            geaendert.raw_dir.mkdir(parents=True, exist_ok=True)
        speichere(geaendert)
    except OSError as exc:
        raise ProjektFehler(f"Einstellungen nicht speicherbar: {exc.strerror or exc}") from exc
    return geaendert
