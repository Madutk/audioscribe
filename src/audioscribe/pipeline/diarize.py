"""Stufe 4 - Sprecher-Diarisierung mit pyannote (via WhisperX).

Ordnet jedem Wort/Segment ein rohes Sprecher-Label (``SPEAKER_00`` ...) zu.
Benoetigt einen HuggingFace-Token (Modell-Bedingungen einmalig akzeptieren).
Modell wird nach Gebrauch aus dem VRAM entladen (NFR-2).
"""

from __future__ import annotations

import gc

from audioscribe.config import settings
from audioscribe.progress import Reporter


def _free_vram() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - best effort
        pass


def _diarize_symbols():
    """Importiert DiarizationPipeline + assign_word_speakers versionsrobust."""
    try:
        from whisperx.diarize import DiarizationPipeline, assign_word_speakers

        return DiarizationPipeline, assign_word_speakers
    except ImportError:
        import whisperx  # aeltere Layouts exportieren beides top-level

        return whisperx.DiarizationPipeline, whisperx.assign_word_speakers


def diarize(audio, result: dict, reporter: Reporter | None = None) -> dict:
    """Weist Sprecher zu und liefert das angereicherte Result-Dict zurueck."""
    if not result.get("segments"):
        if reporter:
            reporter.info("Diarisierung uebersprungen (keine Segmente)")
        return result

    if not settings.hf_token:
        raise RuntimeError(
            "HF_TOKEN fehlt - Diarisierung nicht moeglich. Siehe .env.example "
            "(Modell-Bedingungen akzeptieren + Token in .env setzen) oder '--no-diarize' nutzen."
        )

    from audioscribe.compat import apply_torch_load_compat

    apply_torch_load_compat()  # pyannote-Diarisierungs-Checkpoint laedt nur mit weights_only=False

    DiarizationPipeline, assign_word_speakers = _diarize_symbols()

    try:
        pipeline = DiarizationPipeline(
            model_name=settings.diarization_model,
            use_auth_token=settings.hf_token,
            device=settings.device,
        )
    except TypeError:
        # aeltere Signatur ohne 'model_name'
        pipeline = DiarizationPipeline(use_auth_token=settings.hf_token, device=settings.device)

    kwargs: dict = {}
    if settings.num_speakers:
        kwargs["num_speakers"] = settings.num_speakers
    else:
        if settings.min_speakers:
            kwargs["min_speakers"] = settings.min_speakers
        if settings.max_speakers:
            kwargs["max_speakers"] = settings.max_speakers

    try:
        diarize_segments = pipeline(audio, **kwargs)
        result = assign_word_speakers(diarize_segments, result)
    finally:
        del pipeline
        _free_vram()

    if reporter:
        n = len({s.get("speaker") for s in result.get("segments", []) if s.get("speaker")})
        reporter.info(f"{n} Sprecher erkannt")
    return result
