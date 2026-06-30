"""Umgebungs-Check. Aufruf: ``audioscribe doctor``.

Jeder Check liefert (Status, Name, Detail); Status ist OK / WARN / FAIL.
Exit-Code 0, wenn kein FAIL auftritt.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import Literal

from audioscribe.config import ensure_ffmpeg_on_path, settings

Status = Literal["OK", "WARN", "FAIL"]


@dataclass
class CheckResult:
    status: Status
    name: str
    detail: str


def _check_python() -> CheckResult:
    v = sys.version_info
    ok = (v.major, v.minor) == (3, 12)
    return CheckResult(
        "OK" if ok else "WARN",
        "Python",
        f"{v.major}.{v.minor}.{v.micro}" + ("" if ok else " (empfohlen: 3.12)"),
    )


def _check_ffmpeg() -> CheckResult:
    if shutil.which("ffmpeg"):
        return CheckResult("OK", "ffmpeg", f"System-ffmpeg: {shutil.which('ffmpeg')}")
    try:
        path = ensure_ffmpeg_on_path()
    except Exception as exc:  # noqa: BLE001
        return CheckResult("FAIL", "ffmpeg", str(exc))
    return CheckResult("OK", "ffmpeg", f"gebuendelt (imageio-ffmpeg) via Wrapper: {path}")


def _check_torch_cuda() -> CheckResult:
    try:
        import torch
    except ImportError as exc:
        return CheckResult("FAIL", "PyTorch", f"Import fehlgeschlagen: {exc}")
    if settings.device.startswith("cpu"):
        return CheckResult("WARN", "PyTorch", f"torch {torch.__version__} -> Geraet 'cpu' (langsam)")
    if not torch.cuda.is_available():
        return CheckResult(
            "FAIL", "PyTorch CUDA", f"torch {torch.__version__} -> CUDA nicht verfuegbar"
        )
    return CheckResult(
        "OK", "PyTorch CUDA", f"torch {torch.__version__} -> {torch.cuda.get_device_name(0)}"
    )


def _check_whisperx() -> CheckResult:
    try:
        import whisperx  # noqa: F401
    except ImportError as exc:
        return CheckResult("FAIL", "WhisperX", f"Import fehlgeschlagen: {exc}")
    return CheckResult("OK", "WhisperX", f"verfuegbar; Modell konfiguriert: {settings.whisper_model}")


def _check_diarization() -> CheckResult:
    if not settings.enable_diarization:
        return CheckResult("WARN", "Diarisierung", "deaktiviert (--no-diarize / AUDIOSCRIBE_DIARIZATION=0)")
    try:
        import pyannote.audio  # noqa: F401
    except ImportError as exc:
        return CheckResult("FAIL", "pyannote.audio", f"Import fehlgeschlagen: {exc}")
    if not settings.hf_token:
        return CheckResult(
            "FAIL",
            "pyannote.audio",
            "aktiviert, aber HF_TOKEN fehlt (siehe .env.example) -> 'run' bricht ab",
        )
    return CheckResult("OK", "pyannote.audio", f"Modell: {settings.diarization_model}, HF_TOKEN gesetzt")


def _check_dirs() -> CheckResult:
    try:
        settings.ensure_dirs()
    except OSError as exc:
        return CheckResult("FAIL", "Verzeichnisse", f"nicht anlegbar: {exc}")
    return CheckResult("OK", "Verzeichnisse", f"input/output/work unter {settings.project_root}")


CHECKS = (
    _check_python,
    _check_ffmpeg,
    _check_torch_cuda,
    _check_whisperx,
    _check_diarization,
    _check_dirs,
)

_ICON = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}


def run_doctor() -> int:
    results = [check() for check in CHECKS]
    print("audioscribe - Umgebungs-Check\n" + "=" * 60)
    worst = 0
    for r in results:
        print(f"{_ICON[r.status]}  {r.name:<16} {r.detail}")
        if r.status == "FAIL":
            worst = 1
    n_fail = sum(1 for r in results if r.status == "FAIL")
    n_warn = sum(1 for r in results if r.status == "WARN")
    print("=" * 60)
    print(f"Ergebnis: {len(results) - n_fail - n_warn} OK, {n_warn} WARN, {n_fail} FAIL")
    return worst


if __name__ == "__main__":
    raise SystemExit(run_doctor())
