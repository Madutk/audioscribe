"""Schneidet eine Spur an Sprechpausen in Abschnitte (rein; die VAD wird hereingereicht)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from audioscribe.live.track import SAMPLE_RATE

# VAD: Audio -> Liste von (start, ende) in Samples, aufsteigend.
Vad = Callable[[np.ndarray], list[tuple[int, int]]]


@dataclass
class Utterance:
    start: int  # absolute Samples auf der Zeitleiste der Spur
    end: int
    audio: np.ndarray

    @property
    def start_s(self) -> float:
        return self.start / SAMPLE_RATE

    @property
    def end_s(self) -> float:
        return self.end / SAMPLE_RATE

    @property
    def duration_s(self) -> float:
        return (self.end - self.start) / SAMPLE_RATE


def silero_vad() -> Vad:
    """Silero-VAD aus faster-whisper (ONNX, läuft auf der CPU)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    # Polsterung 0: gepolstert wird beim Ausschneiden, sonst stimmen die Pausen nicht.
    options = VadOptions(
        threshold=0.5, min_speech_duration_ms=200, min_silence_duration_ms=300, speech_pad_ms=0
    )

    def vad(audio: np.ndarray) -> list[tuple[int, int]]:
        return [(int(d["start"]), int(d["end"])) for d in get_speech_timestamps(audio, options)]

    # Einmal vorab: onnxruntime lädt erst beim ersten Aufruf, und das soll nicht mitten
    # in die laufende Aufnahme fallen.
    vad(np.zeros(SAMPLE_RATE, dtype=np.float32))
    return vad


class Chunker:
    def __init__(
        self,
        vad: Vad,
        *,
        pause_s: float = 0.6,
        max_s: float = 12.0,
        pad_s: float = 0.15,
        keep_s: float = 0.5,
    ) -> None:
        self._vad = vad
        self._pause = int(pause_s * SAMPLE_RATE)
        self._max = int(max_s * SAMPLE_RATE)
        self._pad = int(pad_s * SAMPLE_RATE)
        self._keep = int(keep_s * SAMPLE_RATE)
        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_start = 0
        self._open: int | None = None  # Pufferposition des offenen Abschnitts

    def feed(self, start: int, samples: np.ndarray) -> None:
        if not len(samples):
            return
        gap = start - (self._buf_start + len(self._buf))
        if gap > 0:
            self._buf = np.concatenate([self._buf, np.zeros(gap, dtype=np.float32)])
        self._buf = np.concatenate([self._buf, samples])

    def poll(self, *, flush: bool = False) -> list[Utterance]:
        """Abgeschlossene Abschnitte; ``flush`` schließt auch den noch offenen."""
        self._open = None
        if len(self._buf) < SAMPLE_RATE // 4:
            return []
        speech = self._vad(self._buf)
        done: list[Utterance] = []
        consumed = 0
        groups = self._groups(speech)
        for i, (g_start, g_end, gaps) in enumerate(groups):
            is_last = i == len(groups) - 1
            if not is_last or flush or len(self._buf) - g_end >= self._pause:
                done.append(self._cut(g_start, g_end))
                consumed = g_end
            elif g_end - g_start >= self._max:
                cut = self._forced_cut(g_start, gaps)
                done.append(self._cut(g_start, cut))
                consumed = cut
                self._open = cut
            else:
                self._open = g_start

        if self._open is not None:
            drop = max(consumed, self._open - self._pad)
        else:
            drop = max(consumed, len(self._buf) - self._keep)
        if drop > 0:
            self._buf = self._buf[drop:]
            self._buf_start += drop
            if self._open is not None:
                self._open -= drop
        return done

    def open_utterance(self) -> Utterance | None:
        """Der gerade gesprochene, noch nicht abgeschlossene Abschnitt (Stand des letzten poll)."""
        if self._open is None:
            return None
        start = max(0, self._open - self._pad)
        return Utterance(
            self._buf_start + self._open, self._buf_start + len(self._buf), self._buf[start:].copy()
        )

    def _groups(self, speech: list[tuple[int, int]]) -> list[tuple[int, int, list[tuple[int, int]]]]:
        """Fasst VAD-Stücke zusammen, die weniger als eine Pause auseinanderliegen."""
        groups: list[tuple[int, int, list[tuple[int, int]]]] = []
        for start, end in speech:
            if groups and start - groups[-1][1] < self._pause:
                g_start, g_end, gaps = groups[-1]
                groups[-1] = (g_start, end, [*gaps, (g_end, start)])
            else:
                groups.append((start, end, []))
        return groups

    def _forced_cut(self, g_start: int, gaps: list[tuple[int, int]]) -> int:
        """Schnittpunkt für überlange Abschnitte: die größte Atempause der zweiten Hälfte."""
        limit = g_start + self._max
        usable = [(b - a, (a + b) // 2) for a, b in gaps if g_start + self._max // 2 <= a and b <= limit]
        return max(usable)[1] if usable else limit

    def _cut(self, start: int, end: int) -> Utterance:
        a = max(0, start - self._pad)
        b = min(len(self._buf), end + self._pad)
        return Utterance(self._buf_start + start, self._buf_start + end, self._buf[a:b].copy())
