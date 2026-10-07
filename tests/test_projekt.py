"""Projekte (PRD §21): Projektdatei im Projektordner, Pruefung der Angaben, Wiki optional,
globale und eigene Einstellungen."""

import json
import os
from pathlib import Path

import pytest

from audioscribe.projekt import einstellungen, modell
from audioscribe.projekt.modell import Projekt, ProjektFehler


def test_anlegen_schreibt_projektdatei_in_den_projektordner_mit_relativen_pfaden(wiki, tmp_path):
    wurzel = tmp_path / "bahn-projekt"
    projekt = modell.lege_an(
        name=" Bahnbuchung ", wurzel=wurzel, sitzungen_dir=tmp_path / "bahn-sitzungen",
        wiki_art="vorhanden", wiki_dir=wiki, assets_dir=wiki / "raw" / "assets",
    )
    datei = wurzel / ".audioscribe" / "projekt.json"
    daten = json.loads(datei.read_text(encoding="utf-8"))
    assert projekt.name == "Bahnbuchung" and projekt.id and daten["version"] == 2
    # Relativ zum Projektordner: das Projekt zieht mit seinem Ordner um.
    assert daten["wiki_dir"] == "../bahn-wiki" and daten["sitzungen_dir"] == "../bahn-sitzungen"
    assert daten["assets_dir"] == "../bahn-wiki/raw/assets"
    assert wurzel.is_dir() and (tmp_path / "bahn-sitzungen").is_dir() and modell.ist_projekt(wurzel)
    assert not (wiki / ".audioscribe").exists()  # das verknuepfte Wiki bleibt unberuehrt
    geladen = modell.lade(wurzel)
    assert geladen.wiki_dir == wiki and geladen.hat_wiki
    assert geladen.sitzungen_dir == tmp_path / "bahn-sitzungen" and geladen.assets_dir == wiki / "raw" / "assets"
    assert geladen.analysen_dir == tmp_path / "bahn-sitzungen" / "analysen" and geladen.raw_dir == wiki / "raw"
    assert modell.lade(datei).wurzel == wurzel  # auch die Projektdatei selbst ist ein gueltiger Einstieg


def test_projekt_ohne_wiki_hat_keine_wiki_pfade(projekt_ohne_wiki):
    p = projekt_ohne_wiki
    assert p.hat_wiki is False and p.wiki_dir is None and p.raw_dir is None and p.seiten_dir is None
    assert p.assets_dir is None and p.sitzungen_dir == p.wurzel / "sitzungen" and p.sitzungen_dir.is_dir()
    daten = json.loads(p.datei.read_text(encoding="utf-8"))
    assert daten["wiki_dir"] is None and daten["assets_dir"] is None and daten["sitzungen_dir"] == "sitzungen"
    assert modell.lade(p.wurzel) == p
    # Ohne Wiki verlangt die Pruefung keinen Bilder-Ordner; einen zu setzen ist ein Fehler.
    assert modell.pruefe(name="x", wurzel=p.wurzel, sitzungen_dir=p.sitzungen_dir, neu=False) == {}
    with pytest.raises(ProjektFehler, match="kein Wiki"):
        modell.aendere(p, {"assets_dir": str(p.wurzel / "bilder")})


def test_altes_projekt_version_1_oeffnet_sich_mit_wiki_in_der_wurzel(wiki, tmp_path):
    """Projektdateien von vor dem Projektordner liegen im Wiki und kennen kein wiki_dir."""
    (wiki / ".audioscribe").mkdir()
    alt = {"version": 1, "id": "abc", "name": "Alt", "sitzungen_dir": "../bahn-sitzungen", "assets_dir": "raw/assets",
           "wiki_speichern": "immer"}
    (wiki / ".audioscribe" / "projekt.json").write_text(json.dumps(alt), encoding="utf-8")
    p = modell.lade(wiki)
    assert p.wurzel == wiki and p.wiki_dir == wiki and p.raw_dir == wiki / "raw" and p.hinweis == ""
    assert p.sitzungen_dir == tmp_path / "bahn-sitzungen" and p.assets_dir == wiki / "raw" / "assets"
    assert p.wiki_speichern == "immer"
    # Die erste Aenderung hebt die Datei auf Version 2 - mit "." als Wiki, inhaltlich gleich.
    modell.aendere(p, {"sprache": "en"})
    daten = json.loads(p.datei.read_text(encoding="utf-8"))
    assert daten["version"] == 2 and daten["wiki_dir"] == "." and daten["assets_dir"] == "raw/assets"
    wieder = modell.lade(wiki)
    assert wieder.wiki_dir == wiki and wieder.sprache == "en" and wieder.sitzungen_dir == p.sitzungen_dir


