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

import time
from collections.abc import Callable

from audioscribe.compat import free_accelerator as _free_vram
from audioscribe.config import resolve_device, settings, torch_device
from audioscribe.progress import Reporter, emit_progress

SAMPLE_RATE = 16_000

# Die beiden pyannote-Schritte, die ueberhaupt ``total``/``completed`` melden, auf einen
# gemeinsamen 0..100-Balken abgebildet. Alle anderen Schritte melden nur Artefakte.
_HOOK_SPANS: dict[str, tuple[float, float]] = {
    "segmentation": (0.0, 50.0),
    "embeddings": (50.0, 100.0),
}


def _assign_word_speakers():
    """Importiert ``assign_word_speakers`` versionsrobust aus WhisperX."""
    try:
        from whisperx.diarize import assign_word_speakers

        return assign_word_speakers
    except ImportError:
        import whisperx  # aeltere Layouts exportieren es top-level

        return whisperx.assign_word_speakers


def make_progress_hook(
    emit: Callable[[float], None] = emit_progress,
    *,
    min_delta: float = 1.0,
    min_interval: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
):
    """Baut den ``hook``-Rueckruf fuer ``pyannote``-Pipelines.

    Signatur laut pyannote: ``(step_name, step_artifact, file=None, total=None,
    completed=None)``. Drei Eigenschaften sind hier nicht optional:

    * **Nichts darf nach aussen dringen.** pyannote ruft den Hook ungeschuetzt auf - eine
      Ausnahme wuerde mitten in der Diarisierung durchschlagen und die Datei kippen.
      Darum liegt der komplette Rumpf in einem ``try/except``.
    * **``step_artifact`` wird nie angefasst** - bei den reinen Artefakt-Aufrufen sind das
      grosse Numpy-Arrays.
    * **Drosselung.** Das Segmentierungsfenster laeuft mit 1 s Schrittweite ueber die
      gesamte Aufnahme; ohne Bremse waeren das bei zwei Stunden mehrere tausend Zeilen.
    """
    state = {"last_percent": -min_delta, "last_time": float("-inf")}

    def hook(
        step_name: str,
        step_artifact=None,
        file=None,
        total: int | None = None,
        completed: int | None = None,
    ) -> None:
        try:
            span = _HOOK_SPANS.get(step_name)
            if span is None or completed is None or not total:
                return
            low, high = span
            percent = low + (high - low) * min(1.0, max(0.0, completed / total))
            now = clock()
            # monoton halten: der zweite Schritt darf nie hinter den ersten zurueckfallen
            if percent < state["last_percent"] + min_delta:
                return
            if now - state["last_time"] < min_interval and percent < 100.0:
                return
            state["last_percent"] = percent
            state["last_time"] = now
            emit(percent)
        except Exception:  # noqa: BLE001 - Fortschrittsanzeige darf die Diarisierung nie kippen
            return

    return hook


def _akzeptiert_hook(pipeline) -> bool:
    """Kennt ``pipeline.apply`` den ``hook``-Parameter? (rein, testbar)

    Vorab per Signatur pruefen statt einen ``TypeError`` abzufangen: der koennte auch tief
    aus der Diarisierung kommen - dann liefe die ganze Datei ein zweites Mal, nur um am
    Ende mit demselben Fehler ohne Kontext zu scheitern. Ein per
    AUDIOSCRIBE_DIARIZATION_MODEL gesetztes anderes Modell kennt 'hook' evtl. nicht -
    dann eben ohne Fortschrittsanzeige.
    """
    import inspect

    apply = getattr(pipeline, "apply", None)
    if apply is None:
        return False
    try:
        params = inspect.signature(apply).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "hook" or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def _ladefehler_meldung(status: str, detail: str, hint: str = "") -> str:
    """Nutzermeldung fuer ein fehlgeschlagenes Laden des Diarisierungsmodells (rein, testbar).

    ``UNPRUEFBAR`` (kein Netz, Proxy, huggingface_hub fehlt) braucht einen eigenen Zweig:
    sonst hiesse es "Token gueltig, Bedingungen akzeptieren", obwohl schlicht Hugging Face
    nicht erreichbar ist.
    """
    from audioscribe.hf import TOKENS_URL

    if status in ("FEHLT", "UNGUELTIG"):
        return (
            f"Diarisierungsmodell konnte nicht geladen werden: {detail}\n"
            f"Neuen Token erstellen ({TOKENS_URL}, Rolle 'read'), in die .env eintragen "
            "und mit 'audioscribe doctor' pruefen. "
            "Alternativ ohne Sprecher-Trennung: '--no-diarize'." + hint
        )
    if status == "UNPRUEFBAR":
        return (
            "Diarisierungsmodell konnte nicht geladen werden - Hugging Face ist nicht "
            f"erreichbar oder der Token nicht pruefbar ({detail}). Netzwerk/Proxy pruefen "
            "und mit 'audioscribe doctor' gegenchecken. "
            "Alternativ ohne Sprecher-Trennung: '--no-diarize'." + hint
        )
    return (
        "Diarisierungsmodell konnte nicht geladen werden - der HF_TOKEN ist gueltig, also "
        "sind die Modell-Bedingungen noch nicht (vollstaendig) akzeptiert. BEIDE Seiten "
        "muessen EINGELOGGT akzeptiert werden:\n"
        "  https://huggingface.co/pyannote/speaker-diarization-3.1\n"
        "  https://huggingface.co/pyannote/segmentation-3.0\n"
        "Status pruefen mit 'audioscribe doctor'. Alternativ ohne Sprecher-Trennung: '--no-diarize'."
        + hint
    )


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

    from audioscribe.compat import (
        apply_hf_hub_compat,
        apply_speechbrain_lazy_compat,
        apply_torch_load_compat,
    )

    apply_torch_load_compat()  # pyannote-Checkpoint laedt nur mit weights_only=False (PyTorch 2.6)
    apply_hf_hub_compat()  # pyannote uebergibt use_auth_token -> auf 'token' mappen (huggingface_hub 1.x)
    apply_speechbrain_lazy_compat()  # Checkpoint-Laden stolpert sonst ueber speechbrains Lazy-Module

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
        # Ein abgelehnter Token sieht fuer Hugging Face aus wie ein anonymer Zugriff, das
        # gesperrte Repo meldet dann ebenfalls "gated". Erst nachfragen, dann anleiten -
        # sonst klickt der Nutzer 'Agree', obwohl sein Token widerrufen ist.
        from audioscribe.hf import token_status

        status, detail = token_status(settings.hf_token)
        raise RuntimeError(_ladefehler_meldung(status, detail, hint))

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
        pipeline.to(torch.device(torch_device(resolve_device(settings.device))))
        audio_data = {"waveform": torch.from_numpy(audio[None, :]), "sample_rate": SAMPLE_RATE}
        if settings.emit_progress and _akzeptiert_hook(pipeline):
            kwargs["hook"] = make_progress_hook()
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
