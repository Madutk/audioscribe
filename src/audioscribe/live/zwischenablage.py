"""Screenshots aus der Zwischenablage während der Live-Aufnahme übernehmen.

Wer im Meeting einen Ausschnitt mit dem Screenshot-Werkzeug in die Zwischenablage legt
(macOS ⌘⇧⌃4, Windows Win+Shift+S), bekommt ihn ohne weiteren Klick als Standbild der
Sitzung. Abgetastet wird nur ein billiger Änderungszähler der Zwischenablage; das Bild
selbst wird erst gelesen, wenn sich der Zähler geändert hat. Was beim Einschalten schon in
der Zwischenablage lag, wird nicht übernommen.
"""

from __future__ import annotations

import hashlib
import io
import sys
import threading
from collections.abc import Callable

from audioscribe.i18n import tr


class AblageNichtVerfuegbar(RuntimeError):
    """Auf diesem System lässt sich die Zwischenablage nicht beobachten."""


def _mac_pasteboard():
    from AppKit import NSPasteboard

    return NSPasteboard.generalPasteboard()


def _mac_zaehler() -> int:
    return int(_mac_pasteboard().changeCount())


def _mac_bild():
    """PNG oder TIFF der Zwischenablage als PIL-Bild, sonst ``None`` (Text, Dateien ...)."""
    from AppKit import NSPasteboardTypePNG, NSPasteboardTypeTIFF
    from PIL import Image

    tafel = _mac_pasteboard()
    for typ in (NSPasteboardTypePNG, NSPasteboardTypeTIFF):
        daten = tafel.dataForType_(typ)
        if daten is not None and daten.length() > 0:
            img = Image.open(io.BytesIO(bytes(daten)))
            img.load()
            return img
    return None


def _win_zaehler() -> int:
    import ctypes

    return int(ctypes.windll.user32.GetClipboardSequenceNumber())


def _win_bild():
    from PIL import Image, ImageGrab

    inhalt = ImageGrab.grabclipboard()
    return inhalt if isinstance(inhalt, Image.Image) else None  # Dateiliste/Text: kein Bild


def systemzugriff() -> tuple[Callable[[], int], Callable[[], object]]:
    """``(zaehler, lese_bild)`` für dieses System; ``AblageNichtVerfuegbar`` sonst."""
    try:
        if sys.platform == "darwin":
            import AppKit  # noqa: F401

            return _mac_zaehler, _mac_bild
        if sys.platform == "win32":
            import PIL.ImageGrab  # noqa: F401

            return _win_zaehler, _win_bild
    except ImportError as exc:
        raise AblageNichtVerfuegbar(
            tr("Zwischenablage nicht lesbar - Modul fehlt: {modul}", modul=exc.name or exc)
        ) from exc
    raise AblageNichtVerfuegbar(tr("Zwischenablage wird auf diesem System nicht beobachtet"))


def _fingerabdruck(img) -> str:
    klein = img.convert("L").resize((32, 32))
    return hashlib.sha1(klein.tobytes()).hexdigest()


class ClipboardWatcher(threading.Thread):
    """Meldet jedes neue Bild der Zwischenablage über ``on_bild``.

    ``an`` schaltet das Übernehmen ein oder aus (auch während der Sitzung); beim Einschalten
    gilt der jetzige Inhalt als schon gesehen. ``zugriff`` ersetzt den Systemzugriff
    (``(zaehler, lese_bild)``, für Tests).
    """

    def __init__(
        self,
        on_bild: Callable[[object], object],
        *,
        an: bool = False,
        intervall: float = 0.5,
        log: Callable[[str], None] = print,
        zugriff: tuple[Callable[[], int], Callable[[], object]] | None = None,
    ) -> None:
        super().__init__(name="audioscribe-zwischenablage", daemon=True)
        self._on_bild = on_bild
        self._intervall = intervall
        self._log = log
        self._zugriff = zugriff
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._an = bool(an)
        self._gesehen: int | None = None  # Zählerstand, bis zu dem alles als bekannt gilt
        self._letzter_abdruck: str | None = None

    @property
    def aktiv(self) -> bool:
        with self._lock:
            return self._an

    def stop(self) -> None:
        self._halt.set()

    def schalte(self, an: bool) -> None:
        with self._lock:
            if an and not self._an:
                self._gesehen = None  # beim nächsten Blick den Vorbestand übernehmen, nicht melden
            self._an = bool(an)
        self._log(tr("Zwischenablage: Screenshots übernehmen") if an else tr("Zwischenablage: aus"))

    def run(self) -> None:
        try:
            zaehler, lese_bild = self._zugriff or systemzugriff()
        except AblageNichtVerfuegbar as exc:
            self._log(str(exc))
            return
        while not self._halt.wait(self._intervall):
            try:
                self._schritt(zaehler, lese_bild)
            except Exception as exc:  # noqa: BLE001 - die Zwischenablage darf die Sitzung nie kippen
                self._log(tr("Zwischenablage nicht gelesen: {fehler}", fehler=exc))

    def _schritt(self, zaehler: Callable[[], int], lese_bild: Callable[[], object]) -> None:
        with self._lock:
            if not self._an:
                return
            stand = zaehler()
            if self._gesehen is None:
                self._gesehen = stand
                return
            if stand == self._gesehen:
                return
            self._gesehen = stand
        img = lese_bild()
        if img is None:
            return
        abdruck = _fingerabdruck(img)
        if abdruck == self._letzter_abdruck:
            return  # dasselbe Bild noch einmal kopiert
        self._letzter_abdruck = abdruck
        self._on_bild(img)
