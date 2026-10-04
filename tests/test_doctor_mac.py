"""doctor unter macOS (PRD §19, FR-50): reine Bewertungen, Attrappen statt Mac."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from audioscribe import doctor
from audioscribe.doctor import evaluate_asr_backend, evaluate_device, evaluate_mac_platform


def test_mac_platform_ok_auf_apple_silicon():
    r = evaluate_mac_platform("15.1", "arm64", False, "Apple M4 Pro", "Terminal")
    assert r.status == "OK"
    assert "macOS 15.1 (arm64, Apple M4 Pro)" in r.detail and "Terminal-App: Terminal" in r.detail


def test_mac_platform_warnt_bei_altem_macos_und_rosetta():
    alt = evaluate_mac_platform("13.6", "arm64", False, "Apple M1", "iTerm")
    assert alt.status == "WARN" and "MLX braucht macOS >= 14" in alt.detail
    rosetta = evaluate_mac_platform("15.0", "x86_64", True, None, "Terminal")
    assert rosetta.status == "WARN" and "Rosetta" in rosetta.detail and "arm64-Python" in rosetta.detail
    intel = evaluate_mac_platform("15.0", "x86_64", False, None, "Terminal")
    assert intel.status == "WARN" and "CPU-Betrieb" in intel.detail
    kaputt = evaluate_mac_platform("", "arm64", False, None, "Terminal")
    assert kaputt.status == "OK" and "macOS ?" in kaputt.detail


def test_check_platform_linux_nennt_wsl(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor.os, "uname", lambda: SimpleNamespace(release="6.6.1-microsoft-standard-WSL2"))
    r = doctor._check_platform()
    assert r.status == "OK" and "WSL2" in r.detail


def test_check_platform_darwin_mit_attrappen(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor.platform, "mac_ver", lambda: ("15.2", ("", "", ""), ""))
    monkeypatch.setattr(doctor.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(doctor, "_sysctl", lambda name: {"machdep.cpu.brand_string": "Apple M5", "sysctl.proc_translated": "0"}[name])
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    r = doctor._check_platform()
    assert r.status == "OK" and "Apple M5" in r.detail and "Terminal" in r.detail


# --- Device-Matrix mit MPS (FR-53) ---


def test_doctor_auto_mps_mit_chip():
    r = evaluate_device("auto", False, "2.6.0", "auto", mps_ok=True, chip="Apple M4 Pro", darwin=True)
    assert r.status == "OK"
    assert "auto=mps" in r.detail and "Apple M4 Pro" in r.detail
    assert "faster-whisper auf CPU" in r.detail and "compute_type=int8" in r.detail
    assert "--extra cpu" not in r.detail


def test_doctor_mps_erzwungen_ohne_mps_ist_fail():
    r = evaluate_device("mps", False, "2.6.0", "auto", mps_ok=False, darwin=True)
    assert r.status == "FAIL" and "erzwungen" in r.detail


def test_doctor_mps_explizit():
    r = evaluate_device("mps", False, "2.6.0", "auto", mps_ok=True, darwin=True)
    assert r.status == "OK" and r.detail.count("mps") >= 1 and "auto=" not in r.detail


def test_doctor_darwin_ohne_mps_gibt_arm64_tipp_statt_linux_tipps():
    r = evaluate_device("auto", False, "2.6.0", "auto", mps_ok=False, darwin=True)
    assert r.status == "OK" and "auto=cpu" in r.detail
    assert "arm64-Python" in r.detail and "--extra cpu" not in r.detail


def test_doctor_cuda_schlaegt_mps():
    r = evaluate_device("auto", True, "2.6.0+cu124", "auto", gpu_name="RTX", mps_ok=True)
    assert "auto=cuda" in r.detail


def test_doctor_linux_matrix_unveraendert():
    """Alte Aufrufe ohne neue Schluesselwoerter liefern dieselben Texte wie vor der Portierung."""
    r = evaluate_device("auto", False, "2.6.0+cu124", "auto")
    assert r.status == "OK" and "CPU-Fallback" in r.detail and "--extra cpu" in r.detail
    r = evaluate_device("cuda", False, "2.6.0+cpu", "auto")
    assert r.status == "FAIL"


# --- ASR-Backend (FR-52) ---


def test_asr_backend_auf_apple_silicon():
    ok = evaluate_asr_backend("auto", True, "0.4.3", "Device(gpu, 0)")
    assert ok.status == "OK" and "-> mlx" in ok.detail and "whisper-large-v3-turbo" in ok.detail
    fw = evaluate_asr_backend("faster-whisper", True, "0.4.3")
    assert fw.status == "OK" and "-> faster-whisper" in fw.detail and "MLX waere schneller" in fw.detail
    fehlt = evaluate_asr_backend("auto", True, None)
    assert fehlt.status == "WARN" and "--extra mac" in fehlt.detail
    erzwungen = evaluate_asr_backend("mlx", True, None)
    assert erzwungen.status == "FAIL"


def test_asr_backend_ausserhalb_von_apple_silicon():
    r = evaluate_asr_backend("auto", False, None)
    assert r.status == "OK" and "faster-whisper" in r.detail
    r = evaluate_asr_backend("mlx", False, None)
    assert r.status == "WARN" and "nur auf Apple Silicon" in r.detail


def test_check_asr_backend_ohne_mac_ist_faster_whisper(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    assert doctor._check_asr_backend().detail.startswith("faster-whisper")


# --- Live-Check je Plattform (FR-45, FR-51) ---


def _fake_inventory(monkeypatch, loopbacks=1, problems=()):
    fake = types.ModuleType("audioscribe.live.kommando")
    fake.inventory = lambda: {
        "mics": [{"index": 0}],
        "loopbacks": [{"index": -1}] * loopbacks,
        "monitors": [{"index": 1}],
        "windows": [],
        "problems": list(problems),
    }
    monkeypatch.setitem(sys.modules, "audioscribe.live.kommando", fake)
    import audioscribe.live

    monkeypatch.setattr(audioscribe.live, "kommando", fake, raising=False)


def test_check_live_linux_bleibt_warn(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    r = doctor._check_live()
    assert r.status == "WARN" and "macOS (ScreenCaptureKit)" in r.detail


def test_check_live_darwin_mit_berechtigungen_und_inventar(monkeypatch):
    from audioscribe.live import berechtigungen

    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    _fake_inventory(monkeypatch)
    monkeypatch.setattr(berechtigungen, "bildschirm_erlaubt", lambda: True)
    monkeypatch.setattr(berechtigungen, "mikrofon_status", lambda: berechtigungen.ERTEILT)
    monkeypatch.setattr(berechtigungen, "host_app", lambda env=None: "Terminal")
    monkeypatch.setattr(berechtigungen, "pyobjc_fehlt", lambda: False)
    r = doctor._check_live()
    assert r.status == "OK"
    assert "Bildschirmaufnahme: erteilt" in r.detail and "1 Loopback-Geraet(e)" in r.detail


def test_check_live_darwin_ohne_bildschirmaufnahme_ist_warn(monkeypatch):
    from audioscribe.live import berechtigungen

    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    _fake_inventory(monkeypatch, loopbacks=0)
    monkeypatch.setattr(berechtigungen, "bildschirm_erlaubt", lambda: False)
    monkeypatch.setattr(berechtigungen, "mikrofon_status", lambda: berechtigungen.NICHT_GEFRAGT)
    monkeypatch.setattr(berechtigungen, "host_app", lambda env=None: "iTerm")
    monkeypatch.setattr(berechtigungen, "pyobjc_fehlt", lambda: False)
    r = doctor._check_live()
    assert r.status == "WARN"
    assert "Bildschirmaufnahme FEHLT" in r.detail and "'iTerm'" in r.detail
    assert "noch nicht abgefragt" in r.detail


def test_checks_reihenfolge_enthaelt_plattform_und_backend():
    namen = [c.__name__ for c in doctor.CHECKS]
    assert namen[0] == "_check_platform"
    assert namen.index("_check_asr_backend") == namen.index("_check_whisperx") + 1
