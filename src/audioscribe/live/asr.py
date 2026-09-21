"""Residentes faster-whisper-Modell für die Live-Transkription.

``pipeline.transcribe`` lädt und entlädt das Modell je Aufruf (NFR-2) - bei
Sekunden-Abschnitten wäre das Laden teurer als die Arbeit. Hier bleibt es für die ganze
Sitzung geladen; der VRAM wird mit dem Prozessende frei.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np

LIVE_MODEL_CUDA = "large-v3-turbo"
LIVE_MODEL_CPU = "small"


def default_model(device: str) -> str:
    return LIVE_MODEL_CUDA if device.startswith("cuda") else LIVE_MODEL_CPU


def fetch_model(model: str, on_progress: Callable[[int, int], None]) -> str:
    """Lädt das Modell bei Bedarf herunter und meldet ``(geladen, gesamt)`` in Bytes.

    faster-whisper schaltet den Fortschritt seines Downloads fest ab
    (``tqdm_class=disabled_tqdm``); der erste Start wirkte darum minutenlang eingefroren.
    Liegt das Modell schon im Cache, kommt keine Meldung. Der Fortschritt ist Zugabe: geht
    hier etwas schief, lädt ``WhisperModel`` das Modell wie bisher selbst.
    """
    if os.path.isdir(model):
        return model
    try:
        from faster_whisper import utils
        from tqdm import tqdm

        class Progress(tqdm):
            def __init__(self, *args, **kwargs) -> None:
                kwargs.update(file=open(os.devnull, "w"), mininterval=0.5)  # noqa: SIM115
                super().__init__(*args, **kwargs)

            def display(self, *args, **kwargs) -> None:  # noqa: ARG002
                # Der Hub führt zwei Balken: Dateien ("it") und Bytes ("B"); die Gesamtgröße
                # wächst, bis die Metadaten aller Dateien da sind.
                if self.unit == "B" and self.total:
                    on_progress(int(self.n), int(self.total))

        original = utils.disabled_tqdm
        utils.disabled_tqdm = Progress
        try:
            return utils.download_model(model)
        finally:
            utils.disabled_tqdm = original
    except Exception:  # noqa: BLE001
        return model


class LiveTranscriber:
    def __init__(
        self,
        model: str,
        device: str,
        compute_type: str,
        language: str,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        from faster_whisper import WhisperModel

        name, _, index = device.partition(":")
        self.language = None if language.lower() == "auto" else language
        self.detected = self.language or ""
        if on_progress is not None:
            model = fetch_model(model, on_progress)
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
