"""Residentes Whisper-Modell für die Live-Transkription - faster-whisper oder MLX.

``pipeline.transcribe`` lädt und entlädt das Modell je Aufruf (NFR-2) - bei
Sekunden-Abschnitten wäre das Laden teurer als die Arbeit. Hier bleibt es für die ganze
Sitzung geladen; der VRAM wird mit dem Prozessende frei.

Zwei Backends hinter dem ``Transcriber``-Protokoll: ``LiveTranscriber`` (faster-whisper/
CTranslate2: CUDA oder CPU) und ``asr_mlx.MlxTranscriber`` (Apple Silicon, Metal; FR-52).
``make_transcriber`` wählt nach ``backend``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from audioscribe.config import ct2_device
from audioscribe.pipeline.models import fetch_model

LIVE_MODEL_CUDA = "large-v3-turbo"
LIVE_MODEL_CPU = "small"

BACKEND_FASTER_WHISPER = "faster-whisper"
BACKEND_MLX = "mlx"


def default_model(device: str, backend: str = BACKEND_FASTER_WHISPER) -> str:
    """``auto``-Modell: turbo, wo es flott ist (CUDA, MLX); ``small`` auf der CPU."""
    if backend == BACKEND_MLX or device.startswith("cuda"):
        return LIVE_MODEL_CUDA
    return LIVE_MODEL_CPU


class Transcriber(Protocol):
    """Was die Sitzung von einem ASR-Backend braucht."""

    model: str
    detected: str  # erkannte Sprache ("" bis zum ersten fertigen Abschnitt bei language=auto)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        final: bool,
        eco: bool = False,
        initial_prompt: str | None = None,
    ) -> Ergebnis: ...


def make_transcriber(
    backend: str,
    model: str,
    device: str,
    compute_type: str,
    language: str,
    on_progress: Callable[[int, int], None] | None = None,
    cpu_threads: int = 0,
) -> Transcriber:
    """Das Backend zur Wahl; ``mps`` erreicht CTranslate2 nie (``ct2_device``)."""
    if backend == BACKEND_MLX:
        from audioscribe.live.asr_mlx import MlxTranscriber

        return MlxTranscriber(model, language, on_progress=on_progress)
    return LiveTranscriber(
        model, ct2_device(device), compute_type, language, on_progress=on_progress, cpu_threads=cpu_threads
    )


def decode_options(*, final: bool, eco: bool = False) -> dict:
    """Dekodier-Parameter je Auftragsart.

    Fertige Abschnitte bekommen Beam 5 mit Temperatur-Fallback. Die Vorschau und der
    Aufholmodus (``eco``) rechnen billig: Beam 1, kein Fallback - auf der CPU macht das den
    Decoder um ein Mehrfaches schneller.
    """
    cheap = not final or eco
    return {
        "beam_size": 1 if cheap else 5,
        "best_of": 1 if cheap else 5,
        "temperature": 0.0 if cheap else (0.0, 0.2, 0.4),
        # Jeder Abschnitt steht für sich: Vortext schleppt Fehler (und Halluzinationen) mit.
        "condition_on_previous_text": False,
        "without_timestamps": True,
        "vad_filter": False,
    }


@dataclass(frozen=True)
class SegmentInfo:
    """Qualitätswerte eines Whisper-Segments (Diagnose-Log, FR-47)."""

    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float
    temperature: float  # > 0 heißt: der Temperatur-Fallback hat gegriffen


@dataclass(frozen=True)
class Ergebnis:
    text: str
    segmente: tuple[SegmentInfo, ...] = ()

    @classmethod
    def von(cls, wert: object) -> Ergebnis:
        """Ein ``Ergebnis`` oder ein bloßer Text (Attrappen in Tests) -> ``Ergebnis``."""
        if isinstance(wert, cls):
            return wert
        return cls(str(wert or "").strip())


class LiveTranscriber:
    def __init__(
        self,
        model: str,
        device: str,
        compute_type: str,
        language: str,
        on_progress: Callable[[int, int], None] | None = None,
        cpu_threads: int = 0,
    ) -> None:
        from faster_whisper import WhisperModel

        name, _, index = device.partition(":")
        self.model = model
        self.language = None if language.lower() == "auto" else language
        self.detected = self.language or ""
        if on_progress is not None:
            model = fetch_model(model, on_progress)
        self._model = WhisperModel(
            model,
            device=name,
            device_index=int(index or 0),
            compute_type=compute_type,
            cpu_threads=cpu_threads,  # 0 = Bibliotheks-Default (ctranslate2: 4)
        )

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        final: bool,
        eco: bool = False,
        initial_prompt: str | None = None,
    ) -> Ergebnis:
        """Text eines Abschnitts samt Segment-Qualitätswerten; ``eco`` = Aufholmodus."""
        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            initial_prompt=initial_prompt,
            **decode_options(final=final, eco=eco),
        )
        # Der Generator dekodiert erst beim Durchlaufen - einmal materialisieren.
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        if final and not self.detected:
            self.detected = info.language
        return Ergebnis(
            text,
            tuple(
                SegmentInfo(
                    avg_logprob=round(float(s.avg_logprob), 3),
                    compression_ratio=round(float(s.compression_ratio), 3),
                    no_speech_prob=round(float(s.no_speech_prob), 3),
                    temperature=float(s.temperature),
                )
                for s in segs
            ),
        )