def test_neues_wiki_im_projektordner(tmp_path):
    from audioscribe.souffleur.wiki import ZUSTAND_OK, pruefe_wiki

    wurzel = tmp_path / "neu"
    p = modell.lege_an(name="Neu", wurzel=wurzel, sitzungen_dir=wurzel / "sitzungen", wiki_art="neu")
    assert p.wiki_dir == wurzel / "llm-wiki" and (wurzel / "llm-wiki" / "wiki" / "index.md").is_file()
    assert p.assets_dir == wurzel / "llm-wiki" / "raw" / "assets" and p.raw_dir.is_dir()
    daten = json.loads(p.datei.read_text(encoding="utf-8"))
    assert daten["wiki_dir"] == "llm-wiki" and daten["assets_dir"] == "llm-wiki/raw/assets"
    assert pruefe_wiki(p.wiki_dir).zustand == ZUSTAND_OK
    # Ein zweites "neu" in denselben Projektordner: dort liegt schon ein Wiki.
    fehler = modell.pruefe(name="x", wurzel=wurzel, sitzungen_dir=wurzel / "s", wiki_art="neu", neu=False)
    assert "Vorhandenes Wiki" in fehler["wiki_dir"]


def test_projektordner_wird_angelegt_und_geprueft(wiki, tmp_path):
    ok = dict(name="P", wurzel=tmp_path / "neu" , sitzungen_dir=tmp_path / "neu" / "sitzungen")
    assert modell.pruefe(**ok) == {}  # der Ordner fehlt noch, der Elternordner ist da
    assert "übergeordnete" in modell.pruefe(**{**ok, "wurzel": tmp_path / "fehlt" / "neu"})["wurzel"]
    (tmp_path / "datei.txt").write_text("x", encoding="utf-8")
    assert "Datei" in modell.pruefe(**{**ok, "wurzel": tmp_path / "datei.txt"})["wurzel"]
    # Unter den Wiki-Seiten darf kein Projekt entstehen.
    fehler = modell.pruefe(**{**ok, "wurzel": wiki / "wiki" / "p"}, wiki_art="vorhanden", wiki_dir=wiki,
                           assets_dir=wiki / "raw" / "assets")
    assert "Wiki-Seiten" in fehler["wurzel"]
    # Das Wiki selbst als Projektordner ist erlaubt (so sahen Projekte frueher aus).
    fehler = modell.pruefe(**{**ok, "wurzel": wiki}, wiki_art="vorhanden", wiki_dir=wiki, assets_dir=wiki / "raw" / "assets")
    assert fehler == {}


def test_wiki_spaeter_anlegen_verknuepfen_und_loesen(projekt_ohne_wiki, wiki):
    p = projekt_ohne_wiki
    mit = modell.aendere(p, {"wiki_art": "vorhanden", "wiki_dir": str(wiki)})
    assert mit.wiki_dir == wiki and mit.assets_dir == wiki / "raw" / "assets"
    assert modell.lade(p.wurzel).wiki_dir == wiki
    with pytest.raises(ProjektFehler):
        modell.aendere(p, {"wiki_art": "vorhanden", "wiki_dir": str(p.wurzel / "nix")})
    with pytest.raises(ProjektFehler):
        modell.aendere(p, {"wiki_art": "vorhanden"})
    ohne = modell.aendere(mit, {"wiki_art": "keins"})
    assert ohne.wiki_dir is None and ohne.assets_dir is None and modell.lade(p.wurzel).hat_wiki is False
    assert (wiki / "wiki" / "index.md").is_file()  # loesen loescht nichts
    neu = modell.aendere(ohne, {"wiki_art": "neu"})
    assert neu.wiki_dir == p.wurzel / "llm-wiki" and (neu.wiki_dir / "wiki" / "index.md").is_file()
    assert neu.assets_dir == neu.wiki_dir / "raw" / "assets" and neu.raw_dir.is_dir()
    with pytest.raises(ProjektFehler):
        modell.aendere(neu, {"wiki_art": "neu"})  # liegt schon da
    with pytest.raises(ProjektFehler):
        modell.aendere(neu, {"wiki_art": "sonstwas"})


