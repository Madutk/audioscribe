"""Lokaler Webserver der Stapel-Oberflaeche: Ordner waehlen, alle Medien transkribieren.

Optionale Komponente (Extra-Gruppe ``review``): benoetigt ``fastapi`` + ``uvicorn``.
Bindet ausschliesslich an ``localhost`` (NFR-8); kein Upload. Dateiinhalte liefert nur
der Live-Reiter aus - die Standbilder der eigenen Sitzung. fastapi/uvicorn werden erst INNERHALB der Funktionen importiert, damit
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
from audioscribe.ui.runner import AnalyseRunner, BatchRunner, LiveRunner

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


def inject_theme(html: str) -> str:
    """Gemerktes Design (system/light/dark) in das <html>-Tag schreiben.

    Das Attribut steht damit schon vor dem ersten Zeichnen - kein Aufblitzen des
    falschen Designs. Der Wert kommt gefiltert aus ``state._clean`` und ist einer von
    ``state.THEMES``; er braucht kein Escaping.
    """
    theme = state.load_state().get("theme", "system")
    return html.replace('<html lang="de">', f'<html lang="de" data-theme="{theme}">', 1)


def create_app():
    """Baut die FastAPI-App der Stapel-Oberflaeche (haelt genau einen BatchRunner)."""
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from pydantic import BaseModel

    app = FastAPI(title="AudioScribe UI")
    runner = BatchRunner()
    analyse = AnalyseRunner()
    live = LiveRunner()

    class LiveStartIn(BaseModel):
        output_dir: str
        monitor: int = 1
        # Geraeteindex | "default" | "none"; die Namen dienen nur dem Merken der Auswahl.
        mic: str = "default"
        loopback: str = "default"
        mic_name: str = ""
        loopback_name: str = ""
        model: str = "auto"
        language: str = "de"
        device: str = "auto"
        sensitivity: str = "mittel"
        format: str = "jpg-1600"
        partials: bool = True
        speakers: bool = True
        refine: bool = True
        refine_model: str = "large-v3"

    class StateIn(BaseModel):
        input_dir: str | None = None
        output_dir: str | None = None
        model: str | None = None
        language: str | None = None
        device: str | None = None
        diarize: bool | None = None
        frames: bool | None = None
        frame_sensitivity: str | None = None
        frame_format: str | None = None
        theme: str | None = None

    class StartIn(BaseModel):
        input_dir: str
        output_dir: str
        # Nur Dateinamen, keine Pfade - der Server schneidet sie gegen scan_media().
        files: list[str] = []
        model: str = "large-v3"
        language: str = "de"
        device: str = "auto"
        diarize: bool = True
        frames: bool = False
        frame_sensitivity: str = "mittel"
        frame_format: str = "jpg-1600"

    class AgentStartIn(BaseModel):
        source: str
        name: str
        output_dir: str
        context_text: str = ""
        # Ein Pfad je Eintrag; Windows- und WSL-Schreibweise werden umgesetzt.
        context_files: list[str] = []
        skills: list[str] = []
        model: str = "claude-opus-5"
        bash: bool = True

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
        return inject_theme((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    # Nur diese beiden Dateien werden ausgeliefert - kein Verzeichnis-Mount, keine
    # Pfadspiele. no-cache: der Browser fragt per ETag nach, nach einem Update ist das
    # CSS sofort aktuell.
    _ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}

    @app.api_route("/static/{name}", methods=["GET", "HEAD"])
    def static_asset(name: str):
        media = _ASSETS.get(name)
        if media is None:
            raise HTTPException(404, "Unbekannte Datei.")
        return FileResponse(_STATIC_DIR / name, media_type=media, headers={"Cache-Control": "no-cache"})

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
                "frames": settings.enable_screens,
                "frame_sensitivity": settings.screen_sensitivity,
                "frame_format": settings.screen_format,
                "theme": "system",
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
                "sensitivities": list(jobs.SENSITIVITIES),
                "frame_formats": list(jobs.FRAME_FORMATS),
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
        if body.frames and body.frame_sensitivity not in jobs.SENSITIVITIES:
            raise HTTPException(400, f"Unbekannte Empfindlichkeit: {body.frame_sensitivity}")
        if body.frames and body.frame_format not in jobs.FRAME_FORMATS:
            raise HTTPException(400, f"Unbekanntes Bildformat: {body.frame_format}")

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
            frames=body.frames,
            frame_sensitivity=body.frame_sensitivity,
            frame_format=body.frame_format,
        )
        state.save_state(
            {
                "input_dir": str(folder),
                "output_dir": str(out_dir),
                "model": opts.model,
                "language": opts.language,
                "device": opts.device,
                "diarize": opts.diarize,
                "frames": opts.frames,
                "frame_sensitivity": opts.frame_sensitivity,
                "frame_format": opts.frame_format,
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

    # --- KI-Analyse (PRD §16) -------------------------------------------------

    @app.get("/api/agent/defaults")
    def api_agent_defaults():
        from audioscribe.agent.skills import discover_skills

        saved = state.load_state()
        skills = discover_skills(settings.agent_skills_dir)
        known = {s.name for s in skills}
        chosen = saved.get("agent_skills")
        if not isinstance(chosen, list):
            chosen = [n for n in settings.agent_skills if n in known]
        return JSONResponse(
            {
                "skills_dir": str(settings.agent_skills_dir),
                "skills": [
                    {"name": s.name, "description": s.description, "selected": s.name in chosen}
                    for s in skills
                ],
                "model": saved.get("agent_model") or settings.agent_model,
                "models": list(jobs.AGENT_MODELS),
                "output_dir": _remembered_dir(
                    saved.get("agent_output_dir"), settings.agent_output_dir
                ),
                "bash": saved.get("agent_bash", True),
            }
        )

    @app.get("/api/agent/sources")
    def api_agent_sources(output_dir: str = Query("")):
        """Fertige Transkriptionen im Ausgangsordner der Transkription."""
        folder = browse.normalize_path(output_dir, default=settings.output_dir)
        try:
            results = jobs.scan_results(folder)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, f"Keine Leseberechtigung fuer: {folder}") from exc
        return JSONResponse({"output_dir": str(folder), "sources": results})

    @app.post("/api/agent/start")
    def api_agent_start(body: AgentStartIn):
        from audioscribe.agent.material import find_transcript
        from audioscribe.agent.skills import discover_skills

        name = body.name.strip()
        if not name:
            raise HTTPException(400, "Bitte einen Prozessnamen angeben.")
        model = body.model.strip()
        # Der Modellname wandert als eigenes argv-Element in den Subprozess; trotzdem
        # nur harmlose Zeichen zulassen, damit die CLI keine Option daraus liest.
        if not model or model.startswith("-") or not all(c.isalnum() or c in "-_.:[]" for c in model):
            raise HTTPException(400, f"Ungueltiger Modellname: {body.model}")

        source = browse.normalize_path(body.source, default=settings.output_dir)
        try:
            find_transcript(source)
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc)) from exc

        known = {s.name for s in discover_skills(settings.agent_skills_dir)}
        unknown = [s for s in body.skills if s not in known]
        if unknown:
            raise HTTPException(400, "Unbekannte Skills: " + ", ".join(unknown))

        context_files = []
        for raw in body.context_files:
            if not raw.strip():
                continue
            path = browse.normalize_path(raw.strip(), default=settings.project_root)
            if not path.is_file():
                raise HTTPException(400, f"Kontextdatei nicht gefunden: {raw}")
            context_files.append(path)

        out_dir = browse.normalize_path(body.output_dir, default=settings.agent_output_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"Ausgabeordner nicht anlegbar: {exc}") from exc

        opts = jobs.AnalyseOptions(
            source=source,
            name=name,
            output_dir=out_dir,
            context_text=body.context_text,
            context_files=tuple(context_files),
            skills=tuple(body.skills),
            skills_dir=settings.agent_skills_dir,
            model=model,
            bash=body.bash,
        )
        state.save_state(
            {
                "agent_output_dir": str(out_dir),
                "agent_model": model,
                "agent_skills": list(body.skills),
                "agent_bash": body.bash,
            }
        )
        try:
            workspace = analyse.start(opts)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True, "workspace": str(workspace)})

    @app.get("/api/agent/status")
    def api_agent_status(offset: int = Query(0, ge=0)):
        return JSONResponse(analyse.snapshot(offset))

    @app.post("/api/agent/cancel")
    def api_agent_cancel():
        analyse.cancel()
        return JSONResponse({"ok": True})

    # --- Live-Transkription (PRD §17) ------------------------------------------

    @app.get("/api/live/defaults")
    def api_live_defaults():
        from audioscribe.live.kommando import inventory

        saved = state.load_state()
        return JSONResponse(
            {
                **inventory(),
                "models": list(jobs.LIVE_WHISPER_MODELS),
                "refine_models": list(jobs.WHISPER_MODELS),
                "monitor": saved.get("live_monitor", "1"),
                "mic": saved.get("live_mic", "default"),
                "loopback": saved.get("live_loopback", "default"),
                "model": saved.get("live_model", "auto"),
                "language": saved.get("live_language", settings.whisper_language),
                "device": saved.get("live_device", settings.device),
                "sensitivity": saved.get("live_sensitivity", settings.screen_sensitivity),
                "format": saved.get("live_format", settings.screen_format),
                "partials": saved.get("live_partials", True),
                "speakers": saved.get("live_speakers", True),
                "refine": saved.get("live_refine", True),
                "refine_model": saved.get("live_refine_model", settings.whisper_model),
            }
        )

    @app.get("/api/live/monitor/{index}")
    def api_live_monitor(index: int):
        """Vorschaubild eines Monitors fuer die Monitorwahl."""
        from audioscribe.live.screen import preview_jpeg

        try:
            return Response(preview_jpeg(index), media_type="image/jpeg")
        except (ImportError, IndexError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/live/start")
    def api_live_start(body: LiveStartIn):
        if body.device not in jobs.DEVICES:
            raise HTTPException(400, f"Unbekanntes Geraet: {body.device}")
        if body.sensitivity not in jobs.SENSITIVITIES:
            raise HTTPException(400, f"Unbekannte Empfindlichkeit: {body.sensitivity}")
        if body.format not in jobs.FRAME_FORMATS:
            raise HTTPException(400, f"Unbekanntes Bildformat: {body.format}")
        # Alle Werte wandern als argv in den Subprozess - nur harmlose Zeichen zulassen.
        for wert in (body.model, body.refine_model, body.language, body.mic, body.loopback):
            if not wert or wert.startswith("-") or not all(c.isalnum() or c in "-_." for c in wert):
                raise HTTPException(400, f"Ungueltiger Wert: {wert}")
        if body.monitor < 0:
            raise HTTPException(400, "Ungueltiger Monitor.")
        if not body.monitor and body.mic == "none" and body.loopback == "none":
            raise HTTPException(400, "Weder Audio noch Monitor gewaehlt.")

        out_dir = browse.normalize_path(body.output_dir, default=settings.output_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"Ausgangsordner nicht anlegbar: {exc}") from exc

        opts = jobs.LiveJobOptions(
            output_dir=out_dir,
            monitor=body.monitor,
            mic=body.mic,
            loopback=body.loopback,
            model=body.model,
            language=body.language,
            device=body.device,
            frame_sensitivity=body.sensitivity,
            frame_format=body.format,
            partials=body.partials,
            speakers=body.speakers,
            refine=body.refine,
            refine_model=body.refine_model,
        )
        state.save_state(
            {
                "live_monitor": str(body.monitor),
                "live_mic": body.mic_name or body.mic,
                "live_loopback": body.loopback_name or body.loopback,
                "live_model": body.model,
                "live_language": body.language,
                "live_device": body.device,
                "live_sensitivity": body.sensitivity,
                "live_format": body.format,
                "live_partials": body.partials,
                "live_speakers": body.speakers,
                "live_refine": body.refine,
                "live_refine_model": body.refine_model,
            }
        )
        try:
            live.start(opts)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.get("/api/live/status")
    def api_live_status(offset: int = Query(0, ge=0), ev_offset: int = Query(0, ge=0)):
        return JSONResponse(live.snapshot(offset, ev_offset))

    @app.post("/api/live/stop")
    def api_live_stop():
        live.stop()
        return JSONResponse({"ok": True})

    @app.get("/api/live/frame/{name}")
    def api_live_frame(name: str):
        """Standbild der laufenden bzw. letzten Sitzung - nur aus deren ``frames/``."""
        session = live.session_dir()
        if session is None or Path(name).name != name:
            raise HTTPException(404, "Kein solches Standbild.")
        path = session / "frames" / name
        if not path.is_file():
            raise HTTPException(404, "Kein solches Standbild.")
        return FileResponse(path)

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
