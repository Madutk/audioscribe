"""Residentes faster-whisper-Modell für die Live-Transkription.

``pipeline.transcribe`` lädt und entlädt das Modell je Aufruf (NFR-2) - bei
Sekunden-Abschnitten wäre das Laden teurer als die Arbeit. Hier bleibt es für die ganze
Sitzung geladen; der VRAM wird mit dem Prozessende frei.
"""

from __future__ import annotations

import numpy as np

LIVE_MODEL_CUDA = "large-v3-turbo"
LIVE_MODEL_CPU = "small"


def default_model(device: str) -> str:
    return LIVE_MODEL_CUDA if device.startswith("cuda") else LIVE_MODEL_CPU


class LiveTranscriber:
    def __init__(self, model: str, device: str, compute_type: str, language: str) -> None:
        from faster_whisper import WhisperModel

        name, _, index = device.partition(":")
        self.language = None if language.lower() == "auto" else language
        self.detected = self.language or ""
        self._model = WhisperModel(
            model, device=name, device_index=int(index or 0), compute_type=compute_type
        )

    def transcribe(self, audio: np.ndarray, *, final: bool) -> str:
        """Text eines Abschnitts. Die Vorschau rechnet billig: Beam 1, kein Temperatur-Fallback."""
        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5 if final else 1,
            temperature=(0.0, 0.2, 0.4) if final else 0.0,
            # Jeder Abschnitt steht für sich: Vortext schleppt Fehler (und Halluzinationen) mit.
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if final and not self.detected:
            self.detected = info.language
        return text