def test_systemfremder_wiki_pfad_ergibt_projekt_ohne_wiki_mit_hinweis(projekt):
    daten = json.loads(projekt.datei.read_text(encoding="utf-8"))
    fremd = "/Users/m/wiki" if os.name == "nt" else "C:\\Users\\m\\wiki"
    projekt.datei.write_text(json.dumps({**daten, "wiki_dir": fremd}), encoding="utf-8")
    p = modell.lade(projekt.wurzel)
    assert p.wiki_dir is None and p.assets_dir is None and "Wiki-Ordner" in p.hinweis
    assert p.sitzungen_dir == projekt.sitzungen_dir


def test_laden_ohne_projekt_meldet_verstaendlich(tmp_path):
    with pytest.raises(ProjektFehler, match="kein AudioScribe-Projekt"):
        modell.lade(tmp_path)
    (tmp_path / ".audioscribe").mkdir()
    (tmp_path / ".audioscribe" / "projekt.json").write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ProjektFehler, match="nicht lesbar"):
        modell.lade(tmp_path)


def test_pruefung_je_feld(wiki, tmp_path):
    ok = dict(name="P", wurzel=tmp_path / "p", sitzungen_dir=tmp_path / "s", wiki_art="vorhanden", wiki_dir=wiki,
              assets_dir=wiki / "raw" / "assets")
    assert modell.pruefe(**ok) == {}
    assert "name" in modell.pruefe(**{**ok, "name": "  "})
    assert "wurzel" in modell.pruefe(**{**ok, "wurzel": None})
    assert "wiki_dir" in modell.pruefe(**{**ok, "wiki_dir": None})
    # Kein Wiki in dem Ordner: die Meldung kommt aus der Wiki-Pruefung des Souffleurs.
    assert "wiki_dir" in modell.pruefe(**{**ok, "wiki_dir": tmp_path / "leer"})
    assert "wiki_dir" in modell.pruefe(**{**ok, "wiki_art": "sonstwas"})
    # Unter wiki/ stehen nur die Seiten - dort landet nichts von uns.
    assert "sitzungen_dir" in modell.pruefe(**{**ok, "sitzungen_dir": wiki / "wiki" / "sitzungen"})
    assert "sitzungen_dir" in modell.pruefe(**{**ok, "sitzungen_dir": wiki})
    assert "sitzungen_dir" in modell.pruefe(**{**ok, "sitzungen_dir": tmp_path / "p"})
    assert "assets_dir" in modell.pruefe(**{**ok, "assets_dir": wiki / "wiki" / "bilder"})
    assert "assets_dir" in modell.pruefe(**{**ok, "assets_dir": tmp_path / "ausserhalb"})
    assert "assets_dir" in modell.pruefe(**{**ok, "assets_dir": None})
    # Ohne Wiki spielt der Bilder-Ordner keine Rolle.
    assert modell.pruefe(**{**ok, "wiki_art": "keins", "wiki_dir": None, "assets_dir": None}) == {}


def test_zweites_projekt_im_selben_ordner_wird_abgewiesen(projekt, tmp_path):
    fehler = modell.pruefe(name="X", wurzel=projekt.wurzel, sitzungen_dir=tmp_path / "s2")
    assert "Projekt öffnen" in fehler["wurzel"]
    with pytest.raises(ProjektFehler):
        modell.lege_an(name="X", wurzel=projekt.wurzel, sitzungen_dir=tmp_path / "s2")


def test_neues_wiki_bekommt_geruest_und_ist_sofort_lesbar(tmp_path):
    from audioscribe.souffleur.wiki import ZUSTAND_OK, pruefe_wiki

    wurzel = tmp_path / "neues-projekt"
    projekt = modell.lege_an(name="Neu", wurzel=wurzel, sitzungen_dir=tmp_path / "neu-sitzungen", wiki_art="neu")
    wiki = wurzel / "llm-wiki"
    assert (wiki / "raw").is_dir() and (wiki / "wiki" / "index.md").is_file()
    status = pruefe_wiki(projekt.wiki_dir)
    assert status.zustand == ZUSTAND_OK and status.seiten >= 3
    # Die Projektdatei liegt im Projektordner, nicht im Wiki.
    assert (wurzel / ".audioscribe" / "projekt.json").is_file() and not (wiki / ".audioscribe").exists()


