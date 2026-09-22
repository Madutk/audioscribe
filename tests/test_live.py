"""Live-Transkription (PRD §17): reine Bausteine ohne Audio-Hardware und ohne Modelle."""

import json
import threading

import numpy as np
import pytest

from audioscribe.live import events
from audioscribe.live.board import Job, JobBoard
from audioscribe.live.chunker import Chunker, Utterance
from audioscribe.live.devices import pick
from audioscribe.live.screen import ChangeDetector
from audioscribe.live.speakers import GEGENSEITE, ICH, OnlineClusterer, SpeakerLabeler
from audioscribe.live.store import keep_live_copy, session_name, write_transcript
from audioscribe.live.track import SAMPLE_RATE, Resampler, Track, load_wav
from audioscribe.models import Segment

SR = SAMPLE_RATE

# --- Ereignisprotokoll -------------------------------------------------------------


def test_event_roundtrip_keeps_umlauts():
    line = events.event_line(events.SEGMENT, id=1, text="Grüße")
    assert "Grüße" in line
    assert events.parse_event(line) == {"type": "segment", "id": 1, "text": "Grüße"}


@pytest.mark.parametrize("line", ["Lade Modell ...", "[Live] kaputt", '[Live] ["liste"]', "[Live] {}"])
def test_parse_event_ignores_everything_else(line):
    assert events.parse_event(line) is None


# --- Resampler / Spur --------------------------------------------------------------


def test_resampler_blockwise_matches_one_shot():
    from scipy.signal import resample_poly

    rng = np.random.default_rng(1)
    t = np.arange(48_000) / 48_000
    x = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    res = Resampler(48_000)
    out, pos = [], 0
    while pos < len(x):
        n = int(rng.integers(100, 6000))
        out.append(res.process(x[pos : pos + n]))
        pos += n
    y = np.concatenate(out)
    ref = resample_poly(x, 1, 3)
    # Der Resampler haelt nur den rechten Kontext zurueck; der Rest ist nahtlos.
    assert len(ref) - len(y) < 100
    assert np.abs(y[50:] - ref[50 : len(y)]).max() < 1e-4


def _pcm(seconds: float, rate: int, channels: int = 1, amp: float = 0.5) -> bytes:
    n = int(seconds * rate)
    mono = (amp * 32767 * np.sin(2 * np.pi * 300 * np.arange(n) / rate)).astype(np.int16)
    return np.repeat(mono, channels).tobytes()


