"""Live-Transkription (PRD §17): reine Bausteine ohne Audio-Hardware und ohne Modelle."""

import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from audioscribe.live import events, fenster
from audioscribe.live.asr import decode_options
from audioscribe.live.board import Job, JobBoard
from audioscribe.live.chunker import Chunker, Utterance, merge_utterances
from audioscribe.live.devices import pick
from audioscribe.live.fenster import WindowGone
from audioscribe.live.screen import ChangeDetector
from audioscribe.live.speakers import (
    GEGENSEITE,
    ICH,
    BackgroundEmbedder,
    OnlineClusterer,
    SpeakerLabeler,
)
from audioscribe.live.store import MIC_WAV, SYSTEM_WAV, keep_live_copy, session_name, write_transcript
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


def test_resampler_441_keeps_small_context_and_flushes_the_rest():
    from scipy.signal import resample_poly

    t = np.arange(44_100) / 44_100
    x = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    res = Resampler(44_100)
    assert res._ctx == 441  # 10 ms, nicht 32 * 441 = 0,32 s
    blocks = [res.process(x[pos : pos + 4410]) for pos in range(0, len(x), 4410)]
    y = np.concatenate([*blocks, res.flush()])
    ref = resample_poly(x, 160, 441)
    assert len(y) == len(ref) == 16_000
    assert np.abs(y[50:-50] - ref[50:-50]).max() < 1e-3


def test_track_close_appends_held_back_resampler_rest(tmp_path):
    track = Track("mic", 44_100, 1, tmp_path / "audio" / "mikrofon.wav")
    track.feed(_pcm(1.0, 44_100), t_arrival=1.0)
    _, vorher = track.take(1.0)
    track.close()
    track.close()  # zweites Schließen schadet nicht
    _, rest = track.take(1.0)
    assert len(vorher) < SAMPLE_RATE and len(vorher) + len(rest) == SAMPLE_RATE
    assert len(load_wav(tmp_path / "audio" / "mikrofon.wav")) == SAMPLE_RATE


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
    assert utt.schluss == "zeitlimit"
    assert chunker.open_utterance() is not None


def test_chunker_hard_cut_without_any_breath_pause():
    chunker = Chunker(energy_vad, max_s=12.0)
    feed_all(chunker, [speech(13)])
    (utt,) = chunker.poll()
    assert (round(utt.start_s, 1), round(utt.end_s, 1), utt.schluss) == (0.0, 12.0, "zeitlimit")


def test_chunker_hard_cut_does_not_pad_across_the_seam():
    # Ohne Atempause liegt der Schnitt mitten im Wort; der Rest beginnt genau dort,
    # also darf der geschlossene Teil nicht darüber hinaus gepolstert sein.
    chunker = Chunker(energy_vad, max_s=12.0)
    feed_all(chunker, [silence(1), speech(13)])
    (utt,) = chunker.poll()
    assert len(utt.audio) == int(12.15 * SR)  # 0,15 s Polster vorn, keins hinten
    rest = chunker.open_utterance()
    assert rest.start_s == utt.end_s


def test_chunker_flush_closes_open_utterance():
    chunker = Chunker(energy_vad)
    feed_all(chunker, [silence(0.5), speech(1)])
    assert chunker.poll() == []
    (utt,) = chunker.poll(flush=True)
    assert round(utt.duration_s, 1) == 1.0
    assert utt.schluss == "flush"


def test_chunker_marks_pause_closed_utterance_also_on_flush():
    chunker = Chunker(energy_vad)
    feed_all(chunker, [speech(1), silence(1)])
    (utt,) = chunker.poll(flush=True)
    assert utt.schluss == "pause"  # die Pause war da, der Flush hat nichts abgeschnitten


def test_merge_utterances_spans_parts_with_short_gap_of_silence():
    a = Utterance(SR, 3 * SR, speech(2))
    b = Utterance(10 * SR, 11 * SR, speech(1), schluss="zeitlimit")
    merged = merge_utterances([a, b], gap_s=0.3)
    assert (merged.start_s, merged.end_s) == (1.0, 11.0)
    assert len(merged.audio) == int(3.3 * SR)  # 2 s + 0,3 s Stille + 1 s, nicht die echte Luecke
    assert merge_utterances([a]) is a
    # Fuers Diagnose-Log: Schluss des letzten Teils, Latenz ab Ende des ersten Teils.
    assert merged.schluss == "zeitlimit"
    assert merged.teile_end_s == (3.0, 11.0) and merged.erster_teil_end_s == 3.0
    assert a.erster_teil_end_s == 3.0


# --- Auftragsbrett -----------------------------------------------------------------


def utt(seconds: float = 2.0, start: int = 0) -> Utterance:
    return Utterance(start, start + int(seconds * SR), np.zeros(1, dtype=np.float32))


def utt_at(start_s: float, seconds: float) -> Utterance:
    return Utterance(int(start_s * SR), int((start_s + seconds) * SR), speech(seconds))


def test_board_coalesces_waiting_finals_of_same_track():
    board = JobBoard(coalesce_s=25.0)
    for start, dur in ((0, 2), (2.5, 3), (6, 4)):
        board.put_final(Job("system", utt_at(start, dur), final=True, t_abgeschlossen=start + dur))
    assert board.backlog_s() == 9.0
    job = board.get(0)
    assert job.parts == 3 and job.track == "system"
    assert (job.utterance.start_s, job.utterance.end_s) == (0.0, 10.0)
    assert job.t_abgeschlossen == 10.0  # der letzte Teil
    assert board.backlog_s() == 0.0  # in Arbeit heisst nicht wartend
    board.done(job)
    assert board.get(0) is None and board.backlog_s() == 0.0


def test_board_coalesces_only_above_catchup_threshold():
    # Kurzer Rückstand: einzeln lassen, sonst teilen sich zwei Sprecher ein Label.
    board = JobBoard(coalesce_s=25.0, catchup_s=5.0)
    board.put_final(Job("system", utt_at(0.0, 1), final=True))
    board.put_final(Job("system", utt_at(1.5, 1), final=True))
    job = board.get(0)
    assert job.parts == 1 and job.utterance.end_s == 1.0
    board.done(job)
    board.done(board.get(0))
    # Über der Schwelle wartend: zusammenlegen.
    for start in (10.0, 13.5, 17.0):
        board.put_final(Job("system", utt_at(start, 3), final=True))
    job = board.get(0)
    assert job.parts == 3


