"""Packaging (NFR-19/20): ein uv.lock fuer alle Plattformen, mac-Extra nur mit darwin-Markern."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_mac_extra_traegt_plattform_marker():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "mac" in extras
    for spec in extras["mac"]:
        assert "sys_platform == 'darwin'" in spec, spec
    mlx = [s for s in extras["mac"] if s.startswith("mlx-whisper")]
    assert mlx and "platform_machine == 'arm64'" in mlx[0]
    for paket in ("sounddevice", "pyobjc-framework-ScreenCaptureKit", "pyobjc-framework-Quartz", "pyobjc-framework-AVFoundation"):
        assert any(s.startswith(paket) for s in extras["mac"]), paket


def test_mac_und_cu124_schliessen_sich_aus():
    conflicts = _pyproject()["tool"]["uv"]["conflicts"]
    paare = [{c["extra"] for c in gruppe} for gruppe in conflicts]
    assert {"cpu", "cu124"} in paare and {"mac", "cu124"} in paare


def test_live_extra_bleibt_plattformneutral():
    live = _pyproject()["project"]["optional-dependencies"]["live"]
    assert any(s.startswith("PyAudioWPatch") and "win32" in s for s in live)
    assert not any("mlx" in s or "pyobjc" in s for s in live)


def test_lock_haengt_mlx_nur_an_darwin_arm64():
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "pyobjc-framework-screencapturekit"' in lock
    # Im audioscribe-Block traegt die mlx-whisper-Abhaengigkeit den Plattform-Marker.
    zeilen = [z for z in lock.splitlines() if 'name = "mlx-whisper", marker' in z]
    assert zeilen, "mlx-whisper fehlt im Lock"
    for z in zeilen:
        assert "sys_platform == 'darwin'" in z and "platform_machine == 'arm64'" in z, z


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv nicht installiert")
def test_lock_ist_aktuell():
    proc = subprocess.run(["uv", "lock", "--check"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
