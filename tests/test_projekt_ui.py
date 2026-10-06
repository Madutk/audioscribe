"""Routen fuer Kontext, Projekte, Einstellungen, Wiki-Ablage und Demo (PRD §21)."""

import json
from pathlib import Path

import pytest

from audioscribe.ui import state


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "einstellungen.json")
    monkeypatch.setattr(
        "audioscribe.live.kommando.inventory",
        lambda: {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": []},
    )
    return TestClient(server.create_app())


def _neu(client, wiki, tmp_path, **mehr):
    return client.post(
        "/api/projekt/neu",
        json={
            "name": "Bahnbuchung", "wurzel": str(wiki), "sitzungen_dir": str(tmp_path / "sitzungen"),
            "assets_dir": str(wiki / "raw" / "assets"), **mehr,
        },
    )


# --- Kontext ---------------------------------------------------------------------------------


def test_start_ist_die_startseite(client):
    k = client.get("/api/kontext").json()
    assert k["modus"] == "start" and k["projekt"] is None and k["zuletzt"] == []
    assert k["laeuft"] == {"live": False, "analyse": False, "stapel": False}
    assert client.get("/api/defaults").json()["modus"] == "start"


def test_modus_datei_und_unbekannter_modus(client):
    assert client.post("/api/kontext", json={"modus": "datei"}).json()["modus"] == "datei"
    assert client.post("/api/kontext", json={"modus": "projekt"}).status_code == 400  # nur ueber /api/projekt/...
    assert client.post("/api/kontext", json={"modus": "quatsch"}).status_code == 400
    assert client.post("/api/kontext", json={"modus": "start"}).json()["modus"] == "start"


# --- Projekt anlegen und oeffnen -------------------------------------------------------------


def test_pruefen_meldet_je_feld_und_schlaegt_ordner_vor(client, wiki, tmp_path):
    r = client.post("/api/projekt/pruefen", json={"name": "", "wurzel": str(wiki)}).json()
    assert set(r["fehler"]) == {"name", "sitzungen_dir", "assets_dir"}
    assert r["wiki"]["zustand"] == "ok" and r["wiki"]["seiten"] == 2
    assert Path(r["vorschlag"]["assets_dir"]) == wiki / "raw" / "assets"
    assert Path(r["vorschlag"]["sitzungen_dir"]) == wiki.parent / "bahn-wiki-sitzungen"
    r = client.post("/api/projekt/pruefen", json={"name": "x", "wurzel": str(tmp_path / "nix")}).json()
    assert r["wiki"]["zustand"] == "fehler" and "wurzel" in r["fehler"]


def test_neues_projekt_wird_geoeffnet_und_gemerkt(client, wiki, tmp_path):
    r = _neu(client, wiki, tmp_path, sprache="en")
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["modus"] == "projekt" and k["projekt"]["name"] == "Bahnbuchung"
    assert k["projekt"]["wiki"]["zustand"] == "ok"
    assert k["projekt"]["eigen"]["sprache"] == "en" and k["projekt"]["herkunft"]["sprache"] == "projekt"
    assert k["projekt"]["herkunft"]["agent_model"] == "global"
    assert [z["name"] for z in k["zuletzt"]] == ["Bahnbuchung"] and k["zuletzt"][0]["vorhanden"] is True
    assert (wiki / ".audioscribe" / "projekt.json").is_file()
    # Ordner, Sprache und Wiki der Arbeitsansichten kommen jetzt aus dem Projekt.
    d = client.get("/api/defaults").json()
    assert Path(d["output_dir"]) == tmp_path / "sitzungen" and d["language"] == "en" and d["modus"] == "projekt"
    assert Path(d["agent_output_dir"]) == tmp_path / "sitzungen" / "analysen" and Path(d["wiki_dir"]) == wiki
    assert Path(client.get("/api/agent/defaults").json()["output_dir"]) == tmp_path / "sitzungen" / "analysen"
    assert client.get("/api/live/defaults").json()["language"] == "en"
    assert client.get("/api/wiki/status").json()["zustand"] == "ok"


def test_neues_projekt_mit_neuem_wiki(client, tmp_path):
    wurzel = tmp_path / "frisch"
    r = client.post(
        "/api/projekt/neu",
        json={"name": "Frisch", "wurzel": str(wurzel), "sitzungen_dir": str(tmp_path / "fs"),
              "assets_dir": str(wurzel / "raw" / "assets"), "neues_wiki": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["projekt"]["wiki"]["zustand"] == "ok" and (wurzel / "wiki" / "glossar.md").is_file()


def test_fehlerhafte_angaben_und_unbekannter_ordner(client, wiki, tmp_path):
    r = client.post("/api/projekt/neu", json={"name": "X", "wurzel": str(wiki), "sitzungen_dir": str(wiki / "wiki" / "s"),
                                              "assets_dir": str(wiki / "raw" / "assets")})
    assert r.status_code == 400 and "wiki/" in r.json()["detail"]
    r = client.post("/api/projekt/oeffnen", json={"pfad": str(tmp_path)})
    assert r.status_code == 400 and "kein AudioScribe-Projekt" in r.json()["detail"]
    assert client.get("/api/kontext").json()["modus"] == "start"


def test_oeffnen_schliessen_vergessen(client, wiki, tmp_path):
    _neu(client, wiki, tmp_path)
    assert client.post("/api/kontext", json={"modus": "start"}).json()["projekt"] is None
    k = client.post("/api/projekt/oeffnen", json={"pfad": str(wiki)}).json()
    assert k["modus"] == "projekt" and Path(k["projekt"]["wurzel"]) == wiki
    client.post("/api/kontext", json={"modus": "start"})
    assert client.post("/api/projekte/vergessen", json={"pfad": str(wiki)}).json()["zuletzt"] == []
    assert (wiki / ".audioscribe" / "projekt.json").is_file()  # nur aus der Liste, nicht von der Platte


# --- Einstellungen ---------------------------------------------------------------------------


def test_globale_einstellungen_und_ueberschreiben_im_projekt(client, wiki, tmp_path):
    e = client.get("/api/einstellungen").json()
    assert e["optionen"]["ki_dienste"][-1] == {"id": "claude-agent", "label": "Claude (Agent SDK)"}
    r = client.post("/api/einstellungen", json={"agent_model": "claude-sonnet-5", "sprache": "auto"})
    assert r.json()["werte"]["agent_model"] == "claude-sonnet-5" and r.json()["werte"]["sprache"] == "auto"
    assert client.post("/api/einstellungen", json={"agent_model": "--boese"}).status_code == 400
    _neu(client, wiki, tmp_path)
    assert client.get("/api/defaults").json()["language"] == "auto"  # global gilt, solange das Projekt nichts setzt
    k = client.put("/api/projekt", json={"felder": {"sprache": "de", "wiki_speichern": "immer"}}).json()
    assert k["projekt"]["effektiv"]["sprache"] == "de" and k["projekt"]["wiki_speichern"] == "immer"
    assert client.get("/api/agent/defaults").json()["model"] == "claude-sonnet-5"
    k = client.put("/api/projekt", json={"felder": {"sprache": None}}).json()
    assert k["projekt"]["effektiv"]["sprache"] == "auto" and k["projekt"]["herkunft"]["sprache"] == "global"
    assert client.put("/api/projekt", json={"felder": {"assets_dir": str(tmp_path / "draussen")}}).status_code == 400


def test_unerwartete_eingaben_geben_400_statt_500(client, wiki, tmp_path):
    _neu(client, wiki, tmp_path)
    for felder in ({"sitzungen_dir": 123}, {"assets_dir": True}, {"wiki_bilder": "false"}, {"sprache": "--help x"}):
        assert client.put("/api/projekt", json={"felder": felder}).status_code == 400, felder
    client.post("/api/kontext", json={"modus": "start"})
    nul = "C:\\x\u0000y"
    assert client.post("/api/projekt/oeffnen", json={"pfad": nul}).status_code == 400
    assert client.post("/api/projekt/pruefen", json={"name": "x", "wurzel": nul}).status_code == 200
    assert client.post("/api/oeffnen", json={"pfad": nul}).status_code == 400
    assert client.get("/api/transkript", params={"pfad": nul}).status_code == 404
    # "Neues Wiki" auf ein bestehendes Wiki: abgewiesen, nichts unter wiki/ angelegt.
    anderes = tmp_path / "anderes-wiki"
    (anderes / "wiki").mkdir(parents=True)
    (anderes / "wiki" / "index.md").write_text("# Anderes\n", encoding="utf-8")
    r = client.post("/api/projekt/pruefen", json={"name": "x", "wurzel": str(anderes), "neues_wiki": True})
    assert "Vorhandenes Wiki" in r.json()["fehler"]["wurzel"]
    r = client.post(
        "/api/projekt/neu",
        json={"name": "x", "wurzel": str(anderes), "sitzungen_dir": str(tmp_path / "as"),
              "assets_dir": str(anderes / "raw" / "assets"), "neues_wiki": True},
    )
    assert r.status_code == 400 and [p.name for p in (anderes / "wiki").iterdir()] == ["index.md"]


def test_abschliessen_und_verwerfen_nur_fuer_unterbrochene_sitzungen(client, projekt, sitzung, monkeypatch):
    from audioscribe.live import journal
    from audioscribe.ui import runner as runner_modul

    _mit_sitzung(client, projekt, sitzung)
    # Sauber beendet: weder abschliessen noch verwerfen (veraltetes Banner, zweiter Tab).
    journal.schreibe_status(sitzung, status=journal.BEENDET, replay=False)
    assert client.post("/api/live/verwerfen", json={"sitzung": str(sitzung)}).status_code == 400
    assert journal.lies_status(sitzung)["status"] == journal.BEENDET
    # Unterbrochen, aber es laeuft gerade eine andere Aufnahme: Abschliessen darf sie nicht abbrechen.
    journal.schreibe_status(sitzung, status=journal.UNTERBROCHEN)
    zurueckgesetzt = []
    monkeypatch.setattr(runner_modul.LiveRunner, "laeuft", lambda self: True)
    monkeypatch.setattr(runner_modul.LiveRunner, "reset", lambda self, **kw: zurueckgesetzt.append(1))
    r = client.post("/api/live/abschliessen", json={"sitzung": str(sitzung)})
    assert r.status_code == 409 and zurueckgesetzt == []
    assert client.post("/api/live/verwerfen", json={"sitzung": str(sitzung)}).status_code == 200
    assert journal.lies_status(sitzung)["status"] == journal.VERWORFEN


def test_live_status_kennt_die_wiki_ablage_auch_nach_neuladen(client, projekt, sitzung, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    _mit_sitzung(client, projekt, sitzung)
    monkeypatch.setattr(
        runner_modul.LiveRunner, "snapshot",
        lambda self, offset=0, ev_offset=0: {"running": False, "dir": str(sitzung), "phase": "beendet"},
    )
    assert client.get("/api/live/status").json()["wiki_ablage"] is None
    client.post("/api/wiki/speichern", json={"sitzung": str(sitzung)})
    assert client.get("/api/live/status").json()["wiki_ablage"]["ordner"].endswith("2026-10-06_workshop-reisebuchung")


def test_reset_waehrend_des_starts_startet_kein_kind(tmp_path):
    """LiveRunner: ein Reset, der den Start noch beim Aufbau des Souffleurs erwischt, gewinnt."""
    import sys

    from audioscribe.ui.jobs import LiveJobOptions
    from audioscribe.ui.runner import LiveRunner

    runner = LiveRunner()
    gestartet = []

    class Souffleur:
        on_hinweis = None

        def stop(self):
            gestartet.append("souffleur gestoppt")

    def factory(opts):
        runner.reset()  # z. B. "Demo beenden" direkt nach "Demo starten"
        return Souffleur()

    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda o: gestartet.append("kind") or [sys.executable, "-c", "pass"],
        souffleur_factory=factory,
    )
    assert runner.laeuft() is False and runner._thread is None and runner.souffleur() is None
    assert gestartet == ["kind", "souffleur gestoppt"]  # argv gebaut, aber kein Prozess gestartet


def test_projekt_aendern_ohne_projekt(client):
    assert client.put("/api/projekt", json={"felder": {"sprache": "de"}}).status_code == 409


# --- Wiki-Ablage -----------------------------------------------------------------------------


def _mit_sitzung(client, projekt, sitzung):
    assert client.post("/api/projekt/oeffnen", json={"pfad": str(projekt.wurzel)}).status_code == 200


def test_sitzungen_des_projekts_mit_titel_und_ablagen(client, projekt, sitzung):
    _mit_sitzung(client, projekt, sitzung)
    quellen = client.get("/api/agent/sources").json()["sources"]
    assert [q["name"] for q in quellen] == [sitzung.name]
    assert quellen[0]["titel"] == "Workshop Reisebuchung" and quellen[0]["frames"] == 2 and quellen[0]["ablagen"] == []
    r = client.post("/api/wiki/speichern", json={"sitzung": str(sitzung), "bilder": True})
    assert r.status_code == 200, r.text
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    assert Path(r.json()["ordner"]) == ziel and r.json()["bilder"] == 2
    assert (ziel / "transkript.annotiert.md").is_file()
    quellen = client.get("/api/agent/sources").json()["sources"]
    assert Path(quellen[0]["ablagen"][0]["ordner"]) == ziel


def test_immer_speichern_wird_projekteinstellung(client, projekt, sitzung):
    _mit_sitzung(client, projekt, sitzung)
    client.post("/api/wiki/speichern", json={"sitzung": str(sitzung), "bilder": False, "immer": True})
    p = client.get("/api/kontext").json()["projekt"]
    assert p["wiki_speichern"] == "immer" and p["wiki_bilder"] is False


def test_wiki_speichern_nur_fuer_sitzungen_des_projekts(client, projekt, sitzung, tmp_path):
    assert client.post("/api/wiki/speichern", json={"sitzung": str(sitzung)}).status_code == 409  # kein Projekt offen
    _mit_sitzung(client, projekt, sitzung)
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "transkript.md").write_text("x", encoding="utf-8")
    assert client.post("/api/wiki/speichern", json={"sitzung": str(fremd)}).status_code == 400
    assert not any(projekt.raw_dir.iterdir())


def test_laufende_sitzung_geht_erst_nach_dem_stopp_ins_wiki(client, projekt, sitzung, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    _mit_sitzung(client, projekt, sitzung)
    monkeypatch.setattr(runner_modul.LiveRunner, "laeuft", lambda self: True)
    monkeypatch.setattr(runner_modul.LiveRunner, "session_dir", lambda self: sitzung)
    r = client.post("/api/wiki/speichern", json={"sitzung": str(sitzung)})
    assert r.status_code == 409 and "läuft noch" in r.json()["detail"]
    assert not any(projekt.raw_dir.iterdir())


def test_testmodus_geht_nie_von_selbst_ins_wiki_und_setzt_nichts_fort(client, projekt, sitzung, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    _mit_sitzung(client, projekt, sitzung)
    client.put("/api/projekt", json={"felder": {"wiki_speichern": "immer"}})
    gestartet = {}
    monkeypatch.setattr(runner_modul.LiveRunner, "start", lambda self, opts, **kw: gestartet.update(opts=opts, kw=kw))
    body = {"replay_transcript": str(sitzung), "replay_speed": 20}
    assert client.post("/api/live/start", json={**body, "resume": str(sitzung)}).status_code == 400
    assert client.post("/api/live/start", json=body).status_code == 200
    # Sitzungen landen im Sitzungsordner des Projekts - und ein Probelauf hat keinen Nachlauf.
    assert gestartet["opts"].output_dir == projekt.sitzungen_dir and "on_ende" not in gestartet["kw"]


def test_nachbereitung_ins_wiki(client, projekt, sitzung):
    _mit_sitzung(client, projekt, sitzung)
    ws = projekt.analysen_dir / "reisebuchung"
    ws.mkdir(parents=True)
    (ws / "analyse.json").write_text(
        json.dumps({"name": "Reisebuchung", "quelle": str(sitzung), "status": "fertig"}), encoding="utf-8"
    )
    (ws / "INDEX.md").write_text("# Reisebuchung\n", encoding="utf-8")
    quellen = client.get("/api/agent/sources").json()["sources"]
    assert quellen[0]["analysen"][0]["name"] == "Reisebuchung" and quellen[0]["analysen"][0]["status"] == "fertig"
    r = client.post("/api/wiki/speichern-nachbereitung", json={"workspace": str(ws), "bilder": True})
    assert r.status_code == 200, r.text
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung" / "nachbereitung-ki" / "reisebuchung"
    assert Path(r.json()["ordner"]) == ziel and (ziel / "INDEX.md").is_file()
    assert client.post("/api/wiki/speichern-nachbereitung", json={"workspace": str(sitzung)}).status_code == 400


def test_nachlauf_speichert_bei_immer(projekt, sitzung, tmp_path, monkeypatch):
    """LiveRunner ruft on_ende nach einem sauberen Ende; das Ergebnis steht im Status."""
    import sys
    import time

    from audioscribe.ui.jobs import LiveJobOptions
    from audioscribe.ui.runner import LiveRunner

    kind = tmp_path / "kind.py"
    kind.write_text(
        "import json\n"
        f"print('[Live] ' + json.dumps({{'type': 'state', 'phase': 'fertig', 'session': 's', 'dir': {str(sitzung)!r}}}), flush=True)\n",
        encoding="utf-8",
    )
    runner = LiveRunner()
    gerufen = []
    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda o: [sys.executable, str(kind)],
        on_ende=lambda d: gerufen.append(d) or {"wiki_ablage": {"ordner": "x"}},
    )
    ende = time.monotonic() + 20
    while runner.laeuft() and time.monotonic() < ende:
        time.sleep(0.05)
    snap = runner.snapshot()
    assert gerufen == [sitzung] and snap["nachlauf"] == {"wiki_ablage": {"ordner": "x"}} and snap["phase"] == "beendet"


# --- Aufnahme transkribieren: Dateiauswahl, Vorschau -----------------------------------------


def test_browse_liefert_mediendateien_fuer_die_dateiauswahl(client, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "notiz.txt").write_text("x", encoding="utf-8")
    ohne = client.get("/api/browse", params={"path": str(tmp_path)}).json()
    assert ohne["files"] == [] and ohne["media_count"] == 1
    mit = client.get("/api/browse", params={"path": str(tmp_path), "files": "1"}).json()
    assert [f["name"] for f in mit["files"]] == ["a.mp4"]
    # Ein Dateipfad oeffnet seinen Ordner.
    datei = client.get("/api/browse", params={"path": str(tmp_path / "a.mp4"), "files": "1"}).json()
    assert Path(datei["path"]) == tmp_path


def test_transkript_vorschau_nur_transkriptdateien(client, sitzung, tmp_path):
    r = client.get("/api/transkript", params={"pfad": str(sitzung)})
    assert r.status_code == 200 and r.json()["datei"].endswith("transkript.annotiert.md")
    assert "zweite Klasse" in r.json()["text"] and r.json()["gekuerzt"] is False
    (tmp_path / "geheim.md").write_text("x", encoding="utf-8")
    assert client.get("/api/transkript", params={"pfad": str(tmp_path)}).status_code == 404


def test_transkript_vorschau_im_projekt_nur_aus_dem_sitzungsordner(client, projekt, sitzung, tmp_path):
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "transkript.md").write_text("fremd", encoding="utf-8")
    assert client.get("/api/transkript", params={"pfad": str(fremd)}).status_code == 200  # ohne Projekt: frei waehlbar
    _mit_sitzung(client, projekt, sitzung)
    assert client.get("/api/transkript", params={"pfad": str(sitzung)}).status_code == 200
    assert client.get("/api/transkript", params={"pfad": str(fremd)}).status_code == 404


def test_statische_dateien_aus_unterordnern_ohne_pfadspiele(client):
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/js/main.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/static/index.html").status_code == 404  # nur Skripte und Stylesheets
    assert client.get("/static/..%2Fserver.py").status_code == 404
    assert client.get("/static/js/..%2F..%2Fserver.py").status_code == 404


# --- Demo ------------------------------------------------------------------------------------


def test_demo_spielt_das_demo_transkript_ohne_ablage(client, tmp_path, monkeypatch):
    from audioscribe.ui import kontext

    if not kontext.demo_verfuegbar():
        pytest.skip("Demo-Daten fehlen")
    import dataclasses

    # Die Demo-Sitzung landet im Cache - im Test nicht im Cache des Rechners.
    monkeypatch.setattr(kontext, "settings", dataclasses.replace(kontext.settings, cache_dir=tmp_path / "cache"))
    gestartet = {}

    from audioscribe.ui import runner as runner_modul

    def fake_start(self, opts, **kw):
        gestartet["opts"], gestartet["kw"] = opts, kw

    monkeypatch.setattr(runner_modul.LiveRunner, "start", fake_start)
    assert client.post("/api/demo/start").status_code == 409  # Demo nicht geoeffnet
    k = client.post("/api/kontext", json={"modus": "demo"}).json()
    assert k["modus"] == "demo" and k["projekt"]["demo"] is True and k["projekt"]["wiki_speichern"] == "nie"
    assert client.get("/api/wiki/status").json()["zustand"] == "ok"
    assert client.post("/api/demo/start").status_code == 200
    opts = gestartet["opts"]
    assert opts.replay_transcript.name == "transkript.md" and opts.replay_transcript.is_file()
    assert opts.refine is False and opts.mic == "none" and "on_ende" not in gestartet["kw"]
    assert opts.replay_raffen is True and opts.replay_speed == 1.0  # zuegig, aber nicht im Zeitraffer
    # Die Demo ist kein Projekt auf der Platte: nichts gemerkt, nichts ins Demo-Wiki geschrieben.
    assert client.get("/api/kontext").json()["zuletzt"] == []
    assert not (kontext.demo_wurzel() / ".audioscribe").exists()


def test_kontextwechsel_waehrend_eines_laufs_wird_abgewiesen(client, wiki, tmp_path, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    monkeypatch.setattr(runner_modul.AnalyseRunner, "laeuft", lambda self: True)
    r = client.post("/api/kontext", json={"modus": "datei"})
    assert r.status_code == 409 and "KI-Analyse" in r.json()["detail"]
    assert _neu(client, wiki, tmp_path).status_code == 409
