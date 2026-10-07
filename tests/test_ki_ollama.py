"""Lokale KI über Ollama (PRD §20.2 Stufe 2, §16 „lokal, experimentell“): Dienst, Factory,
Einstellungen, Umleitung der KI-Analyse, Doctor. Ohne laufenden Dienst - HTTP ist injiziert."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from audioscribe.agent.material import Auftrag
from audioscribe.agent.runner import AnalyseSitzung, pruefe_lokal, sdk_env
from audioscribe.projekt import einstellungen
from audioscribe.souffleur import ki_ollama
from audioscribe.souffleur.ki import BACKEND_CLAUDE, BACKEND_OLLAMA, KiAuftrag, KiFehler, make_ki, modell_fuer
from audioscribe.souffleur.ki_ollama import (
    DEFAULT_OLLAMA_MODELL,
    OLLAMA_MODELLE,
    OllamaKi,
    OllamaStatus,
    _HttpFehler,
    lokales_modell,
    ollama_status,
)
from audioscribe.ui.jobs import AnalyseOptions, build_analyze_argv
from audioscribe.verbrauch import Verbrauch

SCHEMA = {
    "type": "object",
    "required": ["essenz", "offen"],
    "properties": {"essenz": {"type": "array"}, "offen": {"type": "array"}},
}
ANTWORT = {"essenz": [{"punkt": "Die Freigabe dauert drei Werktage."}], "offen": []}


def _ergebnis(content: str, **extra) -> dict:
    return {
        "model": "qwen3.6:27b-mlx", "done": True,
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 1204, "eval_count": 310, "load_duration": int(2.5e9), "total_duration": int(6.8e9),
        **extra,
    }


def _post(antwort: dict | Exception, aufrufe: list | None = None):
    def post(url: str, body: dict | None, timeout_s: float) -> dict:
        if aufrufe is not None:
            aufrufe.append((url, body, timeout_s))
        if isinstance(antwort, Exception):
            raise antwort
        return antwort
    return post


def _status(url: str = "http://x", **kw) -> OllamaStatus:  # noqa: ARG001
    return OllamaStatus(True, version="0.19.0", modelle=("qwen3.6:35b-a3b-nvfp4", "gemma4:26b-mlx", "qwen3.6:latest"))


# --- Dienst ------------------------------------------------------------------------------------


def test_anfrage_traegt_schema_und_schaltet_denken_ab():
    import json

    aufrufe: list = []
    log: list[str] = []
    ki = OllamaKi("qwen3.6:27b-mlx", url="http://h:1/", keep_alive="5m", log=log.append, post=_post(_ergebnis(json.dumps(ANTWORT)), aufrufe))
    antwort = ki.antworte(KiAuftrag("System", "Prompt", SCHEMA, timeout_s=12))
    url, body, timeout = aufrufe[0]
    assert url == "http://h:1/api/chat" and timeout == 12
    assert body["model"] == "qwen3.6:27b-mlx" and body["stream"] is False and body["think"] is False
    assert body["format"] is SCHEMA and body["keep_alive"] == "5m"
    assert body["options"] == {"temperature": 0, "num_ctx": ki_ollama.NUM_CTX}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == "System" and body["messages"][1]["content"] == "Prompt"
    assert antwort.daten == ANTWORT and antwort.modell == "qwen3.6:27b-mlx" and antwort.session_id is None
    assert antwort.verbrauch is None  # lokal zaehlt nicht (FR-78)
    assert antwort.start_s == 2.5 and antwort.antwort_s >= 0
    assert log and "1204 Tokens ein, 310 aus" in log[0] and "Modell laden 2.5 s" in log[0]


@pytest.mark.parametrize(
    ("content", "extra", "text"),
    [
        ("kein json", {}, "kein gültiges JSON"),
        ('{"essenz": []}', {}, "ohne gültige Struktur"),
        ("[1, 2]", {}, "ohne gültige Struktur"),
        ("", {"done_reason": "length"}, "leer (length)"),
    ],
)
def test_unbrauchbare_antworten_werden_zum_kifehler(content, extra, text):
    ki = OllamaKi("gemma4:26b-mlx", post=_post(_ergebnis(content, **extra)))
    with pytest.raises(KiFehler, match=re.escape(text)):
        ki.antworte(KiAuftrag("s", "p", SCHEMA))


@pytest.mark.parametrize(
    ("fehler", "text"),
    [
        (_HttpFehler(404, "model 'x' not found"), "ollama pull gemma4:26b-mlx"),
        (_HttpFehler(None, "Zeitüberschreitung"), "nach 12 s abgebrochen"),
        (_HttpFehler(None, "[Errno 61] Connection refused"), "nicht erreichbar unter http://h:1 - 'ollama serve'"),
        (_HttpFehler(500, "boom"), "HTTP 500: boom"),
        (ValueError("kaputt"), "KI-Aufruf gescheitert: ValueError: kaputt"),
    ],
)
def test_fehlerbilder_mit_klartext(fehler, text):
    ki = OllamaKi("gemma4:26b-mlx", url="http://h:1", post=_post(fehler))
    with pytest.raises(KiFehler) as exc:
        ki.antworte(KiAuftrag("s", "p", SCHEMA, timeout_s=12))
    assert text in str(exc.value)


def test_lokales_modell_und_modell_fuer():
    assert lokales_modell("claude-sonnet-5") == DEFAULT_OLLAMA_MODELL
    assert lokales_modell("") == DEFAULT_OLLAMA_MODELL and lokales_modell(None) == DEFAULT_OLLAMA_MODELL
    assert lokales_modell(" gemma4:26b-mlx ") == "gemma4:26b-mlx"
    assert modell_fuer(BACKEND_OLLAMA, "claude-opus-5") == DEFAULT_OLLAMA_MODELL
    assert modell_fuer(BACKEND_CLAUDE, "qwen3.6:27b-mlx") == "claude-sonnet-5"  # Ollama-Tag passt nicht zu Claude
    assert modell_fuer(BACKEND_CLAUDE, "opus") == "opus" and modell_fuer(BACKEND_CLAUDE, "") == "claude-sonnet-5"
    assert OllamaKi("claude-sonnet-5", post=_post({})).modell == DEFAULT_OLLAMA_MODELL


def test_ollama_status_liest_version_und_modelle():
    antworten = {
        "http://h:1/api/version": {"version": "0.19.0"},
        "http://h:1/api/tags": {"models": [{"name": "qwen3.6:35b-a3b-nvfp4"}, {"model": "gemma4:latest"}, "murks"]},
    }
    status = ollama_status("http://h:1/", post=lambda url, body, t: antworten[url])
    assert status.erreichbar and status.version == "0.19.0"
    assert status.modelle == ("qwen3.6:35b-a3b-nvfp4", "gemma4:latest")
    assert status.hat_modell("qwen3.6:35b-a3b-nvfp4") and status.hat_modell("gemma4") and not status.hat_modell("qwen3.6")
    down = ollama_status("http://h:1", post=_post(_HttpFehler(None, "Connection refused")))
    assert not down.erreichbar and down.fehler == "Connection refused" and down.modelle == ()
    kaputt = ollama_status("http://h:1", post=_post(RuntimeError("x")))
    assert not kaputt.erreichbar and "RuntimeError" in (kaputt.fehler or "")


def test_ollama_status_echte_verbindung_verweigert():
    """Der echte HTTP-Pfad ohne Dienst: Port 9 (discard) lehnt ab, der Status sagt das."""
    status = ollama_status("http://127.0.0.1:9", timeout_s=1.0)
    assert not status.erreichbar and status.fehler


# --- Factory -----------------------------------------------------------------------------------


def test_make_ki_ollama_prueft_dienst_und_modell(tmp_path, monkeypatch):
    monkeypatch.setattr(ki_ollama, "ollama_status", lambda url, **kw: OllamaStatus(False, fehler="Connection refused"))
    ki, status = make_ki(BACKEND_OLLAMA, "gemma4:26b-mlx", cache_dir=tmp_path)
    assert ki is None and status.zustand == "fehlt" and "ollama serve" in status.meldung
    monkeypatch.setattr(ki_ollama, "ollama_status", _status)
    ki, status = make_ki(BACKEND_OLLAMA, "qwen3.6:27b-mlx", cache_dir=tmp_path)
    assert ki is None and status.zustand == "fehlt" and "ollama pull qwen3.6:27b-mlx" in status.meldung
    ki, status = make_ki(BACKEND_OLLAMA, "claude-sonnet-5", cache_dir=tmp_path)  # Claude-ID nach dem Umschalten
    assert isinstance(ki, OllamaKi) and ki.modell == DEFAULT_OLLAMA_MODELL and status.zustand == "bereit"
    assert status.modell == DEFAULT_OLLAMA_MODELL and "lokal" in status.meldung
    assert "claude" not in status.meldung.lower()  # die Souffleur-Karte zeigt die Meldung: kein Produktname


# --- Einstellungen -----------------------------------------------------------------------------


def test_optionen_tragen_dienst_je_modell():
    opt = einstellungen.optionen({})
    assert [d["id"] for d in opt["ki_dienste"]] == ["claude-agent", "ollama"]
    souffleur = opt["souffleur_models"]
    assert {m["dienst"] for m in souffleur} == {"claude-agent", "ollama"}
    assert [m["id"] for m in souffleur if m["dienst"] == "ollama"] == list(OLLAMA_MODELLE)
    assert einstellungen.modelle("ollama", "agent") == OLLAMA_MODELLE
    assert "claude-opus-5" in einstellungen.modelle("claude-agent", "agent")
    # Ein per Umgebung gesetztes Modell ausserhalb der Listen bleibt waehlbar - mit dem aktuellen Dienst.
    opt = einstellungen.optionen({"souffleur_backend": "ollama", "souffleur_model": "mistral:7b"})
    assert opt["souffleur_models"][0] == {"id": "mistral:7b", "label": "mistral:7b", "dienst": "ollama"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from audioscribe.config import settings
    from audioscribe.ui import server, state

    # Basis ist das von conftest abgeschirmte state.settings - nie die Einstellungen des Rechners.
    fake = replace(
        state.settings, cache_dir=tmp_path / "cache", agent_skills_dir=tmp_path / "skills",
        agent_output_dir=tmp_path / "analysen", output_dir=tmp_path / "output",
    )
    monkeypatch.setattr(server, "settings", fake)
    monkeypatch.setattr(state, "settings", fake)
    return TestClient(server.create_app())


def test_api_agent_defaults_folgen_dem_dienst(client):
    d = client.get("/api/agent/defaults").json()
    assert d["dienst"] == "claude-agent" and d["model"] == "claude-opus-5" and "claude-opus-5" in d["models"]
    r = client.post("/api/einstellungen", json={"ki_dienst": "ollama", "souffleur_model": "gemma4:26b-mlx"})
    assert r.status_code == 200 and r.json()["werte"]["ki_dienst"] == "ollama"
    d = client.get("/api/agent/defaults").json()
    assert d["dienst"] == "ollama" and d["model"] == DEFAULT_OLLAMA_MODELL and d["models"] == list(OLLAMA_MODELLE)


# --- KI-Analyse lokal (experimentell) ---------------------------------------------------------


def test_sdk_env_leitet_nur_lokal_um():
    assert sdk_env(BACKEND_CLAUDE) == {}
    env = sdk_env(BACKEND_OLLAMA)
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama" and env["ANTHROPIC_BASE_URL"].startswith("http")


def test_pruefe_lokal(monkeypatch):
    monkeypatch.setattr(ki_ollama, "ollama_status", lambda url, **kw: OllamaStatus(False, fehler="refused"))
    with pytest.raises(RuntimeError, match="ollama serve"):
        pruefe_lokal("gemma4:26b-mlx")
    monkeypatch.setattr(ki_ollama, "ollama_status", _status)
    with pytest.raises(RuntimeError, match="ollama pull qwen3.6:27b-mlx"):
        pruefe_lokal("qwen3.6:27b-mlx")
    zeile = pruefe_lokal("gemma4:26b-mlx")
    assert zeile.startswith("[experimentell]") and "OLLAMA_CONTEXT_LENGTH" in zeile and "0.19.0" in zeile


def test_auftrag_und_argv_mit_ki_dienst(tmp_path, monkeypatch):
    assert Auftrag(name="x", quelle=tmp_path, ausgabe=tmp_path).dienst == "claude-agent"
    opts = AnalyseOptions(source=tmp_path, name="x", output_dir=tmp_path)
    assert not any(a.startswith("--ki-dienst") for a in build_analyze_argv(opts, prefix=[]))
    argv = build_analyze_argv(replace(opts, dienst="ollama", model="gemma4:26b-mlx"), prefix=[])
    assert "--ki-dienst=ollama" in argv and "--model=gemma4:26b-mlx" in argv
    # Der echte Parser kennt das Flag; unbekannte Dienste lehnt er ab.
    from audioscribe import cli
    from audioscribe.agent import kommando

    seen: dict = {}
    monkeypatch.setattr(kommando, "analyze", lambda args, resolve: seen.update(vars(args)) or 0)
    assert cli.main(argv) == 0 and seen["ki_dienst"] == "ollama"
    with pytest.raises(SystemExit):
        cli.main(["analyze", str(tmp_path), "--ki-dienst", "wolke"])


def test_lokaler_lauf_zaehlt_keinen_verbrauch(tmp_path):
    zeilen: list[str] = []
    auftrag = Auftrag(name="Probe", quelle=tmp_path / "q", ausgabe=tmp_path / "o", dienst=BACKEND_OLLAMA, model="gemma4:26b-mlx")
    sitzung = AnalyseSitzung(auftrag, [], emit=zeilen.append, status_zeilen=True)
    sitzung.workspace.mkdir(parents=True)
    zwischen = SimpleNamespace(message_id="m1", usage={"input_tokens": 500, "output_tokens": 20})
    assert sitzung._zwischenstand(zwischen) is False and not sitzung._vorlaeufig
    ergebnis = SimpleNamespace(
        session_id="s1", num_turns=3, is_error=False, errors=[], result="", subtype="success",
        usage={"input_tokens": 1000, "output_tokens": 100}, model_usage=None, total_cost_usd=0.25,
    )
    assert sitzung._record_result(ergebnis) is True
    m = sitzung.manifest
    assert m.status == "fertig" and m.kosten_usd is None and not Verbrauch.aus_dict(m.tokens).tokens
    assert sitzung.fortschritt.verbrauch["tokens"] == 0
    assert any("[Verbrauch] lokal, zaehlt nicht (1100 Tokens gemeldet)" in z for z in zeilen)


def test_system_append_mit_lokalem_hinweis():
    from audioscribe.agent.prompt import system_append

    assert "lokales Modell" not in system_append()
    text = system_append(lokal=True)
    assert text.endswith(system_append(lokal=False)[-40:]) is False and "ohne Bilder weiter" in text
    assert text.startswith(system_append()[:200])


# --- Doctor ------------------------------------------------------------------------------------


def test_doctor_ki_lokal(monkeypatch):
    from audioscribe import doctor
    from audioscribe.config import settings

    monkeypatch.setattr(ki_ollama, "ollama_status", lambda url, **kw: OllamaStatus(False, fehler="refused"))
    r = doctor._check_ollama()
    assert r.status == "OK" and r.name == "KI lokal" and "nicht eingerichtet (optional)" in r.detail
    monkeypatch.setattr(doctor, "settings", replace(settings, souffleur_backend="ollama"))
    r = doctor._check_ollama()
    assert r.status == "WARN" and "als KI-Dienst eingestellt" in r.detail and "ollama serve" in r.detail
    monkeypatch.setattr(ki_ollama, "ollama_status", _status)
    r = doctor._check_ollama()
    assert r.status == "OK" and "Ollama 0.19.0" in r.detail and f"Souffleur: {DEFAULT_OLLAMA_MODELL}" in r.detail
    assert "OLLAMA_CONTEXT_LENGTH" in r.detail
    monkeypatch.setattr(doctor, "settings", replace(settings, souffleur_backend="ollama", agent_model="qwen3.6:27b-mlx"))
    r = doctor._check_ollama()
    assert r.status == "WARN" and "Analyse: qwen3.6:27b-mlx fehlt -> 'ollama pull qwen3.6:27b-mlx'" in r.detail


# --- Echter Dienst (nur auf Wunsch) -----------------------------------------------------------


@pytest.mark.skipif(os.environ.get("AUDIOSCRIBE_TEST_KI_OLLAMA") != "1", reason="echter Ollama-Aufruf nur auf Wunsch")
def test_echter_ollama_aufruf(tmp_path):
    """Rauchtest gegen den laufenden Dienst mit dem konfigurierten Default-Modell."""
    ki, status = make_ki(BACKEND_OLLAMA, "", cache_dir=tmp_path, log=print)
    assert status.zustand == "bereit", status.meldung
    schema = {"type": "object", "required": ["antwort"], "properties": {"antwort": {"type": "string"}}}
    antwort = ki.antworte(KiAuftrag("Antworte knapp als JSON.", "Schreibe 'ok' ins Feld antwort.", schema, timeout_s=180))
    print(f"\n{antwort.modell}: {antwort.antwort_s:.1f} s (laden {antwort.start_s:.1f} s) -> {antwort.daten}")
    assert antwort.daten["antwort"] and antwort.verbrauch is None
