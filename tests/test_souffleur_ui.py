"""Souffleur in der Oberflaeche: LiveRunner-Anbindung und Routen (ohne Netz, KI-Attrappe)."""

import json
import sys
import time
from pathlib import Path

import pytest

from audioscribe.souffleur.kern import Souffleur
from audioscribe.souffleur.ki import AttrappeKi, KiStatus
from audioscribe.souffleur.konfig import SouffleurKonfig
from audioscribe.ui.jobs import LiveJobOptions
from audioscribe.ui.runner import LiveRunner

DATA = Path(__file__).parent / "data" / "souffleur"
MEETING = DATA / "meeting"
WIKI = DATA / "wiki"


def _attrappe(konfig: SouffleurKonfig, *, ki=None) -> Souffleur:
    return Souffleur(konfig, ki=ki or AttrappeKi(), ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"))


def _warte(runner: LiveRunner, timeout: float = 20.0) -> dict:
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        snap = runner.snapshot()
        if not snap["running"]:
            return snap
        time.sleep(0.05)
    raise AssertionError("Sitzung endet nicht")


# Ein Kind, das wie ``audioscribe live`` spricht: Zustand, Segmente, Messwerte, Fazit.
CHILD = r"""
import json, sys, time
def ev(**d): print('[Live] ' + json.dumps(d, ensure_ascii=False), flush=True)
d = sys.argv[1]
ev(type='state', phase='laden', session='live-x', dir=d, model='m', device='cpu')
ev(type='state', phase='laeuft', session='live-x', dir=d, model='m', device='cpu')
ev(type='stats', elapsed=1.0, backlog=0.0, delay=0.5)
ev(type='segment', id=1, track='system', speaker='Sprecher 1', start=0.0, end=4.0, text='Guten Morgen zusammen, schön dass alle da sind.', delay=0.5)
ev(type='segment', id=2, track='mic', speaker='Ich', start=5.0, end=9.0, text='Wer pflegt eigentlich die Lieferantenstammdaten?', delay=0.5)
ev(type='stats', elapsed=10.0, backlog=0.0, delay=0.5)
time.sleep(0.2)
ev(type='fazit', teil='live', abschnitte=2)
ev(type='state', phase='fertig', session='live-x', dir=d, model='m', device='cpu')
"""


def test_live_runner_fuettert_den_souffleur(tmp_path):
    konfig = SouffleurKonfig(wiki_dir=None, uebergabe_dir=tmp_path / "ueb", backend="attrappe")
    gebaut = []

    def factory(opts):
        s = _attrappe(konfig)
        gebaut.append(s)
        return s

    (tmp_path / "live-x").mkdir()
    runner = LiveRunner()
    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda o: [sys.executable, "-c", CHILD, str(tmp_path / "live-x")],
        souffleur_factory=factory,
    )
    snap = _warte(runner)
    (souffleur,) = gebaut
    assert snap["souffleur"]["segmente"] == 2 and snap["souffleur"]["beendet"] is True
    assert souffleur.session_dir == tmp_path / "live-x"
    assert souffleur.uhr.jetzt() >= 10.0
    # Die Attrappe erkennt die Frage; der Hinweis kommt als eigenes Ereignis hinter den Segmenten.
    assert [e["type"] for e in snap["events"]] == ["segment", "segment", "hinweis"]
    hinweis = snap["events"][-1]
    assert hinweis["art"] == "frage" and hinweis["segment_id"] == 2 and hinweis["ohne_befund"] is True
    assert hinweis["verzoegerung_s"] is not None and hinweis["verzoegerung_real_s"] is not None
    assert (tmp_path / "live-x" / "souffleur.json").is_file()


def test_live_runner_ohne_factory_hat_keinen_souffleur(tmp_path):
    runner = LiveRunner()
    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda o: [sys.executable, "-c", "print('x')"],
    )
    assert _warte(runner)["souffleur"] is None


def test_live_runner_ueberlebt_kaputte_factory(tmp_path):
    runner = LiveRunner()

    def kaputt(opts):
        raise RuntimeError("kein Wiki heute")

    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda o: [sys.executable, "-c", "print('x')"],
        souffleur_factory=kaputt,
    )
    snap = _warte(runner)
    assert snap["souffleur"] is None and any("kein Wiki heute" in line for line in snap["lines"])