def test_track_fills_loopback_silence_with_zeros(tmp_path):
    track = Track("system", 48_000, 2, tmp_path / "audio" / "system.wav")
    track.feed(_pcm(1.0, 48_000, 2), t_arrival=1.0)
    # Zehn Sekunden Stille: WASAPI-Loopback liefert nichts - dann kommt wieder Ton.
    track.feed(_pcm(1.0, 48_000, 2), t_arrival=12.0)
    start, samples = track.take(12.0)
    assert start == 0
    assert abs(len(samples) - 12 * SR) < 0.05 * SR
    assert np.abs(samples[2 * SR : 10 * SR]).max() == 0.0
    assert np.abs(samples[-SR // 2 :]).max() > 0.3
    track.close()
    assert abs(len(load_wav(tmp_path / "audio" / "system.wav")) - 12 * SR) < 0.05 * SR


def test_track_take_advances_timeline_while_source_is_silent():
    track = Track("system", 16_000, 1)
    track.feed(_pcm(1.0, 16_000), t_arrival=1.0)
    first_start, first = track.take(1.0)
    second_start, second = track.take(5.0)  # nichts geliefert -> Stille bis kurz vor "jetzt"
    assert (first_start, len(first)) == (0, SR)
    assert second_start == SR
    assert 3.5 * SR < len(second) < 4 * SR and not second.any()


def test_load_wav_survives_unfinished_header(tmp_path):
    path = tmp_path / "crash.wav"
    data = (np.ones(1000) * 1000).astype("<i2").tobytes()
    path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
                     b"\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00" + data)
    assert len(load_wav(path)) == 1000


# --- Schnitt an Sprechpausen -------------------------------------------------------


def energy_vad(audio: np.ndarray) -> list[tuple[int, int]]:
    """Attrappe: 'Sprache' ist alles ueber einer Pegelschwelle (10-ms-Raster)."""
    hop = SR // 100
    active = [np.abs(audio[i : i + hop]).max() > 0.1 for i in range(0, len(audio), hop)]
    out, start = [], None
    for i, a in enumerate([*active, False]):
        if a and start is None:
            start = i
        elif not a and start is not None:
            out.append((start * hop, min(i * hop, len(audio))))
            start = None
    return out


def speech(seconds: float) -> np.ndarray:
    return np.full(int(seconds * SR), 0.5, dtype=np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


def feed_all(chunker: Chunker, parts: list[np.ndarray], start: int = 0) -> int:
    for part in parts:
        chunker.feed(start, part)
        start += len(part)
    return start


def test_chunker_closes_utterance_after_pause():
    chunker = Chunker(energy_vad)
    feed_all(chunker, [silence(1), speech(2), silence(0.3)])
    assert chunker.poll() == []  # Pause noch zu kurz
    assert chunker.open_utterance() is not None
    chunker.feed(int(3.3 * SR), silence(0.5))
    (utt,) = chunker.poll()
    assert (round(utt.start_s, 2), round(utt.end_s, 2)) == (1.0, 3.0)
    assert chunker.open_utterance() is None


def test_chunker_keeps_short_breath_pause_inside_utterance():
    chunker = Chunker(energy_vad)
    feed_all(chunker, [speech(1), silence(0.4), speech(1), silence(1)])
    (utt,) = chunker.poll()
    assert round(utt.duration_s, 1) == 2.4


def test_chunker_timeline_stays_absolute_after_trimming():
    chunker = Chunker(energy_vad)
    pos = feed_all(chunker, [speech(1), silence(1)])
    chunker.poll()
    feed_all(chunker, [silence(20), speech(1), silence(1)], start=pos)
    (utt,) = chunker.poll()
    assert round(utt.start_s, 1) == 22.0


def test_chunker_forces_cut_at_breath_pause_of_long_utterance():
    chunker = Chunker(energy_vad, max_s=12.0)
    feed_all(chunker, [speech(8), silence(0.4), speech(5)])
    (utt,) = chunker.poll()
    assert round(utt.end_s, 1) == 8.2  # Mitte der Atempause, nicht stumpf bei 12 s
    assert chunker.open_utterance() is not None


def test_chunker_flush_closes_open_utterance():
    chunker = Chunker(energy_vad)
    feed_all(chunker, [silence(0.5), speech(1)])
    assert chunker.poll() == []
    (utt,) = chunker.poll(flush=True)
    assert round(utt.duration_s, 1) == 1.0


# --- Auftragsbrett -----------------------------------------------------------------


def utt(seconds: float = 2.0, start: int = 0) -> Utterance:
    return Utterance(start, start + int(seconds * SR), np.zeros(1, dtype=np.float32))


def test_board_prefers_finals_and_keeps_only_latest_partial():
    board = JobBoard()
    board.put_partial(Job("mic", utt(start=1), final=False))
    board.put_partial(Job("mic", utt(start=2), final=False))
    board.put_final(Job("system", utt(3.0), final=True))
    first = board.get(0)
    assert first.final and board.backlog_s() == 3.0
    board.done(first)
    second = board.get(0)
    assert not second.final and second.utterance.start == 2
    assert board.get(0) is None and board.backlog_s() == 0.0


def test_board_final_discards_partial_of_same_track():
    board = JobBoard()
    board.put_partial(Job("mic", utt(), final=False))
    board.put_final(Job("mic", utt(), final=True))
    board.done(board.get(0))
    assert board.get(0) is None


def test_board_wait_idle_wakes_up_when_worker_finishes():
    board = JobBoard()
    board.put_final(Job("mic", utt(), final=True))
    job = board.get(0)
    assert not board.wait_idle(0.01)
    threading.Timer(0.05, board.done, args=(job,)).start()
    assert board.wait_idle(2.0)


# --- Sprecher ----------------------------------------------------------------------


def test_clusterer_keeps_speakers_stable():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=64), rng.normal(size=64)
    noisy = lambda v: v + 0.2 * rng.normal(size=64)  # noqa: E731
    clusterer = OnlineClusterer(threshold=0.4)
    assert [clusterer.assign(noisy(v)) for v in (a, b, a, a, b)] == [0, 1, 0, 0, 1]
    assert clusterer.assign(np.full(64, np.nan)) is None


def test_clusterer_caps_number_of_speakers():
    clusterer = OnlineClusterer(threshold=0.99, max_speakers=2)
    eye = np.eye(8)
    assert [clusterer.assign(eye[i]) for i in range(4)] == [0, 1, 0, 0]


def test_labeler_channels_and_short_utterances():
    calls = []

    def embedder(audio):
        calls.append(len(audio))
        return np.eye(4)[0 if len(audio) == 2 * SR else 1]

    labeler = SpeakerLabeler(embedder)
    assert labeler.label("mic", speech(3)) == ICH and not calls
    assert labeler.label("system", speech(2)) == "Sprecher 1"
    assert labeler.label("system", speech(3)) == "Sprecher 2"
    assert labeler.label("system", speech(0.5)) == "Sprecher 2"  # zu kurz -> erbt
    assert len(calls) == 2
    assert SpeakerLabeler(None).label("system", speech(2)) == GEGENSEITE


# --- Geraetewahl -------------------------------------------------------------------

DEVICES = [{"index": 5, "name": "A", "default": False}, {"index": 7, "name": "B", "default": True}]


def test_pick_device():
    assert pick(DEVICES, "default")["index"] == 7
    assert pick(DEVICES, "5")["index"] == 5
    assert pick(DEVICES, "none") is None
    assert pick([], "default") is None
    with pytest.raises(RuntimeError):
        pick(DEVICES, "99")


# --- Bildwechsel -------------------------------------------------------------------


def grid(value: int) -> np.ndarray:
    return np.full((9, 16), value, dtype=np.float64)


def run_detector(detector: ChangeDetector, frames: list[int], fps: float = 2.0) -> list[float]:
    shots = []
    for i, value in enumerate(frames):
        t = detector.feed(i / fps, grid(value))
        if t is not None:
            shots.append(t)
    return shots


def test_detector_start_image_and_shot_after_screen_settles():
    frames = [0] * 10 + [50, 100, 150] + [150] * 6
    # Wechsel laeuft ueber die Abtastungen 10..12 (5.0-6.0 s); das Bild traegt den
    # Zeitpunkt des letzten Treffers.
    assert run_detector(ChangeDetector(min_gap=4.0), frames) == [0.0, 6.0]


def test_detector_ignores_mouse_pointer():
    detector = ChangeDetector("mittel")
    assert detector.feed(0.0, grid(0)) == 0.0
    pointer = grid(0)
    pointer[4, 4] = 200  # ein Block von 144
    assert detector.feed(0.5, pointer) is None
    assert all(detector.feed(1 + i / 2, grid(0)) is None for i in range(10))


def test_detector_defers_change_inside_min_gap_instead_of_dropping_it():
    frames = [0, 0, 100, 100, 100] + [100] * 10
    shots = run_detector(ChangeDetector(min_gap=4.0), frames)
    assert shots == [0.0, 1.0]  # Wechsel bei 1.0 s, gesichert sobald 4 s Abstand erreicht sind


def test_detector_continuous_motion_still_yields_images():
    frames = [i % 2 * 100 for i in range(100)]  # 50 s Dauerflackern
    shots = run_detector(ChangeDetector(min_gap=4.0), frames)
    assert len(shots) == 3 and shots[1] == pytest.approx(20.5)


# --- Ablage ------------------------------------------------------------------------


def test_session_folder_is_a_valid_analysis_source(tmp_path):
    from audioscribe.agent.material import find_transcript
    from audioscribe.review.marks import Mark, save_marks
    from audioscribe.ui.jobs import scan_results

    session = tmp_path / session_name()
    session.mkdir()
    save_marks(session, [Mark(t=3.0, png="frames/0001_00-00-03.jpg", id=1, kind="auto")])
    segments = [
        Segment(5.0, 7.0, "Guten Morgen.", "Sprecher 1"),
        Segment(0.5, 4.0, "Hallo zusammen.", ICH),
    ]
    write_transcript(session, segments, duration_s=8.0, language="de", model="small", mode="live")

    md = (session / "transkript.md").read_text(encoding="utf-8")
    assert md.index("Ich:** Hallo") < md.index("Sprecher 1:** Guten")  # nach Zeit sortiert
    data = json.loads((session / "transcript.json").read_text(encoding="utf-8"))
    assert data["mode"] == "live" and data["num_speakers"] == 2
    assert "#0001" in (session / "transkript.annotiert.md").read_text(encoding="utf-8")

    assert find_transcript(session).name == "transkript.annotiert.md"
    assert [r["name"] for r in scan_results(tmp_path)] == [session.name]


def test_keep_live_copy_never_overwrites_during_refine(tmp_path):
    (tmp_path / "transkript.md").write_text("live", encoding="utf-8")
    keep_live_copy(tmp_path, overwrite=True)
    (tmp_path / "transkript.md").write_text("geschaerft", encoding="utf-8")
    keep_live_copy(tmp_path, overwrite=False)
    assert (tmp_path / "transkript.live.md").read_text(encoding="utf-8") == "live"


# --- LiveRunner (ohne Modelle: das Kind ist ein python -c-Einzeiler) ---------------

CHILD = r"""
import sys, json
def ev(**d): print("[Live] " + json.dumps(d), flush=True)
state = dict(session="live-x", dir=sys.argv[1], model="small", device="cpu")
ev(type="state", phase="laeuft", **state)
print("Spur 'mic': Test", flush=True)
ev(type="partial", track="system", start=0.2, text="Gu")
ev(type="partial", track="mic", start=0.5, text="Hal")
ev(type="segment", id=1, track="mic", speaker="Ich", start=0.5, end=2.0, text="Hallo", delay=1.2)
ev(type="shot", id=1, t=0.0, file="0001_00-00-00.jpg")
ev(type="stats", elapsed=3.0, backlog=0.0, delay=1.2, level_mic=0.2, level_sys=None, partials_paused=False)
for line in sys.stdin:
    if line.strip() == "stop":
        break
ev(type="state", phase="fertig", **state)
"""

REFINE = "print('[Stufe 1/2] Transkription Mikrofon', flush=True); print('[Fortschritt] 50.0%', flush=True)"


def wait_for(condition, timeout: float = 15.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Zeit abgelaufen")


def start_runner(tmp_path, *, refine: bool):
    import sys

    from audioscribe.ui.jobs import LiveJobOptions
    from audioscribe.ui.runner import LiveRunner

    runner = LiveRunner()
    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=refine),
        argv_builder=lambda opts: [sys.executable, "-c", CHILD, str(tmp_path)],
        refine_builder=lambda session, opts: [sys.executable, "-c", REFINE],
    )
    return runner


