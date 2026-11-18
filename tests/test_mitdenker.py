"""Mitdenker (zweite Spur des Souffleurs): reine Logik ohne Netz; der KI-Dienst ist eine Attrappe."""

import json
import sys
import threading
import time
import types
from pathlib import Path

from audioscribe.souffleur import SOUFFLEUR_DATEIEN, mitdenker
from audioscribe.souffleur.ki import AttrappeKi, KiAntwort, KiAuftrag, KiFehler, KiStatus
from audioscribe.souffleur.markierung import Fundstelle

WIKI = Path(__file__).parent / "data" / "souffleur" / "wiki"
SRC = Path(__file__).parent.parent / "src" / "audioscribe"


def _segmente():
    return [
        {"id": 1, "start": 0.0, "end": 5.0, "speaker": "Ich", "delay": 0.2,
         "text": "Rechnungen ab 5.000 Euro gibt bei uns die Teamleitung frei."},
        {"id": 2, "start": 6.0, "end": 12.0, "speaker": "Gast", "delay": 0.2,
         "text": "Man könnte die Rechnungen vielleicht automatisch vorprüfen, bevor sie in die Freigabe gehen."},
        {"id": 3, "start": 13.0, "end": 18.0, "speaker": "Ich", "delay": 0.2,
         "text": "Gut, die Vorprüfung der Rechnungen machen wir so, abgemacht."},
    ]


def _souffleur(tmp_path, *, wiki=None, ki=None, mitdenk_ki=None, **extra):
    from audioscribe.souffleur.kern import Souffleur
    from audioscribe.souffleur.konfig import SouffleurKonfig

    konfig = SouffleurKonfig(wiki_dir=wiki, backend="attrappe", fenster_leerlauf_s=0.0, **extra)
    ereignisse = []
    s = Souffleur(konfig, ki=ki if ki is not None else AttrappeKi(),
                  ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"), on_hinweis=ereignisse.append,
                  mitdenk_ki=mitdenk_ki)
    return s, ereignisse


def _starte(s, session_dir, segmente=None):
    s.starte(session_dir)
    ende = time.monotonic() + 10
    while s.status()["wiki"]["zustand"] == "laedt" and time.monotonic() < ende:
        time.sleep(0.05)
    for seg in segmente if segmente is not None else _segmente():
        s.beobachte(seg, empfangen_mono=time.monotonic())


def _warte(bedingung, sekunden=5.0):
    ende = time.monotonic() + sekunden
    while not bedingung() and time.monotonic() < ende:
        time.sleep(0.02)
    return bedingung()


def _karten(ereignisse):
    return [e for e in ereignisse if e.get("type") == mitdenker.EREIGNIS]


def _fund():
    fdict = {"id": "F1", "datei": "wiki/freigaben.md", "ueberschrift": "Grenzen", "zeile": 5,
             "auszug": "Rechnungen ab 5.000 Euro gibt die Teamleitung frei. Darunter die Sachbearbeitung."}
    return {"F1": (fdict, Fundstelle("wiki/freigaben.md", "Grenzen", 5, fdict["auszug"]))}


def _roh(**felder):
    return {"art": "gedanke", "segment_id": 1, "aussage": "", "titel": "Vorprüfung", "ki_text": "Ein Schritt weiter.",
            "fundstelle_id": None, "wiki_zitat": None, "allgemeinwissen": False, "relevanz": "hoch", **felder}


# --- Prüfung -----------------------------------------------------------------------------


