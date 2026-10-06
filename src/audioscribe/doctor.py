"""Umgebungs-Check. Aufruf: ``audioscribe doctor`` (``--json`` fuer Maschinen).

Jeder Check liefert (Status, Name, Detail); Status ist OK / WARN / FAIL.
Exit-Code 0, wenn kein FAIL auftritt.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from audioscribe.config import ct2_device, ensure_ffmpeg_on_path, resolve_compute_type, settings

Status = Literal["OK", "WARN", "FAIL"]


@dataclass
class CheckResult:
    status: Status
    name: str
    detail: str


# --- Plattform (PRD §19, FR-50) ---

MACOS_MIN = (14, 0)  # mlx-Wheels gibt es ab macOS 14; ScreenCaptureKit-Audio ab 13.0


def _sysctl(name: str) -> str:
    try:
        return subprocess.run(  # noqa: S603 - festes Kommando
            ["sysctl", "-n", name], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def mac_chip() -> str | None:
    """``Apple M4 Pro`` o. ae.; ``None`` ausserhalb von macOS."""
    if sys.platform != "darwin":
        return None
    return _sysctl("machdep.cpu.brand_string") or platform.processor() or None


def evaluate_mac_platform(
    version: str, machine: str, translated: bool, chip: str | None, host: str
) -> CheckResult:
    """Reine Bewertung der macOS-Plattform (testbar ohne Mac)."""
    teile = [f"macOS {version or '?'} ({machine}{', ' + chip if chip else ''})", f"Terminal-App: {host}"]
    try:
        parts = tuple(int(p) for p in version.split(".")[:2])
    except ValueError:
        parts = ()
    status: Status = "OK"
    if machine != "arm64" or translated:
        status = "WARN"
        teile.append(
            "Rosetta/Intel -> kein MPS/MLX, CPU-Betrieb"
            + (" (arm64-Python verwenden: uv python install 3.12)" if translated else "")
        )
    if parts and parts < MACOS_MIN:
        status = "WARN"
        teile.append(f"MLX braucht macOS >= {MACOS_MIN[0]}, ScreenCaptureKit-Audio >= 13 -> ohne MLX nur CPU")
    return CheckResult(status, "Plattform", "; ".join(teile))


def _check_platform() -> CheckResult:
    if sys.platform == "darwin":
        from audioscribe.live.berechtigungen import host_app

        return evaluate_mac_platform(
            platform.mac_ver()[0],
            platform.machine(),
            _sysctl("sysctl.proc_translated") == "1",
            mac_chip(),
            host_app(),
        )
    if sys.platform == "win32":
        return CheckResult("OK", "Plattform", f"Windows {platform.release()} ({platform.machine()})")
    release = os.uname().release
    wsl = " (WSL2)" if "microsoft" in release.lower() else ""
    return CheckResult("OK", "Plattform", f"Linux {release}{wsl} ({platform.machine()})")


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
    *,
    mps_ok: bool = False,
    chip: str | None = None,
    darwin: bool = False,
) -> CheckResult:
    """Reine Bewertungslogik fuer den Device-Check (testbar ohne torch).

    Statusmatrix (PRD §14, FR-22; §19, FR-53): fehlendes CUDA/MPS ist nur FAIL, wenn das
    Geraet explizit erzwungen wurde; 'auto' nimmt cuda > mps > cpu.
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
    if raw == "mps" and not mps_ok:
        return CheckResult(
            "FAIL",
            "PyTorch/Device",
            f"{build} -> Device 'mps' erzwungen, aber Metal (MPS) nicht verfuegbar "
            "(Intel-Mac/Rosetta/macOS < 13?) -> '--device auto|cpu'",
        )

    if raw == "auto":
        device = "cuda" if cuda_ok else ("mps" if mps_ok else "cpu")
    else:
        device = raw
    compute_type = resolve_compute_type(compute_type_raw, ct2_device(device))

    if device == "mps":
        label = "auto=mps" if raw == "auto" else "mps"
        wo = f" ({chip})" if chip else ""
        return CheckResult(
            "OK",
            "PyTorch/Device",
            f"{build} -> {label}{wo}; Alignment/Diarisierung auf MPS, faster-whisper auf CPU "
            f"(ctranslate2 ohne Metal, compute_type={compute_type}) -> Whisper siehe 'ASR-Backend'",
        )

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
    if darwin:
        if not mps_ok:
            detail += " — Tipp: arm64-Python und macOS >= 13 fuer MPS/MLX"
    elif not cuda_ok and "+cpu" not in torch_version:
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
    mps = getattr(torch.backends, "mps", None)
    mps_ok = bool(mps is not None and mps.is_available())
    # nvidia-smi kommt mit dem Treiber, nicht mit torch: seine blosse Anwesenheit verraet
    # eine Karte auch dann, wenn torch als CPU-Build gar nichts von ihr wissen kann.
    return evaluate_device(
        settings.device,
        cuda_ok,
        torch.__version__,
        settings.whisper_compute_type,
        gpu_name,
        nvidia_karte=bool(shutil.which("nvidia-smi")),
        mps_ok=mps_ok,
        chip=mac_chip(),
        darwin=sys.platform == "darwin",
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


def evaluate_asr_backend(
    backend_raw: str, darwin_arm: bool, mlx_version: str | None, mlx_device: str | None = None
) -> CheckResult:
    """Reine Bewertung des ASR-Backends (FR-52): faster-whisper ueberall, mlx auf Apple Silicon."""
    raw = backend_raw.strip().lower()
    if darwin_arm:
        if mlx_version:
            backend = "faster-whisper" if raw == "faster-whisper" else "mlx"
            from audioscribe.live.asr_mlx import mlx_repo

            ziel = mlx_repo("large-v3-turbo", settings.mlx_repo or None)
            detail = f"mlx-whisper {mlx_version}{' (' + mlx_device + ')' if mlx_device else ''}; "
            detail += f"AUDIOSCRIBE_ASR_BACKEND={raw} -> {backend}"
            if backend == "mlx":
                detail += f"; Live-Modell: {ziel}"
            else:
                detail += " (MLX waere schneller: AUDIOSCRIBE_ASR_BACKEND=auto)"
            return CheckResult("OK", "ASR-Backend", detail)
        if raw == "mlx":
            return CheckResult(
                "FAIL",
                "ASR-Backend",
                "mlx erzwungen, aber mlx-whisper fehlt -> 'uv sync --extra cpu --extra mac --extra live'",
            )
        return CheckResult(
            "WARN",
            "ASR-Backend",
            "mlx-whisper fehlt -> 'uv sync --extra cpu --extra mac --extra live' "
            "(sonst faster-whisper auf der CPU: large-v3-turbo nicht live-tauglich)",
        )
    if raw == "mlx":
        return CheckResult("WARN", "ASR-Backend", "mlx nur auf Apple Silicon -> faster-whisper oder 'auto'")
    return CheckResult("OK", "ASR-Backend", "faster-whisper (ctranslate2); MLX nur auf Apple Silicon")


def _check_asr_backend() -> CheckResult:
    darwin_arm = sys.platform == "darwin" and platform.machine() == "arm64"
    mlx_version = mlx_device = None
    if darwin_arm:
        try:
            import importlib.metadata

            import mlx.core as mx
            import mlx_whisper  # noqa: F401

            mlx_version = importlib.metadata.version("mlx-whisper")
            mlx_device = str(mx.default_device())
        except Exception:  # noqa: BLE001 - fehlt oder kaputt -> wie nicht installiert
            mlx_version = None
    return evaluate_asr_backend(settings.asr_backend, darwin_arm, mlx_version, mlx_device)


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
        teile.append(
            "Prozessbild: kein Edge/Chrome gefunden -> Chrome oder Edge installieren "
            "(einzige Komponente ausserhalb von pip; nur fuers Prozessbild) oder AUDIOSCRIBE_BROWSER setzen"
        )
    else:
        teile.append(f"Prozessbild via {browser.name}")
    if os.environ.get("ANTHROPIC_API_KEY"):
        status = "WARN"
        teile.append("ANTHROPIC_API_KEY gesetzt -> Abrechnung ueber die API statt ueber das Abo")
    else:
        teile.append("Abrechnung ueber das Claude-Abo (Login per 'claude')")
    return CheckResult(status, "KI-Analyse", "; ".join(teile))


def _live_inventory(prefix: list[str], status: Status = "OK") -> CheckResult:
    from audioscribe.live.kommando import inventory

    inv = inventory()
    teile = [
        *prefix,
        f"{len(inv['mics'])} Mikrofon(e)",
        f"{len(inv['loopbacks'])} Loopback-Geraet(e)",
        f"{len(inv['monitors'])} Monitor(e)",
        *inv["problems"],
    ]
    ok = status == "OK" and not inv["problems"] and inv["loopbacks"] and inv["monitors"]
    return CheckResult("OK" if ok else "WARN", "Live", "; ".join(teile))


def _check_live() -> CheckResult:
    """Live-Transkription (optional, daher hoechstens WARN): Plattform, Berechtigungen, Geraete."""
    if sys.platform == "win32":
        return _live_inventory([])
    if sys.platform == "darwin":
        from audioscribe.live import berechtigungen

        status, teile = berechtigungen.bewerte(
            bildschirm=berechtigungen.bildschirm_erlaubt(),
            mikrofon=berechtigungen.mikrofon_status(),
            host=berechtigungen.host_app(),
            pyobjc_fehlt=berechtigungen.pyobjc_fehlt(),
        )
        return _live_inventory(teile, "OK" if status == "OK" else "WARN")
    return CheckResult(
        "WARN", "Live", "nur unter nativem Windows (WASAPI) und macOS (ScreenCaptureKit) verfuegbar"
    )


def _bekannte_projekte(saved: dict, limit: int = 5) -> list[tuple[str, Path]]:
    """Zuletzt geoeffnete Projekte, deren Projektdatei noch erreichbar ist (Name, Wiki-Ordner)."""
    from audioscribe.projekt import modell

    out: list[tuple[str, Path]] = []
    for eintrag in saved.get("zuletzt_projekte") or []:
        try:
            projekt = modell.lade(eintrag["pfad"])
        except (modell.ProjektFehler, KeyError, TypeError):
            continue
        out.append((projekt.name, projekt.wurzel))
    return out[:limit]


def _check_souffleur() -> CheckResult:
    """Souffleur (PRD §20, optional, daher hoechstens WARN): Wiki-Verknuepfung und KI-Dienst."""
    from audioscribe.souffleur.ki import BACKEND_CLAUDE, sdk_verfuegbar
    from audioscribe.souffleur.konfig import lade_konfig
    from audioscribe.souffleur.wiki import ZUSTAND_OK, pruefe_wiki
    from audioscribe.ui import state

    saved = state.load_state()
    konfig = lade_konfig(saved)
    projekte = _bekannte_projekte(saved)
    if projekte and konfig.wiki_dir is None:
        # Seit den Projekten (PRD §21) gehoert das Wiki zum Projekt - geprueft werden die bekannten.
        zustaende = [(name, pruefe_wiki(wurzel)) for name, wurzel in projekte]
        teile = ["Wiki je Projekt: " + ", ".join(
            f"{name} ({w.seiten} Seiten)" if w.zustand == ZUSTAND_OK else f"{name} (nicht erreichbar)"
            for name, w in zustaende
        )]
        status = "OK" if all(w.zustand == ZUSTAND_OK for _, w in zustaende) else "WARN"
    else:
        wiki = pruefe_wiki(konfig.wiki_dir)
        teile = [f"Wiki: {wiki.meldung}"]
        status = "OK" if wiki.zustand == ZUSTAND_OK else "WARN"
    if konfig.backend == BACKEND_CLAUDE and not sdk_verfuegbar():
        teile.append("KI: Agent SDK fehlt -> 'uv sync --extra agent'")
        status = "WARN"
    else:
        teile.append(f"KI: {konfig.backend}, Modell {konfig.modell}")
    teile.append(f"Einstellungen: {state.state_path()}")
    return CheckResult(status, "Souffleur", " | ".join(teile))


CHECKS = (
    _check_platform,
    _check_python,
    _check_ffmpeg,
    _check_torch_device,
    _check_whisperx,
    _check_asr_backend,
    _check_diarization,
    _check_dirs,
    _check_agent,
    _check_live,
    _check_souffleur,
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
