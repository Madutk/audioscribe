"""CLI-Einstiegspunkt fuer audioscribe.

Befehle:
  doctor  - Umgebungs-Check (Plattform/Python/ffmpeg/Device(CUDA/MPS/CPU)/WhisperX/ASR-Backend/pyannote)
  run     - Audiodatei transkribieren + diarisieren -> Markdown (optional PDF)
  review  - lokale Review-Oberflaeche: Video + Transkript, wichtige Frames markieren (PRD §13)
  export  - Transkript + Markierungen zu annotiertem Markdown/PDF mergen (FR-18)
  ui      - Browser-Oberflaeche: Ein-/Ausgangsordner waehlen, alle Medien darin transkribieren
  analyze - KI-Analyse eines Ergebnisordners per Claude-Agent (Kontext + Skills, PRD §16)
  prozessbild - prozessbild.png/.svg aus prozessbild.mmd neu erzeugen (FR-35)
  bpmn    - BPMN-Modell mit Lanes aus bpmn-modell.json erzeugen/pruefen (FR-36)
  live    - Live-Transkription: Monitor + System-Audio + Mikrofon mitschneiden (PRD §17; Windows, macOS)
  refine  - Live-Sitzung mit der Offline-Pipeline nachschaerfen (FR-43)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from audioscribe import __version__


_BACKEND_HELP = (
    "ASR-Backend fuer Whisper: auto (Default: mlx auf Apple Silicon, sonst faster-whisper) "
    "| faster-whisper | mlx"
)


def _set(name: str, value: object) -> None:
    """Mappt CLI-Flags auf die AUDIOSCRIBE_*-Umgebungsvariablen (vor Config-Import)."""
    if value is not None:
        os.environ[f"AUDIOSCRIBE_{name}"] = str(value)


def _resolve_out_dir(target: str) -> Path:
    """Mappt ``ORDNER|VIDEO`` auf den Ausgabeordner ``output/<name>``.

    Ist ``target`` ein vorhandenes Verzeichnis, wird es direkt genutzt; sonst wird der
    Ausgabeordner aus dem Dateistamm unter ``settings.output_dir`` abgeleitet.
    """
    p = Path(target)
    if p.is_dir():
        return p
    from audioscribe.config import settings

    return settings.output_dir / p.stem


def _prepare_backend() -> tuple[str, str] | None:
    """Loest Geraet/compute_type/ASR-Backend auf und macht ctranslate2 + cuDNN ladbar.

    Liefert ``(device, compute_type)`` oder ``None`` (Fehler bereits ausgegeben). Muss VOR
    dem ersten whisperx-/faster-whisper-/torch-Import laufen.
    """
    # Geraet aufloesen (auto -> cuda|mps|cpu) und das Ergebnis in die Env zurueckschreiben:
    # so gilt nach dem os.execv-Re-Exec des cuDNN-Bootstraps dieselbe Entscheidung.
    from audioscribe.config import (
        ct2_device,
        resolve_asr_backend,
        resolve_compute_type,
        resolve_device,
        settings,
    )

    if sys.platform == "darwin":
        # Fehlende MPS-Operatoren (pyannote: fft u. a.) rechnet torch dann auf der CPU
        # statt abzubrechen. Muss vor dem ersten torch-Import stehen.
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    try:
        device = resolve_device(settings.device)
        backend = resolve_asr_backend(settings.asr_backend, device)
    except RuntimeError as exc:
        print(str(exc))
        return None
    compute_type = resolve_compute_type(settings.whisper_compute_type, ct2_device(device))
    _set("DEVICE", device)
    _set("WHISPER_COMPUTE_TYPE", compute_type)
    _set("ASR_BACKEND", backend)
    if device.startswith("mps"):
        print(f"Device: mps (torch) · Whisper: {backend} ({'Metal' if backend == 'mlx' else 'CPU, ' + compute_type})")
    else:
        print(f"Device: {device}, compute_type: {compute_type}, Backend: {backend}")

    # ctranslate2 importierbar machen (beide Pfade, vor dem whisperx-Import):
    # Wheel-Reparatur fuer neuere glibc (Linux) bzw. pkg_resources-Ersatz (Windows).
    from audioscribe.compat import ensure_ctranslate2_loadable, ensure_pkg_resources

    ensure_ctranslate2_loadable(log=print)
    ensure_pkg_resources(log=print)

    # cuDNN-8-Libs fuer ctranslate2 bereitstellen und auffindbar machen: unter Linux
    # ueber LD_LIBRARY_PATH samt Prozess-Neustart, unter Windows ueber
    # os.add_dll_directory (wirkt sofort). Muss vor dem whisperx-Import geschehen;
    # nur im CUDA-Pfad.
    if device.startswith("cuda"):
        from audioscribe.compat import ensure_native_libs

        ensure_native_libs(log=print)
    return device, compute_type


def _live_transcript(args: argparse.Namespace) -> int:
    """Transkript-Replay (FR-64): vor jedem Backend-Bootstrap - kein torch, kein Modell."""
    from audioscribe.config import settings
    from audioscribe.live.replay_transkript import ReplayOptions, TranskriptReplaySession, finde_transkript

    try:
        quelle = finde_transkript(Path(args.transcript))
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    if args.speed <= 0:
        print("--speed muss groesser als 0 sein")
        return 1
    if args.replay_delay < 0:
        print("--replay-delay darf nicht negativ sein")
        return 1
    opts = ReplayOptions(
        output_dir=Path(args.output) if args.output else settings.output_dir,
        quelle=quelle,
        speed=args.speed,
        delay_s=args.replay_delay,
        sentences_per_timestamp=settings.sentences_per_timestamp,
        titel=args.titel or "",
        raffen=bool(args.raffen),
    )
    return TranskriptReplaySession(opts).run()


def _live_finalize(args: argparse.Namespace) -> int:
    """Unterbrochene Sitzung abschließen (PRD §21): vor jedem Backend-Bootstrap - kein Modell."""
    from audioscribe.config import settings
    from audioscribe.live.session import finalisiere_sitzung

    ordner = Path(args.finalize)
    if not ordner.is_dir():
        print(f"Sitzungsordner nicht gefunden: {ordner}")
        return 1
    return finalisiere_sitzung(ordner, sentences_per_timestamp=settings.sentences_per_timestamp)


def _live(args: argparse.Namespace) -> int:
    if args.finalize:
        return _live_finalize(args)
    if args.transcript:
        if args.resume:
            print("--resume und --transcript schliessen sich aus: ein Transkript-Replay wird nicht fortgesetzt.")
            return 1
        return _live_transcript(args)
    resume_dir = None
    if args.resume:
        from audioscribe.live import journal

        resume_dir = Path(args.resume)
        if not resume_dir.is_dir():
            print(f"Sitzungsordner nicht gefunden: {resume_dir}")
            return 1
        if journal.lebt(resume_dir):
            print(f"Die Sitzung laeuft bereits in einem anderen Prozess: {resume_dir}")
            return 1
    _set("WHISPER_LANGUAGE", args.language)
    _set("WHISPER_COMPUTE_TYPE", args.compute_type)
    _set("DEVICE", args.device)
    _set("ASR_BACKEND", args.backend)
    prepared = _prepare_backend()
    if prepared is None:
        return 1
    device, compute_type = prepared

    from audioscribe.config import resolve_asr_backend, settings
    from audioscribe.live.asr import default_model
    from audioscribe.live.session import LiveOptions, LiveSession

    # settings ist beim Import eingefroren - den von _prepare_backend aufgeloesten Wert
    # liefert die Umgebung, resolve_asr_backend ist darauf idempotent.
    backend = resolve_asr_backend(os.environ.get("AUDIOSCRIBE_ASR_BACKEND", settings.asr_backend), device)
    model = args.model if args.model and args.model != "auto" else default_model(device, backend)
    replay = args.wav is not None or args.wav_mic is not None
    for pfad in (args.wav, args.wav_mic):
        if pfad is not None and not Path(pfad).is_file():
            print(f"WAV nicht gefunden: {pfad}")
            return 1
    if args.speed <= 0:
        print("--speed muss groesser als 0 sein")
        return 1
    opts = LiveOptions(
        output_dir=(
            resume_dir.parent if resume_dir is not None
            else Path(args.output) if args.output else settings.output_dir
        ),
        resume_dir=resume_dir,
        titel=args.titel or "",
        model=model,
        device=device,
        compute_type=compute_type,
        backend=backend,
        language=settings.whisper_language,
        # Replay: keine Standbilder, Spuren nur aus den Dateien.
        monitor=0 if replay else args.monitor,
        window=0 if replay else args.window,
        mic=("default" if args.wav_mic else "none") if replay else args.mic,
        loopback=("default" if args.wav else "none") if replay else args.loopback,
        replay_system=Path(args.wav) if args.wav else None,
        replay_mic=Path(args.wav_mic) if args.wav_mic else None,
        speed=args.speed,
        sensitivity=args.frame_sensitivity or settings.screen_sensitivity,
        bildformat=args.frame_format or settings.screen_format,
        partials=not args.no_partials,
        speakers=not args.no_speakers,
        hf_token=settings.hf_token,
        sentences_per_timestamp=settings.sentences_per_timestamp,
        cpu_threads=args.cpu_threads if args.cpu_threads is not None else settings.cpu_threads,
        force_eco=args.eco,
        pause_s=settings.live_pause_s,
        partial_interval_s=settings.live_partial_interval_s,
        partial_min_s=settings.live_partial_min_s,
        vad_every_tick=settings.live_vad_every_tick,
    )
    try:
        return LiveSession(opts).run()
    except RuntimeError as exc:
        print(str(exc))
        return 1


def _refine(args: argparse.Namespace) -> int:
    if args.no_diarize:
        _set("DIARIZATION", 0)
    _set("WHISPER_LANGUAGE", args.language)
    _set("WHISPER_MODEL", args.model)
    _set("DEVICE", args.device)
    _set("ASR_BACKEND", args.backend)
    if _prepare_backend() is None:
        return 1

    from audioscribe.live.refine import refine_session

    try:
        out = refine_session(_resolve_out_dir(args.target))
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    print(f"\nFertig. Transkript: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audioscribe",
        description="Lokale Audio-Transkription mit Sprecher-Diarisierung (WhisperX).",
    )
    parser.add_argument("--version", action="version", version=f"audioscribe {__version__}")
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="Umgebungs-Check (Python/ffmpeg/Device/WhisperX/pyannote)")
    doctor.add_argument("--json", action="store_true", help="Ergebnis als JSON-Liste (fuer die Oberflaeche)")

    run = sub.add_parser("run", help="Audio-/Videodatei transkribieren und diarisieren")
    run.add_argument(
        "media",
        metavar="DATEI",
        help="Pfad zur Audio- ODER Videodatei (mp3/m4a/wav/...; mp4/mkv/mov/webm/... -> "
        "Audiospur wird zuerst extrahiert)",
    )
    run.add_argument("--no-diarize", action="store_true", help="Sprecher-Diarisierung abschalten")
    run.add_argument("--no-align", action="store_true", help="Wort-Alignment abschalten")
    run.add_argument("--language", help="Sprachcode (z.B. 'de') oder 'auto' fuer Erkennung")
    run.add_argument("--num-speakers", type=int, help="exakte Sprecheranzahl vorgeben")
    run.add_argument("--min-speakers", type=int, help="Mindest-Sprecheranzahl")
    run.add_argument("--max-speakers", type=int, help="Maximal-Sprecheranzahl")
    run.add_argument("--model", help="Whisper-Modell (Default: large-v3)")
    run.add_argument(
        "--compute-type",
        help="Rechenpraezision: auto (Default; cuda->float16, cpu->int8) | float16 | int8_float16 | int8",
    )
    run.add_argument(
        "--device", help="auto (Default: CUDA > MPS (Apple Silicon) > CPU) | cuda | mps | cpu"
    )
    run.add_argument("--backend", help=_BACKEND_HELP)
    run.add_argument(
        "--sentences-per-timestamp",
        type=int,
        metavar="N",
        help="neuer Zeitstempel alle N Saetze (Default 2; 0 = ganzer Sprecher-Beitrag am Stueck)",
    )
    run.add_argument(
        "--frames",
        action="store_true",
        help="Bildwechsel im Video erkennen und je Wechsel ein Standbild sichern "
        "(fuer Bildschirmaufnahmen; erzeugt zusaetzlich transkript.annotiert.md)",
    )
    run.add_argument(
        "--frame-sensitivity",
        choices=("grob", "mittel", "fein"),
        help="Empfindlichkeit der Bildwechsel-Erkennung (Default: mittel)",
    )
    run.add_argument(
        "--frame-format",
        choices=("jpg-1600", "jpg-1280", "png"),
        help="Format/Groesse der Standbilder (Default: jpg-1600)",
    )
    run.add_argument(
        "--frame-fps",
        type=float,
        metavar="N",
        help="Abtastungen je Sekunde bei der Bildanalyse (Default: 2; 1 ist doppelt so schnell)",
    )
    run.add_argument(
        "--frame-min-gap",
        type=float,
        metavar="SEK",
        help="Mindestabstand zwischen zwei Standbildern in Sekunden (Default: 4)",
    )
    run.add_argument("--pdf", action="store_true", help="zusaetzlich PDF erzeugen")
    run.add_argument("--output", help="Ausgabeverzeichnis (Default: ./output)")

    rev = sub.add_parser(
        "review", help="Review-Oberflaeche: Video + Transkript, wichtige Frames markieren"
    )
    rev.add_argument(
        "target", metavar="ORDNER|VIDEO", help="Ausgabeordner (output/<name>) ODER Videopfad"
    )
    rev.add_argument("--port", type=int, default=8765, help="HTTP-Port (Default: 8765)")
    rev.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch oeffnen")

    ui = sub.add_parser(
        "ui", help="Browser-Oberflaeche: Ordner waehlen und alle Medien darin transkribieren"
    )
    # Eigener Port, damit UI (8766) und Review-Oberflaeche (8765) parallel laufen koennen.
    ui.add_argument("--port", type=int, default=8766, help="HTTP-Port (Default: 8766)")
    ui.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch oeffnen")

    exp = sub.add_parser(
        "export", help="Transkript + Markierungen zu annotiertem Markdown/PDF mergen"
    )
    exp.add_argument("target", metavar="ORDNER|VIDEO", help="Ausgabeordner (output/<name>) ODER Videopfad")
    exp.add_argument("--pdf", action="store_true", help="zusaetzlich annotiertes PDF erzeugen")

    ana = sub.add_parser(
        "analyze",
        help="Ergebnisordner per Claude-Agent auswerten (Prozessdoku u.a.; nutzt das Claude-Abo)",
    )
    ana.add_argument(
        "target",
        nargs="?",
        metavar="ORDNER|VIDEO",
        help="Ergebnisordner eines 'run' (output/<name>) ODER Videopfad",
    )
    ana.add_argument("--name", help="Name des Prozesses (bestimmt auch den Unterordner)")
    ana.add_argument(
        "--out", help="Ausgabeordner; Ergebnisse landen in <out>/<name> (Default: ./analysen)"
    )
    ana.add_argument(
        "--context",
        action="append",
        metavar="DATEI",
        help="Kontextdatei fuer den Agenten (mehrfach moeglich; md/txt werden direkt uebergeben)",
    )
    ana.add_argument("--context-text", metavar="TEXT", help="Kontext als Freitext")
    ana.add_argument(
        "--skill",
        action="append",
        metavar="NAME",
        help="Skill bereitstellen (mehrfach moeglich; Default: AUDIOSCRIBE_AGENT_SKILLS)",
    )
    ana.add_argument(
        "--no-skills", action="store_true", help="keine Skills bereitstellen (auch keine Vorauswahl)"
    )
    ana.add_argument("--skills-dir", metavar="PFAD", help="Ordner mit Skills (Default: ~/.claude/skills)")
    ana.add_argument("--list-skills", action="store_true", help="verfuegbare Skills anzeigen und beenden")
    ana.add_argument("--model", help="Claude-Modell (Default: claude-opus-5)")
    ana.add_argument("--max-turns", type=int, metavar="N", help="Obergrenze fuer Agenten-Runden")
    ana.add_argument(
        "--no-bash", action="store_true", help="Agent darf keine Befehle/Skill-Skripte ausfuehren"
    )
    ana.add_argument(
        "--no-prozessbild",
        action="store_true",
        help="kein prozessbild.png/.svg aus dem Mermaid-Diagramm erzeugen",
    )
    ana.add_argument(
        "--no-bpmn",
        action="store_true",
        help="kein BPMN-Modell (bpmn-modell.bpmn/.svg/.png) erzeugen",
    )
    ana.add_argument(
        "--resume",
        action="store_true",
        help="(experimentell) vorhandene Sitzung in <out>/<name> fortsetzen; "
        "--context-text ist dann die Folgeanweisung",
    )

    pb = sub.add_parser(
        "prozessbild",
        help="prozessbild.png/.svg neu aus prozessbild.mmd erzeugen (z. B. nach Handkorrektur)",
    )
    pb.add_argument("target", metavar="ORDNER", help="Ergebnisordner einer Analyse")
    pb.add_argument("--browser", metavar="PFAD", help="Edge/Chrome/Chromium (Default: automatisch)")

    bp = sub.add_parser(
        "bpmn",
        help="BPMN-Modell mit Lanes aus bpmn-modell.json erzeugen bzw. pruefen (FR-36)",
    )
    bp.add_argument("target", metavar="ORDNER", help="Ergebnisordner einer Analyse")
    bp.add_argument("--pruefen", action="store_true", help="nur validieren, nichts schreiben")
    bp.add_argument(
        "--neu",
        action="store_true",
        help="auch eine in einem BPMN-Werkzeug bearbeitete .bpmn ueberschreiben",
    )
    bp.add_argument("--name", help="Name des Pools (Default: Prozessname aus analyse.json)")
    bp.add_argument("--browser", metavar="PFAD", help="Edge/Chrome/Chromium fuer das PNG")

    live = sub.add_parser(
        "live",
        help="Live-Transkription: Monitor, System-Audio und Mikrofon mitschneiden (Windows, macOS)",
    )
    live.add_argument("--output", help="Ausgabeverzeichnis; die Sitzung landet in <output>/live-...")
    live.add_argument(
        "--monitor", type=int, default=1, metavar="N", help="Monitor fuer Standbilder (1 = erster; 0 = aus)"
    )
    live.add_argument(
        "--window",
        type=int,
        default=0,
        metavar="HWND",
        help="Fenster-Handle fuer Standbilder (hat Vorrang vor --monitor; siehe --list-devices)",
    )
    live.add_argument("--mic", default="default", help="Mikrofon: default | none | Geraeteindex")
    live.add_argument(
        "--loopback",
        default="default",
        help="System-Audio (Windows: WASAPI-Loopback, macOS: ScreenCaptureKit): default | none | Geraeteindex",
    )
    live.add_argument(
        "--list-devices", action="store_true", help="Audio-Geraete, Monitore und Fenster anzeigen"
    )
    live.add_argument(
        "--model", help="Whisper-Modell (Default: large-v3-turbo auf CUDA und MLX, small auf CPU)"
    )
    live.add_argument("--language", help="Sprachcode (z.B. 'de') oder 'auto'")
    live.add_argument("--device", help="auto | cuda | mps | cpu")
    live.add_argument("--backend", help=_BACKEND_HELP)
    live.add_argument("--compute-type", help="auto | float16 | int8_float16 | int8")
    live.add_argument(
        "--cpu-threads",
        type=int,
        metavar="N",
        help="Rechen-Threads auf der CPU (Default: AUDIOSCRIBE_CPU_THREADS bzw. Bibliothek)",
    )
    live.add_argument("--frame-sensitivity", choices=("grob", "mittel", "fein"))
    live.add_argument("--frame-format", choices=("jpg-1600", "jpg-1280", "png"))
    live.add_argument("--no-partials", action="store_true", help="keinen vorlaeufigen Text ausgeben")
    live.add_argument(
        "--no-speakers", action="store_true", help="System-Spur nicht in 'Sprecher N' trennen"
    )
    live.add_argument(
        "--eco",
        action="store_true",
        help="Messlaeufe: jeden Abschnitt sparsam dekodieren (Beam 1, kein Fallback), wie im Aufholmodus",
    )
    live.add_argument(
        "--wav",
        metavar="DATEI",
        help="Messlaeufe: WAV als System-Audio durch die Live-Pipeline schicken statt aufzunehmen "
        "(keine Standbilder; laeuft auch unter Linux)",
    )
    live.add_argument("--wav-mic", metavar="DATEI", help="WAV als Mikrofon-Spur (mit oder ohne --wav)")
    live.add_argument(
        "--transcript",
        metavar="DATEI",
        help="Testmodus (Souffleur): gespeichertes Transkript (transcript.json, transkript.md oder "
        "Sitzungsordner) mit seinen Zeitstempeln abspielen, als kaeme es live - ohne Audio und Modell",
    )
    live.add_argument(
        "--replay-delay",
        type=float,
        default=0.0,
        metavar="S",
        help="mit --transcript: konstante Verzoegerung je Absatz in Sekunden (simulierte Erkennungslatenz)",
    )
    live.add_argument(
        "--speed",
        type=float,
        default=1.0,
        metavar="X",
        help="Abspieltempo beim Replay (1.0 = Echtzeit; schneller nur fuer Funktionstests)",
    )
    live.add_argument(
        "--raffen",
        action="store_true",
        help="mit --transcript: Pausen raffen - die Absaetze folgen im Sprechtempo aufeinander (Demo)",
    )
    live.add_argument("--titel", metavar="TEXT", help="Sitzungstitel (steht in sitzung.json)")
    live.add_argument(
        "--resume",
        metavar="ORDNER",
        help="unterbrochene Sitzung in ihrem Ordner fortsetzen: Transkript, Standbilder und "
        "Zeitleiste laufen weiter, der Mitschnitt kommt in eine neue Teil-Datei",
    )
    live.add_argument(
        "--finalize",
        metavar="ORDNER",
        help="unterbrochene Sitzung ohne Modelle abschliessen: Transkript aus dem Journal, "
        "Mitschnitt-Teile verbinden (danach optional 'audioscribe refine')",
    )

    ref = sub.add_parser(
        "refine", help="Live-Sitzung mit der Offline-Pipeline nachschaerfen (Live-Fassung bleibt erhalten)"
    )
    ref.add_argument("target", metavar="ORDNER", help="Sitzungsordner (output/live-...)")
    ref.add_argument("--model", help="Whisper-Modell (Default: large-v3)")
    ref.add_argument("--language", help="Sprachcode (z.B. 'de') oder 'auto'")
    ref.add_argument("--device", help="auto | cuda | mps | cpu")
    ref.add_argument("--backend", help=_BACKEND_HELP)
    ref.add_argument("--no-diarize", action="store_true", help="System-Spur nicht diarisieren")

    args = parser.parse_args(argv)

    if args.command == "live":
        if args.list_devices:
            from audioscribe.live.kommando import list_devices_text

            print(list_devices_text())
            return 0
        return _live(args)

    if args.command == "refine":
        return _refine(args)

    if args.command == "doctor":
        from audioscribe.doctor import run_doctor

        return run_doctor(as_json=args.json)

    if args.command == "run":
        # CLI-Flags -> Umgebungsvariablen, BEVOR die Konfiguration geladen wird.
        if args.no_diarize:
            _set("DIARIZATION", 0)
        if args.no_align:
            _set("ALIGNMENT", 0)
        _set("WHISPER_LANGUAGE", args.language)
        _set("NUM_SPEAKERS", args.num_speakers)
        _set("MIN_SPEAKERS", args.min_speakers)
        _set("MAX_SPEAKERS", args.max_speakers)
        _set("WHISPER_MODEL", args.model)
        _set("WHISPER_COMPUTE_TYPE", args.compute_type)
        _set("DEVICE", args.device)
        _set("ASR_BACKEND", args.backend)
        _set("SENTENCES_PER_TIMESTAMP", args.sentences_per_timestamp)
        if args.frames:
            _set("SCREENS", 1)
        _set("SCREEN_SENSITIVITY", args.frame_sensitivity)
        _set("SCREEN_FORMAT", args.frame_format)
        _set("SCREEN_FPS", args.frame_fps)
        _set("SCREEN_MIN_GAP", args.frame_min_gap)

        if _prepare_backend() is None:
            return 1

        from audioscribe.pipeline.orchestrator import run_pipeline

        result = run_pipeline(args.media, output_dir=args.output, make_pdf=args.pdf)
        print(f"\nFertig. Transkript: {result.output_path}")
        return 0

    if args.command == "review":
        out_dir = _resolve_out_dir(args.target)
        from audioscribe.review.server import serve

        try:
            serve(out_dir, port=args.port, open_browser=not args.no_browser)
        except ModuleNotFoundError:
            print(
                "Die Review-Oberflaeche benoetigt fastapi + uvicorn. Installiere sie mit:\n"
                "  uv sync --extra review"
            )
            return 1
        except FileNotFoundError as exc:
            print(str(exc))
            return 1
        return 0

    if args.command == "ui":
        from audioscribe.ui.server import serve as serve_ui

        try:
            serve_ui(port=args.port, open_browser=not args.no_browser)
        except ModuleNotFoundError:
            print(
                "Die Browser-Oberflaeche benoetigt fastapi + uvicorn. Installiere sie mit:\n"
                "  uv sync --extra review"
            )
            return 1
        return 0

    if args.command == "export":
        out_dir = _resolve_out_dir(args.target)
        from audioscribe.review.exporter import export_annotated

        try:
            out_md = export_annotated(out_dir, make_pdf=args.pdf)
        except FileNotFoundError as exc:
            print(str(exc))
            return 1
        print(f"Annotiertes Transkript: {out_md}")
        return 0

    if args.command == "analyze":
        from audioscribe.agent.kommando import analyze

        return analyze(args, _resolve_out_dir)

    if args.command == "bpmn":
        from audioscribe.agent.kommando import bpmn

        return bpmn(args, _resolve_out_dir)

    if args.command == "prozessbild":
        from audioscribe.agent.kommando import prozessbild

        return prozessbild(args, _resolve_out_dir)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
