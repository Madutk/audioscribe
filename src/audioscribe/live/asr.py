"""Residentes faster-whisper-Modell für die Live-Transkription.

``pipeline.transcribe`` lädt und entlädt das Modell je Aufruf (NFR-2) - bei
Sekunden-Abschnitten wäre das Laden teurer als die Arbeit. Hier bleibt es für die ganze
Sitzung geladen; der VRAM wird mit dem Prozessende frei.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from audioscribe.pipeline.models import fetch_model

LIVE_MODEL_CUDA = "large-v3-turbo"
LIVE_MODEL_CPU = "small"


def default_model(device: str) -> str:
    return LIVE_MODEL_CUDA if device.startswith("cuda") else LIVE_MODEL_CPU


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

    def transcribe(self, audio: np.ndarray, *, final: bool, eco: bool = False) -> str:
        """Text eines Abschnitts; ``eco`` = Aufholmodus (billig dekodieren, s. decode_options)."""
        segments, info = self._model.transcribe(
            audio, language=self.language, **decode_options(final=final, eco=eco)
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if final and not self.detected:
            self.detected = info.language
        return text
