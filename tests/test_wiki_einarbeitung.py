"""Einarbeiten ins Wiki: Zugriffsregeln, Erkennen der Quellseite, Warteschlange (Reihenfolge,
Rückfragen, Nachfassen, Neustart) und die Routen der Oberfläche."""

import json
import sys
import time
from pathlib import Path

import pytest

from audioscribe.agent import guard
from audioscribe.agent.einarbeitung import parse_frage_line, quellseite
from audioscribe.ui import einarbeitung as ea
from audioscribe.ui import state

# --- Zugriffsregeln ---------------------------------------------------------------------------


def test_guard_schreibt_nur_unter_wiki(tmp_path):
    w = tmp_path / "w"
    (w / "wiki").mkdir(parents=True)
    (w / "raw").mkdir()
    ok = lambda tool, **inp: guard.check_wiki_tool(tool, inp, w).erlaubt  # noqa: E731
    assert ok("Write", file_path=str(w / "wiki" / "neu.md"))
    assert ok("Edit", file_path="wiki/index.md")
    assert not ok("Write", file_path=str(w / "raw" / "x.md"))
    assert not ok("Edit", file_path=str(w / "CLAUDE.md"))
    assert not ok("Write", file_path=str(w / "wiki" / ".." / "raw" / "x.md"))
    assert not ok("Write", file_path=str(tmp_path / "draussen.md"))
    assert ok("Read", file_path=str(w / "raw" / "meetings" / "a.md"))
    assert not ok("Read", file_path=str(tmp_path / "anderes" / "a.md"))
    assert not ok("Bash", command="ls")
    assert ok("TodoWrite") and ok("Skill", skill="wiki-ingest")
    aussen = tmp_path / "bilder"
    assert guard.check_wiki_tool("Read", {"file_path": str(aussen / "1.jpg")}, w, read_roots=[aussen]).erlaubt


def test_quellseite_wird_an_der_frontmatter_erkannt(tmp_path):
    w = tmp_path / "w"
    (w / "wiki" / "sources").mkdir(parents=True)
    assert quellseite(w, "raw/meetings/a.md") is None
    seite = w / "wiki" / "sources" / "Q-001.md"
    seite.write_text("---\nid: Q-001\nrohquelle: \"raw/meetings/a.md\"\n---\n# A\n", encoding="utf-8")
    (w / "wiki" / "sonst.md").write_text("# Sonst\n\nrohquelle: raw/meetings/a.md im Text zählt nicht\n", encoding="utf-8")
    assert quellseite(w, "raw/meetings/a.md") == seite
    assert quellseite(w, "raw/meetings/b.md") is None


def test_frage_zeile():
    assert parse_frage_line('[Agent-Frage] {"id": "x1", "questions": []}') == {"id": "x1", "questions": []}
    assert parse_frage_line("[Agent] hallo") is None
    assert parse_frage_line("[Agent-Frage] {kaputt") is None


def test_argv_je_art(tmp_path):
    e = ea.Eintrag(id="a", wiki_dir="/w", rohquelle="raw/x.md", modell="claude-opus-5")
    argv = ea.build_ingest_argv(e, tmp_path, prefix=["as"])
    assert argv[:2] == ["as", "ingest"] and "--rohquelle=raw/x.md" in argv and "--fragen" in argv
    assert "--fortsetzen" not in argv and not any(a.startswith("--nachricht") for a in argv)
    e.art = ea.ART_FORTSETZEN
    assert "--fortsetzen" in ea.build_ingest_argv(e, tmp_path, prefix=["as"])
    e.art, e.nachricht = ea.ART_NACHRICHT, "-- nimm ANF-3"
    assert "--nachricht=-- nimm ANF-3" in ea.build_ingest_argv(e, tmp_path, prefix=["as"])


# --- Warteschlange mit einem Ersatz-Kind ------------------------------------------------------

