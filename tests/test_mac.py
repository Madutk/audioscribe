"""macOS-Portierung (PRD §19): reine Bausteine, unter Linux mit Attrappen getestet.

Die Frameworks (mlx_whisper, sounddevice, ScreenCaptureKit, Quartz, AVFoundation) werden
ueber ``sys.modules`` eingehaengt; echte Mac-Laeufe stehen in PRD §19.4.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from audioscribe.live import berechtigungen
from audioscribe.live.capture import ensure_permissions, list_devices, open_capture, pick
from audioscribe.live.capture import coreaudio, sck
from audioscribe.live.track import SAMPLE_RATE, Track


# --- capture: Fabrik, pick, Geraete ---------------------------------------------------


def test_open_capture_verweist_linux_auf_das_replay():
    with pytest.raises(RuntimeError, match="--wav"):
        open_capture(lambda: 0.0, platform="linux")
    with pytest.raises(RuntimeError):
        list_devices(platform="linux")


def test_open_capture_dispatcht_nach_plattform(monkeypatch):
    aufrufe = []
    fake_mac = types.ModuleType("audioscribe.live.capture.mac")
    fake_mac.MacCapture = lambda clock, log=None: aufrufe.append(("mac", log)) or "MAC"
    fake_win = types.ModuleType("audioscribe.live.capture.wasapi")
    fake_win.AudioCapture = lambda clock: aufrufe.append(("win", clock)) or "WIN"
    monkeypatch.setitem(sys.modules, "audioscribe.live.capture.mac", fake_mac)
    monkeypatch.setitem(sys.modules, "audioscribe.live.capture.wasapi", fake_win)
    assert open_capture(lambda: 1.0, platform="darwin") == "MAC"
    assert open_capture(lambda: 1.0, platform="win32") == "WIN"
    assert [a[0] for a in aufrufe] == ["mac", "win"]
    meldung = print
    open_capture(lambda: 1.0, platform="darwin", log=meldung)
    assert aufrufe[-1] == ("mac", meldung)  # MacCapture-Diagnosen erreichen das Log


def test_pick_findet_synthetischen_loopback_mit_negativem_index():
    geraete = [dict(sck.LOOPBACK_ENTRY)]
    assert pick(geraete, "default") is geraete[0]
    assert pick(geraete, "-1") is geraete[0]
    assert pick(geraete, "none") is None
    with pytest.raises(RuntimeError):
        pick(geraete, "7")


def test_mic_entries_filtert_eingabegeraete_und_setzt_standard():
    devices = [
        {"name": "MacBook Pro Speakers", "max_input_channels": 0, "default_samplerate": 48000.0, "hostapi": 0},
        {"name": "MacBook Pro Microphone", "max_input_channels": 1, "default_samplerate": 48000.0, "hostapi": 0},
        {"name": "AirPods", "max_input_channels": 1, "default_samplerate": 24000.0, "hostapi": 0},
    ]
    hostapis = [{"name": "Core Audio"}]
    out = coreaudio.mic_entries(devices, 2, hostapis)
    assert [d["index"] for d in out] == [1, 2]
    assert out[1]["default"] is True and out[0]["default"] is False
    assert out[1] == {"index": 2, "name": "AirPods", "rate": 24000, "channels": 1, "default": True}
    # Ohne bekannten Standard wird das erste Mikrofon Standard.
    assert coreaudio.mic_entries(devices, None, None)[0]["default"] is True


def test_mac_list_devices_mit_sounddevice_attrappe(monkeypatch):
    fake_sd = SimpleNamespace(
        query_devices=lambda: [{"name": "Mic", "max_input_channels": 1, "default_samplerate": 44100.0, "hostapi": 0}],
        query_hostapis=lambda: [{"name": "Core Audio"}],
        default=SimpleNamespace(device=(0, 1)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(sck, "is_supported", lambda: True)
    from audioscribe.live.capture import mac

    geraete = mac.list_devices()
    assert geraete["mics"] == [{"index": 0, "name": "Mic", "rate": 44100, "channels": 1, "default": True}]
    assert geraete["loopbacks"] == [sck.LOOPBACK_ENTRY]
    monkeypatch.setattr(sck, "is_supported", lambda: False)
    assert mac.list_devices()["loopbacks"] == []


def test_sck_is_supported_braucht_macos_13():
    assert sck.is_supported("linux") is False
    assert sck.is_supported("darwin", version=(12, 7)) is False


# --- ScreenCaptureKit: PCM-Umwandlung und Track.feed_mono -------------------------------


def test_pcm_to_mono_planar_und_interleaved():
    links = np.array([1.0, 0.5, 0.0, -0.5], dtype=np.float32)
    rechts = np.array([0.0, 0.5, 1.0, 0.5], dtype=np.float32)
    planar = np.concatenate([links, rechts]).tobytes()
    interleaved = np.stack([links, rechts], axis=1).reshape(-1).tobytes()
    erwartet = (links + rechts) / 2
    np.testing.assert_allclose(sck.pcm_to_mono(planar, 4, 2, True), erwartet)
    np.testing.assert_allclose(sck.pcm_to_mono(interleaved, 4, 2, False), erwartet)
    np.testing.assert_allclose(sck.pcm_to_mono(links.tobytes(), 4, 1, True), links)


def test_pcm_to_mono_schneidet_ueberlange_puffer():
    data = np.arange(10, dtype=np.float32).tobytes()
    assert len(sck.pcm_to_mono(data, 3, 2, False)) == 3


def test_track_feed_mono_resampelt_48k_nach_16k(tmp_path):
    track = Track("system", 48_000, 2, tmp_path / "s.wav", slack_s=0.15)
    t = np.arange(48_000) / 48_000
    mono = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    for i in range(10):
        track.feed_mono(mono[i * 4800 : (i + 1) * 4800], (i + 1) * 0.1)
    start, samples = track.take(1.0)
    assert start == 0
    assert abs(len(samples) - SAMPLE_RATE) < SAMPLE_RATE * 0.05
    assert track.level > 0.9
    track.close()


def test_track_reset_rate_wechselt_den_resampler(tmp_path):
    track = Track("mic", 48_000, 1, None)
    track.reset_rate(16_000)
    track.feed_mono(np.ones(1600, dtype=np.float32), 0.1)
    _, samples = track.take(0.5)
    assert len(samples) == 1600  # 1:1, kein Resampling mehr


def test_mic_stream_setzt_rate_vor_dem_start_und_schliesst_fehlversuche(monkeypatch):
    track = Track("mic", 96_000, 1, None)
    geoeffnet = []

    class FakeStream:
        def __init__(self, samplerate, **_kw):
            self.rate, self.closed = samplerate, False
            geoeffnet.append(self)

        def start(self):
            # Beim Start muss der Resampler schon zur Rate passen - Callbacks kommen sofort.
            self.resampler_down = track._resampler.down
            if self.rate == 96_000:
                raise RuntimeError("Invalid sample rate")

        def close(self):
            self.closed = True

    monkeypatch.setattr(coreaudio, "_sounddevice", lambda: SimpleNamespace(InputStream=FakeStream))
    log = []
    device = {"index": 0, "name": "Mic", "rate": 96_000, "channels": 1}
    coreaudio.MicStream(track, device, lambda: 0.0, log.append)
    erst, dann = geoeffnet
    assert erst.closed and not dann.closed
    assert (dann.rate, dann.resampler_down) == (48_000, 3)
    assert log == ["Mikrofon: 96000 Hz nicht möglich, nehme 48000 Hz"]


def test_sck_stream_braucht_pyobjc(monkeypatch):
    monkeypatch.setitem(sys.modules, "ScreenCaptureKit", None)
    with pytest.raises(RuntimeError, match="PyObjC"):
        sck.SckStream(Track("system", 48_000, 2, None), lambda: 0.0, lambda _t: None)


# --- Berechtigungen (TCC) ---------------------------------------------------------------


def test_bewerte_berechtigungen_texte():
    status, teile = berechtigungen.bewerte(
        bildschirm=False, mikrofon=berechtigungen.NICHT_GEFRAGT, host="Terminal"
    )
    assert status == "WARN"
    assert any("Bildschirmaufnahme FEHLT" in t and "'Terminal'" in t for t in teile)
    assert any("noch nicht abgefragt" in t for t in teile)
    status, teile = berechtigungen.bewerte(bildschirm=True, mikrofon=berechtigungen.ERTEILT, host="iTerm")
    assert status == "OK" and teile == ["Bildschirmaufnahme: erteilt", "Mikrofon: erteilt"]
    status, teile = berechtigungen.bewerte(bildschirm=None, mikrofon=berechtigungen.UNBEKANNT, host="x", pyobjc_fehlt=True)
    assert status == "WARN" and "--extra mac" in teile[0]
    status, _ = berechtigungen.bewerte(bildschirm=True, mikrofon=berechtigungen.VERWEIGERT, host="x")
    assert status == "WARN"


def test_host_app_aus_term_program():
    assert berechtigungen.host_app({"TERM_PROGRAM": "Apple_Terminal"}) == "Terminal"
    assert berechtigungen.host_app({"TERM_PROGRAM": "vscode"}) == "Visual Studio Code"
    assert berechtigungen.host_app({}) == "Terminal"
    assert berechtigungen.host_app({"TERM_PROGRAM": "Kitty"}) == "Kitty"


def test_berechtigungen_ausserhalb_von_macos_sind_unbekannt(monkeypatch):
    monkeypatch.setattr(berechtigungen.sys, "platform", "linux")
    assert berechtigungen.mikrofon_status() == berechtigungen.UNBEKANNT
    assert berechtigungen.bildschirm_erlaubt() is None
    assert berechtigungen.hinweis() == ""
    assert berechtigungen.pyobjc_fehlt() is False


def test_berechtigungen_mit_pyobjc_attrappen(monkeypatch):
    monkeypatch.setattr(berechtigungen.sys, "platform", "darwin")
    av = types.ModuleType("AVFoundation")
    av.AVMediaTypeAudio = "soun"
    av.AVCaptureDevice = SimpleNamespace(authorizationStatusForMediaType_=lambda t: 2)
    quartz = types.ModuleType("Quartz")
    quartz.CGPreflightScreenCaptureAccess = lambda: False
    monkeypatch.setitem(sys.modules, "AVFoundation", av)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    assert berechtigungen.mikrofon_status() == berechtigungen.VERWEIGERT
    assert berechtigungen.bildschirm_erlaubt() is False
    hinweis = berechtigungen.hinweis()
    assert "Bildschirmaufnahme FEHLT" in hinweis and "Mikrofon: verweigert" in hinweis


def test_ensure_permissions_ist_ausserhalb_von_macos_ein_noop():
    ensure_permissions(mic=True, system=True, log=lambda _t: None, platform="linux")


def test_ensure_permissions_meldet_fehlende_bildschirmaufnahme(monkeypatch):
    monkeypatch.setattr(berechtigungen, "mikrofon_status", lambda: berechtigungen.ERTEILT)
    monkeypatch.setattr(berechtigungen, "bildschirm_erlaubt", lambda: False)
    angefragt = []
    monkeypatch.setattr(berechtigungen, "bildschirm_anfragen", lambda: angefragt.append(1))
    monkeypatch.setattr(berechtigungen, "host_app", lambda env=None: "Terminal")
    with pytest.raises(RuntimeError, match="Bildschirmaufnahme nicht erlaubt.*'Terminal'"):
        ensure_permissions(mic=True, system=True, log=lambda _t: None, platform="darwin")
    assert angefragt == [1]
    # Ohne System-Spur ist die Bildschirmaufnahme egal.
    ensure_permissions(mic=True, system=False, log=lambda _t: None, platform="darwin")


def test_ensure_permissions_fragt_mikrofon_an(monkeypatch):
    monkeypatch.setattr(berechtigungen, "mikrofon_status", lambda: berechtigungen.NICHT_GEFRAGT)
    monkeypatch.setattr(berechtigungen, "mikrofon_anfragen", lambda: berechtigungen.VERWEIGERT)
    monkeypatch.setattr(berechtigungen, "host_app", lambda env=None: "iTerm")
    log = []
    with pytest.raises(RuntimeError, match="Mikrofon nicht erlaubt.*'iTerm'"):
        ensure_permissions(mic=True, system=False, log=log.append, platform="darwin")
    assert any("Mikrofon-Berechtigung" in z for z in log)


def test_ensure_permissions_laesst_unbekannten_stand_durch(monkeypatch):
    # PyObjC fehlt oder die Abfrage scheitert: kein Verbot behaupten, der Stream versucht es.
    monkeypatch.setattr(berechtigungen, "mikrofon_status", lambda: berechtigungen.UNBEKANNT)
    monkeypatch.setattr(berechtigungen, "bildschirm_erlaubt", lambda: None)
    angefragt = []
    monkeypatch.setattr(berechtigungen, "bildschirm_anfragen", lambda: angefragt.append(1))
    ensure_permissions(mic=True, system=True, log=lambda _t: None, platform="darwin")
    assert angefragt == []


# --- MLX-Backend --------------------------------------------------------------------------


def test_mlx_repo_mapping_und_durchreichen(tmp_path):
    from audioscribe.live.asr_mlx import mlx_repo

    assert mlx_repo("large-v3-turbo") == "mlx-community/whisper-large-v3-turbo"
    assert mlx_repo("small") == "mlx-community/whisper-small-mlx"
    assert mlx_repo("org/eigenes-modell") == "org/eigenes-modell"
    assert mlx_repo(str(tmp_path)) == str(tmp_path)
    assert mlx_repo("small", override="org/x") == "org/x"
    with pytest.raises(RuntimeError, match="Kein MLX-Modell"):
        mlx_repo("large-v9")


def test_mlx_decode_options_ohne_beam_search():
    from audioscribe.live.asr_mlx import mlx_decode_options

    final = mlx_decode_options(final=True)
    cheap = mlx_decode_options(final=False)
    eco = mlx_decode_options(final=True, eco=True)
    for opts in (final, cheap, eco):
        assert "beam_size" not in opts
        assert opts["condition_on_previous_text"] is False
    assert final["temperature"] == (0.0, 0.2, 0.4) and final["best_of"] == 5
    assert cheap["temperature"] == 0.0 and cheap["best_of"] is None
    assert eco["temperature"] == 0.0 and eco["compression_ratio_threshold"] is None


def _fake_mlx(calls: list, language="de"):
    def transcribe(audio, **kw):
        calls.append({"n": len(audio), **kw})
        return {
            "text": " Hallo Welt ",
            "language": language,
            "segments": [
                {"text": " Hallo", "start": 0.0, "end": 0.5, "avg_logprob": -0.21234, "compression_ratio": 1.1, "no_speech_prob": 0.02, "temperature": 0.0},
                {"text": " Welt ", "start": 0.5, "end": 1.0, "avg_logprob": -0.3, "compression_ratio": 1.2, "no_speech_prob": 0.01, "temperature": 0.2},
                {"text": "   ", "start": 1.0, "end": 1.1, "avg_logprob": -1.0, "compression_ratio": 9.0, "no_speech_prob": 0.9, "temperature": 1.0},
            ],
        }

    return SimpleNamespace(transcribe=transcribe)


def test_mlx_transcriber_waermt_vor_und_mappt_das_ergebnis(monkeypatch, tmp_path):
    from audioscribe.live import asr_mlx
    from audioscribe.live.asr import make_transcriber

    calls: list = []
    monkeypatch.setitem(sys.modules, "mlx_whisper", _fake_mlx(calls))
    monkeypatch.setattr(asr_mlx, "fetch_mlx_model", lambda repo, on_progress=None: str(tmp_path / repo.replace("/", "_")))
    asr = make_transcriber("mlx", "large-v3-turbo", "mps", "int8", "auto", on_progress=lambda a, b: None)
    assert isinstance(asr, asr_mlx.MlxTranscriber)
    assert len(calls) == 1 and calls[0]["n"] == SAMPLE_RATE  # Aufwaermen mit 1 s Nullen
    assert asr.detected == ""
    erg = asr.transcribe(np.zeros(8000, dtype=np.float32), final=True, initial_prompt="Hallo")
    assert erg.text == "Hallo Welt"
    assert [s.temperature for s in erg.segmente] == [0.0, 0.2]
    assert erg.segmente[0].avg_logprob == -0.212
    assert asr.detected == "de"
    assert calls[-1]["path_or_hf_repo"] == calls[0]["path_or_hf_repo"]  # immer derselbe Pfad -> kein Neuladen
    assert calls[-1]["initial_prompt"] == "Hallo" and calls[-1]["language"] is None
    assert "beam_size" not in calls[-1]
    asr.transcribe(np.zeros(8000, dtype=np.float32), final=False)
    assert calls[-1]["temperature"] == 0.0


def test_make_transcriber_reicht_cpu_statt_mps_an_faster_whisper(monkeypatch):
    from audioscribe.live import asr

    seen = {}

    class FakeModel:
        def __init__(self, model, device, device_index, compute_type, cpu_threads):
            seen.update(model=model, device=device, compute_type=compute_type)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))
    t = asr.make_transcriber("faster-whisper", "small", "mps", "int8", "de")
    assert isinstance(t, asr.LiveTranscriber)
    assert seen == {"model": "small", "device": "cpu", "compute_type": "int8"}


def test_default_model_je_backend_und_geraet():
    from audioscribe.live.asr import default_model

    assert default_model("cuda") == "large-v3-turbo"
    assert default_model("mps", "mlx") == "large-v3-turbo"
    assert default_model("mps", "faster-whisper") == "small"
    assert default_model("cpu") == "small"


def test_fetch_mlx_model_cache_zuerst_dann_download_mit_fortschritt(monkeypatch, tmp_path):
    from audioscribe.pipeline import models

    aufrufe = []

    def snapshot_download(repo, **kw):
        aufrufe.append(kw)
        if kw.get("local_files_only"):
            raise OSError("nicht im Cache")
        return str(tmp_path / "snap")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    meldungen = []
    assert models.fetch_mlx_model("mlx-community/x", lambda a, b: meldungen.append((a, b))) == str(tmp_path / "snap")
    assert aufrufe[0] == {"local_files_only": True}
    assert "tqdm_class" in aufrufe[1]
    bar = aufrufe[1]["tqdm_class"](total=100, unit="B")
    bar.n = 40
    bar.display()
    assert meldungen[-1] == (40, 100)
    assert models.fetch_mlx_model(str(tmp_path)) == str(tmp_path)


# --- Nachschaerfen ueber MLX: WhisperX-kompatibles Ergebnis -------------------------------


def test_speech_windows_fasst_zusammen_und_teilt():
    from audioscribe.pipeline.transcribe_mlx import speech_windows

    r = 16_000
    spans = [(1 * r, 5 * r), (6 * r, 12 * r), (40 * r, 45 * r), (50 * r, 95 * r)]
    win = speech_windows(spans, 100 * r, max_s=30.0, pad_s=0.0, rate=r)
    assert win[0] == (1 * r, 12 * r)  # zwei Spannen in einem Fenster
    assert win[1] == (40 * r, 45 * r)
    assert win[2:] == [(50 * r, 80 * r), (80 * r, 95 * r)]  # 45 s in 30 + 15
    assert speech_windows([], 10 * r) == []
    # Polsterung bleibt im Audio.
    assert speech_windows([(0, r)], 10 * r, pad_s=0.3, rate=r) == [(0, int(1.3 * r))]


def test_transcribe_mlx_liefert_whisperx_format(monkeypatch, tmp_path):
    from audioscribe.pipeline import transcribe_mlx as tm

    calls: list = []
    fake = _fake_mlx(calls, language="en")
    monkeypatch.setattr(tm, "fetch_mlx_model", lambda repo, on_progress=None: str(tmp_path))
    monkeypatch.setattr(tm, "free_mlx_model", lambda: calls.append("free"))
    audio = np.zeros(40 * SAMPLE_RATE, dtype=np.float32)
    vad = lambda a: [(2 * SAMPLE_RATE, 4 * SAMPLE_RATE), (35 * SAMPLE_RATE, 37 * SAMPLE_RATE)]  # noqa: E731
    result = tm.transcribe_mlx(audio, None, model="large-v3", language=None, vad=vad, mlx_module=fake)
    assert result["language"] == "en"
    assert [s["text"] for s in result["segments"]] == ["Hallo", "Welt", "Hallo", "Welt"]
    # Offsets der Fenster (mit 0,3 s Polsterung) sind eingerechnet.
    assert result["segments"][0]["start"] == pytest.approx(1.7, abs=0.01)
    assert result["segments"][2]["start"] == pytest.approx(34.7, abs=0.01)
    assert calls[-1] == "free"
    assert "beam_size" not in calls[0] and calls[0]["best_of"] == 5
    leer = tm.transcribe_mlx(audio, None, model="large-v3", language="de", vad=lambda a: [], mlx_module=fake)
    assert leer == {"segments": [], "language": "de"}


def test_transcribe_dispatcht_auf_mlx(monkeypatch):
    from audioscribe.pipeline import transcribe as t

    monkeypatch.setattr(t, "resolve_device", lambda raw: "mps")
    monkeypatch.setattr(t, "resolve_asr_backend", lambda raw, device: "mlx")
    fake = types.ModuleType("audioscribe.pipeline.transcribe_mlx")
    fake.transcribe_mlx = lambda audio, reporter, *, model, language: {"segments": [], "language": language or "x", "model": model}
    monkeypatch.setitem(sys.modules, "audioscribe.pipeline.transcribe_mlx", fake)
    out = t.transcribe(np.zeros(10, dtype=np.float32))
    assert out["model"] == t.settings.whisper_model


# --- Fenster unter macOS ---------------------------------------------------------------------


def test_fenster_mac_eintraege_filtern_shell_und_eigenes():
    from audioscribe.live import fenster_mac

    infos = [
        {"kCGWindowNumber": 1, "kCGWindowName": "Teams", "kCGWindowOwnerName": "Microsoft Teams", "kCGWindowOwnerPID": 10, "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}},
        {"kCGWindowNumber": 2, "kCGWindowName": "", "kCGWindowOwnerName": "Finder", "kCGWindowOwnerPID": 11, "kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 800, "Height": 600}},
        {"kCGWindowNumber": 3, "kCGWindowName": "Dock", "kCGWindowOwnerName": "Dock", "kCGWindowOwnerPID": 12, "kCGWindowLayer": 20, "kCGWindowBounds": {"Width": 800, "Height": 60}},
        {"kCGWindowNumber": 4, "kCGWindowName": "Ich", "kCGWindowOwnerName": "Terminal", "kCGWindowOwnerPID": 99, "kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 10, "Height": 10}},
    ]
    out = fenster_mac.eintraege(infos, eigene_pid=99)
    assert out == [{"hwnd": 1, "title": "Teams", "process": "Microsoft Teams", "pid": 10, "width": 800, "height": 600}]


def test_fenster_delegiert_unter_macos(monkeypatch):
    from audioscribe.live import fenster

    monkeypatch.setattr(fenster.sys, "platform", "darwin")
    fake = types.ModuleType("audioscribe.live.fenster_mac")
    fake.list_windows = lambda: [{"hwnd": 5}]
    fake.is_window = lambda h: h == 5
    fake.window_title = lambda h: "T"
    import audioscribe.live

    monkeypatch.setitem(sys.modules, "audioscribe.live.fenster_mac", fake)
    monkeypatch.setattr(audioscribe.live, "fenster_mac", fake, raising=False)
    assert fenster.list_windows() == [{"hwnd": 5}]
    assert fenster.is_window(5) and not fenster.is_window(6)
    assert fenster.window_title(5) == "T"


def test_fenster_liste_leer_ohne_pyobjc_unter_macos(monkeypatch):
    from audioscribe.live import fenster

    import audioscribe.live
    from audioscribe.live import fenster_mac

    monkeypatch.setattr(fenster.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "Quartz", None)
    monkeypatch.setattr(audioscribe.live, "fenster_mac", fenster_mac, raising=False)
    assert fenster.list_windows() == []


# --- Session: Backend und Stellschrauben kommen an ----------------------------------------------


def test_session_bilanz_traegt_backend_und_geraet(tmp_path, monkeypatch):
    from audioscribe.live import session as sess
    from audioscribe.live.bilanz import load_bilanz
    from audioscribe.live.session import LiveOptions, LiveSession

    monkeypatch.setattr(sess.events, "emit", lambda *a, **k: None)
    monkeypatch.setattr(sess.events, "log", lambda *a, **k: None)
    s = LiveSession(LiveOptions(output_dir=tmp_path, model="large-v3-turbo", device="mps", compute_type="int8", backend="mlx"))
    s._asr = SimpleNamespace(detected="de")
    s.dir.mkdir(parents=True)
    s._finish(laden_s=1.0, aufnahme_s=2.0, abschluss_s=0.1, gesamt_s=3.2)
    live = load_bilanz(s.dir)["live"]
    assert live["backend"] == "mlx" and live["geraet"] == "mps" and live["modell"] == "large-v3-turbo"


def test_session_laedt_asr_ueber_die_fabrik(monkeypatch, tmp_path):
    from audioscribe.live import asr
    from audioscribe.live.session import LiveOptions, LiveSession

    seen = {}
    monkeypatch.setattr(asr, "make_transcriber", lambda backend, model, device, ct, lang, **kw: seen.update(backend=backend, device=device) or "ASR")
    s = LiveSession(LiveOptions(output_dir=tmp_path, model="small", device="mps", compute_type="int8", backend="mlx"))
    assert s._load_asr() == "ASR"
    assert seen == {"backend": "mlx", "device": "mps"}


def test_beschreibe_live_nennt_backend():
    from audioscribe.live.bilanz import LiveBilanz, beschreibe_live

    b = LiveBilanz(laden_s=1, aufnahme_s=10, abschluss_s=0.1, gesamt_s=11, backend="mlx", geraet="mps", modell="large-v3-turbo")
    assert beschreibe_live(b).endswith("large-v3-turbo/mlx/mps")
