"""Stufe 2+3 - Transkription (faster-whisper large-v3) und Wort-Alignment (wav2vec2).

Beide Modelle werden nach Gebrauch aus dem VRAM entladen (NFR-2: 8 GB-Budget,
Modelle laufen sequenziell).
"""

from __future__ import annotations

import gc

from audioscribe.config import resolve_compute_type, resolve_device, settings
from audioscribe.progress import Reporter


def _free_vram() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - best effort
        pass


def transcribe(audio, reporter: Reporter | None = None) -> dict:
    """Transkribiert das Audio-Array und liefert das WhisperX-Result-Dict.

    Result: ``{"segments": [...], "language": "de"}``.
    """
    import whisperx

    from audioscribe.compat import apply_speechbrain_lazy_compat, apply_torch_load_compat

    apply_torch_load_compat()  # pyannote-VAD-Checkpoint laedt nur mit weights_only=False (PyTorch 2.6)
    apply_speechbrain_lazy_compat()  # Checkpoint-Laden stolpert sonst ueber speechbrains Lazy-Module

    language = None if settings.whisper_language.lower() == "auto" else settings.whisper_language
    device = resolve_device(settings.device)
    model = whisperx.load_model(
        settings.whisper_model,
        device=device,
        compute_type=resolve_compute_type(settings.whisper_compute_type, device),
        language=language,
    )
    try:
        # print_progress: WhisperX druckt je VAD-Abschnitt (~30 s Audio) "Progress: N%..." -
        # die Fortschrittsquelle fuer die Oberflaeche. Im Terminal standardmaessig aus.
        result = model.transcribe(
            audio, batch_size=settings.batch_size, print_progress=settings.emit_progress
        )
    except IndexError:
        # WhisperX/transformers wirft IndexError, wenn die VAD keine Sprache findet
        # (stilles/sprachloses Audio) -> leeres Transkript statt Absturz.
        result = {"segments": [], "language": language or "de"}
        if reporter:
            reporter.info("Keine aktive Sprache erkannt -> leeres Transkript")
    finally:
        del model
        _free_vram()

    if reporter:
        reporter.info(
            f"Sprache: {result.get('language', '?')}, {len(result.get('segments', []))} Segmente"
        )
    return result


def align(audio, result: dict, reporter: Reporter | None = None) -> dict:
    """Verfeinert die Segment-Zeitstempel auf Wortebene (wav2vec2).

    Faellt sauber zurueck auf das unausgerichtete Result, wenn fuer die erkannte
    Sprache kein Alignment-Modell verfuegbar ist.
    """
    import whisperx

    from audioscribe.compat import apply_speechbrain_lazy_compat, apply_torch_load_compat

    if not result.get("segments"):
        if reporter:
            reporter.info("Alignment uebersprungen (keine Segmente)")
        return result

    apply_torch_load_compat()
    apply_speechbrain_lazy_compat()

    language = result.get("language") or settings.whisper_language
    device = resolve_device(settings.device)
    try:
        align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    except Exception as exc:  # noqa: BLE001 - z.B. keine Modellgewichte fuer die Sprache
        if reporter:
            reporter.info(f"Alignment uebersprungen (kein Modell fuer '{language}': {exc})")
        return result

    try:
        aligned = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
    finally:
        del align_model
        _free_vram()

    aligned["language"] = language
    if reporter:
        reporter.info("Wort-Zeitstempel ausgerichtet")
    return aligned