def test_live_runner_collects_events_and_stops_gracefully(tmp_path):
    runner = start_runner(tmp_path, refine=True)
    snap = wait_for(lambda: (s := runner.snapshot()) and s["stats"] and s)
    assert [e["type"] for e in snap["events"]] == ["segment", "shot"]
    assert list(snap["partials"]) == ["system"]  # das Segment hat die mic-Vorschau abgeloest
    assert snap["phase"] == "laeuft" and runner.session_dir() == tmp_path
    assert "Spur 'mic': Test" in snap["lines"]
    assert runner.snapshot(ev_offset=snap["ev_offset"])["events"] == []

    with pytest.raises(RuntimeError):
        start_runner_again = runner.start  # Doppelstart
        from audioscribe.ui.jobs import LiveJobOptions

        start_runner_again(LiveJobOptions(output_dir=tmp_path))

    runner.stop()
    done = wait_for(lambda: (s := runner.snapshot()) and not s["running"] and s)
    assert done["phase"] == "beendet" and done["returncode"] == 0
    assert done["refine"] == {"index": 1, "total": 2, "name": "Transkription Mikrofon", "percent": 50.0}
    assert done["partials"] == {}


def test_live_runner_second_stop_kills_and_skips_refine(tmp_path):
    runner = start_runner(tmp_path, refine=True)
    wait_for(lambda: runner.snapshot()["stats"])
    with runner._lock:
        runner._info["stopping"] = True  # als waere das sanfte Stopp schon unterwegs
    runner.stop()
    done = wait_for(lambda: (s := runner.snapshot()) and not s["running"] and s)
    assert done["phase"] == "fehler" and done["refine"] is None


