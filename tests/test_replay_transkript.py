"""Transkript-Replay (FR-64): ein gespeichertes Transkript als Live-Sitzung abspielen."""

import json
from pathlib import Path

import pytest

from audioscribe.live import events
from audioscribe.live.replay_transkript import (
    MODE_REPLAY,
    ReplayOptions,
    TranskriptReplaySession,
    finde_transkript,
    lade_transkript,
)

DATA = Path(__file__).parent / "data" / "souffleur"
MEETING = DATA / "meeting"


def test_lade_transkript_json_liefert_absaetze_sortiert():
    segs = lade_transkript(MEETING / "transcript.json")
    assert len(segs) == 10
    assert [s.start for s in segs] == sorted(s.start for s in segs)
    assert segs[3].speaker == "Ich" and segs[3].text.endswith("?")
    assert segs[1].end == 12.0


def test_lade_transkript_markdown_nimmt_naechsten_start_als_ende():
    segs = lade_transkript(MEETING / "transkript.md")
    assert len(segs) == 10
    assert (segs[0].start, segs[0].end) == (0.0, 5.0)  # Markdown kennt nur den Anfang
    assert segs[-1].end > segs[-1].start
    assert segs[7].text == "Belege bewahren wir fünf Jahre auf."


def test_lade_transkript_markdown_ohne_fettdruck(tmp_path):
    # Von Hand geschriebene Transkripte: ``[HH:MM:SS] Sprecher: Text`` ohne ``**``.
    (tmp_path / "t.md").write_text(
        "# Meeting\n\n- Datum: 06.10.2026\n\n[00:00:03] Moderator: Guten Morgen.\n\n"
        "[00:00:07] Assistenz: Ja, alles gut: danke.\n", encoding="utf-8",
    )
    segs = lade_transkript(tmp_path / "t.md")
    assert [(s.start, s.end, s.speaker) for s in segs] == [(3.0, 7.0, "Moderator"), (7.0, 10.0, "Assistenz")]
    assert segs[1].text == "Ja, alles gut: danke."


def test_finde_transkript_bevorzugt_live_fassung_im_sitzungsordner(tmp_path):
    (tmp_path / "transcript.json").write_text("{}", encoding="utf-8")
    assert finde_transkript(tmp_path) == tmp_path / "transcript.json"
    (tmp_path / "transcript.live.json").write_text("{}", encoding="utf-8")
    assert finde_transkript(tmp_path) == tmp_path / "transcript.live.json"
    with pytest.raises(FileNotFoundError):
        finde_transkript(tmp_path / "fehlt")
    with pytest.raises(FileNotFoundError):
        finde_transkript(tmp_path / "leer")