def test_hinweis_callback_landet_in_den_ereignissen(tmp_path):
    runner = LiveRunner()
    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda o: [sys.executable, "-c", "import time; time.sleep(0.3)"],
        souffleur_factory=lambda o: _attrappe(SouffleurKonfig(wiki_dir=None, uebergabe_dir=tmp_path)),
    )
    runner.souffleur().on_hinweis({"id": 1, "art": "frage", "aussage": "Wer?"})
    snap = _warte(runner)
    assert snap["events"][-1] == {"type": "hinweis", "id": 1, "art": "frage", "aussage": "Wer?"}


# --- Routen ----------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server, state

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "ui-state.json")
    monkeypatch.setattr(
        "audioscribe.live.kommando.inventory",
        lambda: {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": []},
    )
    return TestClient(server.create_app())


def test_essenz_route_ohne_sitzung(client):
    assert client.post("/api/souffleur/essenz", json={"minuten": 2}).status_code == 409
    assert client.post("/api/souffleur/essenz", json={"minuten": 3}).status_code == 400


def test_essenz_route_mit_replay_und_attrappe(client, tmp_path):
    from audioscribe.ui import state

    state.save_state({"souffleur_backend": "attrappe"})
    body = {"output_dir": str(tmp_path), "replay_transcript": str(MEETING), "replay_speed": 50}
    assert client.post("/api/live/start", json=body).status_code == 200
    ende = time.monotonic() + 30
    while time.monotonic() < ende:
        snap = client.get("/api/live/status").json()
        if not snap["running"]:
            break
        time.sleep(0.1)
    assert not snap["running"] and snap["souffleur"]["segmente"] == 10
    assert snap["souffleur"]["ki"]["zustand"] == "bereit"
    r = client.post("/api/souffleur/essenz", json={"minuten": 5})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ki_erzeugt"] is True and data["punkte"] and data["fenster"].startswith("00:00:00")
    sitzung = Path(snap["dir"])
    assert (sitzung / "souffleur-essenz.jsonl").is_file()
    # Leitplanke 4: der Souffleur hat am Transkript nichts geaendert.
    transkript = json.loads((sitzung / "transcript.json").read_text(encoding="utf-8"))
    assert len(transkript["paragraphs"]) >= 8


def test_toggle_route_merkt_zustand(client):
    from audioscribe.ui import state

    assert client.post("/api/souffleur/toggle", json={"aktiv": False}).json() == {"ok": True, "aktiv": False}
    assert state.load_state()["souffleur_aktiv"] is False


def test_state_route_merkt_souffleur_einstellungen(client, tmp_path):
    from audioscribe.ui import state

    r = client.post("/api/state", json={"wiki_dir": str(WIKI), "souffleur_model": "claude-opus-5", "uebergabe_dir": str(tmp_path)})
    assert r.status_code == 200
    saved = state.load_state()
    assert saved["wiki_dir"] == str(WIKI) and saved["souffleur_model"] == "claude-opus-5"
    # Leeres Feld = Wiki abhaengen (K1): der Schluessel verschwindet, der Zustand wird "keins".
    assert client.post("/api/state", json={"wiki_dir": ""}).status_code == 200
    assert "wiki_dir" not in state.load_state()
    assert client.get("/api/wiki/status").json()["zustand"] == "keins"


def test_wiki_status_route(client, tmp_path):
    from audioscribe.ui import state

    assert client.get("/api/wiki/status").json()["zustand"] == "keins"
    data = client.get(f"/api/wiki/status?path={WIKI}").json()
    assert data["zustand"] == "ok" and data["seiten"] == 4 and data["glossar_eintraege"] == 2
    assert client.get(f"/api/wiki/status?path={tmp_path / 'nix'}").json()["zustand"] == "fehler"
    state.save_state({"wiki_dir": str(WIKI)})
    assert client.get("/api/wiki/status").json()["zustand"] == "ok"


def test_defaults_liefern_souffleur_felder(client):
    data = client.get("/api/defaults").json()
    assert data["souffleur_models"][0]["id"] == "claude-sonnet-5" and "Standard" in data["souffleur_models"][0]["label"]
    assert all("claude" not in m["label"].lower() for m in data["souffleur_models"])
    assert data["souffleur_aktiv"] is True and "uebergabe_dir" in data and "wiki_dir" in data


def test_offene_punkte_route(client):
    assert client.get("/api/souffleur/offene-punkte").json() == {"punkte": []}