def test_board_backlog_excludes_active_but_wait_idle_waits_for_it():
    board = JobBoard()
    board.put_final(Job("system", utt_at(0.0, 12), final=True))
    board.put_final(Job("system", utt_at(13.0, 2), final=True))
    assert board.backlog_s() == 14.0
    job = board.get(0)
    assert job.utterance.duration_s == 12.0 and board.backlog_s() == 2.0
    assert not board.wait_idle(0)
    board.done(job)
    board.done(board.get(0))
    assert board.backlog_s() == 0.0 and board.wait_idle(0)


@pytest.mark.parametrize(
    "second",
    [
        Job("system", utt_at(6.0, 2), final=True),  # Luecke > max_gap_s
        Job("system", utt_at(2.0, 30), final=True),  # Gesamtdauer > coalesce_s
        Job("mic", utt_at(2.0, 2), final=True),  # andere Spur
    ],
)
def test_board_stops_coalescing_at_gap_length_or_track_change(second):
    board = JobBoard(coalesce_s=25.0, max_gap_s=3.0)
    board.put_final(Job("system", utt_at(0.0, 2), final=True))
    board.put_final(second)
    first = board.get(0)
    assert first.parts == 1 and first.utterance.end_s == 2.0
    board.done(first)
    assert board.get(0) is second


def test_board_keeps_queue_order_across_tracks():
    board = JobBoard(coalesce_s=25.0)
    board.put_final(Job("mic", utt_at(0.0, 1), final=True))
    board.put_final(Job("system", utt_at(1.0, 1), final=True))
    board.put_final(Job("mic", utt_at(2.0, 1), final=True))
    order = []
    while (job := board.get(0)) is not None:
        order.append((job.track, job.parts))
        board.done(job)
    assert order == [("mic", 1), ("system", 1), ("mic", 1)]


def test_board_without_coalescing_returns_finals_one_by_one():
    board = JobBoard()
    board.put_final(Job("system", utt_at(0.0, 2), final=True))
    board.put_final(Job("system", utt_at(2.0, 2), final=True))
    assert board.get(0).parts == 1
    assert board.backlog_s() == 2.0


def test_board_prefers_finals_and_keeps_only_latest_partial():
    board = JobBoard()
    board.put_partial(Job("mic", utt(start=1), final=False))
    board.put_partial(Job("mic", utt(start=2), final=False))
    board.put_final(Job("system", utt(3.0), final=True))
    first = board.get(0)
    assert first.final and board.backlog_s() == 0.0
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


# --- Sprecher-Modell im Hintergrund ------------------------------------------------


def test_background_embedder_never_blocks_mic_and_labels_system_when_ready():
    gate, logged = threading.Event(), []

    def load():
        gate.wait(5.0)
        return lambda audio: np.ones(8)

    labeler = SpeakerLabeler(BackgroundEmbedder(load, log=logged.append))
    assert labeler.label("mic", speech(2)) == ICH  # vor dem Laden, ohne zu warten
    assert not logged
    gate.set()
    assert labeler.label("system", speech(2)) == "Sprecher 1"
    assert logged and logged[0].startswith("Sprecher-Modell bereit")


def test_background_embedder_failure_falls_back_to_gegenseite():
    logged = []

    def load():
        raise RuntimeError("kein Token")

    labeler = SpeakerLabeler(BackgroundEmbedder(load, log=logged.append))
    assert labeler.label("system", speech(2)) == GEGENSEITE
    assert "kein Token" in logged[0] and GEGENSEITE in logged[0]


# --- Modell aus dem Cache ohne Hub-Anfrage -----------------------------------------


def fake_faster_whisper(monkeypatch, download_model):
    utils = SimpleNamespace(disabled_tqdm=object(), download_model=download_model)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(utils=utils))
    return utils


def test_fetch_model_uses_cache_without_asking_the_hub(monkeypatch):
    from audioscribe.pipeline.models import fetch_model

    calls = []
    utils = fake_faster_whisper(monkeypatch, lambda m, **kw: (calls.append(kw), "/cache/small")[1])
    assert fetch_model("small", lambda a, b: None) == "/cache/small"
    assert calls == [{"local_files_only": True}]
    assert utils.disabled_tqdm is not None  # Fortschritts-Patch wurde nicht gebraucht


def test_fetch_model_downloads_with_progress_when_not_cached(monkeypatch):
    from audioscribe.pipeline.models import fetch_model

    calls = []

    def download_model(model, **kw):
        calls.append(kw)
        if kw.get("local_files_only"):
            raise FileNotFoundError(model)
        return "/cache/small"

    utils = fake_faster_whisper(monkeypatch, download_model)
    seen = {}
    original = utils.disabled_tqdm
    utils.download_model = lambda m, **kw: (seen.update(tqdm=utils.disabled_tqdm), download_model(m, **kw))[1]
    assert fetch_model("small", lambda a, b: None) == "/cache/small"
    assert calls == [{"local_files_only": True}, {}]
    assert seen["tqdm"] is not original  # beim Online-Pfad war der Fortschritt eingehaengt


# --- Dekodieren / Aufholmodus ------------------------------------------------------


def test_decode_options_final_vs_preview_vs_eco():
    full = decode_options(final=True)
    assert (full["beam_size"], full["best_of"], full["temperature"]) == (5, 5, (0.0, 0.2, 0.4))
    eco = decode_options(final=True, eco=True)
    assert (eco["beam_size"], eco["best_of"], eco["temperature"]) == (1, 1, 0.0)
    preview = decode_options(final=False)
    assert preview["beam_size"] == 1
    assert not full["condition_on_previous_text"] and full["without_timestamps"]


class FakeAsr:
    detected = "de"

    def __init__(self):
        self.calls = []
        self.antwort = "Text"  # str oder Ergebnis

    def transcribe(self, audio, *, final, eco=False, initial_prompt=None):
        self.calls.append(eco)
        return self.antwort