def test_bestaetigung_braucht_woertliches_zitat_und_woertliche_aussage():
    je_id = {1: _segmente()[0]}
    gut = mitdenker.pruefe_karte(_roh(art="bestaetigung", aussage="gibt bei uns die Teamleitung frei", fundstelle_id="F1",
                                      wiki_zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei."), je_id, _fund())
    assert gut is not None and gut.herkunft == ["wiki", "gespraech"] and gut.fundstellen[0].zeile == 5
    erfunden = _roh(art="bestaetigung", aussage="gibt bei uns die Teamleitung frei", fundstelle_id="F1",
                    wiki_zitat="Rechnungen ab 10.000 Euro gibt der Vorstand frei.")
    assert mitdenker.pruefe_karte(erfunden, je_id, _fund()) is None
    ohne_aussage = _roh(art="bestaetigung", aussage="erfundener Satz des Sprechers", fundstelle_id="F1",
                        wiki_zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei.")
    assert mitdenker.pruefe_karte(ohne_aussage, je_id, _fund()) is None
    # Zu kurze "Belege" belegen nichts (Review K4).
    kurz = _roh(art="bestaetigung", aussage="gibt bei uns die Teamleitung frei", fundstelle_id="F1", wiki_zitat="Euro")
    assert mitdenker.pruefe_karte(kurz, je_id, _fund()) is None


def test_gedanke_ohne_beleg_bleibt_und_herkunft_setzt_der_code():
    je_id = {1: _segmente()[0]}
    # Das Modell behauptet, nichts Eigenes beizutragen - ohne Beleg kann es nur aus ihm stammen.
    k = mitdenker.pruefe_karte(_roh(aussage="frei erfunden, steht nicht im Segment", wiki_zitat="auch erfunden",
                                    fundstelle_id="F1"), je_id, _fund())
    assert k is not None and k.aussage == "" and k.wiki_zitat is None and k.fundstellen == []
    assert k.herkunft == ["allgemeinwissen"] and k.ki_erzeugt is True
    mit = mitdenker.pruefe_karte(_roh(aussage="gibt bei uns die Teamleitung frei", allgemeinwissen=True), je_id, _fund())
    assert mit.herkunft == ["gespraech", "allgemeinwissen"]


def test_erkenntnis_braucht_aussage_und_mittel_nur_sensibel_und_unbekanntes_faellt_weg():
    je_id = {1: _segmente()[0]}
    assert mitdenker.pruefe_mit_grund(_roh(art="erkenntnis"), je_id, {})[1] == "ohne_aussage"
    assert mitdenker.pruefe_mit_grund(_roh(relevanz="mittel"), je_id, {}) == (None, "relevanz_mittel")
    assert mitdenker.pruefe_karte(_roh(relevanz="mittel"), je_id, {}, sensibel=True) is not None
    # Eine doppelt wörtlich geprüfte Bestätigung kommt auch mit "mittel" durch - sonst käme nie eine.
    best = _roh(art="bestaetigung", aussage="gibt bei uns die Teamleitung frei", fundstelle_id="F1", relevanz="mittel",
                wiki_zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei.")
    assert mitdenker.pruefe_karte(best, je_id, _fund()) is not None
    assert mitdenker.pruefe_mit_grund({**best, "wiki_zitat": "Rechnungen ab 10.000 Euro gibt der Vorstand frei."},
                                      je_id, _fund()) == (None, "ohne_zitat")
    assert mitdenker.pruefe_karte(_roh(segment_id=99), je_id, {}) is None
    assert mitdenker.pruefe_karte(_roh(art="widerspruch"), je_id, {}) is None
    assert mitdenker.pruefe_karte("kein dict", je_id, {}) is None
    assert mitdenker.pruefe_karte(_roh(titel=""), je_id, {}) is None


def test_dubletten_ueber_die_ganze_sitzung():
    je_id = {1: _segmente()[0], 2: {**_segmente()[1], "start": 3000.0, "end": 3005.0}}
    alt = mitdenker.pruefe_karte(_roh(titel="Automatische Vorprüfung der Rechnungen",
                                      ki_text="Kriterien für die Vorprüfung festlegen."), je_id, {})
    gleich = mitdenker.pruefe_karte(_roh(segment_id=2, titel="Vorprüfung der Rechnungen automatisch",
                                         ki_text="Kriterien für die Vorprüfung festlegen."), je_id, {})
    anders = mitdenker.pruefe_karte(_roh(segment_id=2, titel="Schulung der Sachbearbeitung",
                                         ki_text="Wer schult, ist ungeklärt."), je_id, {})
    assert mitdenker.ist_dublette(gleich, [alt]) and not mitdenker.ist_dublette(anders, [alt])
    # Eine Frage, die der Souffleur schon aus derselben Fundstelle beantwortet hat, wird nicht bestätigt.
    best = mitdenker.pruefe_karte(_roh(art="bestaetigung", aussage="gibt bei uns die Teamleitung frei", fundstelle_id="F1",
                                       wiki_zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei."), je_id, _fund())
    frage = {"art": "frage", "segment_id": 1, "fundstelle": "wiki/freigaben.md › Grenzen"}
    assert mitdenker.ist_dublette(best, [], [frage]) and not mitdenker.ist_dublette(best, [], [])


def test_transkript_teilt_in_kontext_und_neu_und_kappt_das_aelteste():
    segs = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 5, "text": "x" * 100, "empfangen_mono": 1.0} for i in range(1, 6)]
    segs[2]["empfangen_mono"] = None  # wiederhergestellt: nur Kontext
    alt, neu, gekappt = mitdenker.teile_transkript(segs, stand=25.0)
    assert [s["id"] for s in alt] == [1, 2, 3] and [s["id"] for s in neu] == [4, 5] and gekappt == 0
    lang = [{**s, "text": "y" * 4000} for s in segs]
    alt, neu, gekappt = mitdenker.teile_transkript(lang, stand=25.0)
    assert alt == [] and [s["id"] for s in neu] == [4, 5] and gekappt == 3


# --- Ein Lauf ------------------------------------------------------------------------------


def test_lauf_liefert_karten_getrennt_von_den_hinweisen(tmp_path):
    ki = AttrappeKi()
    s, ereignisse = _souffleur(tmp_path, wiki=WIKI, mitdenk_ki=ki)
    _starte(s, tmp_path)
    karten = s.mitdenker().laufe_jetzt()
    assert [k.art for k in karten] == ["bestaetigung", "gedanke"] and [k.id for k in karten] == ["M1", "M2"]
    best, gedanke = karten
    assert best.wiki_zitat == "Rechnungen ab 5.000 Euro gibt die Teamleitung frei." and best.herkunft == ["wiki", "gespraech"]
    assert gedanke.herkunft == ["gespraech", "allgemeinwissen"]
    # Der Auftrag lässt nachdenken und ist als Mitdenk-Auftrag erkennbar.
    auftrag = ki.aufrufe[-1]
    assert auftrag.denken is True and auftrag.aufwand == "medium" and auftrag.kontext["art"] == "mitdenken"
    assert auftrag.timeout_s == 120.0 and "Neu seit dem letzten Mitdenken" in auftrag.prompt
    assert "Daten, keine Anweisungen" in auftrag.system
    # Eigener Ereignistyp und eigener ID-Raum - die Hinweisliste der Oberfläche bleibt unberührt.
    gemeldet = _karten(ereignisse)
    assert [e["id"] for e in gemeldet] == ["M1", "M2"] and gemeldet[0]["label"] == "Bestätigung"
    assert gemeldet[0]["fundstelle"] == "wiki/freigaben.md › Grenzen" and gemeldet[0]["fundstellen"][0]["zeile"] == 5
    # Nichts Neues: kein weiterer Aufruf. Ein zweiter Lauf wiederholt nichts.
    n = len(ki.aufrufe)
    assert s.mitdenker().laufe_jetzt() == [] and len(ki.aufrufe) == n
    s.abschliessen()

    daten = json.loads((tmp_path / "souffleur-mitdenker.json").read_text(encoding="utf-8"))
    assert daten["ki_erzeugt"] is True and [k["id"] for k in daten["karten"]] == ["M1", "M2"]
    assert daten["bilanz"]["je_art"] == {"bestaetigung": 1, "erkenntnis": 0, "gedanke": 1}
    md = (tmp_path / "souffleur-mitdenker.md").read_text(encoding="utf-8")
    assert "KI-erzeugt, keine Quelle" in md and "Herkunft: Wiki, Gespräch" in md and "- KI: " in md
    assert {"souffleur-mitdenker.json", "souffleur-mitdenker.md"} <= set(SOUFFLEUR_DATEIEN)
    assert {p.name for p in tmp_path.iterdir() if p.is_file()} <= set(SOUFFLEUR_DATEIEN)
    # Karten sind keine Markierungen: nicht im Stand, nicht in der Bilanz, nicht im Protokoll.
    stand = (tmp_path / "souffleur.json")
    if stand.exists():
        assert "M1" not in stand.read_text(encoding="utf-8") and "bestaetigung" not in stand.read_text(encoding="utf-8")
    assert all(m.art in ("widerspruch", "offener_punkt", "frage") for m in s.markierungen())
    assert s.status()["mitdenken"]["karten"] == 2 and s.status()["hinweise"] == len(s.markierungen())


def test_vorgabe_ist_aus_und_der_schalter_wirkt_live(tmp_path):
    ki = AttrappeKi()
    s, ereignisse = _souffleur(tmp_path, wiki=WIKI, mitdenk_ki=ki, mitdenken_takt_s=0.0, mitdenken_min_woerter=1)
    _starte(s, tmp_path)
    assert s.status()["mitdenken"] == {**s.status()["mitdenken"], "aktiv": False, "zustand": "aus", "verfuegbar": True}
    time.sleep(1.3)
    assert ki.aufrufe == [] and _karten(ereignisse) == []
    s.setze_mitdenken(True)
    assert _warte(lambda: len(_karten(ereignisse)) == 2)
    assert s.status()["mitdenken"]["aktiv"] is True and s.status()["mitdenken"]["zustand"] in ("wartet", "denkt")
    s.abschliessen()


def test_ausloeser_takt_mindestmenge_und_leerlauf(tmp_path):
    s, _ = _souffleur(tmp_path)
    m = s.mitdenker()
    lang = " ".join(f"wort{i}" for i in range(50))

    def snap(jetzt, text, **extra):
        return {"aktiv": True, "beendet": False, "wiki_laedt": False, "jetzt": jetzt,
                "segmente": [{"id": 1, "start": 0.0, "end": 10.0, "text": text, "empfangen_mono": 1.0}], **extra}

    assert m._faellig(snap(100.0, lang)) == "takt"  # 90 s und 40 Inhaltswörter
    assert m._faellig(snap(60.0, lang)) == "leerlauf"  # Gespräch ruht seit 50 s
    assert m._faellig(snap(15.0, lang)) is None  # zu früh
    wenig = " ".join(f"wort{i}" for i in range(8))
    assert m._faellig(snap(100.0, wenig)) is None  # zu wenig Neues
    assert m._faellig(snap(100.0, lang, aktiv=False)) is None  # Souffleur ruht
    assert m._faellig(snap(100.0, lang, beendet=True)) is None
    assert m._faellig(snap(100.0, lang, wiki_laedt=True)) is None
    assert m._faellig({**snap(100.0, lang), "segmente": []}) is None


def test_nie_zwei_laeufe_und_die_schnelle_spur_wartet_nicht(tmp_path):
    drin, weiter = threading.Event(), threading.Event()

    class LangsameKi:
        modell = "x"; backend = "attrappe"; aufrufe = 0

        def antworte(self, auftrag):
            LangsameKi.aufrufe += 1
            drin.set()
            weiter.wait(10)
            return KiAntwort(daten={"karten": []}, start_s=0.1, antwort_s=0.2, modell="x")

    s, ereignisse = _souffleur(tmp_path, mitdenk_ki=LangsameKi())
    frage = {"id": 9, "start": 20.0, "end": 23.0, "speaker": "Ich", "delay": 0.2,
             "text": "Wer pflegt eigentlich die Lieferantenstammdaten?"}
    _starte(s, tmp_path)
    lauf = threading.Thread(target=s.mitdenker().laufe_jetzt)
    lauf.start()
    assert drin.wait(5) and s.status()["mitdenken"]["zustand"] == "aus"  # von Hand gestartet, Schalter aus
    assert s.mitdenker().laufe_jetzt() == [] and LangsameKi.aufrufe == 1  # kein zweiter Lauf daneben
    # Währenddessen liefert der Abgleich weiter - status() und beobachte() hängen nicht.
    s.beobachte(frage, empfangen_mono=time.monotonic())
    assert _warte(lambda: any(e.get("art") == "frage" for e in ereignisse))
    weiter.set()
    lauf.join(5)
    s.abschliessen()


def test_fehlerpause_ist_getrennt_von_der_schnellen_spur(tmp_path):
    class KaputteKi:
        modell = "x"; backend = "attrappe"

        def antworte(self, auftrag):
            raise KiFehler("Dienst weg")

    s, ereignisse = _souffleur(tmp_path, mitdenk_ki=KaputteKi())
    _starte(s, tmp_path)
    assert s.mitdenker().laufe_jetzt() == [] and s.mitdenker().laufe_jetzt() == []
    st = s.status()
    assert st["mitdenken"]["fehler"] == 2 and "Pause" in st["mitdenken"]["meldung"]
    assert st["ki"]["zustand"] == "bereit" and st["ki"]["fehler"] == 0
    s.setze_mitdenken(True)
    assert s.status()["mitdenken"]["zustand"] == "pause"
    s.abschliessen()
    zeilen = (tmp_path / "souffleur-diagnose.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum('"spur": "mitdenker"' in z and '"fehler"' in z for z in zeilen) == 2


def test_abschluss_startet_keinen_lauf_und_stop_verwirft(tmp_path):
    ki = AttrappeKi()
    s, ereignisse = _souffleur(tmp_path, mitdenk_ki=ki, mitdenken=True)  # Takt 90 s: im Test nie fällig
    _starte(s, tmp_path)
    s.abschliessen()
    assert ki.aufrufe == [] and _karten(ereignisse) == []
    assert not (tmp_path / "souffleur-mitdenker.json").exists()

    s2, ereignisse2 = _souffleur(tmp_path / "b", mitdenk_ki=AttrappeKi())
    (tmp_path / "b").mkdir()
    _starte(s2, tmp_path / "b")
    s2.stop()
    assert s2.mitdenker().laufe_jetzt() == [] and _karten(ereignisse2) == []


def test_wiederaufnahme_meldet_karten_erneut_und_denkt_altes_nicht_nochmal(tmp_path):
    s, _ = _souffleur(tmp_path, wiki=WIKI, mitdenk_ki=AttrappeKi())
    _starte(s, tmp_path)
    assert len(s.mitdenker().laufe_jetzt()) == 2
    s.abschliessen()

    ki = AttrappeKi()
    s2, ereignisse = _souffleur(tmp_path, wiki=WIKI, mitdenk_ki=ki)
    s2.starte(tmp_path)
    for seg in _segmente():
        s2.uebernehme(seg)  # wiederhergestellt: nur Kontext
    assert [e["id"] for e in _karten(ereignisse)] == ["M1", "M2"]
    assert s2.mitdenker().laufe_jetzt() == [] and ki.aufrufe == []
    neu = {"id": 4, "start": 30.0, "end": 36.0, "speaker": "Gast", "delay": 0.2,
           "text": "Wir könnten außerdem die Lieferanten vorab über die neue Prüfung informieren."}
    s2.beobachte(neu, empfangen_mono=time.monotonic())
    karten = s2.mitdenker().laufe_jetzt()
    assert [k.id for k in karten] == ["M3"] and [s["id"] for s in ki.aufrufe[-1].kontext["segmente"]] == [4]
    assert "[M2]" in ki.aufrufe[-1].prompt  # „Schon gesagt“
    s2.abschliessen()


def test_lokale_ki_ist_vorerst_nicht_verfuegbar(tmp_path):
    class LokaleKi:
        modell = "qwen"; backend = "ollama"

        def antworte(self, auftrag):
            raise AssertionError("der Mitdenker ruft die lokale KI nicht")

    s, ereignisse = _souffleur(tmp_path, mitdenk_ki=LokaleKi(), mitdenken=True, mitdenken_takt_s=0.0,
                               mitdenken_min_woerter=1)
    _starte(s, tmp_path)
    time.sleep(1.2)
    st = s.status()["mitdenken"]
    assert st["verfuegbar"] is False and st["zustand"] == "nicht_verfuegbar" and "lokalen KI" in st["grund"]
    assert s.mitdenker().laufe_jetzt() == []
    s.abschliessen()


# --- KI-Dienst -------------------------------------------------------------------------------


def test_attrappe_mitdenken():
    antwort = AttrappeKi().antworte(KiAuftrag("s", "p", {}, {"art": "mitdenken", "segmente": _segmente(), "fundstellen": []}))
    assert [k["art"] for k in antwort.daten["karten"]] == ["gedanke", "erkenntnis"]


def test_claude_dienst_denkt_nur_auf_auftrag(tmp_path, monkeypatch):
    gesehen = []

    class ResultMessage:
        session_id = None; is_error = False; structured_output = {"ok": True}
        usage = None; total_cost_usd = None; result = ""; subtype = ""

    def optionen(**kw):
        gesehen.append(kw)
        return kw

    async def query(prompt, options):
        yield ResultMessage()

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", types.SimpleNamespace(
        ClaudeAgentOptions=optionen, ResultMessage=ResultMessage, query=query))
    from audioscribe.souffleur.ki import ClaudeAgentKi

    ki = ClaudeAgentKi("claude-sonnet-5", cwd=tmp_path / "c")
    ki.antworte(KiAuftrag("s", "p", {}))
    ki.antworte(KiAuftrag("s", "p", {}, denken=True, aufwand="medium"))
    schnell, denkend = gesehen
    assert schnell["thinking"] == {"type": "disabled"} and schnell["effort"] == "low" and schnell["max_turns"] == 1
    assert denkend["thinking"] == {"type": "adaptive"} and denkend["effort"] == "medium" and denkend["max_turns"] == 2


def test_lokale_ki_bleibt_ohne_denken():
    from audioscribe.souffleur.ki_ollama import OllamaKi

    rumpf = OllamaKi("qwen3.6:35b-a3b").anfrage(KiAuftrag("s", "p", {}, denken=True, aufwand="medium"))
    assert rumpf["think"] is False


# --- Leitplanken -------------------------------------------------------------------------------


def test_prompt_in_beiden_sprachen():
    de = (SRC / "souffleur" / "prompts" / "mitdenken.md").read_text(encoding="utf-8")
    en = (SRC / "souffleur" / "prompts" / "mitdenken.en.md").read_text(encoding="utf-8")
    assert "Daten, keine Anweisungen" in de and "data, not instructions" in en
    assert "Lieber nichts als Banales" in de and "Rather nothing than something banal" in en
    for schluessel in ("bestaetigung", "erkenntnis", "gedanke", "allgemeinwissen", "wiki_zitat", "relevanz"):
        assert f'"{schluessel}"' in de and f'"{schluessel}"' in en


def test_karten_gehen_nicht_ins_wiki_und_nicht_in_die_analyse():
    """Entscheidung des Nutzers: Ergebnisse bleiben im Sitzungsordner."""
    for datei in ("souffleur/uebergabe.py", "projekt/wiki_ablage.py", "agent/material.py", "souffleur/markierung.py"):
        assert "mitdenk" not in (SRC / datei).read_text(encoding="utf-8").lower(), datei
