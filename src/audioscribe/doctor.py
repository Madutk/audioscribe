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
from audioscribe.i18n import tr

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
    teile = [f"macOS {version or '?'} ({machine}{', ' + chip if chip else ''})", tr("Terminal-App: {host}", host=host)]
    try:
        parts = tuple(int(p) for p in version.split(".")[:2])
    except ValueError:
        parts = ()
    status: Status = "OK"
    if machine != "arm64" or translated:
        status = "WARN"
        teile.append(
            tr("Rosetta/Intel -> kein MPS/MLX, CPU-Betrieb")
            + (tr(" (arm64-Python verwenden: uv python install 3.12)") if translated else "")
        )
    if parts and parts < MACOS_MIN:
        status = "WARN"
        teile.append(
            tr("MLX braucht macOS >= {version}, ScreenCaptureKit-Audio >= 13 -> ohne MLX nur CPU", version=MACOS_MIN[0])
        )
    return CheckResult(status, tr("Plattform"), "; ".join(teile))


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
        return CheckResult("OK", tr("Plattform"), f"Windows {platform.release()} ({platform.machine()})")
    release = os.uname().release
    wsl = " (WSL2)" if "microsoft" in release.lower() else ""
    return CheckResult("OK", tr("Plattform"), f"Linux {release}{wsl} ({platform.machine()})")


def _check_python() -> CheckResult:
    v = sys.version_info
    ok = (v.major, v.minor) == (3, 12)
    return CheckResult(
        "OK" if ok else "WARN",
        "Python",
        f"{v.major}.{v.minor}.{v.micro}" + ("" if ok else tr(" (empfohlen: 3.12)")),
    )


