"""Nativer Ordnerdialog (ui/dialog_nativ.py): Kommandos je Plattform, Antworten, Route."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest

from audioscribe.ui import dialog_nativ, state


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


def test_mac_kommando_und_antworten(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_nativ, "PLATTFORM", "mac")
    cmd = dialog_nativ.kommando(tmp_path, 'Wiki "A" wählen')
    assert cmd[0] == "osascript" and "activate" in cmd
    wahl = cmd[cmd.index("-e", 4) + 1]
    assert wahl.startswith("set f to choose folder with prompt \"Wiki \\\"A\\\" wählen\"")
    assert f'default location (POSIX file "{tmp_path}")' in wahl
    # Kein Startordner, wenn es ihn nicht gibt.
    assert "default location" not in " ".join(dialog_nativ.kommando(tmp_path / "nix", "x"))
    assert "default location" not in " ".join(dialog_nativ.kommando(None, "x"))
    assert dialog_nativ.ergebnis(_proc(0, "/Users/x/Wiki/\n")) == Path("/Users/x/Wiki")
    assert dialog_nativ.ergebnis(_proc(1, "", "execution error: User canceled. (-128)\n")) is None
    with pytest.raises(dialog_nativ.DialogFehler):
        dialog_nativ.ergebnis(_proc(1, "", "execution error: kaputt (-1700)"))


def test_windows_kommando_und_antworten(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_nativ, "PLATTFORM", "windows")
    cmd = dialog_nativ.kommando(tmp_path, "Mark's Wiki")
    assert cmd[:5] == ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand"]
    skript = base64.b64decode(cmd[5]).decode("utf-16-le")
    assert "FolderBrowserDialog" in skript and "$d.Description = 'Mark''s Wiki'" in skript
    assert f"$d.SelectedPath = '{tmp_path}'" in skript and "exit 2" in skript
    assert "$d.SelectedPath = " not in base64.b64decode(dialog_nativ.kommando(None, "x")[5]).decode("utf-16-le")
    assert dialog_nativ.ergebnis(_proc(0, "C:\\Wiki")) == Path("C:\\Wiki")
    assert dialog_nativ.ergebnis(_proc(2)) is None
    with pytest.raises(dialog_nativ.DialogFehler):
        dialog_nativ.ergebnis(_proc(1, "", "Fehler"))


def test_posix_kommando_verfuegbarkeit_und_antworten(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_nativ, "PLATTFORM", "posix")
    cmd = dialog_nativ.kommando(tmp_path, "Titel\x00mit\nSteuerzeichen")
    assert cmd[:3] == [sys.executable, "-I", "-c"] and cmd[4:] == [str(tmp_path), "TitelmitSteuerzeichen"]
    assert dialog_nativ.ergebnis(_proc(0, "/home/x/wiki\n")) == Path("/home/x/wiki")
    assert dialog_nativ.ergebnis(_proc(0, "\n")) is None
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert dialog_nativ.verfuegbar() is False
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(dialog_nativ.importlib.util, "find_spec", lambda name: object())
    assert dialog_nativ.verfuegbar() is True
    monkeypatch.setattr(dialog_nativ.importlib.util, "find_spec", lambda name: None)
    assert dialog_nativ.verfuegbar() is False


def test_verfuegbar_mac_und_windows(monkeypatch):
    monkeypatch.setattr(dialog_nativ.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    monkeypatch.setattr(dialog_nativ, "PLATTFORM", "mac")
    assert dialog_nativ.verfuegbar() is True
    monkeypatch.setattr(dialog_nativ, "PLATTFORM", "windows")
    assert dialog_nativ.verfuegbar() is False


def test_waehle_ordner_laeuft_als_kindprozess(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_nativ, "PLATTFORM", "mac")
    aufrufe = []

    def run(cmd, **kw):
        aufrufe.append((cmd, kw))
        return _proc(0, f"{tmp_path}/\n")

    monkeypatch.setattr(dialog_nativ.subprocess, "run", run)
    assert dialog_nativ.waehle_ordner(None, "x") == tmp_path
    assert aufrufe[0][0][0] == "osascript" and aufrufe[0][1]["timeout"] == dialog_nativ.TIMEOUT_S

    def zu_lang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(dialog_nativ.subprocess, "run", zu_lang)
    with pytest.raises(dialog_nativ.DialogFehler):
        dialog_nativ.waehle_ordner(None, "x")

    def fehlt(cmd, **kw):
        raise FileNotFoundError("osascript")

    monkeypatch.setattr(dialog_nativ.subprocess, "run", fehlt)
    with pytest.raises(dialog_nativ.DialogFehler):
        dialog_nativ.waehle_ordner(None, "x")


# --- Route -----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "einstellungen.json")
    return TestClient(server.create_app())


def test_route_liefert_pfad_oder_rueckfall(client, monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_nativ, "verfuegbar", lambda: True)
    gefragt = {}
    monkeypatch.setattr(dialog_nativ, "waehle_ordner", lambda start, titel: gefragt.update(start=start, titel=titel) or tmp_path)
    assert client.get("/api/kontext").json()["dialog_nativ"] is True
    r = client.post("/api/dialog/ordner", json={"start": str(tmp_path), "titel": "Wiki wählen"})
    assert r.json() == {"pfad": str(tmp_path), "verfuegbar": True}
    assert gefragt == {"start": tmp_path, "titel": "Wiki wählen"}
    # Abgebrochen
    monkeypatch.setattr(dialog_nativ, "waehle_ordner", lambda start, titel: None)
    assert client.post("/api/dialog/ordner", json={}).json() == {"pfad": None, "verfuegbar": True}
    # Dialog kaputt: Rueckfall auf den eingebauten Dialog
    def kaputt(start, titel):
        raise dialog_nativ.DialogFehler("kein Desktop")

    monkeypatch.setattr(dialog_nativ, "waehle_ordner", kaputt)
    assert client.post("/api/dialog/ordner", json={}).json() == {"pfad": None, "verfuegbar": False, "fehler": "kein Desktop"}
    # Nicht verfuegbar
    monkeypatch.setattr(dialog_nativ, "verfuegbar", lambda: False)
    assert client.post("/api/dialog/ordner", json={}).json() == {"pfad": None, "verfuegbar": False}
    assert client.get("/api/kontext").json()["dialog_nativ"] is False


def test_route_nur_ein_dialog_zur_zeit(client, monkeypatch):
    monkeypatch.setattr(dialog_nativ, "verfuegbar", lambda: True)
    monkeypatch.setattr(dialog_nativ, "waehle_ordner", lambda start, titel: pytest.fail("nicht oeffnen"))
    assert dialog_nativ.sperre.acquire(blocking=False)
    try:
        assert client.post("/api/dialog/ordner", json={}).status_code == 409
    finally:
        dialog_nativ.sperre.release()
