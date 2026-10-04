"""Whisper über MLX (Apple Silicon, Metal) als Live-Backend - FR-52.

CTranslate2 (faster-whisper) kennt kein Metal; auf dem Mac liefe ``large-v3-turbo`` damit
nur auf der CPU und wäre nicht live-tauglich. ``mlx_whisper`` rechnet auf der GPU mit
14-37x Echtzeit. Unterschiede zu faster-whisper, die hier ausgeglichen werden:

- kein Beam-Search (``beam_size`` wirft ``NotImplementedError``): fertige Abschnitte
  bekommen stattdessen den Temperatur-Fallback mit ``best_of``-Sampling;
- Modellnamen sind Hugging-Face-Repos (``mlx-community/whisper-*``), hier gemappt;
- das Modell wird je Aufruf am Pfad gecacht (``ModelHolder``) - darum immer derselbe
  lokale Snapshot-Pfad, und ein Aufwärmen im Konstruktor kompiliert die Metal-Kernel.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np

from audioscribe.live.asr import Ergebnis, SegmentInfo
from audioscribe.live.track import SAMPLE_RATE
from audioscribe.pipeline.models import fetch_mlx_model

MLX_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def mlx_repo(model: str, override: str | None = None) -> str:
    """Whisper-Name -> mlx-community-Repo; ``org/name`` und Ordner gehen unverändert durch."""
    if override:
        return override
    if "/" in model or os.path.isdir(model):
        return model
    try:
        return MLX_REPOS[model]
    except KeyError:
        raise RuntimeError(
            f"Kein MLX-Modell für '{model}' bekannt ({', '.join(MLX_REPOS)}); alternativ ein "
            "Hugging-Face-Repo 'org/name' angeben oder AUDIOSCRIBE_MLX_REPO setzen"
        ) from None


def mlx_decode_options(*, final: bool, eco: bool = False) -> dict:
    """Dekodier-Parameter je Auftragsart - Gegenstück zu ``asr.decode_options``.

    Fertige Abschnitte: Temperatur-Fallback (0, 0.2, 0.4) mit ``best_of`` 5 und den
    Qualitätsschwellen; Vorschau und Aufholmodus (``eco``): reines Greedy ohne Fallback.
    NIE ``beam_size`` - das ist in mlx-whisper nicht implementiert.
    """
    cheap = not final or eco
    return {
        "temperature": 0.0 if cheap else (0.0, 0.2, 0.4),
        "best_of": None if cheap else 5,  # wirkt nur bei temperature > 0
        # Jeder Abschnitt steht für sich: Vortext schleppt Fehler (und Halluzinationen) mit.
        "condition_on_previous_text": False,
        "word_timestamps": False,
        "fp16": True,
        "verbose": None,
        "compression_ratio_threshold": None if cheap else 2.4,
        "logprob_threshold": None if cheap else -1.0,
        "no_speech_threshold": 0.6,
    }


def ergebnis_aus(out: dict) -> Ergebnis:
    """mlx-whisper-Resultat -> ``Ergebnis`` mit denselben Qualitätswerten wie faster-whisper."""
    segs = [s for s in (out.get("segments") or []) if str(s.get("text", "")).strip()]
    text = " ".join(str(s["text"]).strip() for s in segs).strip()
    return Ergebnis(
        text,
        tuple(
            SegmentInfo(
                avg_logprob=round(float(s.get("avg_logprob", 0.0)), 3),
                compression_ratio=round(float(s.get("compression_ratio", 0.0)), 3),
                no_speech_prob=round(float(s.get("no_speech_prob", 0.0)), 3),
                temperature=float(s.get("temperature", 0.0)),
            )
            for s in segs
        ),
    )


class MlxTranscriber:
    def __init__(
        self,
        model: str,
        language: str,
        on_progress: Callable[[int, int], None] | None = None,
        repo_override: str | None = None,
    ) -> None:
        try:
            import mlx_whisper
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper fehlt -> 'uv sync --extra cpu --extra mac --extra live' "
                "(oder --backend faster-whisper)"
            ) from exc
        self._mlx = mlx_whisper
        self.model = model
        self.language = None if language.lower() == "auto" else language
        self.detected = self.language or ""
        self.repo = mlx_repo(model, repo_override)
        self.path = fetch_mlx_model(self.repo, on_progress)
        # Aufwärmen: Modell laden und Metal-Kernel kompilieren - nicht erst beim ersten Abschnitt.
        self._mlx.transcribe(
            np.zeros(SAMPLE_RATE, dtype=np.float32),
            path_or_hf_repo=self.path,
            language=self.language or "de",
            **mlx_decode_options(final=False),
        )

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        final: bool,
        eco: bool = False,
        initial_prompt: str | None = None,
    ) -> Ergebnis:
        out = self._mlx.transcribe(
            np.asarray(audio, dtype=np.float32),
            path_or_hf_repo=self.path,
            language=self.language,
            initial_prompt=initial_prompt,
            **mlx_decode_options(final=final, eco=eco),
        )
        erg = ergebnis_aus(out)
        if final and not self.detected:
            self.detected = str(out.get("language") or "")
        return erg


def free_mlx_model() -> None:
    """Modell-Cache von mlx-whisper leeren (Platz für wav2vec2 und pyannote beim Nachschärfen)."""
    try:
        import mlx.core as mx
        from mlx_whisper import transcribe as t

        holder = getattr(t, "ModelHolder", None)
        if holder is not None:
            holder.model = None
            holder.model_path = None
        mx.clear_cache()
    except Exception:  # noqa: BLE001 - best effort
        pass