# Ersatz für 'audioscribe ingest': schreibt Protokoll, Status und analyse.json; mit "frage"
# im Namen der Rohquelle stellt es eine Rückfrage und gibt die Antwort aus.
_KIND = r'''
import json, sys, time
from pathlib import Path
args = dict(a.split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
flags = [a for a in sys.argv[1:] if "=" not in a]
ordner = Path(args["--arbeitsordner"]); ordner.mkdir(parents=True, exist_ok=True)
print("[Agent] los: " + args["--rohquelle"] + (" fortsetzen" if "--fortsetzen" in flags else "")
      + (" nachricht=" + args["--nachricht"] if "--nachricht" in args else ""), flush=True)
(ordner / "analyse.json").write_text(json.dumps({"session_id": "sess-1", "status": "laeuft"}))
print('[Agent-Status] {"done": 1, "total": 2, "current": "Seiten", "verbrauch": {"eingabe": 5, "ausgabe": 5}}', flush=True)
if "frage" in args["--rohquelle"]:
    print('[Agent-Frage] ' + json.dumps({"id": "f1", "questions": [{"question": "Wer?", "options": []}]}), flush=True)
    antwort = json.loads(sys.stdin.readline())
    print("[Antwort] " + json.dumps(antwort.get("answers")), flush=True)
if "langsam" in args["--rohquelle"]:
    time.sleep(30)
sys.exit(3 if "kaputt" in args["--rohquelle"] else 0)
'''


@pytest.fixture
def kind(tmp_path):
    datei = tmp_path / "kind.py"
    datei.write_text(_KIND, encoding="utf-8")
    return lambda e, ordner: [sys.executable, str(datei), *ea.build_ingest_argv(e, ordner, prefix=[])[1:]]


def _warte(fn, timeout=10.0):
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_reihenfolge_ergebnis_und_protokoll(tmp_path, kind):
    q = ea.Warteschlange(tmp_path / "q", argv_builder=kind, quellseite=lambda e: "/w/wiki/sources/Q.md")
    a = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/a.md", projekt="P")
    b = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/kaputt.md")
    assert q.einreihen(wiki_dir=tmp_path, rohquelle="raw/a.md")["id"] == a["id"]  # kein Duplikat
    assert q.warte_leer()
    da, db = q.detail(a["id"]), q.detail(b["id"])
    assert da["status"] == ea.FERTIG and da["session_id"] == "sess-1" and da["quellseite"] == "/w/wiki/sources/Q.md"
    assert any("los: raw/a.md" in z for z in da["lines"]) and not any("Agent-Status" in z for z in da["lines"])
    assert da["fortschritt"]["total"] == 2 and da["verbrauch"]["eingabe"] == 5
    assert db["status"] == ea.FEHLER and "3" in db["fehler"]
    assert q.uebersicht()["zaehler"]["fertig"] == 1
    # Liste und Protokoll liegen auf der Platte.
    gespeichert = json.loads((tmp_path / "q" / ea.LISTE).read_text(encoding="utf-8"))
    assert {e["status"] for e in gespeichert} == {ea.FERTIG, ea.FEHLER}
    q.beende()


def test_rueckfrage_wartet_auf_antwort(tmp_path, kind):
    q = ea.Warteschlange(tmp_path / "q", argv_builder=kind, quellseite=lambda e: None)
    a = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/frage.md")
    assert _warte(lambda: q.detail(a["id"])["status"] == ea.FRAGE)
    d = q.detail(a["id"])
    assert d["frage"]["id"] == "f1" and d["frage"]["questions"][0]["question"] == "Wer?"
    with pytest.raises(RuntimeError):
        q.antworte(a["id"], "falsch", {"Wer?": "x"})
    q.antworte(a["id"], "f1", {"Wer?": "Teamleitung"})
    assert q.warte_leer()
    d = q.detail(a["id"])
    assert d["status"] == ea.FERTIG and any("Teamleitung" in z for z in d["lines"])
    # Ohne Quellseite ein Hinweis, aber kein Fehler.
    assert "rohquelle" in (d["hinweis"] or "")
    q.beende()


def test_nachfassen_setzt_die_sitzung_fort(tmp_path, kind):
    q = ea.Warteschlange(tmp_path / "q", argv_builder=kind, quellseite=lambda e: "x")
    a = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/a.md")
    with pytest.raises((RuntimeError, ValueError)):
        q.nachricht(a["id"], "")
    assert q.warte_leer()
    q.nachricht(a["id"], "Bitte ANF-3 ergänzen")
    assert q.warte_leer()
    d = q.detail(a["id"])
    assert d["status"] == ea.FERTIG and d["laeufe"] == 2
    assert any(z.endswith("Bitte ANF-3 ergänzen") and "[Du]" in z for z in d["lines"])
    assert any("nachricht=Bitte ANF-3 ergänzen" in z for z in d["lines"])
    q.beende()


