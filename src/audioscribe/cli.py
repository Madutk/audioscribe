"""CLI-Einstiegspunkt fuer audioscribe.

Befehle:
  doctor  - Umgebungs-Check (Python/ffmpeg/CUDA/WhisperX/pyannote/HF-Token)
  run     - Audiodatei transkribieren + diarisieren -> Markdown (optional PDF)
"""

from __future__ import annotations

import argparse
import os

from audioscribe import __version__


def _set(name: str, value: object) -> None:
    """Mappt CLI-Flags auf die AUDIOSCRIBE_*-Umgebungsvariablen (vor Config-Import)."""
    if value is not None:
        os.environ[f"AUDIOSCRIBE_{name}"] = str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audioscribe",
        description="Lokale Audio-Transkription mit Sprecher-Diarisierung (WhisperX).",
    )
    parser.add_argument("--version", action="version", version=f"audioscribe {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="Umgebungs-Check (Python/ffmpeg/CUDA/WhisperX/pyannote)")

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
    run.add_argument("--compute-type", help="Rechenpraezision (float16/int8_float16/int8)")
    run.add_argument("--device", help="cuda (Default) oder cpu")
    run.add_argument(
        "--sentences-per-timestamp",
        type=int,
        metavar="N",
        help="neuer Zeitstempel alle N Saetze (Default 2; 0 = ganzer Sprecher-Beitrag am Stueck)",
    )
    run.add_argument("--pdf", action="store_true", help="zusaetzlich PDF erzeugen")
    run.add_argument("--output", help="Ausgabeverzeichnis (Default: ./output)")

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

        # cuDNN-8-Libs fuer ctranslate2 bereitstellen + via LD_LIBRARY_PATH auffindbar
        # machen (re-exec). Muss vor dem Import von torch/whisperx geschehen.
        from audioscribe.config import settings

        if settings.device.startswith("cuda"):
            from audioscribe.compat import ensure_native_libs

            ensure_native_libs(log=print)

        from audioscribe.pipeline.orchestrator import run_pipeline

        result = run_pipeline(args.media, output_dir=args.output, make_pdf=args.pdf)
        print(f"\nFertig. Transkript: {result.output_path}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
