"""Lokaler Webserver der Stapel-Oberflaeche: Ordner waehlen, alle Medien transkribieren.

Optionale Komponente (Extra-Gruppe ``review``): benoetigt ``fastapi`` + ``uvicorn``.
Bindet ausschliesslich an ``localhost`` (NFR-8); kein Upload, keine Auslieferung von
Dateiinhalten. fastapi/uvicorn werden erst INNERHALB der Funktionen importiert, damit
der Kern-CLI ohne diese Pakete lauffaehig bleibt.

Der Fortschritt wird per Polling geholt (``GET /api/status?offset=N`` liefert Status
UND neue Log-Zeilen in einer Antwort). Das genuegt fuer minutenlange Laeufe, kommt
ohne zweiten Kanal aus und uebersteht ein Neuladen der Seite.
"""

# Bewusst OHNE 'from __future__ import annotations': FastAPI loest String-Annotationen
# nur gegen die Modul-Globals auf. Die Request-Modelle werden hier aber erst INNERHALB
# von create_app() definiert (damit pydantic nicht beim Import gebraucht wird) - als
# String waeren sie unauffindbar und der Body landete faelschlich als Query-Parameter.

import functools
import json
import time
import webbrowser
from pathlib import Path

from audioscribe.config import settings
from audioscribe.pipeline.media import probe_duration
from audioscribe.ui import browse, jobs, state
from audioscribe.ui.runner import BatchRunner

_STATIC_DIR = Path(__file__).parent / "static"

# Lebensdauer des CUDA-Probe-Ergebnisses. Kurz genug, dass ein Wechsel der Installation
# von selbst sichtbar wird; lang genug, dass Seitenaufrufe keinen Subprozess kosten.
_CUDA_TTL_S = 120.0
_cuda_cache: tuple[float, bool | None] | None = None


def _cuda() -> bool | None:
    """CUDA-Probe (Wegwerf-Subprozess), kurz gecacht.

    Die Probe startet Python samt torch-Import und kostet Sekunden - pro Seitenaufruf
    waere das zu teuer. Ein Cache ohne Ablauf haelt aber auch eine laengst geaenderte
    Installation fest: nach 'uv sync --extra cu124' stuende in der Oberflaeche weiter
    'cuda (nicht verfuegbar)', bis jemand den Server neu startet - und niemand vermutet
    die Ursache im Server.
    """
    global _cuda_cache
    jetzt = time.monotonic()
    if _cuda_cache is not None and jetzt - _cuda_cache[0] < _CUDA_TTL_S:
        return _cuda_cache[1]
    wert = jobs.probe_cuda()
    _cuda_cache = (jetzt, wert)
    return wert


def _size_mb(path: Path) -> float:
    """Dateigroesse in MB; 0.0, wenn ``stat`` nicht erlaubt ist (Windows-Systemdateien)."""
    try:
        return round(path.stat().st_size / (1024 * 1024), 1)
    except OSError:
        return 0.0


@functools.lru_cache(maxsize=512)
def _duration_cached(path: str, mtime_ns: int, size: int) -> float | None:
    """Gemessene Laufzeit; der Schluessel invalidiert sich bei jeder Dateiaenderung selbst."""
    return probe_duration(Path(path))


def _media_seconds(media: Path, out_dir: Path) -> float | None:
    """Laufzeit einer Datei - moeglichst ohne ffmpeg-Aufruf.

    Fuer bereits transkribierte Dateien steht sie exakt in ``transcript.json`` (dort
    schreibt ``export.transcript_to_dict`` sie hin); erst sonst wird gemessen.
    Achtung Namensfalle: ``transkript.md`` mit k, ``transcript.json`` mit c.
    """
    meta = Path(out_dir) / media.stem / "transcript.json"
    try:
        value = json.loads(meta.read_text(encoding="utf-8")).get("duration_s")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        stat = media.stat()
    except OSError:
        return None
    return _duration_cached(str(media), stat.st_mtime_ns, stat.st_size)