def test_neues_wiki_nie_in_ein_bestehendes_wiki(wiki, tmp_path):
    """Das Geruest legt Dateien unter wiki/ an - in ein vorhandenes Wiki darf das nie geschehen."""
    vorher = sorted(p.name for p in (wiki / "wiki").iterdir())
    # Ein Projektordner, in dem unter llm-wiki/ schon ein Wiki liegt
    wurzel = tmp_path / "p"
    (wurzel / "llm-wiki" / "wiki").mkdir(parents=True)
    (wurzel / "llm-wiki" / "wiki" / "index.md").write_text("# Da\n", encoding="utf-8")
    ok = dict(name="P", wurzel=wurzel, sitzungen_dir=tmp_path / "s", wiki_art="neu")
    assert "Vorhandenes Wiki" in modell.pruefe(**ok)["wiki_dir"]
    with pytest.raises(ProjektFehler):
        modell.lege_an(**ok)
    assert [p.name for p in (wurzel / "llm-wiki" / "wiki").iterdir()] == ["index.md"] and not modell.ist_projekt(wurzel)
    # raw/ selbst ist kein Bilder-Ordner: Ablage und Bilder bekaemen denselben Ordnernamen.
    mit = dict(name="P", wurzel=tmp_path / "q", sitzungen_dir=tmp_path / "s", wiki_art="vorhanden", wiki_dir=wiki)
    assert "assets_dir" in modell.pruefe(**mit, assets_dir=wiki / "raw")
    # Gross-/Kleinschreibung: WIKI/ trifft unter Windows und macOS denselben Ordner wie wiki/.
    assert "sitzungen_dir" in modell.pruefe(**{**mit, "sitzungen_dir": wiki / "WIKI" / "sitzungen"}, assets_dir=wiki / "raw" / "assets")
    assert sorted(p.name for p in (wiki / "wiki").iterdir()) == vorher


def test_laden_prueft_ordner_aus_der_projektdatei(projekt, tmp_path):
    """Von Hand geaendert oder von einem anderen Rechner: unbrauchbare Ordner ersetzt der Vorschlag."""
    datei = projekt.datei
    daten = json.loads(datei.read_text(encoding="utf-8"))
    fremd = "/Users/m/sitzungen" if os.name == "nt" else "C:\\Users\\m\\sitzungen"
    for sitzungen in ("../bahn-wiki/wiki/sitzungen", "../bahn-wiki/raw/../wiki/y", ".", "../bahn-wiki", fremd):
        datei.write_text(json.dumps({**daten, "sitzungen_dir": sitzungen}), encoding="utf-8")
        geladen = modell.lade(projekt.wurzel)
        assert geladen.sitzungen_dir == projekt.wurzel / "sitzungen", sitzungen
        assert "Sitzungsordner" in geladen.hinweis
    for assets in ("../bahn-wiki/wiki/bilder", "../draussen", "../bahn-wiki/raw", "../bahn-wiki", "."):
        datei.write_text(json.dumps({**daten, "assets_dir": assets}), encoding="utf-8")
        geladen = modell.lade(projekt.wurzel)
        assert geladen.assets_dir == projekt.wiki_dir / "raw" / "assets" and "Bilder-Ordner" in geladen.hinweis, assets
    datei.write_text(json.dumps(daten), encoding="utf-8")
    assert modell.lade(projekt.wurzel).hinweis == ""


def test_markierungen_ins_wiki_sind_vorgabe_aus_und_werden_gemerkt(projekt):
    assert projekt.wiki_markierungen is False and modell.lade(projekt.wurzel).wiki_markierungen is False
    # Aeltere Projektdateien kennen das Feld nicht: es bleibt bei "nein".
    daten = json.loads(projekt.datei.read_text(encoding="utf-8"))
    assert daten["wiki_markierungen"] is False
    del daten["wiki_markierungen"]
    projekt.datei.write_text(json.dumps(daten), encoding="utf-8")
    assert modell.lade(projekt.wurzel).wiki_markierungen is False
    modell.aendere(projekt, {"wiki_markierungen": True})
    assert modell.lade(projekt.wurzel).wiki_markierungen is True


def test_aendern_weist_falsche_typen_und_werte_ab(projekt):
    for felder in ({"sitzungen_dir": 123}, {"assets_dir": ["x"]}, {"wiki_bilder": "false"}, {"sprache": "--help x"},
                   {"agent_model": 5}, {"wiki_speichern": "manchmal"}, {"wiki_markierungen": 1}):
        with pytest.raises(ProjektFehler):
            modell.aendere(projekt, felder)
    assert modell.lade(projekt.wurzel) == projekt  # nichts davon wurde gespeichert


