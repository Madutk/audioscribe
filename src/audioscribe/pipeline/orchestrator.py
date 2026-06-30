"""Orchestrierung der gesamten Transkriptions-Pipeline (Stufen laufen sequenziell)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from audioscribe.config import settings
from audioscribe.export import write_markdown, write_pdf
from audioscribe.models import TranscriptMeta, TranscriptResult
from audioscribe.pipeline.audio import load_audio
from audioscribe.pipeline.diarize import diarize
from audioscribe.pipeline.media import extract_audio, is_video
from audioscribe.pipeline.merge import (
    build_paragraphs,
    fill_segment_speakers,
    relabel_speakers,
    result_to_segments,
)
from audioscribe.pipeline.transcribe import align, transcribe
from audioscribe.progress import ConsoleReporter, Reporter


def run_pipeline(
    media: str | Path,
    *,
    output_dir: str | Path | None = None,
    make_pdf: bool = False,
    reporter: Reporter | None = None,
) -> TranscriptResult:
    """Faehrt (Video->Audio) -> Transkript -> (Alignment) -> (Diarisierung) -> Markdown/PDF.

    Die Eingabe darf eine Audio- ODER Videodatei sein; bei Video wird zuerst die
    Audiospur extrahiert. Die Stufen werden durch die globale Konfiguration
    (``settings``) gesteuert; die CLI setzt diese ueber Umgebungsvariablen.
    """
    source_path = Path(media)
    if not source_path.exists():
        raise FileNotFoundError(f"Eingabedatei nicht gefunden: {source_path}")

    settings.ensure_dirs()
    from_video = is_video(source_path)
    do_align = settings.enable_alignment
    do_diar = settings.enable_diarization

    total = 3 + (1 if from_video else 0) + (1 if do_align else 0) + (1 if do_diar else 0)
    reporter = reporter or ConsoleReporter(total)
    step = 0

    audio_path = source_path
    if from_video:
        step += 1
        reporter.stage(step, "Audiospur extrahieren (ffmpeg)")
        audio_path = extract_audio(source_path, reporter)

    step += 1
    reporter.stage(step, "Audio laden")
    audio_arr, duration = load_audio(audio_path, reporter)

    step += 1
    reporter.stage(step, f"Transkription (faster-whisper {settings.whisper_model})")
    result = transcribe(audio_arr, reporter)

    if do_align:
        step += 1
        reporter.stage(step, "Wort-Alignment (wav2vec2)")
        result = align(audio_arr, result, reporter)

    if do_diar:
        step += 1
        reporter.stage(step, "Diarisierung (pyannote)")
        result = diarize(audio_arr, result, reporter)

    step += 1
    reporter.stage(step, "Zusammenfuehren & Export")
    segments = result_to_segments(result)
    fill_segment_speakers(segments)
    num_speakers = relabel_speakers(segments)
    paragraphs = build_paragraphs(segments)

    meta = TranscriptMeta(
        source=source_path,
        duration_s=duration,
        language=result.get("language") or settings.whisper_language,
        num_speakers=num_speakers,
        model=settings.whisper_model,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    transcript = TranscriptResult(meta=meta, paragraphs=paragraphs, segments=segments)

    out_dir = Path(output_dir) if output_dir else settings.output_dir
    md_path = write_markdown(transcript, out_dir)
    transcript.output_path = md_path
    reporter.info(f"Markdown: {md_path}")

    if make_pdf:
        pdf_path = write_pdf(transcript, md_path.with_suffix(".pdf"))
        reporter.info(f"PDF: {pdf_path}")

    return transcript
