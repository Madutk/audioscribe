"""System-Audio unter macOS über ScreenCaptureKit - ohne Treiber, rein über PyObjC (FR-51).

CoreAudio/PortAudio kennt auf dem Mac kein Loopback. ScreenCaptureKit (macOS 13+) liefert
den gemischten Ton aller Apps als Nebenprodukt einer Bildschirmaufnahme: wir nehmen den
Hauptbildschirm mit 2x2 Pixeln bei einem Bild je Sekunde auf, werten nur die Audiopuffer
aus (Float32, 48 kHz, zwei Kanäle, meist planar) und mischen sie nach mono. Dafür braucht
die startende App (Terminal, iTerm, ...) die Berechtigung "Bildschirmaufnahme".

Alle Framework-Importe stehen in Funktionen: das Modul ist überall importierbar, die reinen
Teile (``pcm_to_mono``, ``LOOPBACK_ENTRY``) sind unter Linux testbar.

Spike auf dem Gerät: ``python -m audioscribe.live.capture.sck --probe 5`` nimmt fünf
Sekunden System-Audio nach ``/tmp/sck.wav`` auf und meldet das Format.
"""

from __future__ import annotations

import functools
import platform
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from audioscribe.live.track import Track

SAMPLE_RATE_SCK = 48_000
CHANNELS_SCK = 2
STARTUP_TIMEOUT_S = 10.0
# Ohne Audiopuffer binnen dieser Zeit stimmt etwas nicht (Berechtigung, kein Ausgang).
SILENT_START_S = 3.0

# kAudioFormatFlagIsNonInterleaved (CoreAudioTypes.h)
_FLAG_NON_INTERLEAVED = 1 << 5

LOOPBACK_ENTRY = {
    "index": -1,
    "name": "System-Audio (ScreenCaptureKit)",
    "rate": SAMPLE_RATE_SCK,
    "channels": CHANNELS_SCK,
    "default": True,
}


def macos_version() -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in platform.mac_ver()[0].split(".") if p.isdigit())
    except Exception:  # noqa: BLE001
        return ()


def is_supported(platform_name: str | None = None, version: tuple[int, ...] | None = None) -> bool:
    """macOS >= 13 und die PyObjC-Brücke für ScreenCaptureKit vorhanden?"""
    if (sys.platform if platform_name is None else platform_name) != "darwin":
        return False
    version = macos_version() if version is None else version
    if version and version[0] < 13:
        return False
    try:
        import importlib.util

        return importlib.util.find_spec("ScreenCaptureKit") is not None
    except Exception:  # noqa: BLE001
        return False


def pcm_to_mono(data: bytes, frames: int, channels: int, planar: bool) -> np.ndarray:
    """Float32-PCM eines Puffers -> mono float32 (rein, testbar).

    Planar heißt: erst alle Werte von Kanal 1, dann alle von Kanal 2 (CoreAudio
    ``kAudioFormatFlagIsNonInterleaved``); sonst abwechselnd L R L R.
    """
    x = np.frombuffer(data, dtype=np.float32)
    n = min(len(x), frames * channels)
    x = x[: n - n % channels] if channels > 1 else x[:n]
    if channels <= 1:
        return x.astype(np.float32, copy=True)
    frames_eff = len(x) // channels
    if planar:
        y = x.reshape(channels, frames_eff).mean(axis=0)
    else:
        y = x.reshape(frames_eff, channels).mean(axis=1)
    return y.astype(np.float32)


# --- PyObjC-Brücke -----------------------------------------------------------------


def _frameworks():
    try:
        import CoreMedia as CM
        import objc
        import ScreenCaptureKit as SCK
        from Foundation import NSObject
    except ImportError as exc:
        raise RuntimeError(
            "ScreenCaptureKit-Brücke fehlt (PyObjC) -> 'uv sync --extra cpu --extra mac --extra live'"
        ) from exc
    return SCK, CM, objc, NSObject


def _protocols(objc) -> list:
    out = []
    for name in ("SCStreamOutput", "SCStreamDelegate"):
        try:
            out.append(objc.protocolNamed(name))
        except Exception:  # noqa: BLE001 - PyObjC dispatcht auch ohne formale Protokolle
            pass
    return out


