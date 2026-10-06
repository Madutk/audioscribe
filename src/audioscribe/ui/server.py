"""Lokaler Webserver der Oberflaeche: Startseite, Projekte, Live-Sitzung, Aufnahme transkribieren.

Der Server haelt einen aktiven Kontext (``ui/kontext.py``, PRD §21): Startseite, ein geoeffnetes
Projekt, die projektlose Transkription einer Aufnahme oder die Demo. Ordner, KI-Modell und
Sprache kommen im Projekt aus dem Projekt bzw. den globalen Einstellungen.

Optionale Komponente (Extra-Gruppe ``review``): benoetigt ``fastapi`` + ``uvicorn``.
Bindet ausschliesslich an ``localhost`` (NFR-8); kein Upload. An Dateiinhalten liefert der
Server nur zweierlei aus: die Standbilder der eigenen Live-Sitzung und die Vorschau eines
fertigen Transkripts (``/api/transkript``: nur ``transkript(.annotiert).md``, im Projekt nur
aus dessen Sitzungsordner). fastapi/uvicorn werden erst INNERHALB der Funktionen importiert,
damit der Kern-CLI ohne diese Pakete lauffaehig bleibt.

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
from audioscribe.projekt import einstellungen, modell, wiki_ablage
from audioscribe.projekt.modell import ProjektFehler
from audioscribe.ui import browse, jobs, kontext as kontext_modul, state
from audioscribe.ui.runner import AnalyseRunner, BatchRunner, LiveRunner
from audioscribe.verbrauch import QUELLE_SOUFFLEUR, Zaehler

_STATIC_DIR = Path(__file__).parent / "static"
# Ausgeliefert werden nur diese Dateiarten aus static/ (samt Unterordnern js/, css/).
_STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
# Vorschau eines Transkripts in der Oberflaeche: nur diese beiden Dateien, gedeckelt.
_TRANSKRIPT_DATEIEN = ("transkript.annotiert.md", "transkript.md")
_TRANSKRIPT_MAX = 400_000

# Lebensdauer des Beschleuniger-Probe-Ergebnisses (CUDA/MPS/MLX). Kurz genug, dass ein
# Wechsel der Installation von selbst sichtbar wird; lang genug, dass Seitenaufrufe
# keinen Subprozess kosten.
_CUDA_TTL_S = 120.0
_cuda_cache: tuple[float, dict | None] | None = None


# Umgebungs-Check ('audioscribe doctor --json' als Subprozess): dauert Sekunden (torch-
# Import, Hugging-Face-Anfrage), darum laenger gecacht; der Reiter hat einen Knopf
# "Aktualisieren", der den Cache umgeht.
_ENV_TTL_S = 600.0
_env_cache: tuple[float, list[dict] | None] | None = None


def _environment(*, refresh: bool = False) -> tuple[list[dict] | None, float]:
    """Ergebnis des Umgebungs-Checks samt Zeitstempel (``time.time``), kurz gecacht."""
    global _env_cache
    jetzt = time.monotonic()
    if not refresh and _env_cache is not None and jetzt - _env_cache[0] < _ENV_TTL_S:
        return _env_cache[1], time.time() - (jetzt - _env_cache[0])
    checks = jobs.probe_environment()
    _env_cache = (time.monotonic(), checks)
    return checks, time.time()


def _accelerator() -> dict | None:
    """Beschleuniger-Probe (Wegwerf-Subprozess), kurz gecacht: ``{"cuda", "mps", "backend"}``.

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
    wert = jobs.probe_accelerator()
    _cuda_cache = (jetzt, wert)
    return wert


def _cuda() -> bool | None:
    acc = _accelerator()
    return None if acc is None else acc["cuda"]


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


def _souffleur_models() -> list[dict]:
    """KI-Modelle fuer den Souffleur mit neutralen Bezeichnungen (kein Produktname in der Oberflaeche)."""
    from audioscribe.souffleur.ki import SOUFFLEUR_MODELS

    labels = ("Standard (schnell)", "Sparsam (am schnellsten)", "Stark (langsamer)", "Maximal (am langsamsten)")
    return [{"id": m, "label": labels[i] if i < len(labels) else m} for i, m in enumerate(SOUFFLEUR_MODELS)]


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


