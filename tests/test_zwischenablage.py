"""Screenshots aus der Zwischenablage während der Live-Aufnahme (live/zwischenablage.py)."""

from __future__ import annotations

import io
import time
from types import SimpleNamespace

import pytest

from audioscribe.live import events

Image = pytest.importorskip("PIL.Image")


def _bild(farbe):
    return Image.new("RGB", (64, 36), farbe)


class FakeAblage:
    """Zwischenablage mit Änderungszähler wie NSPasteboard/GetClipboardSequenceNumber."""

    def __init__(self, inhalt=None):
        self.stand = 1
        self.inhalt = inhalt
        self.gelesen = 0

    def lege(self, inhalt):
        self.stand += 1
        self.inhalt = inhalt

    def zaehler(self):
        return self.stand

    def bild(self):
        self.gelesen += 1
        return self.inhalt if isinstance(self.inhalt, Image.Image) else None


def _watcher(ablage, **kw):
    from audioscribe.live.zwischenablage import ClipboardWatcher

    bilder, log = [], []
    w = ClipboardWatcher(bilder.append, log=log.append, zugriff=(ablage.zaehler, ablage.bild), **kw)
    return w, bilder, log


def _schritt(w, ablage):
    w._schritt(ablage.zaehler, ablage.bild)


def test_vorbestand_wird_nicht_uebernommen_neues_bild_genau_einmal():
    ablage = FakeAblage(_bild((255, 0, 0)))  # lag schon vor dem Einschalten drin
    w, bilder, _ = _watcher(ablage, an=True)
    _schritt(w, ablage)
    _schritt(w, ablage)
    assert bilder == [] and ablage.gelesen == 0  # ohne Änderung wird nicht einmal gelesen

    ablage.lege(_bild((0, 255, 0)))
    _schritt(w, ablage)
    _schritt(w, ablage)
    assert len(bilder) == 1 and bilder[0].getpixel((0, 0)) == (0, 255, 0)


def test_text_und_dasselbe_bild_noch_einmal_werden_ignoriert():
    ablage = FakeAblage()
    w, bilder, _ = _watcher(ablage, an=True)
    _schritt(w, ablage)
    ablage.lege("nur Text")
    _schritt(w, ablage)
    assert bilder == []

    ablage.lege(_bild((0, 0, 255)))
    _schritt(w, ablage)
    ablage.lege(_bild((0, 0, 255)))  # erneut kopiert: neuer Zähler, gleicher Inhalt
    _schritt(w, ablage)
    assert len(bilder) == 1


def test_aus_uebernimmt_nichts_und_wiedereinschalten_ignoriert_das_dazwischen():
    ablage = FakeAblage()
    w, bilder, log = _watcher(ablage, an=False)
    _schritt(w, ablage)
    ablage.lege(_bild((10, 10, 10)))
    _schritt(w, ablage)
    assert bilder == [] and ablage.gelesen == 0

    w.schalte(True)
    assert w.aktiv and log[-1] == "Zwischenablage: Screenshots übernehmen"
    _schritt(w, ablage)  # was im ausgeschalteten Zustand kopiert wurde, gilt als gesehen
    assert bilder == []
    ablage.lege(_bild((200, 200, 200)))
    _schritt(w, ablage)
    assert len(bilder) == 1

    w.schalte(False)
    ablage.lege(_bild((50, 100, 150)))
    _schritt(w, ablage)
    assert len(bilder) == 1 and log[-1] == "Zwischenablage: aus"


def test_thread_ueberlebt_lesefehler_und_meldet_ohne_systemzugriff(monkeypatch):
    from audioscribe.live import zwischenablage

    ablage = FakeAblage()

    def kaputt():
        raise OSError("gesperrt")

    w, bilder, log = _watcher(ablage, an=True, intervall=0.01)
    w._zugriff = (ablage.zaehler, kaputt)
    w.start()
    ablage.lege(_bild((1, 2, 3)))
    ende = time.monotonic() + 5
    while not any(z.startswith("Zwischenablage nicht gelesen") for z in log) and time.monotonic() < ende:
        time.sleep(0.01)
    assert w.is_alive()
    w.stop()
    w.join(timeout=2)
    assert not w.is_alive() and bilder == []

    def nicht_da():
        raise zwischenablage.AblageNichtVerfuegbar("Zwischenablage wird auf diesem System nicht beobachtet")

    monkeypatch.setattr(zwischenablage, "systemzugriff", nicht_da)
    w2 = zwischenablage.ClipboardWatcher(lambda img: None, log=log.append)
    w2.start()
    w2.join(timeout=2)
    assert not w2.is_alive() and log[-1] == "Zwischenablage wird auf diesem System nicht beobachtet"


