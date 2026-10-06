"""Sprecher der System-Spur live unterscheiden: Stimm-Embedding + Online-Clustering.

Die Offline-Diarisierung sieht die ganze Aufnahme und nummeriert je Lauf neu - beides
geht live nicht. Hier bekommt jeder Abschnitt ein Embedding und wird dem ähnlichsten
laufenden Zentroiden zugeordnet; so bleibt "Sprecher 2" über die Sitzung derselbe.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from audioscribe.live.track import SAMPLE_RATE

EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"

ICH = "Ich"
GEGENSEITE = "Gegenseite"

# Unter dieser Länge ist ein Embedding Rauschen; der Abschnitt erbt den letzten Sprecher.
MIN_EMBED_S = 1.5

# Begleitdatei im Sitzungsordner: die laufenden Zentroiden. Ohne sie hieße nach einer
# Wiederaufnahme (PRD §21) der erste System-Sprecher wieder "Sprecher 1", egal wer spricht.
SPRECHER_DATEI = "sprecher.json"


class OnlineClusterer:
    """Ordnet Embeddings laufenden Zentroiden zu (rein, testbar)."""

    def __init__(self, threshold: float = 0.4, max_speakers: int = 8) -> None:
        self.threshold = threshold
        self.max_speakers = max_speakers
        self._sums: list[np.ndarray] = []

    def assign(self, embedding: np.ndarray) -> int | None:
        """Index des Sprechers (0-basiert); ``None`` bei unbrauchbarem Embedding."""
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(norm) or norm == 0.0:
            return None
        e = embedding / norm
        sims = [float(e @ (s / np.linalg.norm(s))) for s in self._sums]
        best = int(np.argmax(sims)) if sims else -1
        if best >= 0 and (sims[best] >= self.threshold or len(self._sums) >= self.max_speakers):
            self._sums[best] = self._sums[best] + e
            return best
        self._sums.append(e.copy())
        return len(self._sums) - 1

    def __len__(self) -> int:
        return len(self._sums)

    def zustand(self) -> list[list[float]]:
        return [[float(v) for v in s] for s in self._sums]

    def setze_zustand(self, sums: list[list[float]]) -> None:
        self._sums = [np.asarray(s, dtype=np.float32) for s in sums if len(s)]


class SpeakerEmbedder:
    def __init__(self, device: str, token: str | None) -> None:
        from audioscribe.compat import (
            apply_hf_hub_compat,
            apply_speechbrain_lazy_compat,
            apply_torch_load_compat,
        )

        apply_torch_load_compat()
        apply_hf_hub_compat()
        apply_speechbrain_lazy_compat()

        import torch
        from pyannote.audio import Inference, Model

        model = Model.from_pretrained(EMBEDDING_MODEL, use_auth_token=token)
        if model is None:
            raise RuntimeError(f"{EMBEDDING_MODEL} nicht ladbar (HF_TOKEN prüfen)")
        self._torch = torch
        self._inference = Inference(model, window="whole")
        self._inference.to(torch.device(device))
        if device != "cpu":
            # Aufwaermen (Metal-Shader bzw. CUDA-Kernel) jetzt im Hintergrund-Thread,
            # nicht erst beim ersten System-Abschnitt.
            try:
                self(np.zeros(int(1.5 * SAMPLE_RATE), dtype=np.float32))
            except Exception:  # noqa: BLE001 - Aufwaermen ist Zugabe
                pass

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        data = {"waveform": self._torch.from_numpy(audio[None, :]), "sample_rate": SAMPLE_RATE}
        return np.asarray(self._inference(data), dtype=np.float32).reshape(-1)


class BackgroundEmbedder:
    """Lädt den Embedder in einem Thread, damit die Aufnahme nicht auf ihn wartet.

    pyannote zieht torch-lightning und Co. mit - auf der CPU dauert das länger als alles
    andere beim Start, gebraucht wird es aber erst beim ersten fertigen Abschnitt der
    System-Spur. ``wait()`` liefert den Embedder oder ``None`` (Fehler protokolliert).
    """

    def __init__(self, load: Callable[[], Callable], log: Callable[[str], None]) -> None:
        self._load = load
        self._log = log
        self._done = threading.Event()
        self._embedder: Callable | None = None
        threading.Thread(target=self._run, name="speaker-embedder", daemon=True).start()

    def _run(self) -> None:
        started = time.monotonic()
        try:
            self._embedder = self._load()
            self._log(f"Sprecher-Modell bereit ({time.monotonic() - started:.1f} s)")
        except Exception as exc:  # noqa: BLE001 - Sprechertrennung ist Zugabe, kein Muss
            self._log(f"Sprecher-Modell nicht ladbar ({exc}) - System-Spur heißt '{GEGENSEITE}'")
        finally:
            self._done.set()

    def wait(self) -> Callable | None:
        self._done.wait()
        return self._embedder


class SpeakerLabeler:
    """Sprecher-Label je Abschnitt: Mikrofon = Ich, System = Sprecher N bzw. Gegenseite."""

    def __init__(
        self, embedder=None, clusterer: OnlineClusterer | None = None, *, pfad: Path | None = None
    ) -> None:
        self._embedder = embedder
        self._clusterer = clusterer or OnlineClusterer()
        self._last: str | None = None
        # ``pfad``: Begleitdatei mit den Zentroiden - beim Start geladen (Wiederaufnahme),
        # bei jedem neuen Sprecher und bei jedem Sichern der Sitzung geschrieben.
        self._pfad = Path(pfad) if pfad is not None else None
        if self._pfad is not None:
            self._lade()

    def sichere(self) -> None:
        """Zentroiden atomar ablegen; ohne Pfad oder ohne Sprecher passiert nichts."""
        if self._pfad is None or not len(self._clusterer):
            return
        try:
            self._pfad.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._pfad.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"version": 1, "sums": self._clusterer.zustand(), "last": self._last}),
                encoding="utf-8",
            )
            os.replace(tmp, self._pfad)
        except OSError:
            pass  # Sprechertrennung ist Zugabe - die Sitzung läuft weiter

    def _lade(self) -> None:
        try:
            data = json.loads(self._pfad.read_text(encoding="utf-8"))
            self._clusterer.setze_zustand(list(data.get("sums") or []))
            last = data.get("last")
            self._last = last if isinstance(last, str) and last else None
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def label(self, track: str, audio: np.ndarray) -> str:
        if track == "mic":
            return ICH  # braucht kein Modell - wartet also auch nie auf das Laden
        if isinstance(self._embedder, BackgroundEmbedder):
            self._embedder = self._embedder.wait()
        if self._embedder is None:
            return GEGENSEITE
        if len(audio) < MIN_EMBED_S * SAMPLE_RATE and self._last:
            return self._last
        bekannt = len(self._clusterer)
        index = self._clusterer.assign(self._embedder(audio))
        if index is None:
            return self._last or GEGENSEITE
        self._last = f"Sprecher {index + 1}"
        if len(self._clusterer) != bekannt:
            self.sichere()
        return self._last