def _folder_info(raw: str, *, default: Path, files: bool = False) -> dict:
    """Verzeichnis-Inhalt fuer den Ordner-Dialog (Unterordner + Medien-Uebersicht).

    Mit ``files`` kommen die Mediendateien des Ordners mit - fuer die Dateiauswahl von
    "Aufnahme transkribieren". Ein Dateipfad oeffnet seinen Ordner.
    """
    folder = browse.normalize_path(raw, default=default)
    try:
        if folder.is_file():
            folder = folder.parent
    except OSError:
        pass
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
        "files": [{"name": m.name, "path": str(m), "mb": _size_mb(m)} for m in media] if files else [],
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
    """Baut die FastAPI-App der Oberflaeche (je ein Stapel-, Analyse- und Live-Runner, ein Kontext)."""
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from pydantic import BaseModel

    app = FastAPI(title="AudioScribe UI")
    runner = BatchRunner()
    # KI-Verbrauch seit Programmstart: Souffleur bucht je Aufruf, die Analyse meldet ihren Stand.
    zaehler = Zaehler()
    analyse = AnalyseRunner(zaehler=zaehler)
    live = LiveRunner()
    kontext = kontext_modul.Kontext()

    # --- Kontext (PRD §21) ----------------------------------------------------------------

    def _projekt():
        return kontext.projekt

    def _ausgabe_dir(raw: str = "") -> Path:
        """Wohin Transkripte gehen: im Projekt der Sitzungsordner, sonst die Angabe des Clients."""
        p = _projekt()
        if p is not None:
            return p.sitzungen_dir
        return browse.normalize_path(raw, default=settings.output_dir)

    def _analysen_dir(raw: str = "") -> Path:
        p = _projekt()
        if p is not None:
            return p.analysen_dir
        return browse.normalize_path(raw, default=settings.agent_output_dir)

    def _eff() -> einstellungen.Effektiv:
        return einstellungen.effektiv(state.load_state(), _projekt())

    def _beschaeftigt() -> str | None:
        if live.laeuft():
            return "Es läuft noch eine Live-Sitzung."
        if analyse.laeuft():
            return "Es läuft noch eine KI-Analyse."
        if runner.laeuft():
            return "Es läuft noch eine Transkription."
        return None

    def _wechsle(modus: str, projekt=None) -> None:
        """Kontext wechseln - nie waehrend eines Laufs. Die Ansichten beginnen danach leer."""
        # Die Demo-Sitzung ist Wegwerfware: "Demo beenden" bricht sie ab, statt zu sperren.
        grund = None if kontext.modus == kontext_modul.MODUS_DEMO else _beschaeftigt()
        if grund:
            raise HTTPException(409, f"{grund} Bitte erst beenden.")
        try:
            live.reset()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        analyse.leeren()
        runner.leeren()
        kontext.setze(modus, projekt)

    def _kontext_antwort() -> dict:
        saved = state.load_state()
        p = _projekt()
        return {
            "modus": kontext.modus,
            "projekt": kontext_modul.projekt_dict(p, saved) if p is not None else None,
            "zuletzt": kontext_modul.zuletzt(saved),
            "demo_verfuegbar": kontext_modul.demo_verfuegbar(),
            "unterbrochen": kontext_modul.unterbrochene(saved, p),
            "laeuft": {"live": live.laeuft(), "analyse": analyse.laeuft(), "stapel": runner.laeuft()},
            # Vorbelegung des Assistenten aus einer Installation von vor den Projekten.
            "alt": {"wiki_dir": saved.get("wiki_dir", "") or settings.wiki_dir},
            "platform": browse.PLATFORM,
        }

    class KontextIn(BaseModel):
        modus: str

    class ProjektIn(BaseModel):
        name: str = ""
        wurzel: str = ""
        sitzungen_dir: str = ""
        assets_dir: str = ""
        neues_wiki: bool = False
        ki_dienst: str | None = None
        souffleur_model: str | None = None
        agent_model: str | None = None
        sprache: str | None = None
        wiki_speichern: str = modell.WIKI_FRAGEN
        wiki_bilder: bool = True
        wiki_markierungen: bool = False

    class PfadIn(BaseModel):
        pfad: str

    class FelderIn(BaseModel):
        felder: dict

    class EinstellungenIn(BaseModel):
        ki_dienst: str | None = None
        souffleur_model: str | None = None
        agent_model: str | None = None
        sprache: str | None = None

    class WikiSpeichernIn(BaseModel):
        sitzung: str
        titel: str = ""
        bilder: bool = True
        markierungen: bool = False  # Markierungen des Souffleurs (KI-erzeugt) nur auf Wunsch
        immer: bool = False

    class NachbereitungIn(BaseModel):
        workspace: str
        bilder: bool = True

    class SitzungIn(BaseModel):
        sitzung: str

    class LiveStartIn(BaseModel):
        output_dir: str = ""
        # Sitzungstitel (PRD §21): benennt die Sitzung und spaeter den Ordner im Wiki.
        titel: str = ""
        # Wiederaufnahme: Ordner einer unterbrochenen Sitzung, die fortgesetzt wird.
        resume: str = ""
        monitor: int = 1
        window: int = 0  # HWND; hat Vorrang vor monitor
        # Geraeteindex | "default" | "none"; die Namen dienen nur dem Merken der Auswahl.
        mic: str = "default"
        loopback: str = "default"
        mic_name: str = ""
        loopback_name: str = ""
        window_label: str = ""
        model: str = "auto"
        language: str = "de"
        device: str = "auto"
        sensitivity: str = "mittel"
        format: str = "jpg-1600"
        partials: bool = True
        speakers: bool = True
        refine: bool = True
        refine_model: str = "large-v3"
        # Testmodus (FR-64): Transkriptdatei oder Sitzungsordner; leer = echte Aufnahme.
        replay_transcript: str = ""
        replay_speed: float = 1.0

    class StateIn(BaseModel):
        input_dir: str | None = None
        output_dir: str | None = None
        agent_output_dir: str | None = None
        model: str | None = None
        language: str | None = None
        device: str | None = None
        diarize: bool | None = None
        frames: bool | None = None
        frame_sensitivity: str | None = None
        frame_format: str | None = None
        theme: str | None = None
        # Testmodus (FR-64): Transkript und Tempo schon bei der Auswahl merken, nicht erst beim Start
        replay_transcript: str | None = None
        replay_speed: str | None = None
        # Souffleur (PRD §20)
        wiki_dir: str | None = None
        souffleur_model: str | None = None
        souffleur_aktiv: bool | None = None
        souffleur_sensibel: bool | None = None

    class EssenzIn(BaseModel):
        minuten: int = 2

    class SouffleurToggleIn(BaseModel):
        aktiv: bool = True

    class PauseIn(BaseModel):
        pausiert: bool = True

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

    # Nur Stylesheets und Skripte aus static/ (samt js/, css/) - kein Verzeichnis-Mount, und
    # der aufgeloeste Pfad muss unter static/ bleiben. no-cache: der Browser fragt per ETag
    # nach, nach einem Update ist das CSS sofort aktuell.
    @app.api_route("/static/{name:path}", methods=["GET", "HEAD"])
    def static_asset(name: str):
        media = _STATIC_TYPES.get(Path(name).suffix.lower())
        datei = (_STATIC_DIR / name).resolve()
        if media is None or not datei.is_relative_to(_STATIC_DIR.resolve()) or not datei.is_file():
            raise HTTPException(404, "Unbekannte Datei.")
        return FileResponse(datei, media_type=media, headers={"Cache-Control": "no-cache"})

    # --- Kontext, Projekte, Einstellungen (PRD §21) ------------------------------------------

    @app.get("/api/kontext")
    def api_kontext():
        return JSONResponse(_kontext_antwort())

    @app.post("/api/kontext")
    def api_kontext_setzen(body: KontextIn):
        """Startseite, "Aufnahme transkribieren" oder Demo waehlen (Projekte: /api/projekt/...)."""
        if body.modus not in (kontext_modul.MODUS_START, kontext_modul.MODUS_DATEI, kontext_modul.MODUS_DEMO):
            raise HTTPException(400, f"Unbekannter Modus: {body.modus}")
        if body.modus == kontext_modul.MODUS_DEMO:
            if not kontext_modul.demo_verfuegbar():
                raise HTTPException(400, "Die Demo-Daten fehlen (Ordner demo/llm-wiki).")
            _wechsle(body.modus, kontext_modul.demo_projekt())
        else:
            _wechsle(body.modus)
        return JSONResponse(_kontext_antwort())

    def _projekt_pfade(body: ProjektIn) -> tuple[Path | None, Path | None, Path | None]:
        def pfad(raw: str) -> Path | None:
            return browse.normalize_path(raw, default=Path("")) if raw.strip() else None

        return pfad(body.wurzel), pfad(body.sitzungen_dir), pfad(body.assets_dir)

    @app.post("/api/projekt/pruefen")
    def api_projekt_pruefen(body: ProjektIn):
        """Sofortpruefung des Assistenten: Meldung je Feld, Wiki-Zustand, Vorschlaege fuer die Ordner."""
        from audioscribe.souffleur.wiki import pruefe_wiki

        wurzel, sitzungen, assets = _projekt_pfade(body)
        vorschlag = modell.vorschlag(wurzel) if wurzel is not None else {}
        fehler = modell.pruefe(
            name=body.name, wurzel=wurzel, sitzungen_dir=sitzungen, assets_dir=assets, neues_wiki=body.neues_wiki
        )
        return JSONResponse(
            {
                "fehler": fehler,
                "wiki": pruefe_wiki(wurzel).als_dict() if wurzel is not None and not body.neues_wiki else None,
                "vorschlag": vorschlag,
                "pfade": {
                    "wurzel": str(wurzel or ""), "sitzungen_dir": str(sitzungen or ""), "assets_dir": str(assets or ""),
                },
            }
        )

    @app.post("/api/projekt/neu")
    def api_projekt_neu(body: ProjektIn):
        wurzel, sitzungen, assets = _projekt_pfade(body)
        if _beschaeftigt():
            raise HTTPException(409, f"{_beschaeftigt()} Bitte erst beenden.")
        if wurzel is None or sitzungen is None or assets is None:
            raise HTTPException(400, "Bitte Wiki-Ordner, Sitzungsordner und Bilder-Ordner angeben.")
        try:
            projekt = modell.lege_an(
                name=body.name, wurzel=wurzel, sitzungen_dir=sitzungen, assets_dir=assets,
                neues_wiki=body.neues_wiki, ki_dienst=body.ki_dienst, souffleur_model=body.souffleur_model,
                agent_model=body.agent_model, sprache=body.sprache, wiki_speichern=body.wiki_speichern,
                wiki_bilder=body.wiki_bilder, wiki_markierungen=body.wiki_markierungen,
            )
        except ProjektFehler as exc:
            raise HTTPException(400, str(exc)) from exc
        _wechsle(kontext_modul.MODUS_PROJEKT, projekt)
        state.merke_projekt(projekt.wurzel, projekt.name)
        return JSONResponse(_kontext_antwort())

    @app.post("/api/projekt/oeffnen")
    def api_projekt_oeffnen(body: PfadIn):
        if not body.pfad.strip():
            raise HTTPException(400, "Bitte einen Projektordner angeben.")
        try:
            projekt = modell.lade(browse.normalize_path(body.pfad, default=Path("")))
        except ProjektFehler as exc:
            raise HTTPException(400, str(exc)) from exc
        _wechsle(kontext_modul.MODUS_PROJEKT, projekt)
        state.merke_projekt(projekt.wurzel, projekt.name)
        return JSONResponse(_kontext_antwort())

    @app.put("/api/projekt")
    def api_projekt_aendern(body: FelderIn):
        """Projekteinstellungen aendern; ``null`` bei KI/Sprache heisst: globale Einstellung."""
        p = _projekt()
        if p is None or p.demo:
            raise HTTPException(409, "Kein Projekt geöffnet.")
        felder = dict(body.felder)
        for key in ("sitzungen_dir", "assets_dir"):
            if isinstance(felder.get(key), str) and felder[key].strip():
                felder[key] = str(browse.normalize_path(felder[key], default=Path("")))
        if "sitzungen_dir" in felder and _beschaeftigt():
            raise HTTPException(409, f"{_beschaeftigt()} Der Sitzungsordner lässt sich erst danach ändern.")
        try:
            neu = modell.aendere(p, felder)
        except ProjektFehler as exc:
            raise HTTPException(400, str(exc)) from exc
        kontext.setze(kontext_modul.MODUS_PROJEKT, neu)
        state.merke_projekt(neu.wurzel, neu.name)
        return JSONResponse(_kontext_antwort())

    @app.post("/api/projekte/vergessen")
    def api_projekt_vergessen(body: PfadIn):
        """Aus der Liste der zuletzt geoeffneten nehmen - die Projektdatei bleibt liegen."""
        state.vergiss_projekt(body.pfad)
        return JSONResponse(_kontext_antwort())

    @app.get("/api/einstellungen")
    def api_einstellungen():
        saved = state.load_state()
        return JSONResponse({"werte": einstellungen.globale(saved), "optionen": einstellungen.optionen(saved)})

    @app.post("/api/einstellungen")
    def api_einstellungen_setzen(body: EinstellungenIn):
        """Globale Einstellungen (KI, Sprache) - gelten fuer alle Projekte, die nichts Eigenes setzen."""
        werte = {k: v for k, v in body.model_dump().items() if v is not None}
        for wert in werte.values():
            if not wert.strip() or wert.startswith("-") or not all(c.isalnum() or c in "-_.:[]" for c in wert):
                raise HTTPException(400, f"Ungültiger Wert: {wert}")
        state.save_state(einstellungen.als_state(werte))
        saved = state.load_state()
        return JSONResponse({"werte": einstellungen.globale(saved), "optionen": einstellungen.optionen(saved)})

    @app.get("/api/verbrauch")
    def api_verbrauch():
        """KI-Verbrauch seit Programmstart (Tokens, Preis zu API-Tarifen) - nur Aufrufe, die das
        Haus verlassen; je Quelle die laufende Aktivitaet und die Summe."""
        return JSONResponse(zaehler.snapshot())

    # --- Wiki-Ablage (PRD §21) ----------------------------------------------------------------

    def _sitzungsordner(raw: str) -> Path:
        """Sitzungsordner des geoeffneten Projekts - nichts ausserhalb des Projekts."""
        p = _projekt()
        if p is None or p.demo:
            raise HTTPException(409, "Kein Projekt geöffnet.")
        ordner = browse.normalize_path(raw, default=Path(""))
        try:
            ok = ordner.is_dir() and ordner.resolve().is_relative_to(p.sitzungen_dir.resolve())
        except OSError:
            ok = False
        if not ok:
            raise HTTPException(400, f"Kein Sitzungsordner dieses Projekts: {raw}")
        return ordner

    @app.post("/api/wiki/speichern")
    def api_wiki_speichern(body: WikiSpeichernIn):
        """Sitzung als neue Quelle nach raw/ legen, Bilder in den Assets-Ordner; die Markierungen
        des Souffleurs nur auf Wunsch (KI-erzeugt)."""
        ordner = _sitzungsordner(body.sitzung)
        p = _projekt()
        laufend = live.session_dir() if live.laeuft() else None
        if laufend is not None and laufend.resolve() == ordner.resolve():
            raise HTTPException(409, "Diese Sitzung läuft noch – ins Wiki geht sie nach dem Stopp.")
        try:
            ablage = wiki_ablage.speichere_sitzung(
                ordner, p, titel=body.titel, bilder=body.bilder, markierungen=body.markierungen
            )
        except (OSError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        antwort = ablage.als_dict()
        if body.immer:
            # Die Ablage ist geschrieben - scheitert nur das Merken von "immer", bleibt es dabei.
            try:
                kontext.setze(
                    kontext_modul.MODUS_PROJEKT,
                    modell.aendere(p, {
                        "wiki_speichern": modell.WIKI_IMMER, "wiki_bilder": body.bilder,
                        "wiki_markierungen": body.markierungen,
                    }),
                )
            except ProjektFehler as exc:
                antwort["hinweis"] = f"„Immer speichern“ ließ sich nicht merken: {exc}"
        return JSONResponse(antwort)

    @app.post("/api/wiki/speichern-nachbereitung")
    def api_wiki_speichern_nachbereitung(body: NachbereitungIn):
        """Dokumente einer KI-Analyse zur Sitzung ins Wiki legen (als KI-erzeugt gekennzeichnet)."""
        from audioscribe.agent.manifest import load_manifest

        p = _projekt()
        if p is None or p.demo:
            raise HTTPException(409, "Kein Projekt geöffnet.")
        workspace = browse.normalize_path(body.workspace, default=Path(""))
        try:
            ok = workspace.is_dir() and workspace.resolve().is_relative_to(p.analysen_dir.resolve())
        except OSError:
            ok = False
        manifest = load_manifest(workspace) if ok else None
        if manifest is None:
            raise HTTPException(400, f"Keine Analyse dieses Projekts: {body.workspace}")
        sitzung = _sitzungsordner(manifest.quelle)
        try:
            ablage = wiki_ablage.speichere_nachbereitung(
                workspace, p, sitzung, bilder=body.bilder, markierungen=p.wiki_markierungen
            )
        except (OSError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(ablage.als_dict())

    @app.get("/api/transkript")
    def api_transkript(pfad: str = Query("")):
        """Vorschau eines fertigen Transkripts (annotiert bevorzugt) - nur diese eine Datei.
        Im Projekt (und in der Demo) nur aus dem Sitzungsordner des Projekts."""
        ordner = browse.normalize_path(pfad, default=Path(""))
        p = _projekt()
        if p is not None:
            try:
                erlaubt = ordner.resolve().is_relative_to(p.sitzungen_dir.resolve())
            except OSError:
                erlaubt = False
            if not erlaubt:
                raise HTTPException(404, "Kein Transkript in diesem Ordner.")
        for name in _TRANSKRIPT_DATEIEN:
            datei = ordner / name
            try:
                if datei.is_file():
                    text = datei.read_text(encoding="utf-8", errors="replace")
                    return JSONResponse(
                        {"datei": str(datei), "text": text[:_TRANSKRIPT_MAX], "gekuerzt": len(text) > _TRANSKRIPT_MAX}
                    )
            except OSError as exc:
                raise HTTPException(400, f"Transkript nicht lesbar: {exc}") from exc
        raise HTTPException(404, "Kein Transkript in diesem Ordner.")

    @app.post("/api/oeffnen")
    def api_oeffnen(body: PfadIn):
        """Ordner im Dateimanager des Systems zeigen (Explorer, Finder)."""
        import subprocess
        import sys

        ordner = browse.normalize_path(body.pfad, default=Path(""))
        if not body.pfad.strip() or not ordner.is_dir():
            raise HTTPException(400, f"Ordner nicht gefunden: {body.pfad}")
        try:
            if browse.IS_WINDOWS:
                import os

                os.startfile(str(ordner))  # type: ignore[attr-defined]  # noqa: S606
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(ordner)])  # noqa: S603, S607
        except OSError as exc:
            raise HTTPException(500, f"Ordner lässt sich nicht öffnen: {exc}") from exc
        return JSONResponse({"ok": True})

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
                # Die drei Standardordner pflegt der Reiter "Einstellungen"; der
                # Analyse-Ordner steht darum auch hier, nicht nur in /api/agent/defaults.
                "agent_output_dir": str(settings.agent_output_dir),
            },
            state.load_state(),
        )
        chosen["input_dir"] = _remembered_dir(chosen["input_dir"], settings.input_dir)
        chosen["output_dir"] = _remembered_dir(chosen["output_dir"], settings.output_dir)
        chosen["agent_output_dir"] = _remembered_dir(
            chosen["agent_output_dir"], settings.agent_output_dir
        )
        # Im Projekt (und in der Demo) bestimmt das Projekt die Ordner; KI und Sprache kommen
        # aus den Einstellungen (global, vom Projekt ueberschreibbar) statt aus dem letzten Lauf.
        p = _projekt()
        if p is not None:
            chosen["output_dir"] = str(p.sitzungen_dir)
            chosen["agent_output_dir"] = str(p.analysen_dir)
        eff = _eff()
        chosen["language"] = eff["sprache"]
        chosen["souffleur_model"] = eff["souffleur_model"]
        chosen["wiki_dir"] = str(p.wurzel) if p is not None else (chosen.get("wiki_dir") or settings.wiki_dir)
        chosen.setdefault("souffleur_aktiv", True)
        chosen["souffleur_models"] = _souffleur_models()
        chosen["modus"] = kontext.modus
        acc = _accelerator()  # None = Probe nicht moeglich -> alle Geraete anbieten
        return JSONResponse(
            {
                **chosen,
                "models": list(jobs.WHISPER_MODELS),
                "languages": list(jobs.LANGUAGES),
                "devices": list(jobs.DEVICES),
                "sensitivities": list(jobs.SENSITIVITIES),
                "frame_formats": list(jobs.FRAME_FORMATS),
                "cuda": None if acc is None else acc["cuda"],
                "mps": None if acc is None else acc["mps"],
                "backend": None if acc is None else acc["backend"],
                # Steuert nur den Hinweistext der Oberflaeche: unter Windows werden
                # Pfade nach C:\... umgesetzt, unter WSL nach /mnt/c/...., auf dem Mac
                # bleiben Pfade, wie der Finder sie liefert.
                "platform": browse.PLATFORM,
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
    def api_browse(path: str = Query(""), files: bool = Query(False)):
        try:
            return JSONResponse(_folder_info(path, default=settings.input_dir, files=files))
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, f"Keine Leseberechtigung fuer: {path}") from exc

    @app.get("/api/scan")
    def api_scan(input_dir: str = Query(""), output_dir: str = Query("")):
        """Vorschau: welche Medien liegen im Eingangsordner, welche sind schon fertig?"""
        folder = browse.normalize_path(input_dir, default=settings.input_dir)
        out_dir = _ausgabe_dir(output_dir)
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

    @app.get("/api/environment")
    def api_environment(refresh: bool = Query(False)):
        """Karte "Umgebung" im Reiter Einstellungen: die Zeilen von ``audioscribe doctor``.

        Laeuft synchron im Threadpool von FastAPI - die Status-Abfragen der anderen
        Reiter laufen derweil weiter. ``checks`` ist ``null``, wenn der Check selbst
        nicht ausfuehrbar war.
        """
        checks, stamp = _environment(refresh=refresh)
        return JSONResponse(
            {
                "checks": checks,
                "checked_at": time.strftime("%H:%M:%S", time.localtime(stamp)),
            }
        )

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
        out_dir = _ausgabe_dir(body.output_dir)
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
                **({} if _projekt() is not None else {"output_dir": str(out_dir)}),
                "model": opts.model,
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
                "model": _eff()["agent_model"],
                "models": list(jobs.AGENT_MODELS),
                "output_dir": str(_projekt().analysen_dir) if _projekt() is not None else _remembered_dir(
                    saved.get("agent_output_dir"), settings.agent_output_dir
                ),
                "bash": saved.get("agent_bash", True),
            }
        )

    @app.get("/api/agent/sources")
    def api_agent_sources(output_dir: str = Query("")):
        """Fertige Transkriptionen im Ausgangsordner der Transkription."""
        folder = _ausgabe_dir(output_dir)
        p = _projekt()
        try:
            if p is not None and not folder.is_dir():
                results = []  # neues Projekt: der Sitzungsordner entsteht mit der ersten Sitzung
            else:
                results = jobs.scan_results(folder)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, f"Keine Leseberechtigung fuer: {folder}") from exc
        if p is not None and not p.demo:
            results = _mit_projektstand(results, p)
        return JSONResponse({"output_dir": str(folder), "sources": results})

    def _mit_projektstand(results: list[dict], p) -> list[dict]:
        """Sitzungen des Projekts um Titel, Status, Wiki-Ablagen und Analysen ergaenzen."""
        from audioscribe.agent.manifest import load_manifest

        analysen: dict[str, list[dict]] = {}
        try:
            ordner = sorted(d for d in p.analysen_dir.iterdir() if d.is_dir())
        except OSError:
            ordner = []
        for ws in ordner:
            manifest = load_manifest(ws)
            if manifest is None:
                continue
            index = ws / "INDEX.md"
            analysen.setdefault(Path(manifest.quelle).name, []).append(
                {
                    "name": manifest.name, "workspace": str(ws), "status": manifest.status,
                    "index": str(index) if index.is_file() else None,
                    "ablagen": wiki_ablage.ablagen(ws),
                }
            )
        out = []
        for r in results:
            sitzung = Path(r["path"])
            info: dict = {}
            try:
                info = json.loads((sitzung / "sitzung.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            out.append(
                {
                    **r,
                    "titel": str(info.get("titel") or "") if isinstance(info, dict) else "",
                    "status": str(info.get("status") or "") if isinstance(info, dict) else "",
                    "ablagen": wiki_ablage.ablagen(sitzung),
                    "analysen": analysen.get(sitzung.name, []),
                }
            )
        return out

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

        out_dir = _analysen_dir(body.output_dir)
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
        # Modell und Ordner gehoeren zu den Einstellungen bzw. zum Projekt - gemerkt werden
        # hier nur die Angaben des Laufs (ohne Projekt auch der zuletzt benutzte Ordner).
        state.save_state(
            {
                **({} if _projekt() is not None else {"agent_output_dir": str(out_dir)}),
                "agent_skills": list(body.skills),
                "agent_bash": body.bash,
            }
        )
        try:
            workspace = analyse.start(opts)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        # Ein neuer Lauf in denselben Ordner ersetzt das alte Ergebnis - dessen Vermerk
        # "im Wiki" gilt fuer das neue nicht mehr.
        try:
            (Path(workspace) / wiki_ablage.VERMERK).unlink(missing_ok=True)
        except OSError:
            pass
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
        hinweis = ""
        if browse.IS_MAC:
            try:
                from audioscribe.live.berechtigungen import hinweis as perm_hinweis

                hinweis = perm_hinweis()
            except Exception:  # noqa: BLE001 - Hinweis ist Zugabe
                hinweis = ""
        return JSONResponse(
            {
                **inventory(),
                "platform": browse.PLATFORM,
                "loopback_label": (
                    "System-Audio (ScreenCaptureKit, Gegenseite)" if browse.IS_MAC else "System-Audio (Ausgabe, Gegenseite)"
                ),
                "permission_hint": hinweis,
                "models": list(jobs.LIVE_WHISPER_MODELS),
                "refine_models": list(jobs.WHISPER_MODELS),
                "source": saved.get("live_source", "monitor"),
                "monitor": saved.get("live_monitor", "1"),
                "window": saved.get("live_window", ""),  # "Prozess – Titel", kein HWND
                "mic": saved.get("live_mic", "default"),
                "loopback": saved.get("live_loopback", "default"),
                "model": saved.get("live_model", "auto"),
                "language": _eff()["sprache"],
                "device": saved.get("live_device", settings.device),
                "sensitivity": saved.get("live_sensitivity", settings.screen_sensitivity),
                "format": saved.get("live_format", settings.screen_format),
                "partials": saved.get("live_partials", True),
                "speakers": saved.get("live_speakers", True),
                "refine": saved.get("live_refine", True),
                "refine_model": saved.get("live_refine_model", settings.whisper_model),
                # Testmodus (FR-64)
                "replay_transcript": saved.get("replay_transcript", ""),
                "replay_speed": saved.get("replay_speed", "1"),
                "replay_speeds": list(jobs.REPLAY_SPEEDS),
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

    @app.get("/api/live/window/{hwnd}")
    def api_live_window(hwnd: int):
        """Vorschaubild eines Anwendungsfensters; 404 wenn weg oder minimiert."""
        from audioscribe.live.fenster import WindowGone, preview_window_jpeg

        if not 0 < hwnd < 2**32:
            raise HTTPException(404, "Kein solches Fenster.")
        try:
            data = preview_window_jpeg(hwnd)
        except (ImportError, RuntimeError, WindowGone) as exc:
            raise HTTPException(404, str(exc)) from exc
        if data is None:
            raise HTTPException(404, "Fenster ist minimiert.")
        return Response(data, media_type="image/jpeg")

    @app.get("/api/live/windows")
    def api_live_windows():
        """Nur die Fensterliste - fuer den Aktualisieren-Knopf im Auswahldialog."""
        from audioscribe.live.fenster import list_windows

        try:
            return JSONResponse({"windows": list_windows()})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Fenster nicht lesbar: {exc}") from exc

    def _souffleur_factory(opts: jobs.LiveJobOptions):
        """Souffleur je Sitzung (PRD §20). Konfiguration kommt aus dem Einstellungsstand -
        der Wiki-Pfad wird nur in ``souffleur.konfig`` gelesen (K1)."""
        from audioscribe.souffleur.kern import Souffleur
        from audioscribe.souffleur.ki import make_ki
        from audioscribe.souffleur.konfig import lade_konfig

        speed = opts.replay_speed if opts.replay_transcript is not None else 1.0
        konfig = lade_konfig(state.load_state(), projekt=_projekt(), speed=speed)
        zaehler.beginne(QUELLE_SOUFFLEUR)
        ki, ki_status = make_ki(
            konfig.backend, konfig.modell, cache_dir=settings.cache_dir, log=live._append,
            on_verbrauch=lambda verbrauch: zaehler.buche(QUELLE_SOUFFLEUR, verbrauch),
        )
        return Souffleur(konfig, ki=ki, ki_status=ki_status, log=live._append)

    @app.post("/api/live/start")
    def api_live_start(body: LiveStartIn):
        if body.replay_transcript.strip():
            if body.resume.strip():
                raise HTTPException(400, "Fortsetzen geht nur mit einer Aufnahme, nicht im Testmodus.")
            return _live_start_replay(body)
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
        # Das HWND wandert als reiner int in argv; 32 Bit sind fuer Fenster-Handles signifikant.
        if body.monitor < 0 or not 0 <= body.window < 2**32:
            raise HTTPException(400, "Ungueltige Bildquelle.")
        if not (body.monitor or body.window) and body.mic == "none" and body.loopback == "none":
            raise HTTPException(400, "Weder Audio noch Bildquelle gewaehlt.")

        out_dir = _ausgabe_dir(body.output_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"Ausgangsordner nicht anlegbar: {exc}") from exc
        resume_dir = _unterbrochene_sitzung(body.resume) if body.resume.strip() else None

        opts = jobs.LiveJobOptions(
            output_dir=out_dir,
            titel=body.titel.strip()[:120],
            resume_dir=resume_dir,
            monitor=0 if body.window else body.monitor,
            window=body.window,
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
        # Bei Fensterwahl den zuletzt gemerkten Monitor stehen lassen.
        gemerkt = {"live_monitor": str(body.monitor)} if body.monitor else {}
        state.save_state(
            {
                **gemerkt,
                "live_source": "window" if body.window else ("monitor" if body.monitor else "none"),
                "live_window": body.window_label.strip()[:200],
                "live_mic": body.mic_name or body.mic,
                "live_loopback": body.loopback_name or body.loopback,
                "live_model": body.model,
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
            live.start(opts, souffleur_factory=_souffleur_factory, on_ende=_nach_sitzung)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True})

    def _nach_sitzung(session_dir: Path) -> dict | None:
        """Nachlauf einer Sitzung: steht das Projekt auf "immer speichern", geht sie ins Wiki."""
        p = _projekt()
        if p is None or p.demo or p.wiki_speichern != modell.WIKI_IMMER:
            return None
        try:
            ablage = wiki_ablage.speichere_sitzung(
                session_dir, p, bilder=p.wiki_bilder, markierungen=p.wiki_markierungen
            )
        except (OSError, RuntimeError) as exc:
            live._append(f"Wiki-Ablage fehlgeschlagen: {exc}")
            return {"wiki_fehler": str(exc)}
        live._append(f"Ins Wiki gespeichert: {ablage.ordner}")
        return {"wiki_ablage": ablage.als_dict()}

    def _unterbrochene_sitzung(raw: str) -> Path:
        """Ordner einer nicht sauber beendeten Sitzung des geoeffneten Projekts."""
        from audioscribe.live import journal

        ordner = _sitzungsordner(raw)
        status = journal.lies_status(ordner)
        if status is None or status.get("replay") or status.get("status") not in (journal.LAEUFT, journal.UNTERBROCHEN):
            raise HTTPException(400, "Diese Sitzung ist nicht unterbrochen.")
        if journal.lebt(ordner):
            raise HTTPException(409, "Die Sitzung läuft noch in einem anderen Prozess.")
        return ordner

    @app.get("/api/live/unterbrochen")
    def api_live_unterbrochen():
        return JSONResponse({"sitzungen": kontext_modul.unterbrochene(state.load_state(), _projekt())})

    @app.post("/api/live/abschliessen")
    def api_live_abschliessen(body: SitzungIn):
        """Unterbrochene Sitzung ohne weitere Aufnahme abschliessen: Transkript aus dem
        Gesicherten schreiben, danach wie gewohnt nachschaerfen."""
        # Abschliessen setzt die Live-Ansicht zurueck - nie, waehrend eine andere Sitzung aufnimmt.
        if live.laeuft():
            raise HTTPException(409, "Es läuft gerade eine Live-Sitzung – bitte erst stoppen.")
        ordner = _unterbrochene_sitzung(body.sitzung)
        saved = state.load_state()
        opts = jobs.LiveJobOptions(
            output_dir=ordner.parent, resume_dir=ordner, monitor=0, mic="none", loopback="none",
            language=_eff()["sprache"], device=saved.get("live_device", settings.device),
            refine=bool(saved.get("live_refine", True)) and (ordner / "audio").is_dir(),
            refine_model=saved.get("live_refine_model", settings.whisper_model),
        )
        try:
            live.reset()
            live.start(
                opts, souffleur_factory=_souffleur_factory, on_ende=_nach_sitzung,
                finalize_builder=jobs.build_finalize_argv,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.post("/api/live/verwerfen")
    def api_live_verwerfen(body: SitzungIn):
        """Unterbrochene Sitzung nicht mehr anbieten - die Dateien bleiben liegen."""
        from audioscribe.live import journal

        ordner = _unterbrochene_sitzung(body.sitzung)
        journal.schreibe_status(ordner, status=journal.VERWORFEN)
        return JSONResponse({"ok": True})

    def _live_start_replay(body: LiveStartIn):
        """Testmodus (FR-64): Transkript abspielen - ohne Geraete, ohne Nachschaerfen."""
        from audioscribe.live.replay_transkript import finde_transkript

        quelle = browse.normalize_path(body.replay_transcript, default=settings.output_dir)
        try:
            finde_transkript(quelle)
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not 0 < body.replay_speed <= 100:
            raise HTTPException(400, "Tempo muss zwischen 0 und 100 liegen.")
        out_dir = _ausgabe_dir(body.output_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"Ausgangsordner nicht anlegbar: {exc}") from exc
        opts = jobs.LiveJobOptions(
            output_dir=out_dir, monitor=0, mic="none", loopback="none", refine=False,
            replay_transcript=quelle, replay_speed=body.replay_speed, titel=body.titel.strip()[:120],
        )
        state.save_state(
            {"live_source": "transcript", "replay_transcript": str(quelle), "replay_speed": f"{body.replay_speed:g}"}
        )
        try:
            # Ohne Nachlauf: ein abgespieltes Transkript geht nie von selbst ins Wiki.
            live.start(opts, souffleur_factory=_souffleur_factory)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.post("/api/demo/start")
    def api_demo_start():
        """Demo (PRD §21): das Test-Meeting gegen das Demo-Wiki abspielen - ein Knopf, sonst nichts.
        Die Sitzung landet im Cache und wird beim naechsten Start ersetzt."""
        import shutil

        p = _projekt()
        if kontext.modus != kontext_modul.MODUS_DEMO or p is None:
            raise HTTPException(409, "Die Demo ist nicht geöffnet.")
        if live.laeuft():
            raise HTTPException(409, "Die Demo läuft bereits.")
        try:
            live.reset()
            shutil.rmtree(p.sitzungen_dir, ignore_errors=True)
            p.sitzungen_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(400, f"Demo nicht startbar: {exc}") from exc
        opts = jobs.LiveJobOptions(
            output_dir=p.sitzungen_dir, monitor=0, mic="none", loopback="none", refine=False,
            replay_transcript=p.wurzel / kontext_modul.DEMO_TRANSKRIPT, replay_speed=kontext_modul.DEMO_TEMPO,
            # Ohne die Gespraechspausen des echten Meetings: nach rund 30 s ist die Demo beim Thema.
            replay_raffen=True,
            titel="Demo",
        )
        try:
            live.start(opts, souffleur_factory=_souffleur_factory)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True})

    # --- Souffleur (PRD §20) -----------------------------------------------------

    @app.post("/api/souffleur/essenz")
    def api_souffleur_essenz(body: EssenzIn):
        """C1: Essenz der letzten 2 oder 5 Minuten - KI-erzeugt, so gekennzeichnet."""
        from dataclasses import asdict

        from audioscribe.souffleur.essenz import MINUTEN
        from audioscribe.souffleur.ki import KiFehler

        if body.minuten not in MINUTEN:
            raise HTTPException(400, f"Fenster muss {' oder '.join(map(str, MINUTEN))} Minuten sein.")
        souffleur = live.souffleur()
        if souffleur is None:
            raise HTTPException(409, "Keine Sitzung mit Souffleur.")
        try:
            essenz = souffleur.essenz(body.minuten)
        except KiFehler as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse({**asdict(essenz), "fenster": essenz.fenster})

    @app.get("/api/wiki/status")
    def api_wiki_status(path: str = Query("")):
        """K1: Wiki-Pfad pruefen - leer = der gemerkte Pfad. Drei Zustaende: keins | ok | fehler."""
        from audioscribe.souffleur.konfig import wiki_pfad
        from audioscribe.souffleur.wiki import pruefe_wiki

        pfad = browse.normalize_path(path, default=Path("")) if path.strip() else wiki_pfad(state.load_state(), _projekt())
        status = pruefe_wiki(pfad if str(pfad) not in ("", ".") else None)
        return JSONResponse(status.als_dict())

    @app.get("/api/souffleur/offene-punkte")
    def api_souffleur_offene_punkte():
        souffleur = live.souffleur()
        return JSONResponse({"punkte": souffleur.offene_punkte() if souffleur is not None else []})

    @app.post("/api/souffleur/toggle")
    def api_souffleur_toggle(body: SouffleurToggleIn):
        state.save_state({"souffleur_aktiv": body.aktiv})
        souffleur = live.souffleur()
        if souffleur is not None:
            souffleur.setze_aktiv(body.aktiv)
        return JSONResponse({"ok": True, "aktiv": body.aktiv})

    @app.get("/api/live/status")
    def api_live_status(offset: int = Query(0, ge=0), ev_offset: int = Query(0, ge=0)):
        snap = live.snapshot(offset, ev_offset)
        # Nach dem Ende: liegt die Sitzung schon im Wiki? Der Vermerk im Sitzungsordner weiss es -
        # auch nach einem Neuladen der Seite (sonst boete die Oberflaeche das Speichern doppelt an).
        p = _projekt()
        if p is not None and not p.demo and snap.get("dir") and not snap.get("running"):
            snap["wiki_ablage"] = wiki_ablage.letzte_ablage(Path(snap["dir"]), p)
        return JSONResponse(snap)

    @app.post("/api/live/pause")
    def api_live_pause(body: PauseIn):
        """Abspielen eines Transkripts anhalten oder fortsetzen (Pauseknopf der Demo)."""
        try:
            live.pause(body.pausiert)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return JSONResponse({"ok": True, "pausiert": body.pausiert})

    @app.post("/api/live/stop")
    def api_live_stop():
        live.stop()
        return JSONResponse({"ok": True})

    @app.post("/api/live/reset")
    def api_live_reset():
        """Alles auf Anfang - eine laufende Sitzung wird dabei verworfen."""
        lief = live.laeuft()
        try:
            discarded = live.reset()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if lief and discarded is not None:
            # Bewusst verworfen: sonst boete die Oberflaeche die Sitzung als "unterbrochen" an.
            from audioscribe.live import journal

            try:
                if journal.lies_status(discarded) is not None and not journal.lebt(discarded):
                    journal.schreibe_status(discarded, status=journal.VERWORFEN)
            except OSError:
                pass
        return JSONResponse({"ok": True, "discarded": str(discarded) if discarded else None})

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
    if not browse.IS_WINDOWS and not browse.IS_MAC:
        print("Unter WSL: die Adresse notfalls von Hand im Windows-Browser oeffnen.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    uvicorn.run(app, host=host, port=port, log_level="warning")
