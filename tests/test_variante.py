"""Variante cloud-compliant (src/audioscribe/variante.py): nur lokale KI, keine KI-Analyse.

Die Tests schalten die Variante per monkeypatch ein - sie laufen so in main wie im Branch.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from audioscribe import variante
from audioscribe.projekt import einstellungen, modell
from audioscribe.souffleur import ki as ki_mod
from audioscribe.souffleur import ki_ollama
from audioscribe.ui import state


@pytest.fixture
def cc(monkeypatch):
    monkeypatch.setattr(variante, "VARIANTE", variante.CLOUD_COMPLIANT)


def _kein_netz(*_a, **_k):
    raise AssertionError("keine Anfrage an einen fremden Rechner")


# --- Schalter --------------------------------------------------------------------------------


def test_standard_laesst_alles_zu():
    assert variante.VARIANTE == variante.STANDARD or variante.aktiv()
    if not variante.aktiv():
        assert variante.pruefe_dienst("claude-agent") is None
        assert variante.pruefe_ollama_url("http://example.com:11434") is None


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"])
def test_lokale_adressen_zulaessig(cc, url):
    assert variante.pruefe_ollama_url(url) is None


@pytest.mark.parametrize("url", ["http://example.com:11434", "http://0.0.0.0:11434", "http://10.0.0.5:11434", "kaputt"])
def test_fremde_adressen_abgelehnt(cc, url):
    assert "nicht zulässig" in variante.pruefe_ollama_url(url)


def test_dienste(cc):
    assert variante.pruefe_dienst("ollama") is None
    assert variante.pruefe_dienst("attrappe") is None  # Tests, ohne Netz
    assert variante.HINWEIS_DIENST in variante.pruefe_dienst("claude-agent")


# --- KI-Dienst -------------------------------------------------------------------------------


def test_make_ki_claude_abgelehnt_ohne_sdk(cc, tmp_path, monkeypatch):
    monkeypatch.setattr(ki_mod, "sdk_verfuegbar", _kein_netz)
    monkeypatch.setattr(ki_mod, "ClaudeAgentKi", _kein_netz)
    ki, status = ki_mod.make_ki("claude-agent", "claude-sonnet-5", cache_dir=tmp_path)
    assert ki is None and status.zustand == "fehlt" and variante.HINWEIS_DIENST in status.meldung


def test_make_ki_ohne_backend_nimmt_lokal(cc, tmp_path, monkeypatch):
    from audioscribe.config import settings

    monkeypatch.setattr("audioscribe.config.settings", replace(settings, ollama_url="http://example.com:11434"))
    monkeypatch.setattr(ki_ollama, "ollama_sicherstellen", _kein_netz)
    ki, status = ki_mod.make_ki("", "", cache_dir=tmp_path)
    assert ki is None and status.backend == "ollama" and "nicht zulässig" in status.meldung


def test_ollama_status_und_http_fragen_fremde_rechner_nicht(cc):
    status = ki_ollama.ollama_status("http://example.com:11434", post=_kein_netz)
    assert not status.erreichbar and "nicht zulässig" in status.fehler
    with pytest.raises(ki_ollama._HttpFehler, match="nicht zulässig"):
        ki_ollama._http_json("http://example.com:11434/api/chat", {}, 1.0)


def test_ollama_ki_lehnt_fremde_adresse_ab(cc):
    ki = ki_ollama.OllamaKi("qwen3:8b", url="http://example.com:11434")
    auftrag = ki_mod.KiAuftrag(system="s", prompt="p", schema={}, timeout_s=1.0)
    with pytest.raises(ki_mod.KiFehler):
        ki.antworte(auftrag)


# --- Einstellungen und Projekt ---------------------------------------------------------------


def test_optionen_nur_lokal(cc):
    opt = einstellungen.optionen({})
    assert [d["id"] for d in opt["ki_dienste"]] == ["ollama"]
    assert "Claude" not in opt["ki_dienste"][0]["label"]
    assert {m["dienst"] for m in opt["souffleur_models"]} == {"ollama"}


def test_gespeichertes_claude_wird_lokal_mit_hinweis(cc):
    stand = {"souffleur_backend": "claude-agent"}
    assert einstellungen.globale(stand)["ki_dienst"] == "ollama"
    assert variante.HINWEIS_DIENST in einstellungen.hinweis(stand)
    assert einstellungen.hinweis({"souffleur_backend": "ollama"}) is None


def test_projekt_mit_claude(cc, projekt):
    alt = replace(projekt, ki_dienst="claude-agent")
    assert einstellungen.effektiv({"souffleur_backend": "ollama"}, alt)["ki_dienst"] == "ollama"
    with pytest.raises(modell.ProjektFehler, match="cloud-compliant"):
        modell.aendere(projekt, {"ki_dienst": "claude-agent"})
    assert modell.aendere(projekt, {"ki_dienst": "ollama"}).ki_dienst == "ollama"


def test_projekt_json_mit_claude_wird_geladen(cc, projekt):
    """Eine alte projekt.json mit claude-agent: laden geht, die Oberfläche zeigt den Hinweis."""
    from audioscribe.ui import kontext

    modell.speichere(replace(projekt, ki_dienst="claude-agent"))
    geladen = modell.lade(projekt.wurzel)
    d = kontext.projekt_dict(geladen, {}, mit_wiki=False)
    assert d["effektiv"]["ki_dienst"] == "ollama" and d["eigen"]["ki_dienst"] is None
    assert variante.HINWEIS_DIENST in d["ki_hinweis"]


def test_lege_an_mit_claude_abgelehnt(cc, tmp_path):
    with pytest.raises(modell.ProjektFehler, match="cloud-compliant"):
        modell.lege_an(name="X", wurzel=tmp_path / "x", sitzungen_dir=tmp_path / "x" / "s", ki_dienst="claude-agent")


# --- Oberfläche ------------------------------------------------------------------------------


@pytest.fixture
def client(cc, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "einstellungen.json")
    return TestClient(server.create_app())


def test_api_einstellungen(client):
    state.save_state({"souffleur_backend": "claude-agent"})
    d = client.get("/api/einstellungen").json()
    assert d["werte"]["ki_dienst"] == "ollama" and variante.HINWEIS_DIENST in d["hinweis"]
    r = client.post("/api/einstellungen", json={"ki_dienst": "claude-agent"})
    assert r.status_code == 400 and "cloud-compliant" in r.json()["detail"]
    assert client.post("/api/einstellungen", json={"ki_dienst": "ollama"}).json()["hinweis"] is None


def test_api_analyse_gesperrt(client, tmp_path):
    for pfad in ("/api/agent/defaults", "/api/agent/status"):
        r = client.get(pfad)
        assert r.status_code == 404 and r.json()["detail"] == variante.HINWEIS_ANALYSE
    assert client.post("/api/agent/start", json={}).status_code == 404
    assert client.post("/api/agent/cancel").status_code == 404
    # Die Sitzungsliste bleibt - die Nachbereitung legt damit ohne KI ins Wiki ab.
    assert client.get("/api/agent/sources", params={"output_dir": str(tmp_path)}).status_code == 200


def test_api_kontext_nennt_variante(client):
    assert client.get("/api/kontext").json()["variante"] == "cloud-compliant"


# --- Kommandozeile und Umgebungsprüfung ------------------------------------------------------


def test_cli_analyze_gesperrt(cc, capsys, monkeypatch):
    import sys

    from audioscribe import cli

    monkeypatch.delitem(sys.modules, "audioscribe.agent.kommando", raising=False)
    assert cli.main(["analyze", "irgendwo"]) == 2
    assert variante.HINWEIS_ANALYSE in capsys.readouterr().err
    assert "audioscribe.agent.kommando" not in sys.modules


def test_doctor(cc):
    from audioscribe import doctor

    assert doctor._check_variante().detail.startswith("cloud-compliant")
    agent = doctor._check_agent()
    assert agent.status == "OK" and "deaktiviert" in agent.detail


def test_server_und_doctor_laden_weder_agent_noch_sdk():
    """Eigener Prozess: nach App-Aufbau und allen Checks ist nichts von agent/SDK geladen."""
    import subprocess
    import sys

    pytest.importorskip("fastapi")
    code = (
        "import sys\n"
        "from audioscribe import variante\n"
        "variante.VARIANTE = variante.CLOUD_COMPLIANT\n"
        "from audioscribe.ui import server\n"
        "server.create_app()\n"
        "from audioscribe import doctor\n"
        "[doctor._safe(c) for c in doctor.CHECKS if c.__name__ in ('_check_variante', '_check_agent', '_check_ollama')]\n"
        "print(sorted(m for m in sys.modules if m.startswith(('claude_agent_sdk', 'audioscribe.agent'))))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "[]"
