"""Tests fuer die Geraete-/compute_type-Aufloesung (PRD §14, FR-20..22).

Reine Logiktests ohne torch: die CUDA-Probe wird injiziert.
"""

import pytest

from audioscribe.config import resolve_compute_type, resolve_device
from audioscribe.doctor import evaluate_device


def _boom() -> bool:
    raise AssertionError("CUDA-Probe darf hier nicht aufgerufen werden")


# --- resolve_device (FR-20) ---


def test_auto_waehlt_cuda_falls_verfuegbar():
    assert resolve_device("auto", cuda_check=lambda: True) == "cuda"


def test_auto_faellt_auf_cpu_zurueck():
    assert resolve_device("auto", cuda_check=lambda: False) == "cpu"


def test_explizites_cpu_ohne_cuda_probe():
    # Bei explizitem cpu darf kein torch-Import/keine Probe passieren.
    assert resolve_device("cpu", cuda_check=_boom) == "cpu"


def test_erzwungenes_cuda_ohne_cuda_ist_fehler():
    with pytest.raises(RuntimeError, match="CUDA"):
        resolve_device("cuda", cuda_check=lambda: False)


def test_cuda_mit_geraetenummer_bleibt_erhalten():
    assert resolve_device("cuda:1", cuda_check=lambda: True) == "cuda:1"


def test_gross_kleinschreibung_und_whitespace():
    assert resolve_device(" AUTO ", cuda_check=lambda: False) == "cpu"


# --- resolve_compute_type (FR-21) ---


@pytest.mark.parametrize(
    ("raw", "device", "expected"),
    [
        ("auto", "cuda", "float16"),
        ("auto", "cuda:0", "float16"),
        ("auto", "cpu", "int8"),
        ("int8_float16", "cpu", "int8_float16"),  # explizite Angabe gewinnt
        ("float16", "cpu", "float16"),
        ("int8", "cuda", "int8"),
    ],
)
def test_resolve_compute_type(raw, device, expected):
    assert resolve_compute_type(raw, device) == expected


# --- doctor-Statusmatrix (FR-22) ---


def test_doctor_cuda_erzwungen_und_verfuegbar():
    r = evaluate_device("cuda", True, "2.6.0+cu124", "auto", gpu_name="RTX 3080")
    assert r.status == "OK"
    assert "RTX 3080" in r.detail
    assert "compute_type=float16" in r.detail


def test_doctor_cuda_erzwungen_ohne_cuda_ist_fail():
    r = evaluate_device("cuda", False, "2.6.0+cpu", "auto")
    assert r.status == "FAIL"
    assert "erzwungen" in r.detail
    assert "+cpu" in r.detail


def test_doctor_explizit_cpu_mit_cuda():
    r = evaluate_device("cpu", True, "2.6.0+cu124", "auto")
    assert r.status == "OK"
    assert "explizit" in r.detail
    assert "CUDA waere verfuegbar" in r.detail
    assert "compute_type=int8" in r.detail


def test_doctor_explizit_cpu_ohne_cuda():
    r = evaluate_device("cpu", False, "2.6.0+cpu", "auto")
    assert r.status == "OK"
    assert "compute_type=int8" in r.detail


def test_doctor_auto_mit_cuda():
    r = evaluate_device("auto", True, "2.6.0+cu124", "auto", gpu_name="RTX 3080")
    assert r.status == "OK"
    assert "auto=cuda" in r.detail
    assert "RTX 3080" in r.detail


def test_doctor_auto_ohne_cuda_ist_ok_mit_fallback_hinweis():
    r = evaluate_device("auto", False, "2.6.0+cpu", "auto")
    assert r.status == "OK"
    assert "CPU-Fallback" in r.detail
    assert "compute_type=int8" in r.detail


def test_doctor_expliziter_compute_type_gewinnt():
    r = evaluate_device("auto", False, "2.6.0+cpu", "int8_float16")
    assert "compute_type=int8_float16" in r.detail


def test_doctor_tipp_auf_cpu_wheels_bei_fettem_build_ohne_cuda():
    # PyPI-/CUDA-Build installiert, aber kein CUDA nutzbar -> Tipp auf --extra cpu.
    r = evaluate_device("auto", False, "2.6.0+cu124", "auto")
    assert r.status == "OK"
    assert "--extra cpu" in r.detail


def test_doctor_kein_tipp_bei_cpu_build():
    r = evaluate_device("auto", False, "2.6.0+cpu", "auto")
    assert "--extra cpu" not in r.detail