def test_vorhandenes_wiki_bleibt_beim_anlegen_unveraendert(wiki, tmp_path):
    vorher = {p: p.read_bytes() for p in wiki.rglob("*") if p.is_file()}
    modell.lege_an(name="P", wurzel=tmp_path / "p", sitzungen_dir=tmp_path / "s", wiki_art="vorhanden", wiki_dir=wiki)
    nachher = {p: p.read_bytes() for p in wiki.rglob("*") if p.is_file()}
    assert nachher == vorher and not (wiki / ".audioscribe").exists()
    # Das Wiki selbst als Projektordner (wie frueher): nur .audioscribe/ kommt dazu.
    modell.lege_an(name="P", wurzel=wiki, sitzungen_dir=tmp_path / "s2", wiki_art="vorhanden", wiki_dir=wiki)
    nachher = {p: p.read_bytes() for p in wiki.rglob("*") if p.is_file() and ".audioscribe" not in p.parts}
    assert nachher == vorher
    assert json.loads(modell.projekt_datei(wiki).read_text(encoding="utf-8"))["wiki_dir"] == "."


def test_aendern_setzt_und_loest_ueberschreibungen(projekt):
    neu = modell.aendere(projekt, {"sprache": "en", "agent_model": " claude-sonnet-5 ", "wiki_speichern": "immer"})
    assert neu.sprache == "en" and neu.agent_model == "claude-sonnet-5" and neu.wiki_speichern == "immer"
    assert modell.lade(projekt.wurzel).sprache == "en"
    # None bzw. leer heisst: wieder die globale Einstellung
    zurueck = modell.aendere(neu, {"sprache": None, "agent_model": ""})
    assert zurueck.sprache is None and zurueck.agent_model is None and zurueck.wiki_speichern == "immer"
    with pytest.raises(ProjektFehler):
        modell.aendere(zurueck, {"assets_dir": str(projekt.wiki_dir / "wiki" / "bilder")})


def test_effektive_einstellungen_projekt_schlaegt_global(projekt):
    stand = {"souffleur_model": "claude-opus-5", "sprache": "en"}
    eff = einstellungen.effektiv(stand, projekt)
    assert eff["souffleur_model"] == "claude-opus-5" and eff["sprache"] == "en"
    assert set(eff.herkunft.values()) == {"global"}
    eigen = modell.aendere(projekt, {"sprache": "de"})
    eff = einstellungen.effektiv(stand, eigen)
    assert eff["sprache"] == "de" and eff.herkunft["sprache"] == "projekt" and eff.herkunft["souffleur_model"] == "global"
    # Ohne Projekt gelten die globalen Werte; ohne Stand die Vorgaben aus der Umgebung.
    from audioscribe.config import settings

    assert einstellungen.effektiv({}, None)["agent_model"] == settings.agent_model
    assert einstellungen.als_state({"ki_dienst": "claude-agent", "sprache": "auto"}) == {
        "souffleur_backend": "claude-agent", "sprache": "auto",
    }


def test_optionen_behalten_unbekannten_wert_waehlbar():
    opt = einstellungen.optionen({"souffleur_backend": "attrappe"})
    assert opt["ki_dienste"][0]["id"] == "attrappe"
    assert any(d["label"] == "Claude (Agent SDK)" for d in opt["ki_dienste"])
    assert {s["id"] for s in opt["sprachen"]} >= {"de", "en", "auto"}


def test_zuletzt_geoeffnete_projekte_im_einstellungsstand(tmp_path):
    from audioscribe.ui import state

    state.merke_projekt(tmp_path / "a", "A", tmp_path)
    state.merke_projekt(tmp_path / "b", "B", tmp_path)
    state.merke_projekt(tmp_path / "a", "A neu", tmp_path)
    liste = state.load_state(tmp_path)["zuletzt_projekte"]
    assert [e["name"] for e in liste] == ["A neu", "B"]  # juengstes zuerst, keine Dublette
    state.vergiss_projekt(tmp_path / "b", tmp_path)
    assert [e["name"] for e in state.load_state(tmp_path)["zuletzt_projekte"]] == ["A neu"]
    # Kaputte Eintraege duerfen die Oberflaeche nicht lahmlegen.
    state.save_state({"zuletzt_projekte": ["x", {"name": "ohne pfad"}, {"pfad": str(tmp_path)}]}, tmp_path)
    assert state.load_state(tmp_path)["zuletzt_projekte"] == [{"pfad": str(tmp_path)}]


def test_demo_projekt_wird_nie_gespeichert(tmp_path):
    demo = Projekt(wurzel=tmp_path, name="Demo", sitzungen_dir=tmp_path / "s", assets_dir=tmp_path / "a", demo=True)
    modell.speichere(demo)
    assert not (tmp_path / ".audioscribe").exists()
    assert Path(demo.datei).name == "projekt.json"
