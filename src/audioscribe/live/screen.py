"""Bildwechsel auf einem Monitor oder in einem Fenster live erkennen und sichern (FR-41).

Dieselbe Blockraster-Heuristik wie offline (``pipeline.screens``), nur Bild für Bild
statt über eine fertige Trefferliste. Die Bildquelle (Monitor per ``mss``, Fenster per
``live.fenster``) ist austauschbar; die Erkennung sieht nur PIL-Bilder.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from audioscribe.live.fenster import WindowGone
from audioscribe.pipeline.screens import (
    _RUHE_ABTASTUNGEN,
    DEFAULT_DAUERBEWEGUNG_S,
    DEFAULT_FORMAT,
    DEFAULT_MAX_BILDER,
    DEFAULT_SENSITIVITY,
    FORMATS,
    KIND_AUTO,
    SCAN_HEIGHT,
    SCAN_WIDTH,
    SENSITIVITIES,
    block_means,
    changed_blocks,
    shot_filename,
)
from audioscribe.review.marks import Mark

_JPEG_QUALITY = 88  # entspricht grob ffmpegs -q:v 3 der Offline-Standbilder


MSS_FEHLT = "mss fehlt - keine Standbilder (uv sync ... --extra live)"


class SourceUnavailable(RuntimeError):
    """Die gewählte Bildquelle gibt es nicht (Monitor-Index, geschlossenes Fenster)."""


class ChangeDetector:
    """Inkrementelles Gegenstück zu ``screens.merge_runs`` (rein, testbar).

    ``feed`` liefert den Zeitpunkt, für den JETZT ein Standbild fällig ist, sonst ``None``.
    Anders als offline wird ein Wechsel innerhalb von ``min_gap`` nicht verworfen, sondern
    nachgeholt: sonst bliebe ein Bildschirm, der kurz nach dem letzten Bild erscheint und
    dann minutenlang steht, ganz ohne Bild.
    """

    def __init__(
        self,
        sensitivity: str = DEFAULT_SENSITIVITY,
        *,
        min_gap: float = 4.0,
        dauerbewegung_s: float = DEFAULT_DAUERBEWEGUNG_S,
    ) -> None:
        self._schwelle, self._min_bloecke = SENSITIVITIES.get(
            sensitivity, SENSITIVITIES[DEFAULT_SENSITIVITY]
        )
        self._min_gap = min_gap
        self._dauer = dauerbewegung_s
        self._vorher = None
        self._serie_start: float | None = None
        self._letzter_treffer = 0.0
        self._ruhe = 0
        self._letztes_bild: float | None = None
        self._offen: float | None = None  # Zeitpunkt eines noch nicht gesicherten Wechsels

    def feed(self, t: float, raster) -> float | None:
        if self._vorher is None:
            self._vorher = raster
            self._letztes_bild = t
            return t  # Startbild
        treffer = changed_blocks(self._vorher, raster, self._schwelle) >= self._min_bloecke
        self._vorher = raster

        if treffer:
            if self._serie_start is None:
                self._serie_start = t
            self._letzter_treffer = t
            self._ruhe = 0
            if self._dauer > 0 and t - self._serie_start >= self._dauer:
                self._serie_start = t
                self._offen = t
        elif self._serie_start is not None:
            self._ruhe += 1
            if self._ruhe >= _RUHE_ABTASTUNGEN:
                self._serie_start = None
                self._offen = self._letzter_treffer

        # Mitten in einer Serie nur der Dauerbewegungs-Notausgang (offen == t): ein
        # nachgeholtes Bild soll den ruhigen Bildschirm zeigen, nicht die nächste Animation.
        ruhig = self._serie_start is None or self._offen == t
        if self._offen is not None and ruhig and t - self._letztes_bild >= self._min_gap:
            faellig, self._offen = self._offen, None
            self._letztes_bild = t
            return faellig
        return None


def list_monitors() -> list[dict]:
    """Monitore in der Zählung von ``mss`` (1 = erster Monitor)."""
    import mss

    with mss.mss() as sct:
        return [
            {"index": i, "width": m["width"], "height": m["height"], "left": m["left"], "top": m["top"]}
            for i, m in enumerate(sct.monitors)
            if i > 0
        ]


def grab_image(sct, monitor: dict):
    from PIL import Image

    shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def preview_jpeg(index: int, width: int = 480) -> bytes:
    """Verkleinertes Vorschaubild eines Monitors für die Monitorwahl."""
    import io

    import mss

    with mss.mss() as sct:
        if not 0 < index < len(sct.monitors):
            raise IndexError(f"Monitor {index} gibt es nicht")
        img = grab_image(sct, sct.monitors[index])
    img.thumbnail((width, width))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return out.getvalue()


def raster(img):
    """Bild -> 9x16-Blockmittel. ``BOX`` mittelt über die Quellpixel (wie ffmpegs
    ``flags=area``); ohne das flackert ein dünner Mauszeiger zwischen den Abtastungen."""
    import numpy as np
    from PIL import Image

    klein = img.convert("L").resize((SCAN_WIDTH, SCAN_HEIGHT), Image.BOX)
    return block_means(np.asarray(klein, dtype=np.int16))


def save_shot(img, path: Path, bildformat: str) -> None:
    from PIL import Image

    _, max_breite, qualitaet = FORMATS.get(bildformat, FORMATS[DEFAULT_FORMAT])
    if 0 < max_breite < img.width:
        img = img.resize((max_breite, round(img.height * max_breite / img.width)), Image.LANCZOS)
    if qualitaet is None:
        img.save(path, "PNG")
    else:
        img.save(path, "JPEG", quality=_JPEG_QUALITY)


class MonitorSource:
    """Ganzer Monitor per ``mss``. Die mss-Instanz ist an ihren Thread gebunden - darum
    entsteht sie erst in ``__enter__`` (das im Watcher-Thread läuft)."""

    def __init__(self, index: int) -> None:
        self._index = index
        self.label = f"Monitor {index}"

    def __enter__(self):
        import mss

        self._sct = mss.mss()
        if not 0 < self._index < len(self._sct.monitors):
            self._sct.close()
            raise SourceUnavailable(f"Monitor {self._index} gibt es nicht")
        self._monitor = self._sct.monitors[self._index]
        return self

    def __exit__(self, *exc) -> None:
        self._sct.close()

    def grab(self):
        return grab_image(self._sct, self._monitor)


class WindowSource:
    """Ein einzelnes Fenster (HWND) per ``fenster.grab_window``; der Rückfall auf den
    Bildschirmausschnitt läuft über ``mss``, wenn es installiert ist."""

    def __init__(self, hwnd: int) -> None:
        self._hwnd = hwnd
        self.label = f"Fenster {hwnd}"

    def __enter__(self):
        from audioscribe.live import fenster

        fenster.dpi_aware()
        if not fenster.is_window(self._hwnd):
            raise SourceUnavailable(f"Fenster {self._hwnd} gibt es nicht")
        self.label = f"Fenster '{fenster.window_title(self._hwnd)}'"
        try:
            import mss

            self._sct = mss.mss()
        except ImportError:
            self._sct = None
        return self

    def __exit__(self, *exc) -> None:
        if self._sct is not None:
            self._sct.close()

    def grab(self):
        from audioscribe.live.fenster import grab_window

        return grab_window(self._hwnd, fallback=self._region if self._sct else None)

    def _region(self, rect):
        """Bildschirmausschnitt am Fensterrechteck, beschnitten auf den virtuellen
        Bildschirm (Monitore links/oben vom Hauptmonitor haben negative Koordinaten)."""
        alles = self._sct.monitors[0]
        left = max(rect[0], alles["left"])
        top = max(rect[1], alles["top"])
        right = min(rect[2], alles["left"] + alles["width"])
        bottom = min(rect[3], alles["top"] + alles["height"])
        if right <= left or bottom <= top:
            return None
        return grab_image(
            self._sct, {"left": left, "top": top, "width": right - left, "height": bottom - top}
        )


class ScreenWatcher(threading.Thread):
    """Tastet die Bildquelle ab und meldet jedes gesicherte Standbild über ``on_shot``.

    ``window`` (HWND) hat Vorrang vor ``monitor``; ``source_factory`` ersetzt beides
    (für Tests ohne mss und WinAPI).
    """

    def __init__(
        self,
        monitor: int,
        out_dir: Path,
        clock: Callable[[], float],
        on_shot: Callable[[Mark], None],
        *,
        window: int = 0,
        sensitivity: str = DEFAULT_SENSITIVITY,
        bildformat: str = DEFAULT_FORMAT,
        fps: float = 2.0,
        min_gap: float = 4.0,
        max_bilder: int = DEFAULT_MAX_BILDER,
        log: Callable[[str], None] = print,
        source_factory: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(name="audioscribe-screen", daemon=True)
        self._monitor = monitor
        self._window = window
        self._out_dir = out_dir
        self._clock = clock
        self._on_shot = on_shot
        self._bildformat = bildformat if bildformat in FORMATS else DEFAULT_FORMAT
        self._fps = fps
        self._max_bilder = max_bilder
        self._log = log
        self._source_factory = source_factory
        self._detector = ChangeDetector(sensitivity, min_gap=min_gap)
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def _source(self):
        if self._source_factory is not None:
            return self._source_factory()
        return WindowSource(self._window) if self._window else MonitorSource(self._monitor)

    def run(self) -> None:
        try:
            with self._source() as source:
                self._log(f"Standbilder: {source.label}")
                self._loop(source)
        except SourceUnavailable as exc:
            self._log(f"{exc} - keine Standbilder")
        except ImportError:  # mss wird erst hier, im Thread, geladen
            self._log(MSS_FEHLT)

    def _loop(self, source) -> None:
        frames = self._out_dir / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        suffix = FORMATS[self._bildformat][0]
        anzahl = 0
        pausiert = False
        while not self._halt.wait(1.0 / self._fps):
            try:
                img = source.grab()
                if img is None:
                    if not pausiert:
                        self._log("Fenster minimiert oder ausgeblendet - Standbilder pausieren")
                        pausiert = True
                    continue
                if pausiert:
                    self._log("Fenster wieder sichtbar")
                    pausiert = False
                t = self._detector.feed(self._clock(), raster(img))
                if t is None:
                    continue
                if anzahl >= self._max_bilder:
                    if anzahl == self._max_bilder:
                        self._log(f"Obergrenze von {self._max_bilder} Standbildern erreicht")
                        anzahl += 1
                    continue
                anzahl += 1
                name = shot_filename(anzahl, t, suffix)
                save_shot(img, frames / name, self._bildformat)
                self._on_shot(
                    Mark(
                        t=round(t, 3),
                        png=f"frames/{name}",
                        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
                        id=anzahl,
                        kind=KIND_AUTO,
                    )
                )
            except WindowGone:
                self._log("Fenster geschlossen - keine weiteren Standbilder")
                return
            except Exception as exc:  # noqa: BLE001 - ein Bild darf die Sitzung nie kippen
                self._log(f"Standbild fehlgeschlagen: {exc}")