def test_live_runner_reset_discards_running_session(tmp_path):
    runner = start_runner(tmp_path, refine=True)
    wait_for(lambda: runner.snapshot()["stats"])
    assert runner.reset() == tmp_path  # Ordner der verworfenen Sitzung
    snap = runner.snapshot()
    assert snap["running"] is False and "phase" not in snap and "dir" not in snap
    assert snap["events"] == [] and snap["lines"] == [] and snap["offset"] == 0 and snap["ev_offset"] == 0
    assert snap.get("refine") is None  # kein Nachschaerfen nach dem Verwerfen
    assert runner.session_dir() is None
    # danach geht ein Neustart, als waere nie etwas gewesen
    import sys

    from audioscribe.ui.jobs import LiveJobOptions

    runner.start(
        LiveJobOptions(output_dir=tmp_path, refine=False),
        argv_builder=lambda opts: [sys.executable, "-c", CHILD, str(tmp_path)],
    )
    wait_for(lambda: runner.snapshot()["stats"])
    runner.stop()
    assert wait_for(lambda: (s := runner.snapshot()) and not s["running"] and s)["phase"] == "beendet"


def test_live_runner_reset_after_end_clears_state(tmp_path):
    runner = start_runner(tmp_path, refine=False)
    wait_for(lambda: runner.snapshot()["stats"])
    runner.stop()
    wait_for(lambda: not runner.snapshot()["running"])
    assert runner.reset() == tmp_path
    assert runner.snapshot() == {"running": False, "offset": 0, "lines": [], "events": [], "ev_offset": 0, "partials": {}}
    assert runner.reset() is None  # ein zweites Mal ist harmlos