def test_abbrechen_und_wiederholen(tmp_path, kind):
    q = ea.Warteschlange(tmp_path / "q", argv_builder=kind, quellseite=lambda e: None)
    a = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/langsam.md")
    b = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/b.md")
    assert _warte(lambda: q.detail(a["id"])["status"] == ea.LAEUFT and q.detail(a["id"])["lines"])
    assert q.aktiv_fuer_wiki(tmp_path)
    q.abbrechen(b["id"])  # wartend: sofort abgebrochen
    q.abbrechen(a["id"])  # laufend: Agent wird beendet
    assert q.warte_leer(15)
    assert q.detail(a["id"])["status"] == ea.ABGEBROCHEN and q.detail(b["id"])["status"] == ea.ABGEBROCHEN
    with pytest.raises(RuntimeError):
        q.entfernen(q.wiederholen(a["id"])["id"])  # wieder wartend/laufend: nicht entfernbar
    q.abbrechen(a["id"])
    assert q.warte_leer(15)
    q.entfernen(b["id"])
    assert not (tmp_path / "q" / b["id"]).exists()
    with pytest.raises(KeyError):
        q.detail(b["id"])
    q.beende()


def test_neustart_setzt_unterbrochene_fort(tmp_path, kind):
    basis = tmp_path / "q"
    basis.mkdir()
    liste = [
        {"id": "a", "wiki_dir": str(tmp_path), "rohquelle": "raw/a.md", "status": "laeuft", "eingereiht": "1", "pid": 999999},
        {"id": "b", "wiki_dir": str(tmp_path), "rohquelle": "raw/b.md", "status": "frage", "eingereiht": "2",
         "frage": {"id": "f", "questions": []}},
        {"id": "c", "wiki_dir": str(tmp_path), "rohquelle": "raw/c.md", "status": "fertig", "eingereiht": "0"},
        {"id": "d", "status": "unsinn"},
    ]
    (basis / ea.LISTE).write_text(json.dumps(liste), encoding="utf-8")
    q = ea.Warteschlange(basis, argv_builder=kind, starten=False)
    stand = {e["id"]: e for e in q.uebersicht()["auftraege"]}
    assert set(stand) == {"a", "b", "c"}
    assert stand["a"]["status"] == ea.WARTET and stand["a"]["art"] == ea.ART_FORTSETZEN and stand["a"]["hinweis"]
    assert stand["b"]["status"] == ea.WARTET and stand["b"]["frage"] is None
    assert stand["c"]["status"] == ea.FERTIG
    q.starte()
    assert q.warte_leer()
    assert any("fortsetzen" in z for z in q.detail("a")["lines"])
    q.beende()


def test_herunterfahren_laesst_den_lauf_zum_fortsetzen_stehen(tmp_path, kind):
    q = ea.Warteschlange(tmp_path / "q", argv_builder=kind, quellseite=lambda e: None)
    a = q.einreihen(wiki_dir=tmp_path, rohquelle="raw/langsam.md")
    assert _warte(lambda: q.detail(a["id"])["lines"] and q.detail(a["id"])["status"] == ea.LAEUFT)
    q.beende()
    assert _warte(lambda: q._proc is None, 15)
    q2 = ea.Warteschlange(tmp_path / "q", argv_builder=kind, starten=False)
    assert q2.detail(a["id"])["art"] == ea.ART_FORTSETZEN and q2.detail(a["id"])["status"] == ea.WARTET


# --- Routen -----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "einstellungen.json")
    # Kein echter Agent: der Arbeiter startet in den Routen-Tests nicht.
    monkeypatch.setattr(ea.Warteschlange, "starte", lambda self: None)
    return TestClient(server.create_app())


def _offen(client, projekt):
    assert client.post("/api/projekt/oeffnen", json={"pfad": str(projekt.wurzel)}).status_code == 200


@pytest.mark.nur_standard
def test_sitzung_einreihen_braucht_ablage_und_schema(client, projekt, sitzung):
    _offen(client, projekt)
    r = client.post("/api/wiki/einarbeiten", json={"sitzung": str(sitzung)})
    assert r.status_code == 409 and "CLAUDE.md" in r.json()["detail"]
    (projekt.wiki_dir / "CLAUDE.md").write_text("# Schema\n", encoding="utf-8")
    r = client.post("/api/wiki/einarbeiten", json={"sitzung": str(sitzung)})
    assert r.status_code == 409  # noch nicht im Wiki gespeichert
    ablage = client.post("/api/wiki/speichern", json={"sitzung": str(sitzung)}).json()
    assert "einarbeitung" not in ablage  # Vorgabe "fragen": nur anbieten
    r = client.post("/api/wiki/einarbeiten", json={"sitzung": str(sitzung)})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "wartet" and a["pfad"] == str(Path(projekt.wiki_dir) / a["rohquelle"])
    assert Path(ablage["ordner"]) == projekt.wiki_dir / a["rohquelle"] and a["projekt"] == "Bahnbuchung"
    uebersicht = client.get("/api/wiki/einarbeitung").json()
    assert uebersicht["zaehler"]["wartet"] == 1 and uebersicht["auftraege"][0]["id"] == a["id"]
    d = client.get(f"/api/wiki/einarbeitung/{a['id']}").json()
    assert d["lines"] and d["offset"] == len(d["lines"])
    assert client.get("/api/wiki/einarbeitung/gibtsnicht").status_code == 404
    assert client.post(f"/api/wiki/einarbeitung/{a['id']}/nachricht", json={"text": "x"}).status_code == 409
    assert client.post(f"/api/wiki/einarbeitung/{a['id']}/abbrechen").status_code == 200
    assert client.delete(f"/api/wiki/einarbeitung/{a['id']}").status_code == 200
    # Projekt wechseln blockiert die Einarbeitung nicht (und umgekehrt).
    assert "wiki" not in client.get("/api/kontext").json()["laeuft"]