def test_screen_watcher_einfuegen_teilt_ids_und_obergrenze(tmp_path):
    from audioscribe.live.screen import ScreenWatcher
    from audioscribe.pipeline.screens import KIND_ZWISCHENABLAGE

    marks, log = [], []
    w = ScreenWatcher(0, tmp_path, lambda: 83.4, marks.append, log=log.append, start_id=4, max_bilder=6)
    assert w.einfuegen(_bild((9, 9, 9)), KIND_ZWISCHENABLAGE) is True
    assert w.einfuegen(_bild((8, 8, 8)), KIND_ZWISCHENABLAGE) is True
    assert w.einfuegen(_bild((7, 7, 7)), KIND_ZWISCHENABLAGE) is False  # Obergrenze erreicht
    assert [m.id for m in marks] == [5, 6]
    assert marks[0].kind == "zwischenablage" and marks[0].t == 83.4
    assert marks[0].png == "frames/0005_00-01-23.jpg" and (tmp_path / marks[0].png).is_file()
    assert log == ["Obergrenze von 6 Standbildern erreicht"]


def test_einfuegen_speichert_rgba_screenshot_als_jpeg(tmp_path):
    """macOS legt Screenshots als RGBA-PNG in die Zwischenablage."""
    from audioscribe.live.screen import ScreenWatcher

    marks = []
    w = ScreenWatcher(0, tmp_path, lambda: 1.0, marks.append, log=lambda z: None)
    assert w.einfuegen(Image.new("RGBA", (40, 20), (255, 0, 0, 128)), "zwischenablage") is True
    with Image.open(tmp_path / marks[0].png) as gespeichert:
        assert gespeichert.format == "JPEG" and gespeichert.size == (40, 20)


def test_nachschaerfen_ersetzt_zwischenablage_bilder_nicht():
    from audioscribe.pipeline.screens import KIND_AUTO, KIND_ZWISCHENABLAGE

    assert KIND_ZWISCHENABLAGE != KIND_AUTO  # screens.py ersetzt nur kind == "auto"


def test_ablage_befehl_rundreise():
    from audioscribe.live.events import ablage_befehl, parse_ablage_befehl

    assert ablage_befehl(True) == "zwischenablage an" and parse_ablage_befehl("Zwischenablage AN\n") is True
    assert ablage_befehl(False) == "zwischenablage aus" and parse_ablage_befehl(" zwischenablage aus ") is False
    for kaputt in ("zwischenablage", "zwischenablage vielleicht", "bild aus", "", "zwischenablage an x"):
        assert parse_ablage_befehl(kaputt) is None, kaputt


def test_session_stdin_schaltet_zwischenablage(tmp_path, monkeypatch):
    from audioscribe.live.session import LiveOptions, LiveSession

    monkeypatch.setattr(events, "emit", lambda typ, **d: None)
    logged = []
    monkeypatch.setattr(events, "log", logged.append)
    session = LiveSession(LiveOptions(output_dir=tmp_path, model="m", device="cpu", compute_type="int8"))
    geschaltet = []
    session._screen = SimpleNamespace(wechsle=lambda monitor=0, window=0: None)
    session._ablage = SimpleNamespace(schalte=geschaltet.append)
    monkeypatch.setattr("sys.stdin", io.StringIO("zwischenablage an\nbild aus\nzwischenablage aus\nstop\n"))
    session._watch_stdin()
    assert geschaltet == [True, False] and session._stop.is_set()

    session._ablage = None
    session.schalte_zwischenablage(True)
    assert logged[-1].startswith("Keine Bildquelle in dieser Sitzung")


def test_live_argv_und_runner_ohne_aufnahme(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions, build_live_argv
    from audioscribe.ui.runner import LiveRunner

    assert "--zwischenablage" not in build_live_argv(LiveJobOptions(output_dir=tmp_path), prefix=["x"])
    assert "--zwischenablage" in build_live_argv(LiveJobOptions(output_dir=tmp_path, zwischenablage=True), prefix=["x"])
    with pytest.raises(RuntimeError):
        LiveRunner().zwischenablage(True)  # nichts läuft


def test_api_zwischenablage_ohne_sitzung_409(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server, state

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "ui-state.json")
    client = TestClient(server.create_app())
    assert client.get("/api/live/defaults").json()["zwischenablage"] is False
    r = client.post("/api/live/zwischenablage", json={"an": True})
    assert r.status_code == 409
    assert "live_zwischenablage" not in state.load_state()  # nur gemerkt, wenn es gewirkt hat
