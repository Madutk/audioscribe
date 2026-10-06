"""WAV-Replay: eine Aufnahme durch die Live-Pipeline schicken, als käme sie gerade rein (FR-49).

Dieselbe Schnittstelle wie ``devices.AudioCapture`` (``mics``, ``loopbacks``, ``open``,
``close``), aber ohne Audio-Hardware - läuft auf Windows und Linux. Ein Feeder-Thread je
Datei schiebt 100-ms-Blöcke zur Sollzeit in den ``Track``; die Sitzungsuhr darf schneller
laufen (``speed``), der Feeder wartet dann entsprechend kürzer. Nach dem letzten Block
plus Nachlauf (damit der Schnitt die Schlusspause sieht) endet die Sitzung von selbst.

Damit lassen sich Modell- und Schnitt-Varianten reproduzierbar gegen eine Referenz messen,
ohne das Video jedes Mal abzuspielen.
"""

from __future__ import annotations

import threading
import wave
from collections.abc import Callable
from pathlib import Path

from audioscribe.live.track import SAMPLE_RATE, Track

BLOCK_S = 0.1  # wie der PortAudio-Callback: rate // 10 Frames je Block
NACHLAUF_S = 2.0  # Stille nach dem Dateiende, bis die Sitzung stoppt (> pause_s + Poll-Raster)


class ReplayCapture:
    """Spielt WAV-Dateien als System- und/oder Mikrofon-Spur auf der Sitzungsuhr ab."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        system: Path | None,
        mic: Path | None,
        speed: float = 1.0,
        on_end: Callable[[], None],
        nachlauf_s: float = NACHLAUF_S,
        start_sample: int = 0,
    ) -> None:
        if speed <= 0:
            raise RuntimeError("--speed muss größer als 0 sein")
        self._clock = clock
        self._speed = speed
        self._on_end = on_end
        self._nachlauf = nachlauf_s
        # Wiederaufnahme (PRD §21): die Datei beginnt auf der Sitzungsuhr bei diesem Versatz.
        self._start_sample = max(0, int(start_sample))
        self._basis_s = self._start_sample / SAMPLE_RATE
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._tracks: list[Track] = []
        self._files: dict[str, Path] = {}
        self._offen = 0  # Feeder, die noch laufen
        self._dauer_max = 0.0
        self.mics: list[dict] = []
        self.loopbacks: list[dict] = []
        for name, path, liste in (("mic", mic, self.mics), ("system", system, self.loopbacks)):
            if path is None:
                continue
            info = _wav_info(Path(path))
            self._files[name] = Path(path)
            liste.append({"index": 0, "name": f"Replay {Path(path).name}", "default": True, **info})

    def open(self, name: str, device: dict, wav_path: Path) -> Track:  # noqa: ARG002 - wie AudioCapture
        path = self._files[name]
        track = Track(name, device["rate"], device["channels"], wav_path, start_sample=self._start_sample)
        with self._lock:
            self._offen += 1
            self._dauer_max = max(self._dauer_max, device["dauer_s"])
        thread = threading.Thread(
            target=self._feed, args=(track, path, device), name=f"replay-{name}", daemon=True
        )
        self._threads.append(thread)
        self._tracks.append(track)
        thread.start()
        return track

    def close(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []
        for track in self._tracks:
            track.close()

    # --- intern ------------------------------------------------------------------

    def _warte_bis(self, t_soll: float) -> bool:
        """Wartet auf der Sitzungsuhr bis ``t_soll``; False, wenn vorher gestoppt wurde."""
        while not self._stop.is_set():
            rest = t_soll - self._clock()
            if rest <= 0:
                return True
            self._stop.wait(min(rest / self._speed, 0.5))
        return False

    def _feed(self, track: Track, path: Path, device: dict) -> None:
        frames_je_block = max(1, int(device["rate"] * BLOCK_S))
        with wave.open(str(path), "rb") as wav:
            i = 0
            while not self._stop.is_set():
                raw = wav.readframes(frames_je_block)
                if not raw:
                    break
                i += 1
                # Ankunft am Blockende, wie beim echten Callback.
                if not self._warte_bis(self._basis_s + i * BLOCK_S):
                    return
                track.feed(raw, self._basis_s + i * BLOCK_S)
        with self._lock:
            self._offen -= 1
            letzter = self._offen == 0
        if letzter and self._warte_bis(self._basis_s + self._dauer_max + self._nachlauf):
            self._on_end()


def _wav_info(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"WAV nicht gefunden: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise RuntimeError(f"{path.name}: nur 16-Bit-PCM (int16) wird abgespielt")
            rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
    except wave.Error as exc:
        raise RuntimeError(f"{path.name}: keine lesbare WAV-Datei ({exc})") from exc
    return {"rate": rate, "channels": channels, "dauer_s": frames / rate if rate else 0.0}