def _block_bytes(CM, block_buffer, length: int) -> bytes:
    """Rohbytes eines CMBlockBuffer - zwei PyObjC-Varianten, die erste, die geht, gewinnt."""
    try:
        status, data = CM.CMBlockBufferCopyDataBytes(block_buffer, 0, length, None)
        if status == 0 and data is not None:
            return bytes(data)
    except Exception:  # noqa: BLE001
        pass
    status, _len_at, _total, ptr = CM.CMBlockBufferGetDataPointer(block_buffer, 0, None, None, None)
    if status != 0 or ptr is None:
        raise RuntimeError(f"CMBlockBuffer nicht lesbar (Status {status})")
    try:
        return bytes(ptr.as_buffer(length))
    except AttributeError:
        return bytes(ptr)[:length]


@functools.cache
def _output_class():
    SCK, CM, objc, NSObject = _frameworks()
    audio_type = int(SCK.SCStreamOutputTypeAudio)

    class _AudioOutput(NSObject, protocols=_protocols(objc)):
        def initWithSink_(self, sink):  # noqa: N802 - Objective-C-Konvention
            self = objc.super(_AudioOutput, self).init()
            if self is None:
                return None
            self._sink = sink
            self._fmt = None
            return self

        def stream_didOutputSampleBuffer_ofType_(self, stream, sbuf, typ):  # noqa: N802, ARG002
            if int(typ) != audio_type:
                return
            try:
                if not CM.CMSampleBufferDataIsReady(sbuf):
                    return
                if self._fmt is None:
                    desc = CM.CMSampleBufferGetFormatDescription(sbuf)
                    asbd = CM.CMAudioFormatDescriptionGetStreamBasicDescription(desc)
                    channels = int(asbd.mChannelsPerFrame) or CHANNELS_SCK
                    planar = bool(int(asbd.mFormatFlags) & _FLAG_NON_INTERLEAVED)
                    self._fmt = (channels, planar, int(asbd.mSampleRate))
                    self._sink.format(*self._fmt)
                frames = int(CM.CMSampleBufferGetNumSamples(sbuf))
                bb = CM.CMSampleBufferGetDataBuffer(sbuf)
                if bb is None or frames <= 0:
                    return
                n = int(CM.CMBlockBufferGetDataLength(bb))
                data = _block_bytes(CM, bb, n)
                self._sink.audio(pcm_to_mono(data, frames, self._fmt[0], self._fmt[1]))
            except Exception as exc:  # noqa: BLE001 - ein kaputter Puffer darf den Stream nicht reißen
                self._sink.error(f"Audiopuffer übersprungen: {exc}")

        def stream_didStopWithError_(self, stream, error):  # noqa: N802, ARG002
            self._sink.stopped(str(error) if error is not None else "")

    return _AudioOutput


class _Sink:
    """Was der Objective-C-Delegate an Python weiterreicht (Track, Uhr, Protokoll)."""

    def __init__(self, track: Track, clock: Callable[[], float], log: Callable[[str], None]) -> None:
        self._track = track
        self._clock = clock
        self._log = log
        self.puffer = 0
        self.fehler: str | None = None
        self.gestoppt: str | None = None
        self.rate = SAMPLE_RATE_SCK

    def format(self, channels: int, planar: bool, rate: int) -> None:
        self.rate = rate or SAMPLE_RATE_SCK
        if self.rate != SAMPLE_RATE_SCK:
            self._track.reset_rate(self.rate)
        self._log(
            f"System-Audio: Float32 {'planar' if planar else 'interleaved'}, {channels} Kanäle, {self.rate} Hz"
        )

    def audio(self, mono: np.ndarray) -> None:
        self.puffer += 1
        self._track.feed_mono(mono, self._clock())

    def error(self, text: str) -> None:
        if self.fehler is None:
            self.fehler = text
            self._log(text)

    def stopped(self, text: str) -> None:
        self.gestoppt = text
        if text:
            self._log(f"System-Audio: Stream beendet ({text})")


def _wait(call, timeout_s: float = STARTUP_TIMEOUT_S):
    """Ruft ``call(handler)`` mit einem Completion-Handler und wartet auf dessen Argumente."""
    fertig = threading.Event()
    ergebnis: list = []

    def handler(*args):
        ergebnis.extend(args)
        fertig.set()

    call(handler)
    if not fertig.wait(timeout_s):
        raise RuntimeError("ScreenCaptureKit antwortet nicht (Zeitüberschreitung)")
    return ergebnis


