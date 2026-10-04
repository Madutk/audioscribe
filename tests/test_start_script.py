"""start.sh / AudioScribe.command (FR-50): Syntax, ASCII, Extras-Wahl je Plattform - ohne uv."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKRIPTE = ("start.sh", "AudioScribe.command")


@pytest.mark.parametrize("name", SKRIPTE)
def test_skript_syntax(name):
    assert subprocess.run(["bash", "-n", str(ROOT / name)], capture_output=True).returncode == 0


@pytest.mark.parametrize("name", (*SKRIPTE, "start.ps1"))
def test_skript_ist_ascii(name):
    assert (ROOT / name).read_bytes().isascii(), f"{name}: nur ASCII (PowerShell 5.1, fremde Terminals)"


@pytest.mark.parametrize("name", SKRIPTE)
def test_skript_ist_im_git_ausfuehrbar(name):
    """Der drvfs-Mount unter WSL verliert das Ausfuehrungsbit - massgeblich ist der Modus im Index."""
    if shutil.which("git") is None:
        pytest.skip("kein git")
    proc = subprocess.run(["git", "ls-files", "-s", name], cwd=ROOT, capture_output=True, text=True)
    if not proc.stdout.strip():
        # Noch nicht eingecheckt: dann muss wenigstens die Datei ausfuehrbar sein.
        assert os.name == "nt" or (ROOT / name).stat().st_mode & stat.S_IXUSR
        return
    assert proc.stdout.split()[0] == "100755", f"{name}: git update-index --chmod=+x {name}"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck nicht installiert")
def test_shellcheck():
    proc = subprocess.run(["shellcheck", str(ROOT / "start.sh")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def _fake_bin(tmp_path: Path, os_name: str, arch: str, nvidia: bool) -> Path:
    """uname und uv (und ggf. nvidia-smi) als Attrappen; uv druckt nur seine Argumente."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uname").write_text(
        f'#!/bin/sh\ncase "$1" in -s) echo {os_name};; -m) echo {arch};; *) echo {os_name};; esac\n'
    )
    (bin_dir / "uv").write_text('#!/bin/sh\necho "UV $*"\necho "VENV $UV_PROJECT_ENVIRONMENT"\necho "MPSFB ${PYTORCH_ENABLE_MPS_FALLBACK:-}"\n')
    if nvidia:
        (bin_dir / "nvidia-smi").write_text("#!/bin/sh\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, os_name: str, arch: str, *args: str, nvidia: bool = False) -> str:
    bin_dir = _fake_bin(tmp_path, os_name, arch, nvidia)
    env = {k: v for k, v in os.environ.items() if k != "UV_PROJECT_ENVIRONMENT"}
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    proc = subprocess.run(
        ["bash", str(ROOT / "start.sh"), *args], capture_output=True, text=True, env=env, cwd=ROOT, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout + proc.stderr


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_start_sh_mac_waehlt_cpu_mac_live_und_venv_mac(tmp_path):
    out = _run(tmp_path, "Darwin", "arm64", "--port", "9000")
    assert "UV run --extra cpu --extra review --extra agent --extra live --extra mac audioscribe ui --port 9000" in out
    assert "VENV " in out and out.split("VENV ")[1].split()[0].endswith(".venv-mac")
    assert "MPSFB 1" in out
    assert "Erster Start auf macOS" in out  # .venv-mac gibt es hier nicht


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_start_sh_intel_mac_ohne_mac_extra(tmp_path):
    out = _run(tmp_path, "Darwin", "x86_64", "--no-browser")
    assert "--extra mac" not in out and "Intel-Mac" in out
    assert "audioscribe ui --port 8766 --no-browser" in out


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_start_sh_linux_ohne_karte_cpu_mit_karte_cu124(tmp_path):
    out = _run(tmp_path, "Linux", "x86_64", "--doctor")
    assert "UV run --extra cpu --extra review --extra agent --extra live audioscribe doctor" in out
    assert out.split("VENV ")[1].split()[0].endswith("/.venv")
    out = _run(tmp_path / "n", "Linux", "x86_64", "--devices", nvidia=True) if (tmp_path / "n").mkdir() is None else ""
    assert "--extra cu124" in out and "live --list-devices" in out


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_start_sh_mac_cu124_wird_zu_cpu(tmp_path):
    out = _run(tmp_path, "Darwin", "arm64", "--torch", "cu124", "--doctor")
    assert "--extra cpu" in out and "--extra cu124" not in out and "CUDA gibt es nicht" in out


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_start_sh_unbekannte_option(tmp_path):
    proc = subprocess.run(["bash", str(ROOT / "start.sh"), "--foo"], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 2 and "Unbekannte Option" in proc.stderr