@pytest.mark.nur_standard
def test_immer_einarbeiten_reiht_nach_der_ablage_ein(client, projekt, sitzung, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    (projekt.wiki_dir / "CLAUDE.md").write_text("# Schema\n", encoding="utf-8")
    _offen(client, projekt)
    r = client.put("/api/projekt", json={"felder": {"wiki_speichern": "immer", "wiki_einarbeiten": "immer"}})
    assert r.status_code == 200 and r.json()["projekt"]["wiki_einarbeiten"] == "immer"
    assert client.put("/api/projekt", json={"felder": {"wiki_einarbeiten": "bald"}}).status_code == 400
    gestartet = {}
    monkeypatch.setattr(runner_modul.LiveRunner, "start", lambda self, opts, **kw: gestartet.update(opts=opts, kw=kw))
    assert client.post("/api/live/start", json={"monitor": 1, "mic": "none", "loopback": "none"}).status_code == 200
    ergebnis = gestartet["kw"]["on_ende"](sitzung)
    assert "wiki_ablage" in ergebnis and ergebnis["einarbeitung"]["status"] == "wartet"
    assert ergebnis["einarbeitung"]["rohquelle"].startswith("raw/")
    assert client.get("/api/wiki/einarbeitung").json()["zaehler"]["wartet"] == 1


# --- Agent: Rückfrage und Zugriff im can_use_tool-Callback (ohne Claude) -----------------------


@pytest.mark.nur_standard
def test_agent_reicht_rueckfragen_durch_und_prueft_zugriffe(tmp_path):
    sdk = pytest.importorskip("claude_agent_sdk")
    import anyio

    from audioscribe.agent.einarbeitung import FRAGE_PREFIX, WikiAuftrag, WikiSitzung

    w = tmp_path / "w"
    (w / "wiki").mkdir(parents=True)
    ausgaben, gefragt = [], []

    async def antwort(frage_id):
        gefragt.append(frage_id)
        return {"id": frage_id, "answers": {"Wer gibt frei?": "Teamleitung"}}

    auftrag = WikiAuftrag(arbeitsordner=tmp_path / "job", wiki_dir=w, rohquelle="raw/a.md")
    s = WikiSitzung(auftrag, emit=ausgaben.append, lies_antwort=antwort)
    frage = {"questions": [{"question": "Wer gibt frei?", "header": "Rolle", "options": [], "multiSelect": False}]}

    async def ablauf():
        return (
            await s._can_use_tool("AskUserQuestion", frage, None),
            await s._can_use_tool("Write", {"file_path": str(w / "raw" / "x.md")}, None),
            await s._can_use_tool("Write", {"file_path": str(w / "wiki" / "x.md")}, None),
        )

    erlaubt, raw, seite = anyio.run(ablauf)
    assert isinstance(erlaubt, sdk.PermissionResultAllow)
    assert erlaubt.updated_input["answers"] == {"Wer gibt frei?": "Teamleitung"}
    zeile = next(a for a in ausgaben if a.startswith(FRAGE_PREFIX))
    assert json.loads(zeile[len(FRAGE_PREFIX):])["id"] == gefragt[0]
    assert isinstance(raw, sdk.PermissionResultDeny) and isinstance(seite, sdk.PermissionResultAllow)

    # Ohne jemanden, der antworten kann: ablehnen statt warten.
    s2 = WikiSitzung(auftrag, emit=ausgaben.append, lies_antwort=None)
    assert isinstance(anyio.run(s2._can_use_tool, "AskUserQuestion", frage, None), sdk.PermissionResultDeny)
