"""Verknüpfung "Sofort aufnehmen" (ui/sofort.py): gemerkter Stand -> Startparameter, laufender
Server, CLI-Schalter ``audioscribe ui --aufnahme``."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from audioscribe.config import settings
from audioscribe.ui import sofort

INVENTAR = {
    "mics": [{"index": 3, "name": "Headset", "default": False}, {"index": 0, "name": "MacBook", "default": True}],
    "loopbacks": [{"index": 7, "name": "System-Audio", "default": True}],
    "monitors": [{"index": 1, "width": 1920, "height": 1080}, {"index": 2, "width": 2560, "height": 1440}],
    "windows": [{"hwnd": 4711, "title": "Angebot.xlsx", "process": "Excel"}, {"hwnd": 4712, "title": "Mail", "process": "Outlook"}],
    "problems": [],
}
LEER = {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": []}


def _start(saved, inventar=INVENTAR, sprache="de"):
    return sofort.aus_einstellungen(saved, inventar, sprache=sprache)


def test_leerer_stand_nimmt_vorgaben():
    p = _start({}, LEER)
    assert (p["mic"], p["mic_name"], p["loopback"], p["loopback_name"]) == ("default", "", "default", "")
    assert (p["monitor"], p["window"], p["window_label"]) == (0, 0, "")  # keine Monitore bekannt
    assert p["model"] == "auto" and p["language"] == "de" and p["device"] == settings.device
    assert p["partials"] and p["speakers"] and p["refine"] and p["refine_model"] == settings.whisper_model
    assert p["output_dir"] == "" and p["resume"] == "" and p["replay_transcript"] == ""
    assert _start({}, INVENTAR)["monitor"] == 1


def test_geraetenamen_werden_zu_indizes():
    p = _start({"live_mic": "Headset", "live_loopback": "System-Audio"})
    assert (p["mic"], p["mic_name"]) == ("3", "Headset")
    assert (p["loopback"], p["loopback_name"]) == ("7", "System-Audio")


def test_abgezogenes_geraet_wird_default_behaelt_aber_den_namen():
    p = _start({"live_mic": "Altes Headset", "live_loopback": "none"})
    assert (p["mic"], p["mic_name"]) == ("default", "Altes Headset")
    assert (p["loopback"], p["loopback_name"]) == ("none", "")


@pytest.mark.parametrize(
    ("gemerkt", "erwartet"),
    [
        ("Excel – Angebot.xlsx", (0, 4711, "Excel – Angebot.xlsx")),   # genau
        ("Excel – Anderes Blatt.xlsx", (0, 4711, "Excel – Angebot.xlsx")),  # nur der Prozess
        ("Word – Weg", (1, 0, "")),                                      # Fenster weg -> Monitor
    ],
)
def test_fenster_quelle(gemerkt, erwartet):
    p = _start({"live_source": "window", "live_window": gemerkt, "live_monitor": "1"})
    assert (p["monitor"], p["window"], p["window_label"]) == erwartet


def test_monitor_quelle_und_rueckfaelle():
    assert _start({"live_monitor": "2"})["monitor"] == 2
    assert _start({"live_monitor": "9"})["monitor"] == 1  # unbekannt -> erster Monitor
    assert _start({"live_monitor": "0"})["monitor"] == 0
    p = _start({"live_source": "none", "live_monitor": "2"})
    assert (p["monitor"], p["window"]) == (0, 0)
    # Der Testmodus startet nie automatisch - echte Aufnahme vom Monitor.
    p = _start({"live_source": "transcript", "live_monitor": "2"})
    assert (p["monitor"], p["window"], p["replay_transcript"]) == (2, 0, "")


def test_skalare_aus_dem_stand():
    p = _start(
        {"live_model": "small", "live_device": "cpu", "live_sensitivity": "hoch", "live_format": "png",
         "live_partials": False, "live_speakers": False, "live_refine": False, "live_refine_model": "medium"},
        sprache="en",
    )
    assert (p["model"], p["language"], p["device"], p["sensitivity"], p["format"]) == ("small", "en", "cpu", "hoch", "png")
    assert (p["partials"], p["speakers"], p["refine"], p["refine_model"]) == (False, False, False, "medium")


# --- laufender Server ----------------------------------------------------------------------


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_server_antwortet_nur_bei_audioscribe(monkeypatch):
    def nix(*a, **k):
        raise urllib.error.URLError("verweigert")

    monkeypatch.setattr(sofort.urllib.request, "urlopen", nix)
    assert sofort.server_antwortet("127.0.0.1", 8766) is False
    monkeypatch.setattr(sofort.urllib.request, "urlopen", lambda *a, **k: _Antwort(b"<html>"))
    assert sofort.server_antwortet("127.0.0.1", 8766) is False
    monkeypatch.setattr(sofort.urllib.request, "urlopen", lambda *a, **k: _Antwort(json.dumps({"modus": "start"}).encode()))
    assert sofort.server_antwortet("127.0.0.1", 8766) is True


def test_an_laufenden_server_startet_und_oeffnet_browser(monkeypatch, capsys):
    aufrufe = []

    def urlopen(anfrage, timeout=None):
        url = anfrage if isinstance(anfrage, str) else anfrage.full_url
        aufrufe.append(url)
        if url.endswith("/api/kontext"):
            return _Antwort(json.dumps({"modus": "start"}).encode())
        assert anfrage.get_method() == "POST"
        return _Antwort(b"{}")

    geoeffnet = []
    monkeypatch.setattr(sofort.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sofort.webbrowser, "open", lambda url: geoeffnet.append(url))
    assert sofort.an_laufenden_server("127.0.0.1", 8766) is True
    assert aufrufe[1] == "http://127.0.0.1:8766/api/aufnahme/sofort"
    assert geoeffnet == ["http://127.0.0.1:8766/#/aufnahme"]
    assert "laeuft bereits" in capsys.readouterr().out
    # --no-browser: nichts oeffnen
    geoeffnet.clear()
    assert sofort.an_laufenden_server("127.0.0.1", 8766, open_browser=False) is True
    assert geoeffnet == []


def test_an_laufenden_server_meldet_409_und_oeffnet_trotzdem(monkeypatch, capsys):
    def urlopen(anfrage, timeout=None):
        if isinstance(anfrage, str):
            return _Antwort(json.dumps({"modus": "projekt"}).encode())
        raise urllib.error.HTTPError(
            anfrage.full_url, 409, "Conflict", {}, io.BytesIO(json.dumps({"detail": "Es läuft noch eine Live-Sitzung."}).encode())
        )

    geoeffnet = []
    monkeypatch.setattr(sofort.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sofort.webbrowser, "open", lambda url: geoeffnet.append(url))
    assert sofort.an_laufenden_server("127.0.0.1", 8766) is True
    assert "Es läuft noch eine Live-Sitzung." in capsys.readouterr().err
    assert len(geoeffnet) == 1


def test_ohne_server_false(monkeypatch):
    monkeypatch.setattr(sofort, "server_antwortet", lambda *a, **k: False)
    assert sofort.an_laufenden_server("127.0.0.1", 8766) is False


# --- CLI -----------------------------------------------------------------------------------


def test_cli_ui_aufnahme(monkeypatch):
    from audioscribe import cli
    from audioscribe.ui import server

    aufrufe = {}
    monkeypatch.setattr(server, "serve", lambda **kw: aufrufe.update(kw))
    monkeypatch.setattr(sofort, "an_laufenden_server", lambda *a, **k: False)
    assert cli.main(["ui", "--aufnahme", "--port", "9000", "--no-browser"]) == 0
    assert aufrufe == {"port": 9000, "open_browser": False, "aufnahme": True}
    aufrufe.clear()
    assert cli.main(["ui"]) == 0
    assert aufrufe == {"port": 8766, "open_browser": True, "aufnahme": False}


def test_cli_ui_aufnahme_bei_laufendem_server_startet_keinen_zweiten(monkeypatch):
    from audioscribe import cli
    from audioscribe.ui import server

    gefragt = {}
    monkeypatch.setattr(server, "serve", lambda **kw: pytest.fail("serve darf nicht laufen"))
    monkeypatch.setattr(sofort, "an_laufenden_server", lambda host, port, **kw: gefragt.update(host=host, port=port, **kw) or True)
    assert cli.main(["ui", "--aufnahme", "--port", "9000"]) == 0
    assert gefragt == {"host": "127.0.0.1", "port": 9000, "open_browser": True}
    # Ohne --aufnahme wird nicht nachgefragt.
    monkeypatch.setattr(sofort, "an_laufenden_server", lambda *a, **k: pytest.fail("nicht fragen"))
    monkeypatch.setattr(server, "serve", lambda **kw: None)
    assert cli.main(["ui"]) == 0