def _check_ffmpeg() -> CheckResult:
    if shutil.which("ffmpeg"):
        return CheckResult("OK", "ffmpeg", tr("System-ffmpeg: {pfad}", pfad=shutil.which("ffmpeg")))
    try:
        path = ensure_ffmpeg_on_path()
    except Exception as exc:  # noqa: BLE001
        return CheckResult("FAIL", "ffmpeg", str(exc))
    return CheckResult("OK", "ffmpeg", tr("gebuendelt (imageio-ffmpeg) via Wrapper: {pfad}", pfad=path))


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
            tr(
                "{build} -> Device '{device}' erzwungen, aber CUDA nicht verfuegbar "
                "(CPU-Build/Treiber?) -> '--device auto|cpu' oder 'uv sync --extra cu124'",
                build=build,
                device=raw_device,
            ),
        )
    if raw == "mps" and not mps_ok:
        return CheckResult(
            "FAIL",
            "PyTorch/Device",
            tr(
                "{build} -> Device 'mps' erzwungen, aber Metal (MPS) nicht verfuegbar "
                "(Intel-Mac/Rosetta/macOS < 13?) -> '--device auto|cpu'",
                build=build,
            ),
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
            tr(
                "{build} -> {label}{wo}; Alignment/Diarisierung auf MPS, faster-whisper auf CPU "
                "(ctranslate2 ohne Metal, compute_type={compute_type}) -> Whisper siehe 'ASR-Backend'",
                build=build,
                label=label,
                wo=wo,
                compute_type=compute_type,
            ),
        )

    if device.startswith("cuda"):
        label = f"auto={device}" if raw == "auto" else device
        gpu = f" ({gpu_name})" if gpu_name else ""
        return CheckResult(
            "OK", "PyTorch/Device", f"{build} -> {label}{gpu}, compute_type={compute_type}"
        )

    if raw == "auto":
        detail = tr("{build} -> auto=cpu, CPU-Fallback (langsam), compute_type={compute_type}", build=build, compute_type=compute_type)
    else:
        hint = tr(" — Hinweis: CUDA waere verfuegbar") if cuda_ok else ""
        detail = tr(
            "{build} -> cpu (explizit; langsam), compute_type={compute_type}", build=build, compute_type=compute_type
        ) + hint
    if darwin:
        if not mps_ok:
            detail += tr(" — Tipp: arm64-Python und macOS >= 13 fuer MPS/MLX")
    elif not cuda_ok and "+cpu" not in torch_version:
        # CUDA-/PyPI-Build ohne nutzbares CUDA: die schlanken CPU-Wheels sparen ~3 GB.
        detail += tr(" — Tipp: 'uv sync --extra cpu' installiert die schlanken CPU-Wheels")
    elif not cuda_ok and nvidia_karte:
        # Karte da, aber CPU-Wheels installiert. Das passiert schneller als man denkt:
        # 'uv run' synchronisiert vorher ohne die gewaehlten Extras und ersetzt die
        # CUDA-Wheels stillschweigend wieder durch die von PyPI.
        detail += tr(
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
            tr("Import fehlgeschlagen: {fehler} -> 'uv sync --extra cpu' oder '--extra cu124'", fehler=exc),
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
        return CheckResult("FAIL", "WhisperX", tr("Import fehlgeschlagen: {fehler}", fehler=exc))
    return CheckResult("OK", "WhisperX", tr("verfuegbar; Modell konfiguriert: {modell}", modell=settings.whisper_model))


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
                detail += tr("; Live-Modell: {modell}", modell=ziel)
            else:
                detail += tr(" (MLX waere schneller: AUDIOSCRIBE_ASR_BACKEND=auto)")
            return CheckResult("OK", "ASR-Backend", detail)
        if raw == "mlx":
            return CheckResult(
                "FAIL",
                "ASR-Backend",
                tr("mlx erzwungen, aber mlx-whisper fehlt -> 'uv sync --extra cpu --extra mac --extra live'"),
            )
        return CheckResult(
            "WARN",
            "ASR-Backend",
            tr(
                "mlx-whisper fehlt -> 'uv sync --extra cpu --extra mac --extra live' "
                "(sonst faster-whisper auf der CPU: large-v3-turbo nicht live-tauglich)"
            ),
        )
    if raw == "mlx":
        return CheckResult("WARN", "ASR-Backend", tr("mlx nur auf Apple Silicon -> faster-whisper oder 'auto'"))
    return CheckResult("OK", "ASR-Backend", tr("faster-whisper (ctranslate2); MLX nur auf Apple Silicon"))


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
        return CheckResult(
            "WARN", tr("Diarisierung"), tr("deaktiviert (--no-diarize / AUDIOSCRIBE_DIARIZATION=0)")
        )
    try:
        import pyannote.audio  # noqa: F401
    except ImportError as exc:
        return CheckResult("FAIL", "pyannote.audio", tr("Import fehlgeschlagen: {fehler}", fehler=exc))
    # Zuerst der Token selbst: ein abgelehnter Token laesst JEDES gesperrte Repo als
    # "Bedingungen nicht akzeptiert" erscheinen - die Meldung schickte den Nutzer sonst
    # zum falschen Knopf.
    from audioscribe.hf import token_status

    status, detail = token_status(settings.hf_token)
    if status == "FEHLT":
        return CheckResult("FAIL", tr("Diarisierung"), tr("{detail} -> 'run' bricht ab", detail=detail))
    if status == "UNGUELTIG":
        return CheckResult("FAIL", "HF_TOKEN", tr("{detail} -> 'run' bricht ab", detail=detail))
    if status == "UNPRUEFBAR":
        return CheckResult("WARN", tr("Diarisierung"), tr("{detail}; HF_TOKEN gesetzt", detail=detail))

    # Ein gueltiger Token heisst NICHT, dass die Modell-Bedingungen akzeptiert sind.
    # auth_check fragt das ohne Download ab.
    try:
        from huggingface_hub import auth_check
        from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
    except Exception:  # noqa: BLE001
        return CheckResult(
            "OK",
            tr("Diarisierung"),
            tr("HF_TOKEN gesetzt (Zugriff nicht pruefbar); {modell}", modell=settings.diarization_model),
        )
    for repo in (settings.diarization_model, "pyannote/segmentation-3.0"):
        try:
            auth_check(repo, token=settings.hf_token)
        except (GatedRepoError, RepositoryNotFoundError):
            return CheckResult(
                "FAIL",
                tr("Diarisierung"),
                tr(
                    "Bedingungen NICHT akzeptiert: https://hf.co/{repo} (eingeloggt 'Agree' klicken) -> 'run' bricht ab",
                    repo=repo,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - Netzwerk o.ae.
            return CheckResult(
                "WARN",
                tr("Diarisierung"),
                tr("Zugriff nicht pruefbar ({fehler}); HF_TOKEN gesetzt", fehler=type(exc).__name__),
            )
    return CheckResult(
        "OK", tr("Diarisierung"), tr("Token + Bedingungen ok (speaker-diarization-3.1, segmentation-3.0)")
    )


def _check_dirs() -> CheckResult:
    try:
        settings.ensure_dirs()
    except OSError as exc:
        return CheckResult("FAIL", tr("Verzeichnisse"), tr("nicht anlegbar: {fehler}", fehler=exc))
    return CheckResult("OK", tr("Verzeichnisse"), tr("input/output/work unter {pfad}", pfad=settings.project_root))


def _check_agent() -> CheckResult:
    """KI-Analyse (optional, daher hoechstens WARN): SDK, Claude Code, Skills, Abrechnung."""
    from audioscribe import variante

    if variante.aktiv():
        # Nichts importieren, nichts suchen: die Analyse gibt es in dieser Variante nicht.
        return CheckResult("OK", tr("KI-Analyse"), tr("deaktiviert (Variante cloud-compliant)"))
    try:
        import claude_agent_sdk
    except ImportError:
        return CheckResult(
            "WARN", tr("KI-Analyse"), tr("Claude Agent SDK fehlt (optional) -> 'uv sync --extra agent'")
        )
    from audioscribe.agent.skills import discover_skills

    # Das SDK bringt eine eigene Claude-Code-CLI mit; sonst wird die installierte benutzt.
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
    has_cli = any(bundled.glob("claude*")) or bool(shutil.which("claude"))
    skills = discover_skills(settings.agent_skills_dir)
    known = {s.name for s in skills}
    fehlend = [n for n in settings.agent_skills if n not in known]

    teile = [
        tr(
            "SDK {version}, Modell {modell}",
            version=getattr(claude_agent_sdk, "__version__", "?"),
            modell=settings.agent_model,
        )
    ]
    teile.append(tr("{anzahl} Skill(s) in {ordner}", anzahl=len(skills), ordner=settings.agent_skills_dir))
    status: Status = "OK"
    if not has_cli:
        status = "WARN"
        teile.append(tr("Claude Code nicht gefunden"))
    if fehlend:
        status = "WARN"
        teile.append(tr("Vorauswahl fehlt: {namen}", namen=", ".join(fehlend)))
    from audioscribe.agent.prozessbild import find_browser

    browser = find_browser()
    if browser is None:
        status = "WARN"
        teile.append(
            tr(
                "Prozessbild: kein Edge/Chrome gefunden -> Chrome oder Edge installieren "
                "(einzige Komponente ausserhalb von pip; nur fuers Prozessbild) oder AUDIOSCRIBE_BROWSER setzen"
            )
        )
    else:
        teile.append(tr("Prozessbild via {browser}", browser=browser.name))
    if os.environ.get("ANTHROPIC_API_KEY"):
        status = "WARN"
        teile.append(tr("ANTHROPIC_API_KEY gesetzt -> Abrechnung ueber die API statt ueber das Abo"))
    else:
        teile.append(tr("Abrechnung ueber das Claude-Abo (Login per 'claude')"))
    return CheckResult(status, tr("KI-Analyse"), "; ".join(teile))


def _check_ollama() -> CheckResult:
    """Lokale KI ueber Ollama (optional): Dienst erreichbar, Version, konfigurierte Modelle.
    Nicht eingerichtet ist OK, solange der Dienst nicht als KI-Dienst eingestellt ist."""
    from audioscribe import variante
    from audioscribe.souffleur.ki import BACKEND_OLLAMA, modell_fuer
    from audioscribe.souffleur.ki_ollama import ANALYSE_MIN_CTX, ollama_status

    status = ollama_status(settings.ollama_url)
    eingestellt = settings.souffleur_backend == BACKEND_OLLAMA or variante.aktiv()
    if not status.erreichbar:
        detail = tr(
            "nicht erreichbar unter {url} ({fehler}) -> 'brew install ollama' bzw. ollama.com, dann 'ollama serve'",
            url=settings.ollama_url,
            fehler=status.fehler,
        )
        if eingestellt:
            return CheckResult("WARN", tr("KI lokal"), tr("als KI-Dienst eingestellt, aber {detail}", detail=detail))
        return CheckResult("OK", tr("KI lokal"), tr("nicht eingerichtet (optional); {detail}", detail=detail))
    st: Status = "OK"
    teile = [
        tr("Ollama {version} unter {url}", version=status.version or "?", url=settings.ollama_url),
        tr("{anzahl} Modell(e)", anzahl=len(status.modelle)),
    ]
    zwecke = [("Souffleur", modell_fuer(BACKEND_OLLAMA, settings.souffleur_model))]
    if not variante.aktiv():
        zwecke.append((tr("Analyse"), modell_fuer(BACKEND_OLLAMA, settings.agent_model)))
    for zweck, modell in zwecke:
        if status.hat_modell(modell):
            teile.append(f"{zweck}: {modell}")
        else:
            st = "WARN"
            teile.append(tr("{zweck}: {modell} fehlt -> 'ollama pull {modell}'", zweck=zweck, modell=modell))
    if not variante.aktiv():
        teile.append(
            tr(
                "KI-Analyse lokal ist experimentell und braucht OLLAMA_CONTEXT_LENGTH>={ctx}",
                ctx=ANALYSE_MIN_CTX,
            )
        )
    return CheckResult(st, tr("KI lokal"), "; ".join(teile))


def _live_inventory(prefix: list[str], status: Status = "OK") -> CheckResult:
    from audioscribe.live.kommando import inventory

    inv = inventory()
    teile = [
        *prefix,
        tr("{anzahl} Mikrofon(e)", anzahl=len(inv["mics"])),
        tr("{anzahl} Loopback-Geraet(e)", anzahl=len(inv["loopbacks"])),
        tr("{anzahl} Monitor(e)", anzahl=len(inv["monitors"])),
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
        "WARN", "Live", tr("nur unter nativem Windows (WASAPI) und macOS (ScreenCaptureKit) verfuegbar")
    )


def _bekannte_projekte(saved: dict, limit: int = 5) -> list[tuple[str, Path | None]]:
    """Zuletzt geoeffnete Projekte, deren Projektdatei noch erreichbar ist (Name, Wiki-Ordner
    oder None ohne Wiki)."""
    from audioscribe.projekt import modell

    out: list[tuple[str, Path | None]] = []
    for eintrag in saved.get("zuletzt_projekte") or []:
        try:
            projekt = modell.lade(eintrag["pfad"])
        except (modell.ProjektFehler, KeyError, TypeError):
            continue
        out.append((projekt.name, projekt.wiki_dir))
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
        zustaende = [(name, pruefe_wiki(wiki) if wiki is not None else None) for name, wiki in projekte]
        teile = [tr("Wiki je Projekt: {liste}", liste=", ".join(
            tr("{name} (ohne Wiki)", name=name) if w is None
            else tr("{name} ({seiten} Seiten)", name=name, seiten=w.seiten) if w.zustand == ZUSTAND_OK
            else tr("{name} (nicht erreichbar)", name=name)
            for name, w in zustaende
        ))]
        status = "OK" if all(w is None or w.zustand == ZUSTAND_OK for _, w in zustaende) else "WARN"
    else:
        wiki = pruefe_wiki(konfig.wiki_dir)
        teile = [tr("Wiki: {meldung}", meldung=wiki.meldung)]
        status = "OK" if wiki.zustand == ZUSTAND_OK else "WARN"
    if konfig.backend == BACKEND_CLAUDE and not sdk_verfuegbar():
        teile.append(tr("KI: Agent SDK fehlt -> 'uv sync --extra agent'"))
        status = "WARN"
    else:
        teile.append(tr("KI: {backend}, Modell {modell}", backend=konfig.backend, modell=konfig.modell))
    teile.append(tr("Einstellungen: {pfad}", pfad=state.state_path()))
    return CheckResult(status, "Souffleur", " | ".join(teile))


def _check_variante() -> CheckResult:
    """Welche Programmvariante läuft (src/audioscribe/variante.py)?"""
    from audioscribe import variante

    if variante.aktiv():
        return CheckResult("OK", tr("Variante"), tr("cloud-compliant - nur lokale KI (Ollama), ohne KI-Analyse"))
    return CheckResult("OK", tr("Variante"), tr("standard"))


CHECKS = (
    _check_platform,
    _check_variante,
    _check_python,
    _check_ffmpeg,
    _check_torch_device,
    _check_whisperx,
    _check_asr_backend,
    _check_diarization,
    _check_dirs,
    _check_agent,
    _check_ollama,
    _check_live,
    _check_souffleur,
)

_ICON = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}


def _safe(check) -> CheckResult:
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - ein Check darf die anderen nicht mitreissen
        name = check.__name__.removeprefix("_check_")
        return CheckResult(
            "FAIL", name, tr("Pruefung abgebrochen: {typ}: {fehler}", typ=type(exc).__name__, fehler=exc)
        )


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