def _remembered_dir(raw: object, fallback: Path) -> str:
    """Gemerkten Ordner uebernehmen - aber nur, wenn er auf diesem Rechner existiert.

    Der Zustand ueberdauert einen Wechsel des Betriebssystems (WSL <-> Windows) und den
    Umzug auf einen anderen Rechner; ein Pfad von dort waere sonst eine Sackgasse, die
    der Nutzer erst von Hand ueberschreiben muesste. Der Ausgangsordner darf fehlen,
    solange sein uebergeordneter Ordner steht - angelegt wird er erst beim Start.
    """
    if not isinstance(raw, str) or not raw.strip():
        return str(fallback)
    path = browse.normalize_path(raw, default=fallback)
    try:
        plausibel = path.is_dir() or path.parent.is_dir()
    except OSError:
        plausibel = False
    return str(path if plausibel else fallback)


def _folder_info(raw: str, *, default: Path) -> dict:
    """Verzeichnis-Inhalt fuer den Ordner-Dialog (Unterordner + Medien-Uebersicht)."""
    folder = browse.normalize_path(raw, default=default)
    dirs = browse.list_dirs(folder)
    try:
        media = jobs.scan_media(folder)
    except OSError:
        # Die Medien-Zahl ist nur ein Hinweis - sie darf das Blaettern nie blockieren.
        media = []
    return {
        "path": str(folder),
        "parent": None if folder.parent == folder else str(folder.parent),
        "crumbs": [{"name": n, "path": p} for n, p in browse.breadcrumbs(folder)],
        "dirs": [{"name": d.name, "path": str(d)} for d in dirs],
        "media_count": len(media),
    }


