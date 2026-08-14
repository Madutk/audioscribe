"""CLI-Einstiegspunkt fuer audioscribe.

Befehle:
  doctor  - Umgebungs-Check (Python/ffmpeg/Device(CUDA/CPU)/WhisperX/pyannote/HF-Token)
  run     - Audiodatei transkribieren + diarisieren -> Markdown (optional PDF)
  review  - lokale Review-Oberflaeche: Video + Transkript, wichtige Frames markieren (PRD §13)
  export  - Transkript + Markierungen zu annotiertem Markdown/PDF mergen (FR-18)
  ui      - Browser-Oberflaeche: Ein-/Ausgangsordner waehlen, alle Medien darin transkribieren
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from audioscribe import __version__


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audioscribe",
        description="Lokale Audio-Transkription mit Sprecher-Diarisierung (WhisperX).",
    )
    parser.add_argument("--version", action="version", version=f"audioscribe {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="Umgebungs-Check (Python/ffmpeg/Device/WhisperX/pyannote)")

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
        "--device", help="auto (Default: CUDA falls verfuegbar, sonst CPU) | cuda | cpu"
    )
    run.add_argument(
        "--sentences-per-timestamp",
        type=int,
        metavar="N",
        help="neuer Zeitstempel alle N Saetze (Default 2; 0 = ganzer Sprecher-Beitrag am Stueck)",
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

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from audioscribe.doctor import run_doctor

        return run_doctor()

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
        _set("SENTENCES_PER_TIMESTAMP", args.sentences_per_timestamp)

        # Geraet aufloesen (auto -> cuda|cpu) und das Ergebnis in die Env zurueckschreiben:
        # so gilt nach dem os.execv-Re-Exec des cuDNN-Bootstraps dieselbe Entscheidung.
        from audioscribe.config import resolve_compute_type, resolve_device, settings

        try:
            device = resolve_device(settings.device)
        except RuntimeError as exc:
            print(str(exc))
            return 1
        compute_type = resolve_compute_type(settings.whisper_compute_type, device)
        _set("DEVICE", device)
        _set("WHISPER_COMPUTE_TYPE", compute_type)
        print(f"Device: {device}, compute_type: {compute_type}")

        # ctranslate2-Wheel fuer neuere glibc reparieren (beide Pfade, vor whisperx-Import).
        from audioscribe.compat import ensure_ctranslate2_loadable

        ensure_ctranslate2_loadable(log=print)

        # cuDNN-8-Libs fuer ctranslate2 bereitstellen + via LD_LIBRARY_PATH auffindbar
        # machen (re-exec). Muss vor dem Import von whisperx geschehen; nur im CUDA-Pfad.
        if device.startswith("cuda"):
            from audioscribe.compat import ensure_native_libs

            ensure_native_libs(log=print)

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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
