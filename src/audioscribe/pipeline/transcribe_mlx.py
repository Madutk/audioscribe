"""Stufe 2 auf Apple Silicon: Transkription ueber mlx-whisper statt WhisperX (FR-52).

WhisperX zerlegt die Aufnahme per VAD in Fenster bis 30 s und dekodiert sie gestapelt mit
faster-whisper. Auf dem Mac rechnet faster-whisper nur auf der CPU (CTranslate2 ohne Metal) -
eine Stunde Audio dauerte mit ``large-v3`` laenger als eine Stunde. Hier dieselbe
Fensterlogik, dekodiert mit MLX auf der GPU; das Ergebnis hat das WhisperX-Format
(``{"segments": [{start, end, text}], "language"}``), damit Alignment und Diarisierung
unveraendert weiterarbeiten.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from audioscribe.config import settings
from audioscribe.live.asr_mlx import free_mlx_model, mlx_repo
from audioscribe.pipeline.models import fetch_mlx_model
from audioscribe.progress import Reporter, emit_download, emit_progress

SAMPLE_RATE = 16_000
WINDOW_S = 30.0  # Whisper-Fenster
PAD_S = 0.3  # Rand um jede Sprachspanne


SUCH_S = 5.0  # so weit vor der Fenstergrenze wird nach der leisesten Stelle gesucht
_SUCH_RASTER_S = 0.05


def _leiseste_stelle(audio: np.ndarray, von: int, bis: int, rate: int) -> int:
    """Mitte des energieaermsten 50-ms-Rasters in ``audio[von:bis]`` (rein, testbar)."""
    raster = max(1, int(_SUCH_RASTER_S * rate))
    n = (bis - von) // raster
    if n < 1:
        return bis
    stueck = audio[von : von + n * raster].astype(np.float32).reshape(n, raster)
    i = int(np.argmin((stueck * stueck).mean(axis=1)))
    return von + i * raster + raster // 2


def speech_windows(
    spans: list[tuple[int, int]],
    total: int,
    *,
    max_s: float = WINDOW_S,
    pad_s: float = PAD_S,
    rate: int = SAMPLE_RATE,
    audio: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    """VAD-Spannen (Samples) -> Fenster bis ``max_s`` fuer je einen Whisper-Aufruf (rein, testbar).

    Benachbarte Spannen werden zusammengefasst, solange das Fenster unter ``max_s`` bleibt;
    eine einzelne zu lange Spanne wird in Stuecke von hoechstens ``max_s`` geschnitten.
    Ohne Spannen: leer (stilles Audio -> leeres Transkript).

    Fenster ueberlappen nie: die Polsterung einer neuen Spanne endet am Ende des vorigen
    Fensters - sonst stuenden die Randwoerter doppelt im Transkript. Ist ``audio``
    gegeben, wird eine zu lange Spanne an der leisesten Stelle der letzten ``SUCH_S``
    Sekunden geschnitten statt hart nach ``max_s`` mitten im Wort.
    """
    max_n = int(max_s * rate)
    pad = int(pad_s * rate)
    out: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for a, b in sorted(spans):
        a, b = max(0, a - pad), min(total, b + pad)
        if cur is not None:
            if b <= cur[1]:
                continue  # liegt schon im laufenden Fenster
            if b - cur[0] <= max_n:
                cur = (cur[0], b)
                continue
            out.append(cur)
            a = max(a, cur[1])
        if b <= a:
            continue
        cur = (a, b)
    if cur is not None:
        out.append(cur)
    # Zu lange Einzelstuecke zerteilen.
    such_n = int(SUCH_S * rate)
    final: list[tuple[int, int]] = []
    for a, b in out:
        while b - a > max_n:
            schnitt = a + max_n
            if audio is not None:
                schnitt = _leiseste_stelle(audio, max(a + max_n // 2, schnitt - such_n), schnitt, rate)
            final.append((a, schnitt))
            a = schnitt
        final.append((a, b))
    return final


def _vad_spans(audio: np.ndarray) -> list[tuple[int, int]]:
    from audioscribe.live.chunker import silero_vad

    return silero_vad()(audio)


def transcribe_mlx(
    audio: np.ndarray,
    reporter: Reporter | None = None,
    *,
    model: str,
    language: str | None,
    on_progress: Callable[[int, int], None] | None = None,
    vad: Callable[[np.ndarray], list[tuple[int, int]]] | None = None,
    mlx_module=None,
) -> dict:
    """Transkribiert das Audio-Array ueber MLX und liefert das WhisperX-Result-Dict."""
    if mlx_module is None:
        try:
            import mlx_whisper as mlx_module
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper fehlt -> 'uv sync --extra cpu --extra mac --extra live' "
                "(oder AUDIOSCRIBE_ASR_BACKEND=faster-whisper)"
            ) from exc

    audio = np.asarray(audio, dtype=np.float32)
    if reporter:
        reporter.info("Modell wird geladen (MLX) ...")
    progress = on_progress or (emit_download if settings.emit_progress else None)
    path = fetch_mlx_model(mlx_repo(model, settings.mlx_repo or None), progress)

    spans = (vad or _vad_spans)(audio) if len(audio) else []
    windows = speech_windows(spans, len(audio), audio=audio)
    if reporter:
        reporter.info(f"Transkribiere {len(windows)} Fenster ...")
    segments: list[dict] = []
    lang = language
    try:
        for i, (a, b) in enumerate(windows):
            out = mlx_module.transcribe(
                audio[a:b],
                path_or_hf_repo=path,
                language=lang,
                temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                best_of=5,
                condition_on_previous_text=False,
                fp16=True,
                verbose=None,
            )
            lang = lang or out.get("language")
            for seg in out.get("segments") or []:
                text = str(seg.get("text", "")).strip()
                if not text:
                    continue
                segments.append(
                    {
                        "start": round(a / SAMPLE_RATE + float(seg.get("start", 0.0)), 3),
                        "end": round(a / SAMPLE_RATE + float(seg.get("end", 0.0)), 3),
                        "text": text,
                    }
                )
            if settings.emit_progress:
                emit_progress(100.0 * (i + 1) / len(windows))
    finally:
        free_mlx_model()  # Platz fuer wav2vec2 und pyannote

    result = {"segments": segments, "language": lang or "de"}
    if reporter:
        if not windows:
            reporter.info("Keine aktive Sprache erkannt -> leeres Transkript")
        reporter.info(f"Sprache: {result['language']}, {len(segments)} Segmente")
    return result
