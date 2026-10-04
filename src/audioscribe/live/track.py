"""Eine Audioquelle als lückenlose 16-kHz-Mono-Zeitleiste (rein, ohne Audio-Hardware).

Die Zeitleiste hängt an der Sitzungsuhr, nicht an der Zahl gelieferter Samples:
WASAPI-Loopback liefert bei Stille KEINE Pakete. Ohne Auffüllen läge Sekunde 600 des
Gesprächs nach zehn stillen Minuten bei Sekunde 0 der Spur, und ein offener
Sprechabschnitt bekäme nie die Stille zu sehen, die ihn beendet.
"""

from __future__ import annotations

import threading
import wave
from math import gcd
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000

# Erst ab dieser Lücke wird aufgefüllt; darunter liegt normale Puffer-Latenz.
_GAP_MIN_S = 0.25
# So weit hinter "jetzt" darf die Spur liegen, bevor take() von Stille ausgeht.
_TAKE_SLACK_S = 0.3


class Resampler:
    """Blockweises Resampling ohne Nahtstellen.

    ``resample_poly`` nimmt an den Blockrändern Nullen an; bei zehn Blöcken je Sekunde
    gäbe das ein 10-Hz-Knacken. Darum läuft je Seite ein kleiner Kontext mit, der aus der
    Ausgabe wieder herausgeschnitten wird (Preis: 2 ms Latenz).
    """

    def __init__(self, rate_in: int, rate_out: int = SAMPLE_RATE) -> None:
        g = gcd(int(rate_in), int(rate_out))
        self.up = int(rate_out) // g
        self.down = int(rate_in) // g
        self._ctx = 32 * self.down
        self._buf = np.zeros(self._ctx, dtype=np.float32)
        # Hier laden, nicht erst in process(): das läuft im Audio-Callback, und ein
        # DLL-Import dort verklemmt sich unter Windows mit Importen anderer Threads
        # (onnxruntime der VAD) - die Spur bliebe für immer stumm.
        self._poly = None
        if self.up != self.down:
            from scipy.signal import resample_poly

            self._poly = resample_poly

    def process(self, x: np.ndarray) -> np.ndarray:
        if self._poly is None:
            return x.astype(np.float32, copy=False)

        self._buf = np.concatenate([self._buf, x.astype(np.float32, copy=False)])
        payload = ((len(self._buf) - 2 * self._ctx) // self.down) * self.down
        if payload <= 0:
            return np.zeros(0, dtype=np.float32)
        y = self._poly(self._buf[: payload + 2 * self._ctx], self.up, self.down)
        head = self._ctx * self.up // self.down
        out = y[head : head + payload * self.up // self.down]
        self._buf = self._buf[payload:]
        return out.astype(np.float32)


class Track:
    """Nimmt Rohblöcke einer Quelle an und führt die 16-kHz-Zeitleiste samt WAV-Mitschnitt."""

    def __init__(
        self,
        name: str,
        rate_in: int,
        channels: int,
        wav_path: Path | None = None,
        *,
        slack_s: float = _TAKE_SLACK_S,
    ) -> None:
        self.name = name
        self.channels = max(1, int(channels))
        self.written = 0  # Samples auf der Zeitleiste
        self.level = 0.0  # Spitzenpegel des letzten Blocks (0..1)
        self._slack_s = slack_s
        self._resampler = Resampler(rate_in)
        self._lock = threading.Lock()
        self._pending: list[np.ndarray] = []
        self._pending_start = 0
        self._wav: wave.Wave_write | None = None
        if wav_path is not None:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            self._wav = wave.open(str(wav_path), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(SAMPLE_RATE)

    def reset_rate(self, rate_in: int) -> None:
        """Eingangsrate nachträglich ändern (Gerät nahm die Wunschrate nicht an); vor dem ersten Block."""
        with self._lock:
            self._resampler = Resampler(rate_in)

    def feed(self, raw: bytes, t_arrival: float) -> None:
        """Rohblock (int16, interleaved), eingetroffen zur Sitzungszeit ``t_arrival``."""
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if self.channels > 1:
            x = x[: len(x) - len(x) % self.channels].reshape(-1, self.channels).mean(axis=1)
        self.feed_mono(x, t_arrival)

    def feed_mono(self, mono: np.ndarray, t_arrival: float) -> None:
        """Block als float32 mono mit Eingangsrate (ScreenCaptureKit liefert Float32, kein int16)."""
        y = self._resampler.process(np.asarray(mono, dtype=np.float32))
        if not len(y):
            return
        with self._lock:
            self.level = float(np.abs(y).max())
            self._fill_to(int(t_arrival * SAMPLE_RATE) - len(y))
            self._append(y)

    def take(self, t_now: float) -> tuple[int, np.ndarray]:
        """Alle neuen Samples seit dem letzten Aufruf als ``(startsample, samples)``."""
        with self._lock:
            self._fill_to(int((t_now - self._slack_s) * SAMPLE_RATE))
            start = self._pending_start
            if self._pending:
                samples = np.concatenate(self._pending)
            else:
                samples = np.zeros(0, dtype=np.float32)
            self._pending = []
            self._pending_start = self.written
            return start, samples

    def close(self) -> None:
        with self._lock:
            if self._wav is not None:
                self._wav.close()
                self._wav = None

    def _fill_to(self, position: int) -> None:
        """Aufrufer hält den Lock."""
        gap = position - self.written
        if gap > _GAP_MIN_S * SAMPLE_RATE:
            self._append(np.zeros(gap, dtype=np.float32))
            self.level = 0.0

    def _append(self, y: np.ndarray) -> None:
        """Aufrufer hält den Lock."""
        self._pending.append(y)
        self.written += len(y)
        if self._wav is not None:
            self._wav.writeframes((np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())


def load_wav(path: Path) -> np.ndarray:
    """Liest einen Mitschnitt als float32 - auch nach einem Absturz.

    ``wave`` trägt die Länge erst beim Schließen in den Kopf ein. Nach einem Absturz steht
    dort 0, die Daten liegen aber vollständig dahinter.
    """
    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
    if not frames:
        frames = Path(path).read_bytes()[44:]
    frames = frames[: len(frames) - len(frames) % 2]
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
