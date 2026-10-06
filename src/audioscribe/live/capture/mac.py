"""Aufnahme unter macOS: Mikrofon über CoreAudio (sounddevice), System-Audio über
ScreenCaptureKit. Gleiche Schnittstelle wie ``capture.wasapi.AudioCapture``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from audioscribe.live.capture import coreaudio, sck
from audioscribe.live.track import Track

# ScreenCaptureKit und sounddevice liefern stetig (auch Stille) - weniger Puffer nötig
# als bei WASAPI-Loopback, das in der Stille schweigt.
SLACK_S = 0.15


def list_devices() -> dict:
    out = {"mics": [], "loopbacks": []}
    out["mics"] = coreaudio.list_mics()
    if sck.is_supported():
        out["loopbacks"] = [dict(sck.LOOPBACK_ENTRY)]
    return out


class MacCapture:
    def __init__(
        self, clock: Callable[[], float], log: Callable[[str], None] | None = None, *, start_sample: int = 0
    ) -> None:
        self._clock = clock
        self._start_sample = start_sample
        self._log = log or (lambda _text: None)
        self._streams: list = []
        self._tracks: list[Track] = []
        geraete = list_devices()
        self.mics = geraete["mics"]
        self.loopbacks = geraete["loopbacks"]

    def open(self, name: str, device: dict, wav_path: Path) -> Track:
        track = Track(
            name, device["rate"], device["channels"], wav_path, slack_s=SLACK_S, start_sample=self._start_sample
        )
        if name == "system":
            self._streams.append(sck.SckStream(track, self._clock, self._log))
        else:
            self._streams.append(coreaudio.MicStream(track, device, self._clock, self._log))
        self._tracks.append(track)
        return track

    def close(self) -> None:
        for stream in self._streams:
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - beim Aufräumen nie scheitern
                pass
        self._streams = []
        for track in self._tracks:
            track.close()