def test_lade_transkript_lehnt_leere_dateien_ab(tmp_path):
    (tmp_path / "transcript.json").write_text(json.dumps({"paragraphs": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        lade_transkript(tmp_path / "transcript.json")
    (tmp_path / "x.md").write_text("# nur Kopf\n", encoding="utf-8")
    with pytest.raises(ValueError):
        lade_transkript(tmp_path / "x.md")


def test_replay_session_spielt_segmente_auf_der_sitzungsuhr_ab(tmp_path, monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", lambda msg: None)
    opts = ReplayOptions(output_dir=tmp_path, quelle=MEETING / "transcript.json", speed=40.0, delay_s=0.5)
    session = TranskriptReplaySession(opts)
    monkeypatch.setattr(session, "_watch_stdin", lambda: None)
    assert session.run() == 0

    phasen = [d["phase"] for typ, d in emitted if typ == events.STATE]
    assert phasen == ["laden", "laeuft", "stoppt", "fertig"]
    assert all(d.get("replay") is True for typ, d in emitted if typ == events.STATE)
    segs = [d for typ, d in emitted if typ == events.SEGMENT]
    assert len(segs) == 10
    assert [s["id"] for s in segs] == list(range(1, 11))
    assert segs[3]["track"] == "mic" and segs[0]["track"] == "system"
    assert segs[0]["delay"] == 0.5 and segs[0]["start"] == 0.0 and segs[0]["end"] == 4.0
    assert any(typ == events.STATS for typ, _ in emitted)
    fazit = [d for typ, d in emitted if typ == events.FAZIT]
    assert fazit and fazit[0]["teil"] == "live" and fazit[0]["abschnitte"] == 10

    # Sitzungsordner wie ein echter Live-Lauf - nur ohne Audio.
    assert session.dir.name.startswith("live-")
    assert (session.dir / "transkript.md").is_file() and (session.dir / "transkript.live.md").is_file()
    data = json.loads((session.dir / "transcript.json").read_text(encoding="utf-8"))
    # build_paragraphs legt Folgesaetze desselben Sprechers zusammen - der Wortlaut bleibt.
    assert data["mode"] == MODE_REPLAY and 8 <= len(data["paragraphs"]) <= 10
    assert "Die Freigabe von Rechnungen ab 10.000" in " ".join(p["text"] for p in data["paragraphs"])
    assert not (session.dir / "audio").exists()
    assert (session.dir / "bilanz.json").is_file()


def test_replay_session_stoppt_auf_befehl(tmp_path, monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", lambda msg: None)
    session = TranskriptReplaySession(ReplayOptions(output_dir=tmp_path, quelle=MEETING, speed=2.0))

    def sofort_stop():
        session._stop.set()

    monkeypatch.setattr(session, "_watch_stdin", sofort_stop)
    assert session.run() == 0
    assert len([1 for typ, _ in emitted if typ == events.SEGMENT]) < 10
    assert [d["phase"] for typ, d in emitted if typ == events.STATE][-1] == "fertig"


def test_replay_session_meldet_fehlende_quelle(tmp_path, monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    meldungen = []
    monkeypatch.setattr(events, "log", meldungen.append)
    session = TranskriptReplaySession(ReplayOptions(output_dir=tmp_path, quelle=tmp_path / "fehlt.json"))
    assert session.run() == 1
    assert "nicht gefunden" in meldungen[-1]
    assert not session.dir.exists()
    # Kein Verweis auf einen Sitzungsordner, den es nie gab.
    assert all("dir" not in d for typ, d in emitted if typ == events.STATE)


# --- CLI ----------------------------------------------------------------------------


def test_cli_live_transcript_zweigt_vor_dem_backend_ab(tmp_path, monkeypatch):
    from audioscribe import cli

    def kein_backend():
        raise AssertionError("Audio-Backend darf beim Transkript-Replay nicht geladen werden")

    monkeypatch.setattr(cli, "_prepare_backend", kein_backend)
    gestartet = []

    class FakeSession:
        def __init__(self, opts):
            gestartet.append(opts)

        def run(self):
            return 0

    monkeypatch.setattr("audioscribe.live.replay_transkript.TranskriptReplaySession", FakeSession)
    quelle = str(MEETING / "transcript.json")
    assert cli.main(["live", "--transcript", quelle, "--speed", "5", "--replay-delay", "1.5",
                     "--output", str(tmp_path)]) == 0
    (opts,) = gestartet
    assert opts.quelle == MEETING / "transcript.json" and opts.output_dir == tmp_path
    assert (opts.speed, opts.delay_s) == (5.0, 1.5)
    assert cli.main(["live", "--transcript", str(MEETING)]) == 0  # Sitzungsordner geht auch
    assert cli.main(["live", "--transcript", str(tmp_path / "fehlt.json")]) == 1
    assert cli.main(["live", "--transcript", quelle, "--speed", "0"]) == 1
    assert cli.main(["live", "--transcript", quelle, "--replay-delay", "-1"]) == 1


# --- Oberflaeche ------------------------------------------------------------------------


def test_build_live_argv_replay_ohne_geraete(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions, build_live_argv

    argv = build_live_argv(
        LiveJobOptions(output_dir=tmp_path, replay_transcript=MEETING, replay_speed=10.0), prefix=["x"]
    )
    assert argv[:2] == ["x", "live"]
    assert f"--transcript={MEETING}" in argv and "--speed=10" in argv
    assert not any(a.startswith(("--mic", "--loopback", "--monitor", "--model")) for a in argv)


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


def test_live_start_replay_route(client, tmp_path, monkeypatch):
    from audioscribe.ui import state
    from audioscribe.ui.runner import LiveRunner

    gestartet = []
    monkeypatch.setattr(LiveRunner, "start", lambda self, opts, **kw: gestartet.append(opts))
    body = {"output_dir": str(tmp_path), "replay_transcript": str(MEETING), "replay_speed": 20}
    assert client.post("/api/live/start", json=body).status_code == 200
    (opts,) = gestartet
    assert opts.replay_transcript == MEETING and opts.replay_speed == 20.0
    assert opts.refine is False and opts.mic == "none" and opts.monitor == 0
    saved = state.load_state()
    assert saved["live_source"] == "transcript" and saved["replay_speed"] == "20"
    assert Path(saved["replay_transcript"]) == MEETING
    defaults = client.get("/api/live/defaults").json()
    assert defaults["source"] == "transcript" and defaults["replay_speeds"] == [1.0, 2.0, 5.0, 10.0, 20.0]

    # Die Auswahl wird schon vor dem Start gemerkt - ein Neuladen der Seite behaelt sie.
    assert client.post("/api/state", json={"replay_speed": "5", "replay_transcript": "x.md"}).status_code == 200
    saved = state.load_state()
    assert (saved["replay_speed"], saved["replay_transcript"]) == ("5", "x.md")
    assert client.get("/api/live/defaults").json()["replay_speed"] == "5"

    fehlt = {**body, "replay_transcript": str(tmp_path / "fehlt")}
    assert client.post("/api/live/start", json=fehlt).status_code == 400
    assert client.post("/api/live/start", json={**body, "replay_speed": 0}).status_code == 400


def test_live_runner_merkt_replay_modus(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions
    from audioscribe.ui.runner import LiveRunner

    runner = LiveRunner()
    runner.start(
        LiveJobOptions(output_dir=tmp_path, replay_transcript=MEETING),
        argv_builder=lambda o: [__import__("sys").executable, "-c", "print('hallo')"],
    )
    runner._thread.join(10)
    snap = runner.snapshot()
    assert snap["replay"] is True and snap["error"] is None


def test_live_runner_meldet_letzte_zeile_als_fehler(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions
    from audioscribe.ui.runner import LiveRunner

    runner = LiveRunner()
    skript = "import sys; print('Keine Absätze mit Zeitstempel in x.md'); sys.exit(1)"
    runner.start(
        LiveJobOptions(output_dir=tmp_path, replay_transcript=MEETING),
        argv_builder=lambda o: [__import__("sys").executable, "-c", skript],
    )
    runner._thread.join(10)
    snap = runner.snapshot()
    assert snap["phase"] == "fehler" and snap["dir"] is None
    assert snap["error"] == "Keine Absätze mit Zeitstempel in x.md"


# --- Pausen raffen (Demo) ----------------------------------------------------------------


def test_raffen_behaelt_reihenfolge_und_wortlaut_und_streicht_leerlauf():
    from audioscribe.live.replay_transkript import raffe
    from audioscribe.models import Segment

    original = [
        Segment(3.0, 60.0, "Guten Morgen.", "Moderator"),  # 57 s bis zum naechsten Beitrag
        Segment(60.0, 61.0, "Ja.", "Assistenz"),  # schon kurz - wird nicht laenger
        Segment(61.0, 200.0, "x" * 200, "Moderator"),  # langer Beitrag: Sprechzeit zaehlt
    ]
    gerafft = raffe(original)
    assert [(s.text, s.speaker) for s in gerafft] == [(s.text, s.speaker) for s in original]
    assert gerafft[0].start == 1.0 and gerafft[0].end == 2.5  # Vorlauf 1 s, Mindestdauer 1,5 s
    assert gerafft[1].start == gerafft[0].end and gerafft[1].end - gerafft[1].start == 1.5
    assert round(gerafft[2].end - gerafft[2].start, 2) == 10.6  # 200 Zeichen / 20 + 0,6 s
    assert all(a.end == b.start for a, b in zip(gerafft, gerafft[1:]))  # lueckenlos
    assert raffe([]) == []


def test_demo_transkript_ist_gerafft_nach_einer_halben_minute_beim_thema():
    from pathlib import Path

    from audioscribe.live.replay_transkript import lade_transkript, raffe

    demo = Path(__file__).resolve().parents[1] / "demo" / "llm-wiki" / "live_bahn_test" / "transkript.md"
    if not demo.is_file():
        pytest.skip("Demo-Daten fehlen")
    original = lade_transkript(demo)
    gerafft = raffe(original)
    klasse = next(i for i, s in enumerate(original) if "länger als drei Stunden" in s.text)
    assert original[klasse].end > 80  # im Original erst nach knapp anderthalb Minuten ausgesprochen
    assert 25 <= gerafft[klasse].end <= 40  # gerafft nach rund einer halben Minute
    assert gerafft[-1].end < original[-1].end / 3


def test_argv_und_cli_reichen_raffen_durch(tmp_path, monkeypatch):
    from audioscribe import cli
    from audioscribe.live import replay_transkript
    from audioscribe.ui.jobs import LiveJobOptions, build_live_argv

    quelle = tmp_path / "transkript.md"
    quelle.write_text("[00:00:03] A: Hallo.\n", encoding="utf-8")
    argv = build_live_argv(LiveJobOptions(output_dir=tmp_path, replay_transcript=quelle, replay_raffen=True), prefix=["x"])
    assert "--raffen" in argv
    assert "--raffen" not in build_live_argv(LiveJobOptions(output_dir=tmp_path, replay_transcript=quelle), prefix=["x"])

    gesehen = {}

    class Sitzung:
        def __init__(self, opts):
            gesehen["opts"] = opts

        def run(self):
            return 0

    monkeypatch.setattr(replay_transkript, "TranskriptReplaySession", Sitzung)
    assert cli.main(["live", f"--output={tmp_path}", f"--transcript={quelle}", "--raffen"]) == 0
    assert gesehen["opts"].raffen is True


# --- Pause (Demo) ------------------------------------------------------------------------


def test_pause_haelt_die_sitzungsuhr_an(tmp_path, monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", lambda msg: None)
    jetzt = [100.0]
    from audioscribe.live import replay_transkript

    monkeypatch.setattr(replay_transkript.time, "monotonic", lambda: jetzt[0])
    session = TranskriptReplaySession(ReplayOptions(output_dir=tmp_path, quelle=MEETING, speed=2.0))
    session._t0 = 100.0
    jetzt[0] = 110.0
    assert session.clock() == 20.0  # 10 s real bei Tempo 2
    session.pausiere(True)
    jetzt[0] = 170.0
    assert session.clock() == 20.0  # eine Minute Pause: die Uhr steht
    session.pausiere(True)  # doppelt gedrueckt: aendert nichts
    session.pausiere(False)
    jetzt[0] = 175.0
    assert session.clock() == 30.0  # laeuft dort weiter, wo sie stand
    zustaende = [(d["phase"], d["pausiert"]) for typ, d in emitted if typ == events.STATE]
    assert zustaende == [("laeuft", True), ("laeuft", False)]


def test_stdin_befehle_pause_und_weiter(tmp_path, monkeypatch):
    import io

    monkeypatch.setattr(events, "emit", lambda typ, **d: None)
    monkeypatch.setattr(events, "log", lambda msg: None)
    session = TranskriptReplaySession(ReplayOptions(output_dir=tmp_path, quelle=MEETING))
    gesehen = []
    monkeypatch.setattr(session, "pausiere", gesehen.append)
    monkeypatch.setattr("sys.stdin", io.StringIO("pause\nquatsch\nWeiter\nstop\npause\n"))
    session._watch_stdin()
    assert gesehen == [True, False] and session._stop.is_set()  # nach "stop" wird nichts mehr gelesen


def test_live_runner_pausiert_nur_ein_laufendes_replay(tmp_path):
    import sys
    import time

    from audioscribe.ui.jobs import LiveJobOptions
    from audioscribe.ui.runner import LiveRunner

    kind = tmp_path / "kind.py"
    kind.write_text(
        "import json, sys\n"
        "def state(**d): print('[Live] ' + json.dumps({'type': 'state', **d}), flush=True)\n"
        "state(phase='laeuft')\n"
        "for line in sys.stdin:\n"
        "    b = line.strip()\n"
        "    if b == 'stop': break\n"
        "    state(phase='laeuft', pausiert=(b == 'pause'))\n"
        "state(phase='fertig')\n",
        encoding="utf-8",
    )

    def warte(runner, bedingung):
        ende = time.monotonic() + 20
        while time.monotonic() < ende:
            if bedingung(runner.snapshot()):
                return runner.snapshot()
            time.sleep(0.05)
        raise AssertionError(runner.snapshot())

    runner = LiveRunner()
    with pytest.raises(RuntimeError):
        runner.pause(True)  # nichts laeuft
    runner.start(LiveJobOptions(output_dir=tmp_path, replay_transcript=MEETING), argv_builder=lambda o: [sys.executable, str(kind)])
    warte(runner, lambda s: s["phase"] == "laeuft")
    assert runner.snapshot()["pausiert"] is False
    runner.pause(True)
    warte(runner, lambda s: s["pausiert"] is True)
    runner.pause(False)
    warte(runner, lambda s: s["pausiert"] is False)
    runner.pause(True)
    warte(runner, lambda s: s["pausiert"] is True)
    runner.stop()
    ende = warte(runner, lambda s: not s["running"])
    assert ende["pausiert"] is False and ende["phase"] == "beendet"

    # Eine echte Aufnahme laesst sich nicht pausieren.
    aufnahme = LiveRunner()
    aufnahme.start(LiveJobOptions(output_dir=tmp_path, refine=False), argv_builder=lambda o: [sys.executable, str(kind)])
    warte(aufnahme, lambda s: s["phase"] == "laeuft")
    with pytest.raises(RuntimeError, match="Aufnahme"):
        aufnahme.pause(True)
    aufnahme.stop()
    warte(aufnahme, lambda s: not s["running"])


def test_route_pause_ohne_laufendes_abspielen(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import runner as runner_modul
    from audioscribe.ui import server

    client = TestClient(server.create_app())
    assert client.post("/api/live/pause", json={"pausiert": True}).status_code == 409
    gesehen = []
    monkeypatch.setattr(runner_modul.LiveRunner, "pause", lambda self, an: gesehen.append(an))
    assert client.post("/api/live/pause", json={"pausiert": True}).json() == {"ok": True, "pausiert": True}
    assert client.post("/api/live/pause", json={"pausiert": False}).status_code == 200 and gesehen == [True, False]
