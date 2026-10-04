"""Modell-Download mit Fortschritt (faster-whisper, MLX / Hugging Face Hub)."""

from __future__ import annotations

import os
from collections.abc import Callable


def progress_tqdm(on_progress: Callable[[int, int], None]):
    """tqdm-Klasse, die nur den Byte-Balken als ``on_progress(geladen, gesamt)`` meldet.

    Der Hub führt zwei Balken: Dateien ("it") und Bytes ("B"); die Gesamtgröße wächst,
    bis die Metadaten aller Dateien da sind.
    """
    from tqdm import tqdm

    class Progress(tqdm):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.update(file=open(os.devnull, "w"), mininterval=0.5)  # noqa: SIM115
            super().__init__(*args, **kwargs)

        def display(self, *args, **kwargs) -> None:  # noqa: ARG002
            if self.unit == "B" and self.total:
                on_progress(int(self.n), int(self.total))

    return Progress


def fetch_mlx_model(repo: str, on_progress: Callable[[int, int], None] | None = None) -> str:
    """MLX-Gewichte (Hugging-Face-Repo) als lokalen Snapshot-Pfad; Cache zuerst, Hub nur bei Bedarf.

    Immer derselbe Pfad-String zurück: ``mlx_whisper`` cacht sein Modell am Pfad, ein
    wechselnder Bezeichner (Repo vs. Pfad) würde es neu laden. Ein lokaler Ordner geht
    unverändert durch.
    """
    if os.path.isdir(repo):
        return repo
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(repo, local_files_only=True)
    except Exception:  # noqa: BLE001 - nicht (vollständig) im Cache -> herunterladen
        pass
    kwargs = {"tqdm_class": progress_tqdm(on_progress)} if on_progress is not None else {}
    return snapshot_download(repo, **kwargs)


def fetch_model(model: str, on_progress: Callable[[int, int], None]) -> str:
    """Lädt das Modell bei Bedarf herunter und meldet ``(geladen, gesamt)`` in Bytes.

    faster-whisper schaltet den Fortschritt seines Downloads fest ab
    (``tqdm_class=disabled_tqdm``); der erste Start wirkte darum minutenlang eingefroren.
    Liegt das Modell schon im Cache, wird der Hub gar nicht erst befragt (spart je Start
    eine Netzwerkrunde) und es kommt keine Meldung. Der Fortschritt ist Zugabe: geht hier
    etwas schief, lädt ``WhisperModel`` das Modell wie bisher selbst.
    """
    if os.path.isdir(model):
        return model
    try:
        from faster_whisper import utils

        try:
            return utils.download_model(model, local_files_only=True)
        except Exception:  # noqa: BLE001 - nicht (vollständig) im Cache -> herunterladen
            pass

        original = utils.disabled_tqdm
        utils.disabled_tqdm = progress_tqdm(on_progress)
        try:
            return utils.download_model(model)
        finally:
            utils.disabled_tqdm = original
    except Exception:  # noqa: BLE001
        return model
