"""Projekte (PRD §21): Projektdatei im Wiki, Pruefung der Angaben, globale und eigene Einstellungen."""

import json
import os
from pathlib import Path

import pytest

from audioscribe.projekt import einstellungen, modell
from audioscribe.projekt.modell import Projekt, ProjektFehler


def test_anlegen_schreibt_projektdatei_ins_wiki_mit_relativen_pfaden(wiki, tmp_path):
    projekt = modell.lege_an(
        name=" Bahnbuchung ", wurzel=wiki, sitzungen_dir=tmp_path / "bahn-sitzungen", assets_dir=wiki / "raw" / "assets"
    )
    datei = wiki / ".audioscribe" / "projekt.json"
    daten = json.loads(datei.read_text(encoding="utf-8"))
    assert projekt.name == "Bahnbuchung" and projekt.id and daten["version"] == 1
    # Relativ zur Wiki-Wurzel: das Projekt zieht mit dem Wiki um.
    assert daten["sitzungen_dir"] == "../bahn-sitzungen" and daten["assets_dir"] == "raw/assets"
    assert (tmp_path / "bahn-sitzungen").is_dir() and modell.ist_projekt(wiki)
    geladen = modell.lade(wiki)
    assert geladen.sitzungen_dir == tmp_path / "bahn-sitzungen" and geladen.assets_dir == wiki / "raw" / "assets"
    assert geladen.analysen_dir == tmp_path / "bahn-sitzungen" / "analysen" and geladen.raw_dir == wiki / "raw"
    assert modell.lade(datei).wurzel == wiki  # auch die Projektdatei selbst ist ein gueltiger Einstieg


def test_laden_ohne_projekt_meldet_verstaendlich(tmp_path):
    with pytest.raises(ProjektFehler, match="kein AudioScribe-Projekt"):
        modell.lade(tmp_path)
    (tmp_path / ".audioscribe").mkdir()
    (tmp_path / ".audioscribe" / "projekt.json").write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ProjektFehler, match="nicht lesbar"):
        modell.lade(tmp_path)


def test_pruefung_je_feld(wiki, tmp_path):
    ok = dict(name="P", wurzel=wiki, sitzungen_dir=tmp_path / "s", assets_dir=wiki / "raw" / "assets")
    assert modell.pruefe(**ok) == {}
    assert "name" in modell.pruefe(**{**ok, "name": "  "})
    assert "wurzel" in modell.pruefe(**{**ok, "wurzel": None})
    # Kein Wiki: die Meldung kommt aus der Wiki-Pruefung des Souffleurs.
    assert "wurzel" in modell.pruefe(**{**ok, "wurzel": tmp_path / "leer"})
    # Unter wiki/ stehen nur die Seiten - dort landet nichts von uns.
    assert "sitzungen_dir" in modell.pruefe(**{**ok, "sitzungen_dir": wiki / "wiki" / "sitzungen"})
    assert "sitzungen_dir" in modell.pruefe(**{**ok, "sitzungen_dir": wiki})
    assert "assets_dir" in modell.pruefe(**{**ok, "assets_dir": wiki / "wiki" / "bilder"})
    assert "assets_dir" in modell.pruefe(**{**ok, "assets_dir": tmp_path / "ausserhalb"})


def test_zweites_projekt_im_selben_wiki_wird_abgewiesen(projekt, tmp_path):
    fehler = modell.pruefe(name="X", wurzel=projekt.wurzel, sitzungen_dir=tmp_path / "s2", assets_dir=projekt.assets_dir)
    assert "Projekt öffnen" in fehler["wurzel"]
    with pytest.raises(ProjektFehler):
        modell.lege_an(name="X", wurzel=projekt.wurzel, sitzungen_dir=tmp_path / "s2", assets_dir=projekt.assets_dir)


def test_neues_wiki_bekommt_geruest_und_ist_sofort_lesbar(tmp_path):
    from audioscribe.souffleur.wiki import ZUSTAND_OK, pruefe_wiki

    wurzel = tmp_path / "neues-wiki"
    projekt = modell.lege_an(
        name="Neu", wurzel=wurzel, sitzungen_dir=tmp_path / "neu-sitzungen", assets_dir=wurzel / "raw" / "assets",
        neues_wiki=True,
    )
    assert (wurzel / "raw").is_dir() and (wurzel / "wiki" / "index.md").is_file()
    status = pruefe_wiki(projekt.wurzel)
    assert status.zustand == ZUSTAND_OK and status.seiten >= 3
    # Die Projektdatei im Punktordner zaehlt nicht als Wiki-Seite.
    assert not any(".audioscribe" in a for a in [str(p) for p in (wurzel / "wiki").rglob("*")])


