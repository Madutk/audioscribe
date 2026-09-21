"""Sprecher der System-Spur live unterscheiden: Stimm-Embedding + Online-Clustering.

Die Offline-Diarisierung sieht die ganze Aufnahme und nummeriert je Lauf neu - beides
geht live nicht. Hier bekommt jeder Abschnitt ein Embedding und wird dem ähnlichsten
laufenden Zentroiden zugeordnet; so bleibt "Sprecher 2" über die Sitzung derselbe.
"""

from __future__ import annotations

import numpy as np

from audioscribe.live.track import SAMPLE_RATE

EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"

ICH = "Ich"
GEGENSEITE = "Gegenseite"

# Unter dieser Länge ist ein Embedding Rauschen; der Abschnitt erbt den letzten Sprecher.
MIN_EMBED_S = 1.5


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

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        data = {"waveform": self._torch.from_numpy(audio[None, :]), "sample_rate": SAMPLE_RATE}
        return np.asarray(self._inference(data), dtype=np.float32).reshape(-1)


class SpeakerLabeler:
    """Sprecher-Label je Abschnitt: Mikrofon = Ich, System = Sprecher N bzw. Gegenseite."""

    def __init__(self, embedder=None, clusterer: OnlineClusterer | None = None) -> None:
        self._embedder = embedder
        self._clusterer = clusterer or OnlineClusterer()
        self._last: str | None = None

    def label(self, track: str, audio: np.ndarray) -> str:
        if track == "mic":
            return ICH
        if self._embedder is None:
            return GEGENSEITE
        if len(audio) < MIN_EMBED_S * SAMPLE_RATE and self._last:
            return self._last
        index = self._clusterer.assign(self._embedder(audio))
        if index is None:
            return self._last or GEGENSEITE
        self._last = f"Sprecher {index + 1}"
        return self._last
