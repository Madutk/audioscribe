"""Lokaler Review-Webserver (FR-13/14/17): Video + synchrones Transkript, Frame-Markierung.

Optionale Komponente (Extra-Gruppe ``review``): benoetigt ``fastapi`` + ``uvicorn``. Bindet
ausschliesslich an ``localhost`` (NFR-8); kein Upload – Frames werden lokal per ffmpeg aus
dem Originalvideo extrahiert. fastapi/uvicorn werden erst INNERHALB der Funktionen
importiert, damit der Kern-CLI ohne diese Pakete lauffaehig bleibt.
"""

# Bewusst OHNE 'from __future__ import annotations': FastAPI loest String-Annotationen
# nur gegen die Modul-Globals auf. MarkIn/DeleteIn werden aber erst INNERHALB von
# create_app() definiert (damit pydantic nicht beim Import gebraucht wird) - als String
# waeren sie unauffindbar und der Request-Body landete faelschlich als Query-Parameter
# (POST /api/mark antwortete dann mit 422).

import json
import webbrowser
from datetime import datetime
from pathlib import Path

from audioscribe.review.frames import extract_frame, frame_filename
from audioscribe.review.marks import Mark, load_marks, save_marks

_STATIC_DIR = Path(__file__).parent / "static"


def _load_transcript(out_dir: Path) -> dict:
    tj = out_dir / "transcript.json"
    if not tj.exists():
        raise FileNotFoundError(
            f"transcript.json nicht gefunden in {out_dir}. "
            "Zuerst 'audioscribe run <video>' ausfuehren."
        )
    return json.loads(tj.read_text(encoding="utf-8"))


def _unique_frame_path(frames_dir: Path, t: float) -> tuple[Path, str]:
    """(absoluter PNG-Pfad, relativer 'frames/...') – ueberschreibt kein bestehendes Bild."""
    name = frame_filename(t)
    stem, suffix = name[:-4], name[-4:]
    candidate = frames_dir / name
    i = 2
    while candidate.exists():
        candidate = frames_dir / f"{stem}-{i}{suffix}"
        i += 1
    return candidate, f"frames/{candidate.name}"


def create_app(out_dir: str | Path):
    """Baut die FastAPI-App fuer einen Ausgabeordner (output/<name>)."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    out_dir = Path(out_dir).resolve()
    data = _load_transcript(out_dir)
    video_path = Path(data["source_path"])
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="AudioScribe Review")

    class MarkIn(BaseModel):
        t: float
        note: str | None = None

    class DeleteIn(BaseModel):
        png: str

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # Gleiches Design wie die Stapel-Oberflaeche (dort umschaltbar, hier nur gelesen).
        from audioscribe.ui.server import inject_theme

        return inject_theme((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/transcript")
    def api_transcript():
        return JSONResponse(data)

    @app.get("/api/marks")
    def api_marks():
        return JSONResponse([m.__dict__ for m in load_marks(out_dir)])

    @app.get("/video")
    def video():
        # FileResponse von Starlette beantwortet Range-Anfragen (206) -> Scrubbing moeglich.
        if not video_path.exists():
            raise HTTPException(404, f"Originalvideo nicht gefunden: {video_path}")
        return FileResponse(video_path)

    @app.post("/api/mark")
    def add_mark(body: MarkIn):
        if not video_path.exists():
            raise HTTPException(404, f"Originalvideo nicht gefunden: {video_path}")
        t = max(0.0, body.t)
        abs_png, rel_png = _unique_frame_path(frames_dir, t)
        try:
            extract_frame(video_path, t, abs_png)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Frame-Extraktion fehlgeschlagen: {exc}") from exc
        mark = Mark(
            t=t,
            png=rel_png,
            note=(body.note or None),
            created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        marks = load_marks(out_dir)
        marks.append(mark)
        save_marks(out_dir, marks)
        return JSONResponse(mark.__dict__)

    @app.delete("/api/mark")
    def delete_mark(body: DeleteIn):
        marks = load_marks(out_dir)
        kept = [m for m in marks if m.png != body.png]
        save_marks(out_dir, kept)
        png = (out_dir / body.png).resolve()
        # Pfad-Traversal absichern: nur Dateien innerhalb von frames/ loeschen.
        if frames_dir in png.parents and png.exists():
            try:
                png.unlink()
            except OSError:
                pass
        return JSONResponse({"ok": True, "count": len(kept)})

    app.mount("/frames", StaticFiles(directory=str(frames_dir)), name="frames")
    return app


def serve(
    out_dir: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Startet den lokalen Review-Server (blockierend bis Strg+C)."""
    import uvicorn

    app = create_app(out_dir)
    url = f"http://{host}:{port}/"
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    print(f"AudioScribe Review laeuft auf {url}  (Strg+C zum Beenden)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
