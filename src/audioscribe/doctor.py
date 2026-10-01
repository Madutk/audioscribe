"""Umgebungs-Check. Aufruf: ``audioscribe doctor`` (``--json`` fuer Maschinen).

Jeder Check liefert (Status, Name, Detail); Status ist OK / WARN / FAIL.
Exit-Code 0, wenn kein FAIL auftritt.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from audioscribe.config import ensure_ffmpeg_on_path, resolve_compute_type, settings

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


def evaluate_device(
    raw_device: str,
    cuda_ok: bool,
    torch_version: str,
    compute_type_raw: str,
    gpu_name: str | None = None,
    nvidia_karte: bool = False,
) -> CheckResult:
    """Reine Bewertungslogik fuer den Device-Check (testbar ohne torch).

    Statusmatrix (PRD §14, FR-22): fehlendes CUDA ist nur noch FAIL, wenn das
    Geraet explizit auf cuda erzwungen wurde; 'auto' faellt auf CPU zurueck.
    """
    raw = raw_device.strip().lower()
    build = f"torch {torch_version}"

    if raw.startswith("cuda") and not cuda_ok:
        return CheckResult(
            "FAIL",
            "PyTorch/Device",
            f"{build} -> Device '{raw_device}' erzwungen, aber CUDA nicht verfuegbar "
            "(CPU-Build/Treiber?) -> '--device auto|cpu' oder 'uv sync --extra cu124'",
        )

    device = "cuda" if (raw == "auto" and cuda_ok) else ("cpu" if raw == "auto" else raw)
    compute_type = resolve_compute_type(compute_type_raw, device)

    if device.startswith("cuda"):
        label = f"auto={device}" if raw == "auto" else device
        gpu = f" ({gpu_name})" if gpu_name else ""
        return CheckResult(
            "OK", "PyTorch/Device", f"{build} -> {label}{gpu}, compute_type={compute_type}"
        )

    if raw == "auto":
        detail = f"{build} -> auto=cpu, CPU-Fallback (langsam), compute_type={compute_type}"
    else:
        hint = " — Hinweis: CUDA waere verfuegbar" if cuda_ok else ""
        detail = f"{build} -> cpu (explizit; langsam), compute_type={compute_type}{hint}"
    if not cuda_ok and "+cpu" not in torch_version:
        # CUDA-/PyPI-Build ohne nutzbares CUDA: die schlanken CPU-Wheels sparen ~3 GB.
        detail += " — Tipp: 'uv sync --extra cpu' installiert die schlanken CPU-Wheels"
    elif not cuda_ok and nvidia_karte:
        # Karte da, aber CPU-Wheels installiert. Das passiert schneller als man denkt:
        # 'uv run' synchronisiert vorher ohne die gewaehlten Extras und ersetzt die
        # CUDA-Wheels stillschweigend wieder durch die von PyPI.
        detail += (
            " — NVIDIA-Karte erkannt, aber CPU-Build installiert: "
            "'uv sync --extra cu124 --extra review' (und die UI danach ohne 'uv run' starten)"
        )
    return CheckResult("OK", "PyTorch/Device", detail)


def _check_torch_device() -> CheckResult:
    try:
        import torch
    except ImportError as exc:
        return CheckResult(
            "FAIL",
            "PyTorch",
            f"Import fehlgeschlagen: {exc} -> 'uv sync --extra cpu' oder '--extra cu124'",
        )
    cuda_ok = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_ok else None
    # nvidia-smi kommt mit dem Treiber, nicht mit torch: seine blosse Anwesenheit verraet
    # eine Karte auch dann, wenn torch als CPU-Build gar nichts von ihr wissen kann.
    return evaluate_device(
        settings.device,
        cuda_ok,
        torch.__version__,
        settings.whisper_compute_type,
        gpu_name,
        nvidia_karte=bool(shutil.which("nvidia-smi")),
    )


def _check_whisperx() -> CheckResult:
    from audioscribe.compat import ensure_ctranslate2_loadable, ensure_pkg_resources

    ensure_ctranslate2_loadable()  # execstack-Fix fuer glibc >= 2.41, vor dem Import
    ensure_pkg_resources()  # pkg_resources-Ersatz fuer ctranslate2 unter Windows
    try:
        import whisperx  # noqa: F401

        # whisperx laedt sein ASR-Modul erst bei Gebrauch nach - ohne diesen Import
        # faende der Check ein kaputtes ctranslate2 nicht und der Lauf braeche erst
        # in Stufe 3 ab, nach Audio-Extraktion und Modell-Download.
        import ctranslate2  # noqa: F401
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
    # Zuerst der Token selbst: ein abgelehnter Token laesst JEDES gesperrte Repo als
    # "Bedingungen nicht akzeptiert" erscheinen - die Meldung schickte den Nutzer sonst
    # zum falschen Knopf.
    from audioscribe.hf import token_status

    status, detail = token_status(settings.hf_token)
    if status == "FEHLT":
        return CheckResult("FAIL", "Diarisierung", f"{detail} -> 'run' bricht ab")
    if status == "UNGUELTIG":
        return CheckResult("FAIL", "HF_TOKEN", f"{detail} -> 'run' bricht ab")
    if status == "UNPRUEFBAR":
        return CheckResult("WARN", "Diarisierung", f"{detail}; HF_TOKEN gesetzt")

    # Ein gueltiger Token heisst NICHT, dass die Modell-Bedingungen akzeptiert sind.
    # auth_check fragt das ohne Download ab.
    try:
        from huggingface_hub import auth_check
        from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
    except Exception:  # noqa: BLE001
        return CheckResult(
            "OK", "Diarisierung", f"HF_TOKEN gesetzt (Zugriff nicht pruefbar); {settings.diarization_model}"
        )
    for repo in (settings.diarization_model, "pyannote/segmentation-3.0"):
        try:
            auth_check(repo, token=settings.hf_token)
        except (GatedRepoError, RepositoryNotFoundError):
            return CheckResult(
                "FAIL",
                "Diarisierung",
                f"Bedingungen NICHT akzeptiert: https://hf.co/{repo} "
                "(eingeloggt 'Agree' klicken) -> 'run' bricht ab",
            )
        except Exception as exc:  # noqa: BLE001 - Netzwerk o.ae.
            return CheckResult(
                "WARN", "Diarisierung", f"Zugriff nicht pruefbar ({type(exc).__name__}); HF_TOKEN gesetzt"
            )
    return CheckResult("OK", "Diarisierung", "Token + Bedingungen ok (speaker-diarization-3.1, segmentation-3.0)")


def _check_dirs() -> CheckResult:
    try:
        settings.ensure_dirs()
    except OSError as exc:
        return CheckResult("FAIL", "Verzeichnisse", f"nicht anlegbar: {exc}")
    return CheckResult("OK", "Verzeichnisse", f"input/output/work unter {settings.project_root}")


def _check_agent() -> CheckResult:
    """KI-Analyse (optional, daher hoechstens WARN): SDK, Claude Code, Skills, Abrechnung."""
    try:
        import claude_agent_sdk
    except ImportError:
        return CheckResult(
            "WARN", "KI-Analyse", "Claude Agent SDK fehlt (optional) -> 'uv sync --extra agent'"
        )
    from audioscribe.agent.skills import discover_skills

    # Das SDK bringt eine eigene Claude-Code-CLI mit; sonst wird die installierte benutzt.
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
    has_cli = any(bundled.glob("claude*")) or bool(shutil.which("claude"))
    skills = discover_skills(settings.agent_skills_dir)
    known = {s.name for s in skills}
    fehlend = [n for n in settings.agent_skills if n not in known]

    teile = [f"SDK {getattr(claude_agent_sdk, '__version__', '?')}, Modell {settings.agent_model}"]
    teile.append(f"{len(skills)} Skill(s) in {settings.agent_skills_dir}")
    status: Status = "OK"
    if not has_cli:
        status = "WARN"
        teile.append("Claude Code nicht gefunden")
    if fehlend:
        status = "WARN"
        teile.append("Vorauswahl fehlt: " + ", ".join(fehlend))
    from audioscribe.agent.prozessbild import find_browser

    browser = find_browser()
    if browser is None:
        status = "WARN"
        teile.append("Prozessbild: kein Edge/Chrome gefunden (AUDIOSCRIBE_BROWSER setzen)")
    else:
        teile.append(f"Prozessbild via {browser.name}")
    if os.environ.get("ANTHROPIC_API_KEY"):
        status = "WARN"
        teile.append("ANTHROPIC_API_KEY gesetzt -> Abrechnung ueber die API statt ueber das Abo")
    else:
        teile.append("Abrechnung ueber das Claude-Abo (Login per 'claude')")
    return CheckResult(status, "KI-Analyse", "; ".join(teile))


def _check_live() -> CheckResult:
    """Live-Transkription (optional, daher hoechstens WARN): Plattform, Geraete, Monitore."""
    if sys.platform != "win32":
        return CheckResult("WARN", "Live", "nur unter nativem Windows verfuegbar (WASAPI)")
    from audioscribe.live.kommando import inventory

    inv = inventory()
    teile = [
        f"{len(inv['mics'])} Mikrofon(e)",
        f"{len(inv['loopbacks'])} Loopback-Geraet(e)",
        f"{len(inv['monitors'])} Monitor(e)",
        *inv["problems"],
    ]
    ok = not inv["problems"] and inv["loopbacks"] and inv["monitors"]
    return CheckResult("OK" if ok else "WARN", "Live", "; ".join(teile))


CHECKS = (
    _check_python,
    _check_ffmpeg,
    _check_torch_device,
    _check_whisperx,
    _check_diarization,
    _check_dirs,
    _check_agent,
    _check_live,
)

_ICON = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}


def _safe(check) -> CheckResult:
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - ein Check darf die anderen nicht mitreissen
        name = check.__name__.removeprefix("_check_")
        return CheckResult("FAIL", name, f"Pruefung abgebrochen: {type(exc).__name__}: {exc}")


def run_doctor(*, as_json: bool = False) -> int:
    """Alle Checks ausfuehren; ``as_json`` gibt sie als Liste von Objekten aus.

    Die JSON-Form liest die Browser-Oberflaeche (Karte "Umgebung" im Reiter
    Einstellungen) aus einem Wegwerf-Subprozess - torch/pyannote bleiben so aus dem
    Server-Prozess heraus. Ein einzelner geplatzter Check wird dort als FAIL-Zeile
    gemeldet statt die ganze Liste zu verlieren.
    """
    results = [_safe(check) for check in CHECKS] if as_json else [check() for check in CHECKS]
    if as_json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False))
        return 1 if any(r.status == "FAIL" for r in results) else 0
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
