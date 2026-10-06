"""Audio-Aufnahme über WASAPI: Mikrofon und Loopback des Ausgabegeräts (nur Windows).

PyAudioWPatch ist ein PyAudio-Fork, der WASAPI-Loopback als Eingabegerät anbietet - das
offizielle PortAudio/sounddevice kann das nicht.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from audioscribe.live.track import Track

INSTALL_HINT = "uv sync --extra <cu124|cpu> --extra review --extra live"


def _pyaudio():
    if sys.platform != "win32":
        raise RuntimeError(
            "Live-Aufnahme braucht natives Windows (WASAPI); unter WSL/Linux nicht verfügbar."
        )
    try:
        import pyaudiowpatch
    except ImportError as exc:
        raise RuntimeError(f"PyAudioWPatch fehlt -> {INSTALL_HINT}") from exc
    return pyaudiowpatch


def _scan(pa, p) -> tuple[list[dict], list[dict]]:
    wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
    default_in = wasapi.get("defaultInputDevice", -1)
    default_out = wasapi.get("defaultOutputDevice", -1)
    out_name = p.get_device_info_by_index(default_out)["name"] if default_out >= 0 else ""

    mics, loopbacks = [], []
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev["hostApi"] != wasapi["index"] or dev["maxInputChannels"] <= 0:
            continue
        entry = {
            "index": dev["index"],
            "name": dev["name"],
            "rate": int(dev["defaultSampleRate"]),
            "channels": int(dev["maxInputChannels"]),
        }
        if dev.get("isLoopbackDevice"):
            # Das Loopback-Gerät heißt wie sein Ausgabegerät plus "[Loopback]".
            entry["default"] = bool(out_name) and out_name in dev["name"]
            loopbacks.append(entry)
        else:
            entry["default"] = dev["index"] == default_in
            mics.append(entry)
    return mics, loopbacks


def list_devices() -> dict:
    pa = _pyaudio()
    p = pa.PyAudio()
    try:
        mics, loopbacks = _scan(pa, p)
    finally:
        p.terminate()
    return {"mics": mics, "loopbacks": loopbacks}


class AudioCapture:
    """Hält die offenen Eingabe-Streams einer Sitzung."""

    def __init__(self, clock: Callable[[], float], *, start_sample: int = 0) -> None:
        self._pa = _pyaudio()
        self._p = self._pa.PyAudio()
        self._clock = clock
        self._start_sample = start_sample
        self._streams: list = []
        self._tracks: list[Track] = []
        self.mics, self.loopbacks = _scan(self._pa, self._p)

    def open(self, name: str, device: dict, wav_path: Path) -> Track:
        track = Track(name, device["rate"], device["channels"], wav_path, start_sample=self._start_sample)
        pa = self._pa

        def callback(in_data, frame_count, time_info, status):  # noqa: ARG001
            track.feed(in_data, self._clock())
            return (None, pa.paContinue)

        # WASAPI im Shared Mode nimmt nur das Mix-Format des Geräts an (Rate und Kanäle);
        # heruntergemischt und auf 16 kHz gebracht wird in Track.
        self._streams.append(
            self._p.open(
                format=pa.paInt16,
                channels=device["channels"],
                rate=device["rate"],
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=device["rate"] // 10,
                stream_callback=callback,
            )
        )
        self._tracks.append(track)
        return track

    def close(self) -> None:
        for stream in self._streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # noqa: BLE001 - beim Aufräumen nie scheitern
                pass
        self._streams = []
        for track in self._tracks:
            track.close()
        self._p.terminate()
