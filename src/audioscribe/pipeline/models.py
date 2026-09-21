"""Modell-Download mit Fortschritt (faster-whisper / Hugging Face Hub)."""

from __future__ import annotations

import os
from collections.abc import Callable


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