def make_session(tmp_path, **kw):
    from audioscribe.live.session import LiveOptions, LiveSession

    session = LiveSession(LiveOptions(output_dir=tmp_path, model="m", device="cpu", compute_type="int8", **kw))
    session._asr = FakeAsr()
    session._labeler = SpeakerLabeler(None)
    return session


def test_persist_writes_recording_length_not_clock_after_drain(tmp_path):
    session = make_session(tmp_path, language="de")
    session.dir.mkdir(parents=True, exist_ok=True)
    session._aufnahme_s = 600.0  # gestoppt bei 10 min; die Uhr läuft beim Abarbeiten weiter
    session._persist()
    data = json.loads((session.dir / "transcript.json").read_text(encoding="utf-8"))
    assert data["duration_s"] == 600.0


def test_ergebnis_von_accepts_text_and_ergebnis():
    from audioscribe.live.asr import Ergebnis, SegmentInfo

    assert Ergebnis.von("  Hallo ") == Ergebnis("Hallo")
    assert Ergebnis.von("") == Ergebnis("") and Ergebnis.von(None).text == ""
    erg = Ergebnis("x", (SegmentInfo(-0.2, 1.1, 0.0, 0.0),))
    assert Ergebnis.von(erg) is erg


def test_do_final_switches_to_eco_only_while_behind(tmp_path, monkeypatch):
    emitted, logged = [], []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", logged.append)
    session = make_session(tmp_path, catchup_s=5.0, coalesce_s=0.0)
    board = session._board
    for start in (0.0, 2.0, 4.0, 6.0):
        board.put_final(Job("system", utt_at(start, 2), final=True))

    job = board.get(0)  # drei weitere warten: 6 s Rueckstand > 5 s -> Sparmodus
    session._do_final(job)
    board.done(job)
    assert session._asr.calls == [True]
    assert any("Aufholmodus" in line for line in logged)
    assert session.rtf() is not None
    (typ, seg) = emitted[-1]
    assert typ == events.SEGMENT and (seg["start"], seg["end"], seg["speaker"]) == (0.0, 2.0, GEGENSEITE)

    job = board.get(0)  # noch 4 s wartend -> volle Qualitaet, Wechsel wird protokolliert
    session._do_final(job)
    assert session._asr.calls == [True, False]
    assert any("abgebaut" in line for line in logged)


def test_do_final_alone_in_queue_is_never_eco_even_if_long(tmp_path, monkeypatch):
    """Ein einzelner 12-s-Abschnitt ist kein Rueckstand - der alte Fehler zaehlte ihn mit."""
    monkeypatch.setattr(events, "emit", lambda typ, **d: None)
    session = make_session(tmp_path, catchup_s=5.0)
    board = session._board
    board.put_final(Job("system", utt_at(0.0, 12), final=True))
    session._do_final(board.get(0))
    assert session._asr.calls == [False]


def test_do_final_force_eco_decodes_cheaply_regardless_of_backlog(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "emit", lambda typ, **d: None)
    session = make_session(tmp_path, force_eco=True)
    session._board.put_final(Job("mic", utt_at(0.0, 1), final=True))
    session._do_final(session._board.get(0))
    assert session._asr.calls == [True]
    assert session._diagnose.abschnitte[0].eco is True


