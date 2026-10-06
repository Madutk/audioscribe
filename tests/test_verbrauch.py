"""KI-Verbrauch: Rechnen, Zähler, Souffleur-Dienst, Analyse-Sitzung, Runner, Route, Oberfläche."""

from __future__ import annotations

import json
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from audioscribe.agent.fortschritt import STATUS_PREFIX, parse_status_line
from audioscribe.agent.manifest import Manifest, load_manifest, save_manifest
from audioscribe.agent.material import Auftrag
from audioscribe.agent.runner import AnalyseSitzung
from audioscribe.ui.jobs import AnalyseOptions
from audioscribe.ui.runner import AnalyseRunner
from audioscribe.verbrauch import (
    QUELLE_ANALYSE,
    QUELLE_SOUFFLEUR,
    Verbrauch,
    Zaehler,
    aus_ergebnis,
    aus_usage,
)

STATIC = Path(__file__).resolve().parents[1] / "src" / "audioscribe" / "ui" / "static"


# --- Rechnen --------------------------------------------------------------------------------


def test_verbrauch_addiert_und_kennt_fehlenden_preis():
    a = Verbrauch(100, 20, 300, 40, kosten_usd=0.01, aufrufe=1)
    b = Verbrauch(1, 2, 3, 4, kosten_usd=None, aufrufe=1)
    summe = a + b
    assert (summe.eingabe, summe.ausgabe, summe.cache_lesen, summe.cache_schreiben) == (101, 22, 303, 44)
    assert summe.tokens == 470 and summe.aufrufe == 2 and summe.kosten_usd == pytest.approx(0.01)
    assert (b + b).kosten_usd is None  # kein Preis genannt bleibt "kein Preis", nicht 0
    assert Verbrauch.aus_dict(summe.als_dict()) == Verbrauch(101, 22, 303, 44, 0.01, 2)
    assert Verbrauch.aus_dict("quatsch") == Verbrauch() and Verbrauch.aus_dict({"eingabe": -5, "ausgabe": True}) == Verbrauch()


def test_minus_ist_die_differenz_laufender_summen_und_nie_negativ():
    vorher = Verbrauch(100, 20, 0, 0, kosten_usd=0.10, aufrufe=1)
    jetzt = Verbrauch(250, 60, 10, 0, kosten_usd=0.25, aufrufe=1)
    dazu = jetzt.minus(vorher)
    assert (dazu.eingabe, dazu.ausgabe, dazu.cache_lesen) == (150, 40, 10)
    assert dazu.kosten_usd == pytest.approx(0.15) and dazu.aufrufe == 1
    # Zurueckgesetzte Summe des Dienstes: nichts Negatives buchen.
    assert vorher.minus(jetzt) == Verbrauch(0, 0, 0, 0, 0.0, 1)
    assert jetzt.minus(Verbrauch()).kosten_usd == pytest.approx(0.25)


def test_text_fuers_protokoll():
    assert Verbrauch(182_000, 340, kosten_usd=1.239).text() == "182.340 Tokens, ca. 1,24 $ (API-Gegenwert)"
    assert Verbrauch(900, 100, kosten_usd=0.004).text() == "1.000 Tokens, ca. unter 0,01 $ (API-Gegenwert)"
    assert Verbrauch(5, 5).text() == "10 Tokens"