def test_neues_wiki_nie_in_ein_bestehendes_wiki(wiki, tmp_path):
    """Das Geruest legt Dateien unter wiki/ an - in ein vorhandenes Wiki darf das nie geschehen."""
    vorher = sorted(p.name for p in (wiki / "wiki").iterdir())
    ok = dict(name="P", wurzel=wiki, sitzungen_dir=tmp_path / "s", assets_dir=wiki / "raw" / "assets")
    assert "Vorhandenes Wiki" in modell.pruefe(**ok, neues_wiki=True)["wurzel"]
    with pytest.raises(ProjektFehler):
        modell.lege_an(**ok, neues_wiki=True)
    assert sorted(p.name for p in (wiki / "wiki").iterdir()) == vorher and not modell.ist_projekt(wiki)
    # raw/ selbst ist kein Bilder-Ordner: Ablage und Bilder bekaemen denselben Ordnernamen.
    assert "assets_dir" in modell.pruefe(**{**ok, "assets_dir": wiki / "raw"})
    # Gross-/Kleinschreibung: WIKI/ trifft unter Windows und macOS denselben Ordner wie wiki/.
    assert "sitzungen_dir" in modell.pruefe(**{**ok, "sitzungen_dir": wiki / "WIKI" / "sitzungen"})


def test_laden_prueft_ordner_aus_der_projektdatei(projekt, tmp_path):
    """Von Hand geaendert oder von einem anderen Rechner: unbrauchbare Ordner ersetzt der Vorschlag."""
    datei = projekt.datei
    daten = json.loads(datei.read_text(encoding="utf-8"))
    fremd = "/Users/m/sitzungen" if os.name == "nt" else "C:\\Users\\m\\sitzungen"
    for sitzungen in ("wiki/sitzungen", "raw/../wiki/y", ".", fremd):
        datei.write_text(json.dumps({**daten, "sitzungen_dir": sitzungen}), encoding="utf-8")
        geladen = modell.lade(projekt.wurzel)
        assert geladen.sitzungen_dir == projekt.wurzel.parent / f"{projekt.wurzel.name}-sitzungen", sitzungen
        assert "Sitzungsordner" in geladen.hinweis
    for assets in ("wiki/bilder", "../draussen", "raw", "."):
        datei.write_text(json.dumps({**daten, "assets_dir": assets}), encoding="utf-8")
        geladen = modell.lade(projekt.wurzel)
        assert geladen.assets_dir == projekt.wurzel / "raw" / "assets" and "Bilder-Ordner" in geladen.hinweis, assets
    datei.write_text(json.dumps(daten), encoding="utf-8")
    assert modell.lade(projekt.wurzel).hinweis == ""


def test_aendern_weist_falsche_typen_und_werte_ab(projekt):
    for felder in ({"sitzungen_dir": 123}, {"assets_dir": ["x"]}, {"wiki_bilder": "false"}, {"sprache": "--help x"},
                   {"agent_model": 5}, {"wiki_speichern": "manchmal"}):
        with pytest.raises(ProjektFehler):
            modell.aendere(projekt, felder)
    assert modell.lade(projekt.wurzel) == projekt  # nichts davon wurde gespeichert


def test_vorhandenes_wiki_bleibt_beim_anlegen_unveraendert(wiki, tmp_path):
    vorher = {p: p.read_bytes() for p in wiki.rglob("*") if p.is_file()}
    modell.lege_an(name="P", wurzel=wiki, sitzungen_dir=tmp_path / "s", assets_dir=wiki / "raw" / "assets")
    nachher = {p: p.read_bytes() for p in wiki.rglob("*") if p.is_file() and ".audioscribe" not in p.parts}
    assert nachher == vorher


def test_aendern_setzt_und_loest_ueberschreibungen(projekt):
    neu = modell.aendere(projekt, {"sprache": "en", "agent_model": " claude-sonnet-5 ", "wiki_speichern": "immer"})
    assert neu.sprache == "en" and neu.agent_model == "claude-sonnet-5" and neu.wiki_speichern == "immer"
    assert modell.lade(projekt.wurzel).sprache == "en"
    # None bzw. leer heisst: wieder die globale Einstellung
    zurueck = modell.aendere(neu, {"sprache": None, "agent_model": ""})
    assert zurueck.sprache is None and zurueck.agent_model is None and zurueck.wiki_speichern == "immer"
    with pytest.raises(ProjektFehler):
        modell.aendere(zurueck, {"assets_dir": str(projekt.wurzel / "wiki" / "bilder")})


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
