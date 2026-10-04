"""Mikrofon unter macOS über ``sounddevice`` (PortAudio, im Wheel gebündelt).

PortAudio kennt auf dem Mac kein Loopback - das System-Audio kommt aus ``capture.sck``.
Hier nur Eingabegeräte des Core-Audio-Host-API, gelesen als int16 mit der nativen Rate;
Downmix und 16 kHz macht ``Track``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from audioscribe.live.track import Track

INSTALL_HINT = "uv sync --extra cpu --extra mac --extra review --extra live"
_RETRY_RATES = (48_000, 44_100, 16_000)


def _sounddevice():
    try:
        import sounddevice
    except ImportError as exc:
        raise RuntimeError(f"sounddevice fehlt -> {INSTALL_HINT}") from exc
    return sounddevice


def mic_entries(devices: list[dict], default_index: int | None, hostapis: list[dict] | None = None) -> list[dict]:
    """Geräteliste von ``sounddevice.query_devices()`` -> unsere Einträge (rein, testbar).

    Nur Eingabegeräte; mit ``hostapis`` nur die des Core-Audio-Host-API (andere gibt es
    auf dem Mac normalerweise nicht, aber sicher ist sicher).
    """
    core = None
    if hostapis:
        for i, api in enumerate(hostapis):
            if "core audio" in str(api.get("name", "")).lower():
                core = i
    out: list[dict] = []
    for i, dev in enumerate(devices):
        if int(dev.get("max_input_channels", 0)) <= 0:
            continue
        if core is not None and dev.get("hostapi") is not None and dev.get("hostapi") != core:
            continue
        out.append(
            {
                "index": i,
                "name": str(dev.get("name", f"Gerät {i}")),
                "rate": int(round(float(dev.get("default_samplerate", 48_000)))),
                "channels": int(dev.get("max_input_channels", 1)),
                "default": i == default_index,
            }
        )
    if out and not any(d["default"] for d in out):
        out[0]["default"] = True
    return out


def list_mics() -> list[dict]:
    sd = _sounddevice()
    devices = [dict(d) for d in sd.query_devices()]
    try:
        hostapis = [dict(a) for a in sd.query_hostapis()]
    except Exception:  # noqa: BLE001
        hostapis = None
    default = sd.default.device
    default_in = default[0] if isinstance(default, (tuple, list)) else default
    return mic_entries(devices, int(default_in) if default_in is not None and default_in >= 0 else None, hostapis)


class MicStream:
    """Ein offener Eingabestream; ``callback`` füttert den Track mit int16-Blöcken."""

    def __init__(self, track: Track, device: dict, clock: Callable[[], float], log: Callable[[str], None] | None = None) -> None:
        sd = _sounddevice()
        self._track = track
        self._stream = None
        channels = max(1, int(device["channels"]))

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            track.feed(bytes(indata), clock())

        letzter: Exception | None = None
        for rate in (int(device["rate"]), *_RETRY_RATES):
            # Vor dem Start: sonst laufen die ersten Callbacks noch durch den Resampler
            # der alten Rate. Es kam noch kein Block, das Zurücksetzen kostet nichts.
            track.reset_rate(rate)
            stream = None
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=channels,
                    dtype="int16",
                    device=device["index"],
                    blocksize=max(1, rate // 10),
                    callback=callback,
                )
                stream.start()
            except Exception as exc:  # noqa: BLE001 - z. B. PortAudioError bei fremder Rate
                letzter = exc
                if stream is not None:  # geöffnet, aber start() scheiterte
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass
                continue
            if rate != int(device["rate"]):
                if log:
                    log(f"Mikrofon: {device['rate']} Hz nicht möglich, nehme {rate} Hz")
            self._stream = stream
            return
        raise RuntimeError(f"Mikrofon '{device['name']}' lässt sich nicht öffnen ({letzter})")

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001 - beim Aufräumen nie scheitern
                pass
            self._stream = None