def test_aus_ergebnis_nimmt_model_usage_sonst_usage():
    je_modell = SimpleNamespace(
        total_cost_usd=0.42,
        usage={"input_tokens": 1, "output_tokens": 1},
        model_usage={
            "gross": {"inputTokens": 100, "outputTokens": 50, "cacheReadInputTokens": 1000, "cacheCreationInputTokens": 200, "costUSD": 0.4},
            "klein": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0, "costUSD": 0.02},
        },
    )
    assert aus_ergebnis(je_modell) == Verbrauch(110, 55, 1000, 200, 0.42, 1)
    nur_usage = SimpleNamespace(
        total_cost_usd=None, model_usage=None,
        usage={"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 5},
    )
    assert aus_ergebnis(nur_usage) == Verbrauch(7, 3, 20, 5, None, 1)
    assert aus_ergebnis(SimpleNamespace()) == Verbrauch(aufrufe=1)
    assert aus_usage(None) == Verbrauch() and aus_usage({"input_tokens": "viele"}) == Verbrauch()


def test_zaehler_trennt_laufende_aktivitaet_und_summe():
    z = Zaehler()
    leer = z.snapshot()
    assert leer["gesamt"]["tokens"] == 0 and leer["gesamt"]["kosten_usd"] is None
    z.buche(QUELLE_SOUFFLEUR, Verbrauch(100, 10, kosten_usd=0.01, aufrufe=1))
    z.buche(QUELLE_SOUFFLEUR, Verbrauch(200, 20, kosten_usd=0.02, aufrufe=1))
    z.setze(QUELLE_ANALYSE, Verbrauch(1000, 0, kosten_usd=None))
    z.setze(QUELLE_ANALYSE, Verbrauch(5000, 500, kosten_usd=1.0, aufrufe=1))  # ersetzt, addiert nicht
    s = z.snapshot()
    assert s["quellen"]["souffleur"]["aktuell"]["tokens"] == 330 and s["quellen"]["souffleur"]["aktuell"]["aufrufe"] == 2
    assert s["quellen"]["analyse"]["aktuell"]["tokens"] == 5500
    assert s["gesamt"]["tokens"] == 5830 and s["gesamt"]["kosten_usd"] == pytest.approx(1.03)
    # Neue Sitzung: die laufende Anzeige beginnt bei null, die Summe bleibt.
    z.beginne(QUELLE_SOUFFLEUR)
    s = z.snapshot()
    assert s["quellen"]["souffleur"]["aktuell"]["tokens"] == 0 and s["quellen"]["souffleur"]["gesamt"]["tokens"] == 330
    assert s["gesamt"]["tokens"] == 5830


# --- Souffleur: der KI-Dienst bucht je Aufruf ------------------------------------------------


@dataclass
class _Ergebnis:
    is_error: bool = False
    structured_output: object = None
    session_id: str = "s1"
    result: str | None = None
    subtype: str = "success"
    total_cost_usd: float | None = 0.0031
    usage: dict | None = None
    model_usage: dict | None = None


def _falsches_sdk(monkeypatch, ergebnis: _Ergebnis) -> None:
    async def query(*, prompt, options):
        yield SimpleNamespace(art="system")
        yield ergebnis

    modul = types.ModuleType("claude_agent_sdk")
    modul.ClaudeAgentOptions = lambda **kw: kw
    modul.ResultMessage = _Ergebnis
    modul.query = query
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", modul)


def test_claude_ki_bucht_verbrauch_auch_bei_fehler(tmp_path, monkeypatch):
    pytest.importorskip("anyio")
    from audioscribe.souffleur.ki import AttrappeKi, ClaudeAgentKi, KiAuftrag, KiFehler

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    gebucht: list[Verbrauch] = []
    ki = ClaudeAgentKi("modell-x", cwd=tmp_path / "souffleur", on_verbrauch=gebucht.append)
    auftrag = KiAuftrag("system", "prompt", {"type": "object"})

    usage = {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    _falsches_sdk(monkeypatch, _Ergebnis(structured_output={"befunde": []}, usage=usage))
    antwort = ki.antworte(auftrag)
    assert antwort.verbrauch == Verbrauch(1200, 80, 0, 0, 0.0031, 1) and gebucht == [antwort.verbrauch]

    # Der Dienst meldet einen Fehler: verbraucht wurde trotzdem.
    _falsches_sdk(monkeypatch, _Ergebnis(is_error=True, result="kaputt", usage=usage, total_cost_usd=0.002))
    with pytest.raises(KiFehler):
        ki.antworte(auftrag)
    assert len(gebucht) == 2 and gebucht[1].kosten_usd == 0.002

    # Lokal (Attrappe): kein Verbrauch.
    assert AttrappeKi().antworte(KiAuftrag("s", "p", {}, kontext={"segmente": []})).verbrauch is None


# --- KI-Analyse: laufende Summen, Zwischenstand, Statuszeile ----------------------------------


def _ergebnis(kosten: float, eingabe: int, ausgabe: int) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="sess", num_turns=2, total_cost_usd=kosten, is_error=False, errors=None, result="ok",
        subtype="success", usage=None,
        model_usage={"m": {"inputTokens": eingabe, "outputTokens": ausgabe, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}},
    )


def test_analyse_zaehlt_laufende_summen_nicht_doppelt(tmp_path):
    zeilen: list[str] = []
    auftrag = Auftrag(name="Probe", quelle=tmp_path / "q", ausgabe=tmp_path / "o")
    sitzung = AnalyseSitzung(auftrag, [], emit=zeilen.append, status_zeilen=True)

    # Zwischenstand: dieselbe Antwort (mehrere Bloecke) zaehlt einmal.
    antwort = SimpleNamespace(message_id="m1", usage={"input_tokens": 400, "output_tokens": 10})
    assert sitzung._zwischenstand(antwort) is True
    assert sitzung._zwischenstand(antwort) is False
    assert sitzung._zwischenstand(SimpleNamespace(message_id=None, usage={"input_tokens": 5})) is False
    assert sitzung.fortschritt.verbrauch["tokens"] == 410 and sitzung.fortschritt.verbrauch["vorlaeufig"] is True

    # Erstes Ergebnis ersetzt den Zwischenstand durch die verbindlichen Zahlen.
    assert sitzung._record_result(_ergebnis(0.10, 1000, 100)) is True
    v = sitzung.fortschritt.verbrauch
    assert (v["tokens"], v["kosten_usd"], v["vorlaeufig"]) == (1100, 0.10, False)
    # Folgenachricht in derselben Verbindung: der Dienst meldet die Summe, gezaehlt wird die Differenz.
    sitzung._record_result(_ergebnis(0.25, 2500, 300))
    v = sitzung.fortschritt.verbrauch
    assert v["tokens"] == 2800 and v["kosten_usd"] == pytest.approx(0.25)

    manifest = load_manifest(auftrag.workspace)
    assert manifest.kosten_usd == pytest.approx(0.25)  # nicht 0,35
    assert manifest.tokens == {"eingabe": 2500, "ausgabe": 300, "cache_lesen": 0, "cache_schreiben": 0}
    assert "[Verbrauch] 1.100 Tokens, ca. 0,10 $ (API-Gegenwert)" in zeilen
    status = [parse_status_line(z) for z in zeilen if z.startswith(STATUS_PREFIX)]
    assert status[-1]["verbrauch"]["tokens"] == 2800


def test_analyse_addiert_auf_fruehere_laeufe_im_manifest(tmp_path):
    auftrag = Auftrag(name="Probe", quelle=tmp_path / "q", ausgabe=tmp_path / "o", resume="alt")
    sitzung = AnalyseSitzung(auftrag, [], emit=lambda z: None)
    sitzung.manifest = Manifest(name="Probe", quelle="q", kosten_usd=1.0, tokens={"eingabe": 100, "ausgabe": 10})
    sitzung._record_result(_ergebnis(0.5, 50, 5))
    assert sitzung.manifest.kosten_usd == pytest.approx(1.5)
    assert sitzung.manifest.tokens == {"eingabe": 150, "ausgabe": 15, "cache_lesen": 0, "cache_schreiben": 0}
    assert sitzung.fortschritt.verbrauch["tokens"] == 55  # die Anzeige zeigt nur diesen Lauf


def test_analyse_runner_meldet_verbrauch_an_den_zaehler(tmp_path):
    opts = AnalyseOptions(source=tmp_path, name="Lauf", output_dir=tmp_path / "o")
    ws = tmp_path / "o" / "lauf"
    save_manifest(ws, Manifest(name="x", quelle="q", status="fertig", kosten_usd=9.0))
    stand = Verbrauch(3000, 200, kosten_usd=0.3, aufrufe=1).als_dict()
    zeile = STATUS_PREFIX + json.dumps({"todos": [], "verbrauch": stand})
    zaehler = Zaehler()
    zaehler.buche(QUELLE_ANALYSE, Verbrauch(10, 0, kosten_usd=0.01))  # ein frueherer Lauf
    runner = AnalyseRunner(zaehler=zaehler)
    runner.start(opts, argv_builder=lambda o: [sys.executable, "-c", f"print({zeile!r}, flush=True)"])
    ende = time.monotonic() + 30
    while runner.snapshot()["running"] and time.monotonic() < ende:
        time.sleep(0.05)
    snap = runner.snapshot()
    assert snap["result"]["verbrauch"]["tokens"] == 3200 and snap["result"]["verbrauch"]["kosten_usd"] == 0.3
    quelle = zaehler.snapshot()["quellen"]["analyse"]
    assert quelle["aktuell"]["tokens"] == 3200 and quelle["gesamt"]["tokens"] == 3210


# --- Route und Oberfläche --------------------------------------------------------------------


def test_route_verbrauch_beginnt_leer(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server, state

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "ui-state.json")
    daten = TestClient(server.create_app()).get("/api/verbrauch").json()
    assert daten["gesamt"]["tokens"] == 0 and daten["gesamt"]["kosten_usd"] is None
    assert set(daten["quellen"]) == {"souffleur", "analyse"}
    assert daten["quellen"]["souffleur"]["aktuell"]["aufrufe"] == 0


def test_kopf_zeigt_den_verbrauch_dezent_und_ehrlich():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "js" / "verbrauch.js").read_text(encoding="utf-8")
    kopf = html[html.index('<header class="top">'):html.index("</header>")]
    # Zwischen Abstandhalter und Zahnrad, anfangs unsichtbar, Einzelheiten im Popover.
    assert kopf.index('class="spacer"') < kopf.index('id="kiVerbrauch"') < kopf.index('id="openSettings"')
    knopf = kopf[kopf.index('id="kiVerbrauch"'):kopf.index("</button>", kopf.index('id="kiVerbrauch"'))]
    assert " hidden" in knopf and 'popovertarget="kiVerbrauchInfo"' in knopf
    assert 'id="kiVerbrauchInfo" popover' in kopf and '<symbol id="i-coins"' in html
    # Der Preis ist ein Gegenwert, keine Rechnung - das steht dabei.
    assert "Gegenwert zu API-Preisen" in kopf and "nichts abgerechnet" in kopf
    assert "api('/api/verbrauch')" in js and "currency: 'USD'" in js and "`≈ ${" in js
    assert "starteVerbrauch();" in (STATIC / "js" / "main.js").read_text(encoding="utf-8")