def test_build_live_argv_and_refine_argv(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions, build_live_argv, build_refine_argv

    opts = LiveJobOptions(output_dir=tmp_path, monitor=2, mic="23", loopback="none", partials=False)
    argv = build_live_argv(opts, prefix=["audioscribe"])
    assert argv[:2] == ["audioscribe", "live"]
    assert {"--monitor=2", "--mic=23", "--loopback=none", "--model=auto", "--no-partials"} <= set(argv)
    assert "--no-speakers" not in argv
    assert build_refine_argv(tmp_path / "live-x", opts, prefix=["audioscribe"])[:3] == [
        "audioscribe", "refine", str(tmp_path / "live-x")
    ]


# --- Routen ------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server, state

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "ui-state.json")
    monkeypatch.setattr(
        "audioscribe.live.kommando.inventory",
        lambda: {"mics": [], "loopbacks": [], "monitors": [], "problems": ["Attrappe"]},
    )
    return TestClient(server.create_app())


def test_live_defaults_route(client):
    data = client.get("/api/live/defaults").json()
    assert data["models"][0] == "auto" and "large-v3-turbo" in data["models"]
    assert data["problems"] == ["Attrappe"] and data["refine"] is True


def test_live_start_rejects_bad_input(client, tmp_path):
    base = {"output_dir": str(tmp_path)}
    assert client.post("/api/live/start", json={**base, "model": "--evil"}).status_code == 400
    assert client.post("/api/live/start", json={**base, "device": "tpu"}).status_code == 400
    nothing = {**base, "monitor": 0, "mic": "none", "loopback": "none"}
    assert client.post("/api/live/start", json=nothing).status_code == 400


def test_live_reset_route_without_session(client):
    assert client.post("/api/live/reset").json() == {"ok": True, "discarded": None}


def test_live_frame_route_without_session(client):
    assert client.get("/api/live/frame/0001_00-00-00.jpg").status_code == 404
    assert client.get("/api/live/frame/..%5Cmarks.json").status_code == 404


def test_first_tab_is_renamed():
    from pathlib import Path

    from audioscribe.ui import server

    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert html.index(">Offline Transcription<") < html.index(">Live Transcription<") < html.index(">KI-Analyse<")