def test_do_final_writes_diagnose_record(tmp_path, monkeypatch):
    from audioscribe.live.asr import Ergebnis, SegmentInfo

    monkeypatch.setattr(events, "emit", lambda typ, **d: None)
    # catchup_s=0: schon ein wartender Abschnitt gilt als Rückstand, damit zusammengelegt wird.
    session = make_session(tmp_path, coalesce_s=25.0, catchup_s=0.0)
    session._asr.antwort = Ergebnis("eins zwei drei", (SegmentInfo(-0.3, 1.2, 0.01, 0.2),))
    board = session._board
    a = Utterance(SR, 3 * SR, speech(2), schluss="zeitlimit")
    b = Utterance(4 * SR, 5 * SR, speech(1))
    board.put_final(Job("system", a, final=True, t_abgeschlossen=3.5))
    board.put_final(Job("system", b, final=True, t_abgeschlossen=5.5))
    session._do_final(board.get(0))

    (rec,) = session._diagnose.abschnitte
    assert (rec.chunk_index, rec.track, rec.parts, rec.schluss) == (1, "system", 2, "pause")
    assert (rec.audio_start_s, rec.audio_end_s, rec.audio_dauer_s) == (1.0, 5.0, 4.0)
    assert rec.t_abgeschlossen == 5.5 and rec.anzahl_woerter == 3 and rec.eco is False
    assert rec.segmente == [{"avg_logprob": -0.3, "compression_ratio": 1.2, "no_speech_prob": 0.01, "temperature": 0.2}]
    assert rec.latenz_s == pytest.approx(rec.t_ende - 5.0, abs=0.02)
    assert rec.latenz_max_s == pytest.approx(rec.t_ende - 3.0, abs=0.02)  # ab Ende des ersten Teils
    assert rec.wartezeit_s == pytest.approx(rec.t_start - 5.5, abs=0.02)
    assert rec.rechenzeit_s >= 0 and rec.sprecher_s >= 0 and rec.t_ende >= rec.t_start
    lines = [json.loads(line) for line in (session.dir / "diagnose.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["art"] == "abschnitt" and lines[0]["modell"] == "m"


# --- Fazit (FR-46) -----------------------------------------------------------------


def abschnitt(i=1, *, dauer=2.0, rechen=0.5, sprecher=0.0, latenz=1.0, woerter=3, parts=1, eco=False):
    from audioscribe.live.diagnose import Abschnitt

    return Abschnitt(
        chunk_index=i, track="system", audio_start_s=0.0, audio_end_s=dauer, audio_dauer_s=dauer,
        t_abgeschlossen=dauer, t_start=dauer + 0.1, t_ende=dauer + latenz, wartezeit_s=0.1,
        rechenzeit_s=rechen, sprecher_s=sprecher, latenz_s=latenz, latenz_max_s=latenz, modell="m",
        eco=eco, parts=parts, anzahl_woerter=woerter, schluss="pause",
    )


def test_diagnose_writes_jsonl_and_derives_bilanz(tmp_path):
    from audioscribe.live.diagnose import Diagnose, Vorschau, lies_diagnose

    d = Diagnose(tmp_path / "diagnose.jsonl")
    d.abschnitt(abschnitt(1, dauer=2.0, rechen=0.5, latenz=1.0))
    d.abschnitt(abschnitt(2, dauer=4.0, rechen=1.0, latenz=3.0, parts=3, eco=True))
    d.abschnitt(abschnitt(3, dauer=1.0, rechen=0.3, woerter=0))  # leer: nur Rechenzeit
    d.abschnitt(abschnitt(4, dauer=2.0, rechen=0.2, sprecher=0.4, latenz=2.0))
    d.vorschau(Vorschau("system", 1.0, 1.5, 0.1, "m"))
    d.vorschau(Vorschau("system", 3.0, 3.5, 0.2, "m"))
    for t, backlog in ((0, 1.0), (1, 20.0), (2, 20.0), (3, 6.5), (4, 2.0)):
        d.rueckstand(t, backlog)
    b = d.bilanz(laden_s=3.04, aufnahme_s=60.0, abschluss_s=1.0, gesamt_s=65.0, schwelle_s=12.0)
    d.close()

    assert (b.abschnitte, b.zusammengelegt, b.eco_abschnitte) == (3, 1, 1)
    assert (b.audio_s, b.rechenzeit_s, b.sprecher_s, b.tempo) == (9.0, 2.4, 0.4, 0.22)
    assert b.tempo_inkl_vorschau == 0.3  # (2,0 + 0,4 + 0,3) / 9
    assert (b.verzoegerung_mittel_s, b.verzoegerung_median_s, b.verzoegerung_max_s) == (2.0, 2.0, 3.0)
    assert (b.vorschau_n, b.vorschau_s) == (2, 0.3)
    assert (b.rueckstand_max_s, b.aufholmodus_s, b.aufholmodus_anteil, b.laden_s) == (20.0, 2.0, 0.03, 3.0)

    zeilen = lies_diagnose(tmp_path)
    assert [z["art"] for z in zeilen] == ["abschnitt"] * 4 + ["vorschau"] * 2
    assert zeilen[1]["parts"] == 3 and zeilen[4]["fenster_s"] == 1.5
    assert d.tempo_letzte(2) == 0.3  # (0,3 + 0,2 + 0,4) / 3


def test_diagnose_without_measurements_has_no_tempo_or_latency(tmp_path):
    from audioscribe.live.bilanz import beschreibe_live
    from audioscribe.live.diagnose import Diagnose

    b = Diagnose(None).bilanz(laden_s=1.0, aufnahme_s=5.0, abschluss_s=0.0, gesamt_s=6.0, schwelle_s=12.0)
    assert b.tempo is None and b.verzoegerung_max_s is None and b.abschnitte == 0
    assert b.tempo_inkl_vorschau is None and b.aufholmodus_anteil == 0.0
    text = beschreibe_live(b)
    assert text.startswith("Fazit: Aufnahme 0:05") and "Verzögerung" not in text and "0 Abschnitte" in text
    leer = Diagnose(tmp_path / "leer" / "diagnose.jsonl")
    leer.close()  # ohne Abschnitte: Datei da, aber leer
    assert (tmp_path / "leer" / "diagnose.jsonl").read_text(encoding="utf-8") == ""


def test_beschreibe_live_mentions_preview_tempo_and_catchup_share():
    from audioscribe.live.bilanz import LiveBilanz, beschreibe_live

    b = LiveBilanz(laden_s=1.0, aufnahme_s=90.0, abschluss_s=1.0, gesamt_s=95.0, abschnitte=5, audio_s=80.0,
                   rechenzeit_s=12.0, tempo=0.15, vorschau_n=20, vorschau_s=40.0, tempo_inkl_vorschau=0.65,
                   verzoegerung_mittel_s=3.0, verzoegerung_median_s=3.0, verzoegerung_max_s=5.0,
                   aufholmodus_s=9.0, aufholmodus_anteil=0.1, eco_abschnitte=2)
    text = beschreibe_live(b)
    assert "Rechenzeit 12,0 s (0,15× Echtzeit) · 20 Vorschauen 40,0 s (0,65× Echtzeit)" in text
    assert "5 Abschnitte (2 sparsam)" in text and "Aufholmodus 9,0 s (10 %)" in text


def test_beschreibe_live_mentions_all_the_numbers():
    from audioscribe.live.bilanz import LiveBilanz, beschreibe_live

    b = LiveBilanz(laden_s=6.2, aufnahme_s=114.0, abschluss_s=2.9, gesamt_s=125.0, abschnitte=27,
                   zusammengelegt=3, audio_s=100.0, rechenzeit_s=38.4, tempo=0.34,
                   verzoegerung_mittel_s=2.1, verzoegerung_median_s=1.8, verzoegerung_max_s=4.8,
                   aufholmodus_s=12.0)
    assert beschreibe_live(b) == (
        "Fazit: Aufnahme 1:54 · Modelle 6,2 s · Rechenzeit 38,4 s (0,34× Echtzeit) · "
        "Verzögerung Ø 2,1 s / max 4,8 s · 27 Abschnitte (3 zusammengelegt) · Aufholmodus 12,0 s · Abschluss 2,9 s"
    )


def test_save_bilanz_merges_parts_and_replaces_broken_file(tmp_path):
    from audioscribe.live.bilanz import RefineBilanz, load_bilanz, save_bilanz

    save_bilanz(tmp_path, "live", {"aufnahme_s": 3.0})
    save_bilanz(tmp_path, "nachschaerfen", RefineBilanz(gesamt_s=9.0, audio_s=3.0, tempo=3.0, stufen=[]))
    data = load_bilanz(tmp_path)
    assert data["version"] == 1 and data["live"] == {"aufnahme_s": 3.0}
    assert data["nachschaerfen"]["gesamt_s"] == 9.0 and data["nachschaerfen"]["modell"] is None
    assert not (tmp_path / "bilanz.tmp").exists()

    (tmp_path / "bilanz.json").write_text("{kaputt", encoding="utf-8")
    assert load_bilanz(tmp_path) is None
    save_bilanz(tmp_path, "live", {"aufnahme_s": 1.0})
    assert load_bilanz(tmp_path) == {"version": 1, "live": {"aufnahme_s": 1.0}}


def test_session_finish_writes_bilanz_and_reports_before_fertig(tmp_path, monkeypatch):
    from audioscribe.live.bilanz import load_bilanz

    emitted, logged = [], []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", logged.append)
    session = make_session(tmp_path)
    session.dir.mkdir()
    session._segments.append(Segment(0.0, 2.0, "Hallo", ICH))
    session._diagnose.abschnitt(abschnitt(1, dauer=2.0, rechen=0.4, latenz=1.5))
    session._finish(laden_s=1.0, aufnahme_s=10.0, abschluss_s=0.5, gesamt_s=12.0)

    types = [(typ, d.get("teil") or d.get("phase")) for typ, d in emitted]
    assert types.index((events.FAZIT, "live")) < types.index((events.STATE, "fertig"))
    fazit = next(d for typ, d in emitted if typ == events.FAZIT)
    assert (fazit["aufnahme_s"], fazit["abschnitte"], fazit["verzoegerung_max_s"], fazit["tempo"]) == (10.0, 1, 1.5, 0.2)
    assert any(line.startswith("Fazit: Aufnahme 0:10") for line in logged)
    assert load_bilanz(session.dir)["live"]["rechenzeit_s"] == 0.4
    assert (session.dir / "transkript.live.md").exists()
    assert (session.dir / "diagnose.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_refine_session_times_its_stages(tmp_path, monkeypatch):
    import wave
    from dataclasses import replace

    from audioscribe.live import refine
    from audioscribe.live.bilanz import load_bilanz
    from audioscribe.live.store import MIC_WAV

    (tmp_path / "audio").mkdir()
    with wave.open(str(tmp_path / MIC_WAV), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(np.zeros(SR * 3, dtype="<i2").tobytes())
    monkeypatch.setattr(refine, "settings", replace(refine.settings, enable_alignment=True, enable_diarization=True,
                                                    whisper_model="tiny"))
    ergebnis = {"language": "de", "segments": [{"start": 0.0, "end": 1.0, "text": "Hallo", "words": []}]}
    monkeypatch.setattr("audioscribe.pipeline.transcribe.transcribe", lambda audio, reporter: dict(ergebnis))
    monkeypatch.setattr("audioscribe.pipeline.transcribe.align", lambda audio, result, reporter: result)
    emitted = []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))

    assert refine.refine_session(tmp_path) == tmp_path / "transkript.md"
    data = load_bilanz(tmp_path)["nachschaerfen"]
    assert [st["name"] for st in data["stufen"]] == [
        "Transkription Mikrofon (faster-whisper tiny)", "Wort-Alignment Mikrofon", "Zusammenführen & Export"
    ]
    assert all(st["dauer_s"] >= 0 for st in data["stufen"])
    assert data["audio_s"] == 3.0 and data["modell"] == "tiny" and data["tempo"] is not None
    assert emitted[-1][0] == events.FAZIT and emitted[-1][1]["teil"] == "nachschaerfen"
    # Diagnose-Log: je Segment und je Stufe eine Zeile, alle als Teil "nachschaerfen".
    from audioscribe.live.diagnose import lies_diagnose

    zeilen = lies_diagnose(tmp_path)
    assert [z["art"] for z in zeilen] == ["nachschaerfen", "stufe", "stufe", "stufe"]
    assert zeilen[0] == {"art": "nachschaerfen", "teil": "nachschaerfen", "spur": "Mikrofon", "start_s": 0.0,
                         "end_s": 1.0, "dauer_s": 1.0, "anzahl_woerter": 1, "modell": "tiny"}
    assert all(z["teil"] == "nachschaerfen" for z in zeilen)


# --- WAV-Replay (FR-49) ------------------------------------------------------------


def write_wav(path, samples: np.ndarray, rate: int = SR, channels: int = 1) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.repeat(pcm, channels).tobytes())


def wait_until(cond, timeout: float = 10.0) -> bool:
    import time

    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_replay_capture_feeds_wav_on_session_clock(tmp_path):
    import time

    from audioscribe.live.replay import ReplayCapture

    write_wav(tmp_path / "in.wav", np.full(int(1.2 * 8000), 0.4, dtype=np.float32), rate=8000, channels=2)
    t0 = time.monotonic()
    speed = 20.0
    clock = lambda: (time.monotonic() - t0) * speed  # noqa: E731
    ended = []
    cap = ReplayCapture(clock, system=tmp_path / "in.wav", mic=None, speed=speed, on_end=lambda: ended.append(1),
                        nachlauf_s=0.5)
    assert cap.mics == [] and len(cap.loopbacks) == 1
    dev = cap.loopbacks[0]
    assert (dev["rate"], dev["channels"], dev["default"], round(dev["dauer_s"], 2)) == (8000, 2, True, 1.2)
    track = cap.open("system", dev, tmp_path / "audio" / "system.wav")
    assert wait_until(lambda: ended, timeout=10)
    assert ended == [1]
    start, samples = track.take(1.0)  # nicht clock(): take() fuellt bis "jetzt" mit Stille auf
    assert start == 0 and abs(len(samples) - 1.2 * SR) < 0.05 * SR
    assert np.abs(samples[SR // 2 : SR]).max() > 0.3  # Stereo heruntergemischt, auf 16 kHz gebracht
    cap.close()
    assert abs(len(load_wav(tmp_path / "audio" / "system.wav")) - 1.2 * SR) < 0.05 * SR


def test_replay_capture_rejects_bad_files(tmp_path):
    from audioscribe.live.replay import ReplayCapture

    with pytest.raises(RuntimeError, match="nicht gefunden"):
        ReplayCapture(lambda: 0.0, system=tmp_path / "fehlt.wav", mic=None, on_end=lambda: None)
    (tmp_path / "kaputt.wav").write_bytes(b"nicht wav")
    with pytest.raises(RuntimeError, match="keine lesbare WAV"):
        ReplayCapture(lambda: 0.0, system=None, mic=tmp_path / "kaputt.wav", on_end=lambda: None)


def test_live_session_replays_wav_end_to_end(tmp_path, monkeypatch):
    from audioscribe.live.bilanz import load_bilanz
    from audioscribe.live.diagnose import lies_diagnose
    from audioscribe.live.session import LiveOptions, LiveSession

    write_wav(tmp_path / "ref.wav", np.concatenate([silence(1.0), speech(1.5), silence(0.5)]))
    emitted, logged = [], []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", logged.append)
    opts = LiveOptions(output_dir=tmp_path / "out", model="m", device="cpu", compute_type="int8",
                       replay_system=tmp_path / "ref.wav", speed=10.0, monitor=0, mic="none",
                       partials=False, speakers=False)
    session = LiveSession(opts)
    monkeypatch.setattr(session, "_load_asr", lambda: FakeAsr())
    monkeypatch.setattr(session, "_load_vad", lambda: energy_vad)
    monkeypatch.setattr(session, "_watch_stdin", lambda: None)

    assert session.run() == 0

    segs = [d for typ, d in emitted if typ == events.SEGMENT]
    assert len(segs) == 1
    assert abs(segs[0]["start"] - 1.0) < 0.15 and abs(segs[0]["end"] - 2.5) < 0.15
    assert segs[0]["text"] == "Text" and segs[0]["track"] == "system"
    # Mitschnitt: die Datei plus die Nachlauf-Stille, mit der die Sitzung ausklingt.
    mitschnitt = load_wav(session.dir / "audio" / "system.wav")
    assert 3 * SR <= len(mitschnitt) < 6 * SR and np.abs(mitschnitt[int(1.2 * SR) : int(2.3 * SR)]).max() > 0.4
    (rec,) = [z for z in lies_diagnose(session.dir) if z["art"] == "abschnitt"]
    assert rec["schluss"] == "pause" and rec["eco"] is False and rec["anzahl_woerter"] == 1
    assert load_bilanz(session.dir)["live"]["abschnitte"] == 1
    assert (session.dir / "transkript.txt").read_text(encoding="utf-8") == "Text\n"
    types = [(typ, d.get("teil") or d.get("phase")) for typ, d in emitted]
    assert types.index((events.FAZIT, "live")) < types.index((events.STATE, "fertig"))
    assert any("Replay statt Aufnahme" in line for line in logged)


def test_cli_live_wav_builds_replay_options(tmp_path, monkeypatch):
    from audioscribe import cli

    write_wav(tmp_path / "ref.wav", silence(0.5))
    monkeypatch.setattr(cli, "_prepare_backend", lambda: ("cpu", "int8"))
    gestartet = []

    class FakeSession:
        def __init__(self, opts):
            gestartet.append(opts)

        def run(self):
            return 0

    monkeypatch.setattr("audioscribe.live.session.LiveSession", FakeSession)
    assert cli.main(["live", "--wav", str(tmp_path / "ref.wav"), "--speed", "4", "--model", "base",
                     "--output", str(tmp_path), "--eco", "--monitor", "2"]) == 0
    (opts,) = gestartet
    assert opts.replay_system == tmp_path / "ref.wav" and opts.replay_mic is None
    assert (opts.speed, opts.model, opts.force_eco) == (4.0, "base", True)
    assert (opts.monitor, opts.window, opts.mic, opts.loopback) == (0, 0, "none", "default")
    assert cli.main(["live", "--wav", str(tmp_path / "fehlt.wav")]) == 1
    assert cli.main(["live", "--wav-mic", str(tmp_path / "ref.wav"), "--speed", "0"]) == 1
    assert cli.main(["live", "--wav-mic", str(tmp_path / "ref.wav")]) == 0
    assert (gestartet[-1].mic, gestartet[-1].loopback, gestartet[-1].replay_mic) == ("default", "none", tmp_path / "ref.wav")


def test_cli_live_backend_mlx_waehlt_turbo_und_stellschrauben(tmp_path, monkeypatch):
    """Der aufgeloeste Backend-Wert kommt aus der Umgebung - settings ist beim Import eingefroren."""
    from audioscribe import cli

    write_wav(tmp_path / "ref.wav", silence(0.5))
    monkeypatch.setattr(cli, "_prepare_backend", lambda: ("mps", "int8"))
    monkeypatch.setattr("audioscribe.config.resolve_asr_backend", lambda raw, device: "mlx" if raw == "mlx" else "faster-whisper")
    monkeypatch.setenv("AUDIOSCRIBE_LIVE_PAUSE_S", "0.45")
    gestartet = []

    class FakeSession:
        def __init__(self, opts):
            gestartet.append(opts)

        def run(self):
            return 0

    monkeypatch.setattr("audioscribe.live.session.LiveSession", FakeSession)
    assert cli.main(["live", "--wav", str(tmp_path / "ref.wav"), "--backend", "mlx", "--output", str(tmp_path)]) == 0
    (opts,) = gestartet
    assert (opts.backend, opts.device, opts.model) == ("mlx", "mps", "large-v3-turbo")
    assert opts.pause_s in (0.45, 0.6)  # 0.45, wenn settings in diesem Prozess frisch geladen wurde
    assert cli.main(["live", "--wav", str(tmp_path / "ref.wav"), "--backend", "faster-whisper", "--output", str(tmp_path)]) == 0
    assert (gestartet[-1].backend, gestartet[-1].model) == ("faster-whisper", "small")


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


# --- Anwendungsfenster als Bildquelle ---------------------------------------------


@pytest.mark.parametrize(
    "kw, erwartet",
    [
        ({}, True),
        ({"title": "  "}, False),
        ({"cloaked": 1}, False),  # virtueller Desktop / UWP im Hintergrund
        ({"width": 0}, False),
        ({"class_name": "Progman"}, False),
        ({"style_ex": fenster.WS_EX_TOOLWINDOW}, False),
        ({"style_ex": fenster.WS_EX_TOOLWINDOW | fenster.WS_EX_APPWINDOW}, True),
        ({"has_owner": True}, False),  # Dialog eines anderen Fensters
        ({"has_owner": True, "style_ex": fenster.WS_EX_APPWINDOW}, True),
    ],
)
def test_wanted_follows_alt_tab_rules(kw, erwartet):
    basis = {"title": "Editor", "class_name": "Chrome_WidgetWin_1", "style_ex": 0, "cloaked": 0,
             "has_owner": False, "width": 800, "height": 600}
    assert fenster._wanted(**{**basis, **kw}) is erwartet


def test_group_by_process_keeps_first_seen_order():
    ws = [
        {"hwnd": 1, "process": "chrome", "title": "A"},
        {"hwnd": 2, "process": "code", "title": "B"},
        {"hwnd": 3, "process": "chrome", "title": "C"},
    ]
    gruppen = fenster.group_by_process(ws)
    assert [g["process"] for g in gruppen] == ["chrome", "code"]
    assert [w["hwnd"] for w in gruppen[0]["windows"]] == [1, 3]
    assert fenster.group_by_process([]) == []
    assert fenster.window_label(ws[0]) == "chrome – A"


def test_list_windows_is_empty_off_windows(monkeypatch):
    monkeypatch.setattr(fenster, "_api", lambda: None)
    assert fenster.list_windows() == []
    assert fenster.is_window(4711) is False


class FakeSource:
    """Bildquelle aus einer festen Folge: PIL-Bild, ``None`` (pausiert) oder Ausnahme."""

    label = "Attrappe"

    def __init__(self, folge):
        self._folge = list(folge)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def grab(self):
        if not self._folge:
            raise WindowGone("zu Ende")
        item = self._folge.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def run_watcher(tmp_path, source, **kw):
    from itertools import count

    from audioscribe.live.screen import ScreenWatcher

    takt = count()
    marks, log = [], []
    watcher = ScreenWatcher(
        1, tmp_path, lambda: next(takt) * 5.0, marks.append, fps=500.0, log=log.append,
        source_factory=lambda: source, **kw,
    )
    watcher.start()
    watcher.join(timeout=5)
    assert not watcher.is_alive()
    return marks, log


def test_screen_watcher_pauses_and_ends_with_window(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    weiss = Image.new("RGB", (64, 36), (255, 255, 255))
    schwarz = Image.new("RGB", (64, 36), (0, 0, 0))
    marks, log = run_watcher(tmp_path, FakeSource([weiss, weiss, None, None, schwarz, WindowGone("weg")]))

    assert [m.id for m in marks] == [1]  # Startbild; der Wechsel auf Schwarz ist noch nicht ruhig
    assert (tmp_path / "frames" / marks[0].png.split("/")[1]).exists()
    assert log == [
        "Standbilder: Attrappe",
        "Fenster minimiert oder ausgeblendet - Standbilder pausieren",
        "Fenster wieder sichtbar",
        "Fenster geschlossen - keine weiteren Standbilder",
    ]


def test_screen_watcher_reports_missing_source(tmp_path):
    from audioscribe.live.screen import SourceUnavailable

    class Kaputt:
        def __enter__(self):
            raise SourceUnavailable("Monitor 7 gibt es nicht")

        def __exit__(self, *exc):
            return None

    marks, log = run_watcher(tmp_path, Kaputt())
    assert marks == [] and log == ["Monitor 7 gibt es nicht - keine Standbilder"]


def test_screen_watcher_reports_missing_mss(tmp_path):
    from audioscribe.live.screen import MSS_FEHLT

    class OhneMss:
        def __enter__(self):
            raise ImportError("No module named 'mss'")  # mss lädt erst im Thread

        def __exit__(self, *exc):
            return None

    marks, log = run_watcher(tmp_path, OhneMss())
    assert marks == [] and log == [MSS_FEHLT]


def test_window_source_region_clips_to_virtual_screen(monkeypatch):
    from audioscribe.live.screen import WindowSource

    # Zweiter Monitor links vom Hauptmonitor -> negative Koordinaten im virtuellen Bildschirm.
    monkeypatch.setattr("audioscribe.live.screen.grab_image", lambda sct, region: region)
    src = WindowSource(1)
    src._sct = SimpleNamespace(monitors=[{"left": -1920, "top": 0, "width": 3840, "height": 1080}])
    assert src._region((-2000, -50, 100, 500)) == {"left": -1920, "top": 0, "width": 2020, "height": 500}
    assert src._region((5000, 0, 5100, 100)) is None  # ganz außerhalb


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
    # Reintext fuer WER-Vergleiche: ohne Zeitstempel und Sprecher, nach Zeit sortiert.
    assert (session / "transkript.txt").read_text(encoding="utf-8") == "Hallo zusammen.\nGuten Morgen.\n"
    data = json.loads((session / "transcript.json").read_text(encoding="utf-8"))
    assert data["mode"] == "live" and data["num_speakers"] == 2
    assert "#0001" in (session / "transkript.annotiert.md").read_text(encoding="utf-8")

    assert find_transcript(session).name == "transkript.annotiert.md"
    assert [r["name"] for r in scan_results(tmp_path)] == [session.name]


def test_transcript_source_path_points_to_existing_track(tmp_path):
    seg = [Segment(0.0, 1.0, "Hallo.", ICH)]
    (tmp_path / "audio").mkdir()
    (tmp_path / MIC_WAV).write_bytes(b"")
    write_transcript(tmp_path, seg, duration_s=1.0, language="de", model="small", mode="live")
    data = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert Path(data["source_path"]) == (tmp_path / MIC_WAV).resolve()  # nur Mikrofon
    (tmp_path / SYSTEM_WAV).write_bytes(b"")
    write_transcript(tmp_path, seg, duration_s=1.0, language="de", model="small", mode="live")
    data = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert Path(data["source_path"]) == (tmp_path / SYSTEM_WAV).resolve()


def test_keep_live_copy_never_overwrites_during_refine(tmp_path):
    (tmp_path / "transkript.md").write_text("live", encoding="utf-8")
    (tmp_path / "transkript.txt").write_text("live txt", encoding="utf-8")
    keep_live_copy(tmp_path, overwrite=True)
    (tmp_path / "transkript.md").write_text("geschaerft", encoding="utf-8")
    keep_live_copy(tmp_path, overwrite=False)
    assert (tmp_path / "transkript.live.md").read_text(encoding="utf-8") == "live"
    assert (tmp_path / "transkript.live.txt").read_text(encoding="utf-8") == "live txt"


# --- LiveRunner (ohne Modelle: das Kind ist ein python -c-Einzeiler) ---------------

CHILD = r"""
import sys, json
def ev(**d): print("[Live] " + json.dumps(d), flush=True)
state = dict(session="live-x", dir=sys.argv[1], model="small", device="cpu")
ev(type="state", phase="laden", step="Whisper small", **state)
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
ev(type="fazit", teil="live", aufnahme_s=3.0, rechenzeit_s=0.9, tempo=0.3, abschnitte=1)
ev(type="state", phase="fertig", **state)
"""

REFINE = (
    "print('[Stufe 1/2] Transkription Mikrofon', flush=True); print('[Fortschritt] 50.0%', flush=True); "
    "print('[Live] {\"type\": \"fazit\", \"teil\": \"nachschaerfen\", \"gesamt_s\": 4.0, \"stufen\": []}', flush=True)"
)


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
    assert snap["step"] is None  # der Ladeschritt gilt nur waehrend "laden"
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
    assert done["fazit"] == {
        "live": {"aufnahme_s": 3.0, "rechenzeit_s": 0.9, "tempo": 0.3, "abschnitte": 1},
        "nachschaerfen": {"gesamt_s": 4.0, "stufen": []},
    }
    assert not any("fazit" in line for line in runner.snapshot()["lines"])  # Ereigniszeilen bleiben dem Protokoll fern


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
    assert runner.snapshot() == {"running": False, "offset": 0, "lines": [], "events": [], "ev_offset": 0, "partials": {}, "souffleur": None}
    assert runner.reset() is None  # ein zweites Mal ist harmlos


def test_build_live_argv_and_refine_argv(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions, build_live_argv, build_refine_argv

    opts = LiveJobOptions(output_dir=tmp_path, monitor=2, mic="23", loopback="none", partials=False,
                          model="small", refine_model="large-v3-turbo")
    argv = build_live_argv(opts, prefix=["audioscribe"])
    assert argv[:2] == ["audioscribe", "live"]
    assert {"--monitor=2", "--mic=23", "--loopback=none", "--model=small", "--no-partials"} <= set(argv)
    assert "--no-speakers" not in argv
    assert not any(a.startswith("--window") for a in argv)
    # Nachschaerfen laeuft mit seinem eigenen Modell, nicht mit dem Live-Modell.
    refine_argv = build_refine_argv(tmp_path / "live-x", opts, prefix=["audioscribe"])
    assert refine_argv[:3] == ["audioscribe", "refine", str(tmp_path / "live-x")]
    assert "--model=large-v3-turbo" in refine_argv and "--model=small" not in refine_argv
    fenster_argv = build_live_argv(LiveJobOptions(output_dir=tmp_path, monitor=0, window=4711), prefix=["x"])
    assert {"--monitor=0", "--window=4711"} <= set(fenster_argv)


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
        lambda: {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": ["Attrappe"]},
    )
    return TestClient(server.create_app())


def test_live_defaults_route(client):
    data = client.get("/api/live/defaults").json()
    assert data["models"][0] == "auto" and "large-v3-turbo" in data["models"]
    assert "large-v3-turbo" in data["refine_models"] and "auto" not in data["refine_models"]
    assert data["problems"] == ["Attrappe"] and data["refine"] is True


def test_live_start_rejects_bad_input(client, tmp_path):
    base = {"output_dir": str(tmp_path)}
    assert client.post("/api/live/start", json={**base, "model": "--evil"}).status_code == 400
    assert client.post("/api/live/start", json={**base, "device": "tpu"}).status_code == 400
    nothing = {**base, "monitor": 0, "mic": "none", "loopback": "none"}
    assert client.post("/api/live/start", json=nothing).status_code == 400
    assert client.post("/api/live/start", json={**base, "window": -1}).status_code == 400
    assert client.post("/api/live/start", json={**base, "window": 2**40}).status_code == 400


def test_live_start_with_window_remembers_label(client, tmp_path, monkeypatch):
    from audioscribe.ui import state
    from audioscribe.ui.runner import LiveRunner

    gestartet = []
    monkeypatch.setattr(LiveRunner, "start", lambda self, opts, **kw: gestartet.append(opts))
    state.save_state({"live_monitor": "2"})
    body = {"output_dir": str(tmp_path), "monitor": 0, "window": 4711, "window_label": "chrome – Jira",
            "mic": "none", "loopback": "none"}
    assert client.post("/api/live/start", json=body).status_code == 200
    assert gestartet[0].window == 4711 and gestartet[0].monitor == 0
    saved = state.load_state()
    assert saved["live_source"] == "window" and saved["live_window"] == "chrome – Jira"
    assert saved["live_monitor"] == "2"  # Fensterwahl ueberschreibt den gemerkten Monitor nicht
    data = client.get("/api/live/defaults").json()
    assert data["source"] == "window" and data["window"] == "chrome – Jira"


def test_live_window_preview_rejects_bad_handles(client):
    assert client.get("/api/live/window/0").status_code == 404
    assert client.get("/api/live/window/99999999999").status_code == 404


def test_live_windows_route_lists_only_windows(client, monkeypatch):
    fenster = [{"hwnd": 4711, "title": "Jira", "process": "chrome", "pid": 7, "width": 800, "height": 600}]
    monkeypatch.setattr("audioscribe.live.fenster.list_windows", lambda: fenster)
    assert client.get("/api/live/windows").json() == {"windows": fenster}


def test_index_has_window_picker_dialog():
    from pathlib import Path

    from audioscribe.ui import server

    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="winPick"' in html and 'id="winFilter"' in html and 'id="winList"' in html


def test_index_has_fazit_box_before_result():
    from pathlib import Path

    from audioscribe.ui import server

    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert html.index('id="liveFazit"') < html.index('id="liveResult"')


def test_live_reset_route_without_session(client):
    assert client.post("/api/live/reset").json() == {"ok": True, "discarded": None}


def test_live_frame_route_without_session(client):
    assert client.get("/api/live/frame/0001_00-00-00.jpg").status_code == 404
    assert client.get("/api/live/frame/..%5Cmarks.json").status_code == 404


def test_first_tab_is_renamed():
    from pathlib import Path

    from audioscribe.ui import server

    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    # PRD §21: statt gleichrangiger Reiter die Bereiche je Einstieg - im Projekt Live vor Nachbereitung.
    assert html.index(">Live-Sitzung<") < html.index(">Nachbereitung<") < html.index(">Transkribieren<") < html.index(">KI-Analyse<")
    assert ">Offline Transcription<" not in html
