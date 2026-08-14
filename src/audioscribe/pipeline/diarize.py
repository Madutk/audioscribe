"""Stufe 4 - Sprecher-Diarisierung mit pyannote.

Ordnet jedem Wort/Segment ein rohes Sprecher-Label (``SPEAKER_00`` ...) zu.
Benoetigt einen HuggingFace-Token UND einmalig akzeptierte Modell-Bedingungen.
Modell wird nach Gebrauch aus dem VRAM entladen (NFR-2).

Wir laden die pyannote-Pipeline direkt (statt ueber ``whisperx.DiarizationPipeline``),
weil dessen Wrapper bei einem fehlgeschlagenen Laden ``.to()`` auf ``None`` aufruft
und damit nur einen kryptischen ``AttributeError`` liefert. So koennen wir den Fall
sauber erkennen und eine hilfreiche Meldung ausgeben. Das Zuordnen der Sprecher zu
den Woertern uebernimmt weiterhin ``whisperx.assign_word_speakers``.
"""

from __future__ import annotations

import gc

from audioscribe.config import resolve_device, settings
from audioscribe.progress import Reporter

SAMPLE_RATE = 16_000


def _free_vram() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - best effort
        pass


def _assign_word_speakers():
    """Importiert ``assign_word_speakers`` versionsrobust aus WhisperX."""
    try:
        from whisperx.diarize import assign_word_speakers

        return assign_word_speakers
    except ImportError:
        import whisperx  # aeltere Layouts exportieren es top-level

        return whisperx.assign_word_speakers


def diarize(audio, result: dict, reporter: Reporter | None = None) -> dict:
    """Weist Sprecher zu und liefert das angereicherte Result-Dict zurueck."""
    if not result.get("segments"):
        if reporter:
            reporter.info("Diarisierung uebersprungen (keine Segmente)")
        return result

    if not settings.hf_token:
        raise RuntimeError(
            "HF_TOKEN fehlt - Diarisierung nicht moeglich. Siehe .env.example "
            "(Token setzen + Modell-Bedingungen akzeptieren) oder '--no-diarize' nutzen."
        )

    from audioscribe.compat import apply_hf_hub_compat, apply_torch_load_compat

    apply_torch_load_compat()  # pyannote-Checkpoint laedt nur mit weights_only=False (PyTorch 2.6)
    apply_hf_hub_compat()  # pyannote uebergibt use_auth_token -> auf 'token' mappen (huggingface_hub 1.x)

    import pandas as pd
    import torch
    from pyannote.audio import Pipeline

    # pyannote liefert bei gesperrtem Haupt-Repo None zurueck; ist ein TEILMODELL gesperrt
    # (z.B. segmentation-3.0), crasht es intern (get_model -> None.eval()). Beides abfangen.
    try:
        pipeline = Pipeline.from_pretrained(settings.diarization_model, use_auth_token=settings.hf_token)
    except Exception as exc:  # noqa: BLE001
        pipeline, load_exc = None, exc
    else:
        load_exc = None
    if pipeline is None:
        hint = f"\n(Ursache: {type(load_exc).__name__}: {str(load_exc)[:200]})" if load_exc else ""
        raise RuntimeError(
            "Diarisierungsmodell konnte nicht geladen werden - meist sind die Modell-Bedingungen "
            "noch nicht (vollstaendig) akzeptiert. BEIDE Seiten muessen EINGELOGGT akzeptiert werden:\n"
            "  https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "  https://huggingface.co/pyannote/segmentation-3.0\n"
            "Status pruefen mit 'audioscribe doctor'. Alternativ ohne Sprecher-Trennung: '--no-diarize'."
            + hint
        )

    assign_word_speakers = _assign_word_speakers()

    kwargs: dict = {}
    if settings.num_speakers:
        kwargs["num_speakers"] = settings.num_speakers
    else:
        if settings.min_speakers:
            kwargs["min_speakers"] = settings.min_speakers
        if settings.max_speakers:
            kwargs["max_speakers"] = settings.max_speakers

    try:
        pipeline.to(torch.device(resolve_device(settings.device)))
        audio_data = {"waveform": torch.from_numpy(audio[None, :]), "sample_rate": SAMPLE_RATE}
        diarization = pipeline(audio_data, **kwargs)

        diarize_df = pd.DataFrame(
            diarization.itertracks(yield_label=True),
            columns=["segment", "label", "speaker"],
        )
        diarize_df["start"] = diarize_df["segment"].apply(lambda x: x.start)
        diarize_df["end"] = diarize_df["segment"].apply(lambda x: x.end)
        result = assign_word_speakers(diarize_df, result)
    finally:
        del pipeline
        _free_vram()

    if reporter:
        n = len({s.get("speaker") for s in result.get("segments", []) if s.get("speaker")})
        reporter.info(f"{n} Sprecher erkannt")
    return result