def create_app():
    """Baut die FastAPI-App der Stapel-Oberflaeche (haelt genau einen BatchRunner)."""
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel

    app = FastAPI(title="AudioScribe UI")
    runner = BatchRunner()

    class StateIn(BaseModel):
        input_dir: str | None = None
        output_dir: str | None = None
        model: str | None = None
        language: str | None = None
        device: str | None = None
        diarize: bool | None = None

    class StartIn(BaseModel):
        input_dir: str
        output_dir: str
        # Nur Dateinamen, keine Pfade - der Server schneidet sie gegen scan_media().
        files: list[str] = []
        model: str = "large-v3"
        language: str = "de"
        device: str = "auto"
        diarize: bool = True

    @app.middleware("http")
    async def _same_origin_only(request: Request, call_next):
        """Schuetzt vor Zugriffen fremder Seiten im Browser (Loopback-CSRF).

        Jede Webseite im Windows-Browser kann ``127.0.0.1`` erreichen; ohne diese
        Pruefung waere ``/api/browse`` ein Dateisystem-Orakel und ``/api/start``
        fremdausloesbar. Anfragen ohne ``Origin`` (die Seite selbst, curl) passieren.
        """
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if origin not in (f"http://{host}", f"https://{host}"):
                return JSONResponse({"detail": "Fremde Herkunft abgelehnt."}, status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/defaults")
    def api_defaults():
        # Zuletzt benutzte Werte gewinnen ueber die Config-Defaults.
        chosen = state.merge_defaults(
            {
                "input_dir": str(settings.input_dir),
                "output_dir": str(settings.output_dir),
                "model": settings.whisper_model,
                "language": settings.whisper_language,
                "device": settings.device,
                "diarize": settings.enable_diarization,
            },
            state.load_state(),
        )
        chosen["input_dir"] = _remembered_dir(chosen["input_dir"], settings.input_dir)
        chosen["output_dir"] = _remembered_dir(chosen["output_dir"], settings.output_dir)
        return JSONResponse(
            {
                **chosen,
                "models": list(jobs.WHISPER_MODELS),
                "languages": list(jobs.LANGUAGES),
                "devices": list(jobs.DEVICES),
                "cuda": _cuda(),
                # Steuert nur den Hinweistext der Oberflaeche: unter Windows werden
                # Pfade nach C:\... umgesetzt, unter WSL nach /mnt/c/....
                "platform": "windows" if browse.IS_WINDOWS else "posix",
                "quick_links": [
                    {"label": label, "path": path}
                    for label, path in browse.quick_links(
                        project_root=settings.project_root,
                        input_dir=settings.input_dir,
                        output_dir=settings.output_dir,
                    )
                ],
            }
        )

    @app.get("/api/browse")
    def api_browse(path: str = Query("")):
        try:
            return JSONResponse(_folder_info(path, default=settings.input_dir))
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, f"Keine Leseberechtigung fuer: {path}") from exc

    @app.get("/api/scan")
    def api_scan(input_dir: str = Query(""), output_dir: str = Query("")):
        """Vorschau: welche Medien liegen im Eingangsordner, welche sind schon fertig?"""
        folder = browse.normalize_path(input_dir, default=settings.input_dir)
        out_dir = browse.normalize_path(output_dir, default=settings.output_dir)
        try:
            media = jobs.scan_media(folder)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, f"Keine Leseberechtigung fuer: {folder}") from exc

        files = [
            {
                "name": m.name,
                "mb": _size_mb(m),
                "seconds": _media_seconds(m, out_dir),
                "done": jobs.is_done(m, out_dir),
            }
            for m in media
        ]
        return JSONResponse(
            {
                "input_dir": str(folder),
                "output_dir": str(out_dir),
                "files": files,
                "count": len(files),
                "open": sum(1 for f in files if not f["done"]),
            }
        )

    @app.post("/api/state")
    def api_state(body: StateIn):
        """Zuletzt benutzte Ordner/Optionen merken (einzige Speicherstelle)."""
        state.save_state({k: v for k, v in body.model_dump().items() if v is not None})
        return JSONResponse({"ok": True})

    @app.post("/api/start")
    def api_start(body: StartIn):
        if body.device not in jobs.DEVICES:
            raise HTTPException(400, f"Unbekanntes Geraet: {body.device}")
        if not body.model.strip():
            raise HTTPException(400, "Kein Modell gewaehlt.")

        folder = browse.normalize_path(body.input_dir, default=settings.input_dir)
        out_dir = browse.normalize_path(body.output_dir, default=settings.output_dir)
        try:
            media = jobs.select_files(folder, body.files)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if not media:
            raise HTTPException(400, f"Keine der gewaehlten Dateien liegt in {folder}.")

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"Ausgangsordner nicht anlegbar: {exc}") from exc

        opts = jobs.JobOptions(
            input_dir=folder,
            output_dir=out_dir,
            model=body.model.strip(),
            language=body.language.strip() or "de",
            device=body.device,
            diarize=body.diarize,
        )
        state.save_state(
            {
                "input_dir": str(folder),
                "output_dir": str(out_dir),
                "model": opts.model,
                "language": opts.language,
                "device": opts.device,
                "diarize": opts.diarize,
            }
        )
        # Laufzeiten VOR dem Start messen - im Runner darf nie gemessen werden, das
        # wuerde den Lesethread hinter dem Lock blockieren.
        durations = {m.name: _media_seconds(m, out_dir) for m in media}
        try:
            runner.start(opts, media, durations=durations)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True, "count": len(media)})

    @app.get("/api/status")
    def api_status(offset: int = Query(0, ge=0)):
        return JSONResponse(runner.snapshot(offset))

    @app.post("/api/cancel")
    def api_cancel():
        runner.cancel()
        return JSONResponse({"ok": True})

    return app


def serve(*, host: str = "127.0.0.1", port: int = 8766, open_browser: bool = True) -> None:
    """Startet die Stapel-Oberflaeche (blockierend bis Strg+C)."""
    import uvicorn

    app = create_app()
    url = f"http://{host}:{port}/"
    # Adresse ZUERST ausgeben: unter WSL oeffnet webbrowser.open haeufig nichts,
    # dann muss der Nutzer die URL selbst in den Windows-Browser kopieren.
    print(f"AudioScribe UI laeuft auf {url}  (Strg+C zum Beenden)")
    print("Unter WSL: die Adresse notfalls von Hand im Windows-Browser oeffnen.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    uvicorn.run(app, host=host, port=port, log_level="warning")
