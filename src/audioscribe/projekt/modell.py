"""Das Projekt und seine Datei im LLM-Wiki-Ordner.

Die Projektdatei liegt im Wiki selbst (``<wiki>/.audioscribe/projekt.json``): das Projekt
wandert mit dem Wiki mit (anderer Rechner, Git), und der Punktordner wird vom Wiki-Index
übersprungen (``souffleur/wiki.py``). Pfade stehen relativ zur Wiki-Wurzel in der Datei, wo
das geht - ein Wiki unter ``C:\\Users\\…`` öffnet sich so auch unter ``/Users/…``.
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
VERSION = 1

RAW_ORDNER = "raw"
SEITEN_ORDNER = "wiki"
ASSETS_VORSCHLAG = "raw/assets"
ANALYSEN_ORDNER = "analysen"

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
    wurzel: Path  # LLM-Wiki-Ordner (mit raw/ und wiki/)
    name: str
    sitzungen_dir: Path  # Live-Mitschnitte und Analysen
    assets_dir: Path  # Bilder der ins Wiki gespeicherten Sitzungen
    id: str = ""
    erstellt: str = ""
    ki_dienst: str | None = None
    souffleur_model: str | None = None
    agent_model: str | None = None
    sprache: str | None = None
    wiki_speichern: str = WIKI_FRAGEN
    wiki_bilder: bool = True
    # Demo-Projekt: liegt nicht auf der Platte, wird nie gespeichert (ui/kontext.py).
    demo: bool = False
    # Hinweis vom Laden (nicht gespeichert): z. B. ein Ordner aus der Projektdatei war auf
    # diesem Rechner nicht brauchbar und wurde durch den Vorschlag ersetzt.
    hinweis: str = ""

    @property
    def raw_dir(self) -> Path:
        return self.wurzel / RAW_ORDNER

    @property
    def seiten_dir(self) -> Path:
        return self.wurzel / SEITEN_ORDNER

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

_WINDOWS_PFAD = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _systemfremd(text: str) -> bool:
    """Absoluter Pfad eines anderen Betriebssystems (Projekt per Git/Stick auf einen anderen
    Rechner gebracht): ``C:\\…`` unter macOS/Linux bzw. ``/Users/…`` unter Windows."""
    windows = bool(_WINDOWS_PFAD.match(text))
    return (windows and os.name != "nt") or (text.startswith("/") and os.name == "nt")


def _als_text(pfad: Path, wurzel: Path) -> str:
    """Relativ zur Wurzel (POSIX), wenn der Pfad im Wiki oder daneben liegt - sonst absolut."""
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
    """Projekt aus dem Wiki-Ordner lesen; ``pfad`` darf auch die Projektdatei selbst sein."""
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

    # Dieselben Regeln wie beim Anlegen - die Datei kann von Hand geändert oder von einem
    # anderen Rechner gekommen sein. Unbrauchbare Ordner ersetzt der Vorschlag; der Hinweis
    # sagt es dem Nutzer, statt dass Mitschnitte stillschweigend unter wiki/ landen.
    ersatz = vorschlag(wurzel)
    hinweise: list[str] = []
    seiten = wurzel / SEITEN_ORDNER
    sitzungen = _aus_text(text("sitzungen_dir") or "", wurzel) if text("sitzungen_dir") else None
    if sitzungen is None or ist_unter(sitzungen, seiten) or sitzungen.resolve() == wurzel.resolve():
        hinweise.append(
            f"Der Sitzungsordner aus der Projektdatei ({text('sitzungen_dir') or 'fehlt'}) ist auf diesem "
            f"Rechner nicht verwendbar – verwendet wird {ersatz['sitzungen_dir']}. Bitte in den "
            "Projekteinstellungen prüfen."
        )
        sitzungen = Path(ersatz["sitzungen_dir"])
    assets = _aus_text(text("assets_dir") or ASSETS_VORSCHLAG, wurzel)
    if (
        assets is None or not ist_unter(assets, wurzel) or ist_unter(assets, seiten)
        or assets.resolve() in (wurzel.resolve(), (wurzel / RAW_ORDNER).resolve())
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
    )


def speichere(projekt: Projekt) -> Path:
    """Projektdatei schreiben (atomar). Das Demo-Projekt wird nie gespeichert."""
    if projekt.demo:
        return projekt.datei
    data = {
        "version": VERSION,
        "id": projekt.id,
        "name": projekt.name,
        "erstellt": projekt.erstellt,
        "sitzungen_dir": _als_text(projekt.sitzungen_dir, projekt.wurzel),
        "assets_dir": _als_text(projekt.assets_dir, projekt.wurzel),
        "ki_dienst": projekt.ki_dienst,
        "souffleur_model": projekt.souffleur_model,
        "agent_model": projekt.agent_model,
        "sprache": projekt.sprache,
        "wiki_speichern": projekt.wiki_speichern,
        "wiki_bilder": projekt.wiki_bilder,
    }
    datei = projekt.datei
    datei.parent.mkdir(parents=True, exist_ok=True)
    tmp = datei.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, datei)
    return datei


# --- Prüfen und Anlegen ----------------------------------------------------------------------


def vorschlag(wurzel: Path) -> dict[str, str]:
    """Vorbelegung des Assistenten: Sitzungen neben dem Wiki (Mitschnitte sind groß und gehören
    selten in ein Wiki-Repository), Bilder im Wiki unter ``raw/assets``."""
    wurzel = Path(wurzel)
    return {
        "sitzungen_dir": str(wurzel.parent / f"{wurzel.name}-sitzungen"),
        "assets_dir": str(wurzel / ASSETS_VORSCHLAG),
    }


def pruefe(
    *,
    name: str,
    wurzel: Path | None,
    sitzungen_dir: Path | None,
    assets_dir: Path | None,
    neues_wiki: bool = False,
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

    if wurzel is None:
        fehler["wurzel"] = "Bitte den Ordner des LLM-Wikis angeben."
    else:
        wurzel = Path(wurzel)
        if neu and ist_projekt(wurzel):
            fehler["wurzel"] = "In diesem Ordner liegt schon ein Projekt – über „Projekt öffnen“ laden."
        elif neues_wiki:
            try:
                if wurzel.is_file():
                    fehler["wurzel"] = "Das ist eine Datei, kein Ordner."
                elif (wurzel / SEITEN_ORDNER).exists():
                    # Das Gerüst legt Dateien unter wiki/ an - in ein bestehendes Wiki nie.
                    fehler["wurzel"] = "Hier liegt schon ein Wiki – bitte „Vorhandenes Wiki verknüpfen“ wählen."
                elif not wurzel.exists() and not wurzel.parent.is_dir():
                    fehler["wurzel"] = f"Der übergeordnete Ordner fehlt: {wurzel.parent}"
            except OSError as exc:
                fehler["wurzel"] = f"Ordner nicht erreichbar: {exc.strerror or exc}"
        else:
            status = pruefe_wiki(wurzel)
            if status.zustand != ZUSTAND_OK:
                fehler["wurzel"] = status.meldung

    seiten = Path(wurzel) / SEITEN_ORDNER if wurzel is not None else None

    if sitzungen_dir is None:
        fehler["sitzungen_dir"] = "Bitte den Ordner für Sitzungen angeben."
    elif wurzel is not None:
        sitzungen_dir = Path(sitzungen_dir)
        if _ist_unter(sitzungen_dir, seiten):
            fehler["sitzungen_dir"] = "Sitzungen dürfen nicht unter wiki/ liegen – dort stehen nur die Wiki-Seiten."
        elif sitzungen_dir.resolve() == Path(wurzel).resolve():
            fehler["sitzungen_dir"] = "Bitte einen eigenen Ordner wählen, nicht den Wiki-Ordner selbst."
        elif not _anlegbar(sitzungen_dir):
            fehler["sitzungen_dir"] = f"Ordner nicht anlegbar: {sitzungen_dir}"

    if assets_dir is None:
        fehler["assets_dir"] = "Bitte den Ordner für Bilder angeben."
    elif wurzel is not None:
        assets_dir = Path(assets_dir)
        if not _ist_unter(assets_dir, wurzel) or assets_dir.resolve() == Path(wurzel).resolve():
            fehler["assets_dir"] = "Der Bilder-Ordner muss im LLM-Wiki liegen, damit die Verweise beim Umzug gültig bleiben."
        elif _ist_unter(assets_dir, seiten):
            fehler["assets_dir"] = "Bilder dürfen nicht unter wiki/ liegen – dort stehen nur die Wiki-Seiten."
        elif assets_dir.resolve() == (Path(wurzel) / RAW_ORDNER).resolve():
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
    assets_dir: Path,
    neues_wiki: bool = False,
    ki_dienst: str | None = None,
    souffleur_model: str | None = None,
    agent_model: str | None = None,
    sprache: str | None = None,
    wiki_speichern: str = WIKI_FRAGEN,
    wiki_bilder: bool = True,
) -> Projekt:
    """Projekt anlegen: Angaben prüfen, bei Bedarf das Wiki-Gerüst schreiben, Ordner und
    Projektdatei erzeugen. Ein vorhandenes Wiki wird dabei nicht verändert."""
    fehler = pruefe(
        name=name, wurzel=wurzel, sitzungen_dir=sitzungen_dir, assets_dir=assets_dir, neues_wiki=neues_wiki
    )
    if fehler:
        raise ProjektFehler(" ".join(fehler.values()))
    wurzel = Path(wurzel)
    if neues_wiki:
        from audioscribe.projekt.vorlage import lege_wiki_an

        try:
            lege_wiki_an(wurzel, name.strip())
        except OSError as exc:
            raise ProjektFehler(f"Wiki nicht anlegbar: {exc.strerror or exc}") from exc
    projekt = Projekt(
        wurzel=wurzel,
        name=name.strip(),
        sitzungen_dir=Path(sitzungen_dir),
        assets_dir=Path(assets_dir),
        id=uuid.uuid4().hex[:12],
        erstellt=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ki_dienst=ki_dienst or None,
        souffleur_model=souffleur_model or None,
        agent_model=agent_model or None,
        sprache=sprache or None,
        wiki_speichern=wiki_speichern if wiki_speichern in WIKI_SPEICHERN else WIKI_FRAGEN,
        wiki_bilder=bool(wiki_bilder),
    )
    try:
        projekt.sitzungen_dir.mkdir(parents=True, exist_ok=True)
        projekt.raw_dir.mkdir(parents=True, exist_ok=True)
        speichere(projekt)
    except OSError as exc:
        raise ProjektFehler(f"Projekt nicht anlegbar: {exc.strerror or exc}") from exc
    return projekt


def aendere(projekt: Projekt, felder: dict) -> Projekt:
    """Projekteinstellungen ändern und speichern. Bei den überschreibbaren Feldern heißt
    ``None`` bzw. leer: wieder die globale Einstellung verwenden."""
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
    for key in ("sitzungen_dir", "assets_dir"):
        if key in felder and felder[key] not in (None, ""):
            if not isinstance(felder[key], (str, Path)):
                raise ProjektFehler(f"Ungültiger Ordner für {key}.")
            neu[key] = Path(felder[key])
    if "wiki_speichern" in felder:
        if felder["wiki_speichern"] not in WIKI_SPEICHERN:
            raise ProjektFehler(f"Unbekannte Wiki-Ablage: {felder['wiki_speichern']}")
        neu["wiki_speichern"] = felder["wiki_speichern"]
    if "wiki_bilder" in felder and felder["wiki_bilder"] is not None:
        if not isinstance(felder["wiki_bilder"], bool):
            raise ProjektFehler("Ungültiger Wert für wiki_bilder.")
        neu["wiki_bilder"] = felder["wiki_bilder"]
    geaendert = replace(projekt, **neu, hinweis="")
    fehler = pruefe(
        name=geaendert.name, wurzel=geaendert.wurzel, sitzungen_dir=geaendert.sitzungen_dir,
        assets_dir=geaendert.assets_dir, neu=False,
    )
    # Ein Wiki, das gerade nicht lesbar ist, darf das Ändern der übrigen Einstellungen nicht sperren.
    fehler.pop("wurzel", None)
    if fehler:
        raise ProjektFehler(" ".join(fehler.values()))
    try:
        geaendert.sitzungen_dir.mkdir(parents=True, exist_ok=True)
        speichere(geaendert)
    except OSError as exc:
        raise ProjektFehler(f"Einstellungen nicht speicherbar: {exc.strerror or exc}") from exc
    return geaendert