def _shareable_content(SCK):
    content, error = (_wait(SCK.SCShareableContent.getShareableContentWithCompletionHandler_) + [None, None])[:2]
    if content is None:
        raise RuntimeError(
            "ScreenCaptureKit: keine freigegebenen Inhalte - Bildschirmaufnahme in den "
            f"Systemeinstellungen erlauben und die App neu starten ({error})"
        )
    return content


def _queue():
    try:
        from libdispatch import dispatch_queue_create

        return dispatch_queue_create(b"audioscribe.sck", None)
    except Exception:  # noqa: BLE001 - SCK nimmt dann seine eigene Queue
        return None


class SckStream:
    """Ein laufender ScreenCaptureKit-Stream, der nur Audio in den ``Track`` schreibt."""

    def __init__(self, track: Track, clock: Callable[[], float], log: Callable[[str], None]) -> None:
        SCK, CM, _objc, _ns = _frameworks()
        self._sink = _Sink(track, clock, log)
        self._log = log
        content = _shareable_content(SCK)
        displays = list(content.displays() or [])
        if not displays:
            raise RuntimeError("ScreenCaptureKit: kein Bildschirm gefunden")
        filt = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(displays[0], [])
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setCapturesAudio_(True)
        cfg.setExcludesCurrentProcessAudio_(True)
        cfg.setSampleRate_(SAMPLE_RATE_SCK)
        cfg.setChannelCount_(CHANNELS_SCK)
        # Video so klein und selten wie möglich - gebraucht wird nur der Ton.
        cfg.setWidth_(2)
        cfg.setHeight_(2)
        cfg.setMinimumFrameInterval_(CM.CMTimeMake(1, 1))
        cfg.setShowsCursor_(False)
        try:
            cfg.setQueueDepth_(8)
        except Exception:  # noqa: BLE001
            pass
        self._output = _output_class().alloc().initWithSink_(self._sink)
        self._stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(filt, cfg, self._output)
        ok, err = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, SCK.SCStreamOutputTypeAudio, _queue(), None
        )
        if not ok:
            raise RuntimeError(f"ScreenCaptureKit: Audio-Ausgang nicht anmeldbar ({err})")
        error = (_wait(self._stream.startCaptureWithCompletionHandler_) + [None])[0]
        if error is not None:
            raise RuntimeError(
                "ScreenCaptureKit: Aufnahme startet nicht - Bildschirmaufnahme erlaubt? "
                f"({error})"
            )
        self._started = time.monotonic()
        threading.Thread(target=self._watch_start, name="sck-watch", daemon=True).start()

    def _watch_start(self) -> None:
        time.sleep(SILENT_START_S)
        if self._sink.puffer == 0 and self._sink.gestoppt is None:
            self._log(
                f"System-Audio: kein Ton nach {SILENT_START_S:.0f} s - spielt gerade etwas? "
                "Bildschirmaufnahme für die Terminal-App erlaubt?"
            )

    @property
    def puffer(self) -> int:
        return self._sink.puffer

    def close(self) -> None:
        try:
            _wait(self._stream.stopCaptureWithCompletionHandler_, timeout_s=3.0)
        except Exception:  # noqa: BLE001 - beim Aufräumen nie scheitern
            pass


# --- Spike: python -m audioscribe.live.capture.sck --probe 5 -------------------------


def _probe(seconds: float, out: Path) -> int:
    from audioscribe.live.track import SAMPLE_RATE

    t0 = time.monotonic()
    track = Track("system", SAMPLE_RATE_SCK, CHANNELS_SCK, out)
    stream = SckStream(track, lambda: time.monotonic() - t0, print)
    time.sleep(seconds)
    stream.close()
    track.close()
    print(f"{stream.puffer} Audiopuffer, {track.written / SAMPLE_RATE:.1f} s Audio -> {out}")
    return 0 if stream.puffer else 1


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="ScreenCaptureKit-Spike: System-Audio nach WAV")
    ap.add_argument("--probe", type=float, default=5.0, metavar="SEK")
    ap.add_argument("--out", default="/tmp/sck.wav")
    a = ap.parse_args()
    raise SystemExit(_probe(a.probe, Path(a.out)))
