"""Souffleur (PRD §20): reine Logik ohne Netz; der KI-Dienst ist eine Attrappe."""

import json
import os
from pathlib import Path

import pytest

from audioscribe.souffleur import SOUFFLEUR_DATEIEN
from audioscribe.souffleur.ki import (
    BACKEND_ATTRAPPE,
    BACKEND_CLAUDE,
    AttrappeKi,
    AttrappenRegel,
    KiAuftrag,
    _slug,
    make_ki,
)

DATA = Path(__file__).parent / "data" / "souffleur"
WIKI = DATA / "wiki"
MEETING = DATA / "meeting"


# --- KI-Dienst ------------------------------------------------------------------------


def _fundstellen():
    return [
        {"id": "F1", "datei": "wiki/freigaben.md", "ueberschrift": "Grenzen",
         "auszug": "Rechnungen ab 5.000 Euro gibt die Teamleitung frei. Rechnungen unter 5.000 Euro gibt die Sachbearbeitung selbst frei."},
        {"id": "F2", "datei": "wiki/stammdaten.md", "ueberschrift": "Rollen",
         "auszug": "Die Pflege der Lieferantenstammdaten liegt beim Einkauf. Die Buchhaltung prüft nur die Bankverbindung."},
    ]


def test_attrappe_erkennt_fragen_offene_punkte_und_regeln():
    regel = AttrappenRegel(aussage="ab 10.000 Euro", fundstelle="freigaben.md › Grenzen",
                           zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei.")
    ki = AttrappeKi(regeln=[regel])
    segmente = [
        {"id": 1, "text": "Guten Morgen zusammen."},
        {"id": 2, "text": "Die Freigabe von Rechnungen ab 10.000 Euro macht bei uns die Teamleitung."},
        {"id": 3, "text": "Wer pflegt eigentlich die Lieferantenstammdaten?"},
        {"id": 4, "text": "Das ist doch klar, oder?"},
        {"id": 5, "text": "Wer die Schulung übernimmt, ist noch offen."},
        {"id": 6, "text": "Gibt es eine Vorgabe für die Reisekostenabrechnung?"},
    ]
    antwort = ki.antworte(KiAuftrag("sys", "prompt", {}, {"segmente": segmente, "fundstellen": _fundstellen()}))
    befunde = {b["segment_id"]: b for b in antwort.daten["befunde"]}
    assert befunde[2]["art"] == "widerspruch" and befunde[2]["fundstelle_id"] == "F1"
    assert befunde[2]["wiki_zitat"] == regel.zitat
    assert befunde[3]["art"] == "frage" and befunde[3]["fundstelle_id"] == "F2"
    assert befunde[3]["wiki_zitat"] == "Die Pflege der Lieferantenstammdaten liegt beim Einkauf."
    assert 4 not in befunde  # rhetorisch
    uebergangen = {u["segment_id"]: u["grund"] for u in antwort.daten["uebergangen"]}
    assert uebergangen[1] == "smalltalk" and uebergangen[4] == "rhetorische_frage"
    # Hoechstens vier Befunde je Aufruf - wie das Schema es verlangt.
    assert len(antwort.daten["befunde"]) == 4
    assert antwort.antwort_s >= 0 and antwort.start_s == 0.0 and ki.aufrufe


def test_attrappe_frage_ohne_treffer_und_offener_punkt():
    ki = AttrappeKi()
    segmente = [
        {"id": 5, "text": "Wer die Schulung übernimmt, ist noch offen."},
        {"id": 6, "text": "Gibt es eine Vorgabe für die Reisekostenabrechnung?"},
    ]
    antwort = ki.antworte(KiAuftrag("s", "p", {}, {"segmente": segmente, "fundstellen": _fundstellen()}))
    befunde = {b["segment_id"]: b for b in antwort.daten["befunde"]}
    assert befunde[5]["art"] == "offener_punkt"
    assert befunde[6]["art"] == "frage" and befunde[6]["fundstelle_id"] is None and befunde[6]["wiki_zitat"] is None


def test_attrappe_essenz_nimmt_erste_saetze():
    ki = AttrappeKi()
    segmente = [{"id": 1, "text": "Die Freigabe dauert drei Werktage. Danach folgt die Buchung."},
                {"id": 2, "text": "Ja."}]
    antwort = ki.antworte(KiAuftrag("s", "p", {}, {"art": "essenz", "segmente": segmente}))
    assert antwort.daten == {"essenz": [{"punkt": "Die Freigabe dauert drei Werktage."}], "offen": []}


def test_make_ki_attrappe_und_fehlendes_sdk(tmp_path, monkeypatch):
    ki, status = make_ki(BACKEND_ATTRAPPE, "", cache_dir=tmp_path)
    assert isinstance(ki, AttrappeKi) and status.zustand == "bereit"
    monkeypatch.setattr("audioscribe.souffleur.ki.sdk_verfuegbar", lambda: False)
    ki, status = make_ki(BACKEND_CLAUDE, "claude-sonnet-5", cache_dir=tmp_path)
    assert ki is None and status.zustand == "fehlt" and "claude-agent-sdk" in status.meldung
    ki, status = make_ki("unbekannt", "x", cache_dir=tmp_path)
    assert ki is None and status.zustand == "fehlt"


def test_make_ki_claude_nutzt_eigenes_arbeitsverzeichnis(tmp_path, monkeypatch):
    monkeypatch.setattr("audioscribe.souffleur.ki.sdk_verfuegbar", lambda: True)
    ki, status = make_ki(BACKEND_CLAUDE, "claude-sonnet-5", cache_dir=tmp_path)
    assert ki is not None and ki.cwd == tmp_path / "souffleur" and status.modell == "claude-sonnet-5"
    assert "claude" not in status.meldung.lower().replace("claude-sonnet-5", "")  # Modell-ID ja, Produktname nein


def test_slug_entspricht_der_ablage_der_cli():
    assert _slug(Path("C:/Users/x/a b")) == "C--Users-x-a-b"
    assert _slug(Path("/home/x/.cache")) == "-home-x--cache"


@pytest.mark.skipif(os.environ.get("AUDIOSCRIBE_TEST_KI") != "1", reason="echter KI-Aufruf nur auf Wunsch")
def test_claude_agent_ki_hinterlaesst_keine_sitzungsdatei(tmp_path):
    """Verifikation von Leitplanke 'nichts bleibt auf der Platte' (einmalig, braucht Anmeldung)."""
    from audioscribe.souffleur.ki import ClaudeAgentKi, claude_config_dir

    ki = ClaudeAgentKi("claude-haiku-4-5-20251001", cwd=tmp_path / "souffleur", log=print)
    schema = {"type": "object", "required": ["antwort"], "properties": {"antwort": {"type": "string"}}}
    antwort = ki.antworte(KiAuftrag("Antworte knapp als JSON.", "Sag 'ok'.", schema, timeout_s=90))
    assert antwort.daten["antwort"] and antwort.start_s <= antwort.antwort_s
    ordner = claude_config_dir() / "projects" / _slug(ki.cwd.resolve())
    assert not list(ordner.glob("*.jsonl")) if ordner.exists() else True


def test_sidecar_namen_sind_fest():
    assert "souffleur.json" in SOUFFLEUR_DATEIEN and all(n.startswith("souffleur") for n in SOUFFLEUR_DATEIEN)


# --- Sitzungsuhr ---------------------------------------------------------------------


def test_sitzungsuhr_schaetzt_zwischen_meldungen():
    from audioscribe.souffleur.uhr import SitzungsUhr

    uhr = SitzungsUhr(speed=4.0)
    assert uhr.jetzt() is None
    uhr.sync(10.0, mono=100.0)
    assert uhr.jetzt(mono=100.0) == 10.0
    assert uhr.jetzt(mono=100.5) == pytest.approx(12.0)  # 0,5 s real = 2 s Sitzung bei 4x
    assert uhr.sitzungszeit_von(99.0) == pytest.approx(6.0)


# --- Essenz (C1) ---------------------------------------------------------------------


def _segmente():
    import json

    data = json.loads((MEETING / "transcript.json").read_text(encoding="utf-8"))
    return [{"id": p["index"] + 1, "track": "system", **p} for p in data["paragraphs"]]


def test_essenz_fenster_nimmt_genau_die_letzten_minuten():
    from audioscribe.souffleur import essenz

    segs = _segmente()
    auswahl = essenz.im_fenster(segs, jetzt=60.0, minuten=2)
    assert [s["id"] for s in auswahl] == list(range(1, 11))
    # Fenster von 50 s: nur Segmente, deren Ende in [-70, 50] liegt
    auswahl = essenz.im_fenster(segs, jetzt=50.0, minuten=2)
    assert auswahl[-1]["id"] == 8 and len(auswahl) == 8
    assert essenz.im_fenster(segs, jetzt=200.0, minuten=2) == []  # alles aelter als 2 min


def test_essenz_erzeugen_ist_als_ki_gekennzeichnet_und_wird_angehaengt(tmp_path):
    from audioscribe.souffleur import essenz
    from audioscribe.souffleur.ki import KiFehler

    ki = AttrappeKi()
    e = essenz.erzeuge(ki, _segmente(), jetzt=60.0, minuten=2)
    assert e.ki_erzeugt is True and e.minuten == 2 and e.fenster == "00:00:00–00:01:00"
    assert 1 <= len(e.punkte) <= 5 and e.segment_ids[0] == 1
    assert "Systemanweisung" not in ki.aufrufe[-1].prompt and "Ausschnitt" in ki.aufrufe[-1].prompt
    pfad = essenz.anhaengen(tmp_path, e)
    essenz.anhaengen(tmp_path, e)
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    assert len(zeilen) == 2 and '"ki_erzeugt": true' in zeilen[0]
    with pytest.raises(KiFehler):
        essenz.erzeuge(ki, _segmente(), jetzt=500.0, minuten=5)
    with pytest.raises(ValueError):
        essenz.erzeuge(ki, _segmente(), jetzt=60.0, minuten=3)


def test_kern_puffert_segmente_und_liefert_essenz(tmp_path):
    from audioscribe.souffleur.kern import Souffleur
    from audioscribe.souffleur.ki import KiStatus
    from audioscribe.souffleur.konfig import SouffleurKonfig

    konfig = SouffleurKonfig(wiki_dir=None, uebergabe_dir=tmp_path / "ueb", backend="attrappe")
    s = Souffleur(konfig, ki=AttrappeKi(), ki_status=KiStatus("bereit", "attrappe", "attrappe", "ok"))
    s.starte(tmp_path)
    for seg in _segmente():
        s.beobachte(seg, empfangen_mono=1.0)
    assert s.status()["segmente"] == 10 and s.uhr.jetzt() >= 60.0
    e = s.essenz(5)
    assert e.ki_erzeugt and (tmp_path / "souffleur-essenz.jsonl").is_file()
    assert s.status()["essenzen"] == 1
    s.abschliessen()
    assert s.status()["beendet"] is True


def test_kern_ohne_ki_meldet_zustand_statt_abzubrechen(tmp_path):
    from audioscribe.souffleur.kern import Souffleur
    from audioscribe.souffleur.ki import KiFehler, KiStatus
    from audioscribe.souffleur.konfig import SouffleurKonfig

    konfig = SouffleurKonfig(wiki_dir=None, uebergabe_dir=tmp_path)
    s = Souffleur(konfig, ki=None, ki_status=KiStatus("fehlt", "claude-agent", "x", "KI-Dienst nicht verfügbar"))
    s.beobachte({"id": 1, "start": 0, "end": 3, "text": "Hallo zusammen, guten Morgen."})
    assert s.status()["ki"]["zustand"] == "fehlt"
    with pytest.raises(KiFehler):
        s.essenz(2)


# --- Konfiguration (K1: eine Lesestelle) ---------------------------------------------


def test_lade_konfig_liest_wiki_pfad_nur_aus_dem_stand(tmp_path, monkeypatch):
    from audioscribe.souffleur import konfig

    k = konfig.lade_konfig({}, output_dir=tmp_path)
    assert k.wiki_dir is None and k.uebergabe_dir == tmp_path / "wiki-uebergabe"
    k = konfig.lade_konfig({"wiki_dir": str(WIKI), "souffleur_model": "claude-opus-5", "souffleur_aktiv": False,
                            "uebergabe_dir": str(tmp_path / "u")}, output_dir=tmp_path, speed=5.0)
    assert k.wiki_dir == WIKI.resolve() and k.modell == "claude-opus-5" and k.aktiv is False and k.speed == 5.0
    assert k.uebergabe_dir == (tmp_path / "u").resolve()


def test_wiki_pfad_wird_nur_in_konfig_gelesen():
    """Architektur-Guard: der Schluessel 'wiki_dir' des Einstellungsstands wird im Souffleur-
    Paket nur in konfig.py angefasst - die Stelle fuer spaetere Projekte."""
    paket = Path(__file__).parent.parent / "src" / "audioscribe" / "souffleur"
    for datei in paket.glob("*.py"):
        if datei.name == "konfig.py":
            continue
        assert '"wiki_dir"' not in datei.read_text(encoding="utf-8"), datei


# --- B1/A3: Fensterung, Validierung, Begleitdateien ------------------------------------


def _souffleur(tmp_path, *, wiki=None, ki=None, aktiv=True, **extra):
    from audioscribe.souffleur.kern import Souffleur
    from audioscribe.souffleur.ki import KiStatus
    from audioscribe.souffleur.konfig import SouffleurKonfig

    konfig = SouffleurKonfig(wiki_dir=wiki, uebergabe_dir=tmp_path / "ueb", backend="attrappe", aktiv=aktiv,
                             fenster_leerlauf_s=0.0, **extra)
    hinweise = []
    s = Souffleur(konfig, ki=ki if ki is not None else AttrappeKi(),
                  ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"), on_hinweis=hinweise.append)
    return s, hinweise


def _laufen_lassen(s, segmente, session_dir, *, warte=5.0):
    import time

    s.starte(session_dir)
    for seg in segmente:
        s.beobachte(seg, empfangen_mono=time.monotonic())
    s.abschliessen()


def test_fragen_werden_markiert_rhetorische_nicht(tmp_path):
    s, hinweise = _souffleur(tmp_path)
    _laufen_lassen(s, _segmente(), tmp_path)
    arten = {h["segment_id"]: h["art"] for h in hinweise}
    assert arten[4] == "frage" and arten[9] == "frage"  # echte Fragen
    assert 5 not in arten  # "Das ist doch klar, oder?" ist rhetorisch
    assert arten[7] == "offener_punkt"
    # Ohne Wiki: Fragen sind ohne Befund und zaehlen als offene Punkte (B2 -> A3)
    assert all(h["ohne_befund"] for h in hinweise if h["art"] == "frage")
    assert {p["segment_id"] for p in s.offene_punkte()} == {4, 7, 9}
    # Jede Markierung traegt Zeitbezug und Verzoegerung
    for h in hinweise:
        assert h["t_start"] >= 0 and h["verzoegerung_s"] is not None and h["ki_antwort_s"] is not None
    assert s.status()["hinweise"] == 3 and s.status()["ki"]["aufrufe"] >= 1


def test_begleitdateien_und_transkript_bleibt_bytegleich(tmp_path):
    import hashlib

    from audioscribe.live.store import write_transcript
    from audioscribe.models import Segment
    from audioscribe.souffleur import SOUFFLEUR_DATEIEN, markierung

    segs = _segmente()
    write_transcript(tmp_path, [Segment(s["start"], s["end"], s["text"], s["speaker"]) for s in segs],
                     duration_s=60, language="de", model="t", mode="live")
    vorher = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir() if p.is_file()}
    s, hinweise = _souffleur(tmp_path)
    _laufen_lassen(s, segs, tmp_path)
    s.essenz(5)
    nachher = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir() if p.is_file()}
    for name, h in vorher.items():
        assert nachher[name] == h, name
    neu = set(nachher) - set(vorher)
    assert neu and neu <= set(SOUFFLEUR_DATEIEN)
    stand = markierung.lade(tmp_path)
    assert stand is not None and len(stand.markierungen) == len(hinweise) == 3
    assert stand.bilanz["hinweise"] == 3 and stand.bilanz["offene_punkte"] == 3
    protokoll = (tmp_path / "souffleur-protokoll.md").read_text(encoding="utf-8")
    assert "| Zeit | Art | Aussage | Fundstelle |" in protokoll and "Offene Punkte (3)" in protokoll
    assert "nichts im Wiki" in protokoll


def test_validierung_verwirft_erfundenes(tmp_path):
    """Leitplanke 7: Aussage muss im Segment stehen, Widerspruch braucht Zitat aus dem Auszug."""
    from audioscribe.souffleur.ki import KiAntwort

    class LuegenKi:
        modell = "x"; backend = "attrappe"

        def antworte(self, auftrag):
            seg = auftrag.kontext["segmente"][0]["id"]
            return KiAntwort(daten={"befunde": [
                {"segment_id": seg, "art": "widerspruch", "aussage": "erfundener Satz", "fundstelle_id": None,
                 "wiki_zitat": None, "ki_text": "x", "sicherheit": "hoch"},
                {"segment_id": seg, "art": "widerspruch", "aussage": "Freigabe", "fundstelle_id": None,
                 "wiki_zitat": "irgendwas", "ki_text": "x", "sicherheit": "hoch"},
                {"segment_id": seg, "art": "offener_punkt", "aussage": "Freigabe", "fundstelle_id": None,
                 "wiki_zitat": None, "ki_text": "unsicher", "sicherheit": "mittel"},
                {"segment_id": 999, "art": "frage", "aussage": "x", "fundstelle_id": None, "wiki_zitat": None,
                 "ki_text": "", "sicherheit": "hoch"},
            ], "uebergangen": []}, start_s=0.1, antwort_s=0.2, modell="x")

    s, hinweise = _souffleur(tmp_path, ki=LuegenKi())
    _laufen_lassen(s, _segmente()[1:3], tmp_path)
    assert hinweise == []
    s2, hinweise2 = _souffleur(tmp_path / "b", ki=LuegenKi(), sensibel=True)
    (tmp_path / "b").mkdir()
    _laufen_lassen(s2, _segmente()[1:3], tmp_path / "b")
    assert [h["art"] for h in hinweise2] == ["offener_punkt"]  # nur mit "sensibel" kommt "mittel" durch


def test_dubletten_werden_unterdrueckt(tmp_path):
    s, hinweise = _souffleur(tmp_path)
    frage = {"id": 1, "start": 0.0, "end": 3.0, "speaker": "Ich", "text": "Wer pflegt eigentlich die Lieferantenstammdaten?", "delay": 0.2}
    nochmal = {**frage, "id": 2, "start": 30.0, "end": 33.0, "text": "Wer pflegt die Lieferantenstammdaten eigentlich?"}
    _laufen_lassen(s, [frage, nochmal], tmp_path)
    assert len(hinweise) == 1


def test_ausgeschaltet_beurteilt_nichts_puffert_aber(tmp_path):
    s, hinweise = _souffleur(tmp_path, aktiv=False)
    _laufen_lassen(s, _segmente(), tmp_path)
    assert hinweise == [] and s.status()["segmente"] == 10 and s.status()["aktiv"] is False


def test_ki_fehler_fuehren_zu_pause_nicht_zu_absturz(tmp_path):
    from audioscribe.souffleur.ki import KiFehler

    class KaputteKi:
        modell = "x"; backend = "attrappe"

        def antworte(self, auftrag):
            raise KiFehler("Dienst weg")

    s, hinweise = _souffleur(tmp_path, ki=KaputteKi(), fenster_max_segmente=1)
    _laufen_lassen(s, _segmente(), tmp_path)
    st = s.status()
    assert hinweise == [] and st["ki"]["fehler"] >= 3 and st["ki"]["zustand"] == "pause"
    assert "Pause" in st["ki"]["meldung"]
    zeilen = (tmp_path / "souffleur-diagnose.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"fehler"' in z for z in zeilen) and any('"ki_pause"' in z for z in zeilen)


# --- K1: Wiki lesen ----------------------------------------------------------------------


def test_pruefe_wiki_drei_zustaende(tmp_path):
    from audioscribe.souffleur import wiki

    assert wiki.pruefe_wiki(None).zustand == "keins"
    assert wiki.pruefe_wiki("").zustand == "keins"
    st = wiki.pruefe_wiki(WIKI)
    assert st.zustand == "ok" and st.name == "Testwiki Rechnungsprozess (Testdaten)"
    assert st.seiten == 4 and st.glossar_eintraege == 2 and st.glossar_datei == "wiki/glossar.md"
    assert "4 Seiten" in st.meldung and "Glossar: 2" in st.meldung
    assert wiki.pruefe_wiki(tmp_path / "gibt-es-nicht").zustand == "fehler"
    leer = tmp_path / "leer"; leer.mkdir()
    st = wiki.pruefe_wiki(leer)
    assert st.zustand == "fehler" and "Kein Wiki" in st.meldung
    (leer / "notizen.md").write_text("# Notizen\n\nEin Satz.\n", encoding="utf-8")
    st = wiki.pruefe_wiki(leer)
    assert st.zustand == "ok" and st.name == "leer" and "Glossar: keins" in st.meldung


def test_wiki_index_liest_nur_seiten_und_findet_abschnitte():
    from audioscribe.souffleur import wiki

    index = wiki.WikiIndex.laden(WIKI)
    dateien = {a.datei for a in index.abschnitte}
    assert dateien == {"wiki/freigaben.md", "wiki/stammdaten.md", "wiki/archivierung.md", "wiki/glossar.md"}
    assert not any("raw/" in d or d == "log.md" for d in dateien)
    treffer = index.suche("Die Freigabe von Rechnungen ab 10.000 Euro macht bei uns die Teamleitung.")
    assert treffer and treffer[0].datei == "wiki/freigaben.md" and treffer[0].ueberschrift == "Grenzen"
    assert "5.000 Euro" in treffer[0].auszug and treffer[0].zeile == 5
    treffer = index.suche("Wer pflegt eigentlich die Lieferantenstammdaten?")
    assert treffer[0].datei == "wiki/stammdaten.md" and treffer[0].ueberschrift == "Rollen"
    treffer = index.suche("Belege bewahren wir fünf Jahre auf.")
    assert treffer[0].datei == "wiki/archivierung.md"
    assert index.suche("Zyklopenfeder") == []  # steht nur in raw/
    assert index.suche("") == []


def test_glossar_korrigiert_suchtext_und_wird_erkannt():
    from audioscribe.souffleur import wiki

    index = wiki.WikiIndex.laden(WIKI)
    assert index.glossar.eintraege == [("Fak Tura", "Faktura"), ("Teamleidung", "Teamleitung")]
    assert index.glossar.fachbegriffe == [("Sachbearbeitung", "Rolle, die Rechnungen unter der Freigabegrenze freigibt")]
    assert index.glossar.korrigiere("im fak tura gepflegt") == "im Faktura gepflegt"
    treffer = index.suche("Die Stammdaten pflegen wir im Fak Tura.")
    # Ohne Glossar-Korrektur traefe "Faktura" nicht; mit ihr steht der Abschnitt "Systeme" unter den Treffern.
    assert ("wiki/stammdaten.md", "Systeme") in {(t.datei, t.ueberschrift) for t in treffer[:2]}
    assert index.suche("Fak Tura") and index.suche("Fak Tura")[0].ueberschrift == "Systeme"
    g = wiki.parse_glossar("# Glossar\n\n- Soundshark → Splunk\n\n| Fehlerkennung | Korrekt |\n|---|---|\n| A B | AB |\n")
    assert g.eintraege == [("A B", "AB"), ("Soundshark", "Splunk")]


def test_wiki_wird_nur_gelesen(tmp_path):
    import os
    import shutil

    from audioscribe.souffleur import wiki

    kopie = tmp_path / "wiki"
    shutil.copytree(WIKI, kopie)
    vorher = sorted((str(p.relative_to(kopie)), p.stat().st_size, p.read_bytes()) for p in kopie.rglob("*") if p.is_file())
    if os.name != "nt":
        for p in kopie.rglob("*"):
            p.chmod(0o555 if p.is_dir() else 0o444)
    try:
        index = wiki.WikiIndex.laden(kopie)
        index.suche("Freigabe Teamleitung")
        s, hinweise = _souffleur(tmp_path, wiki=kopie)
        _laufen_lassen(s, _segmente(), tmp_path)
    finally:
        if os.name != "nt":
            for p in kopie.rglob("*"):
                p.chmod(0o755 if p.is_dir() else 0o644)
    nachher = sorted((str(p.relative_to(kopie)), p.stat().st_size, p.read_bytes()) for p in kopie.rglob("*") if p.is_file())
    assert vorher == nachher
    assert hinweise  # Fragen wurden trotzdem erkannt


def test_tokenisierung_mit_umlauten_zahlen_und_stamm():
    from audioscribe.souffleur.wiki import tokenisiere

    assert tokenisiere("Rechnungen ab 5.000 Euro gibt die Teamleitung frei") == ["rechn", "5000", "euro", "teamleit", "frei"]
    assert "belege" not in tokenisiere("Belege") and tokenisiere("Belege") == ["beleg"]


# --- A1/A2/B2: Abgleich mit dem Mini-Wiki ------------------------------------------------


def _regeln():
    return [
        AttrappenRegel(aussage="ab 10.000 Euro", fundstelle="freigaben.md › Grenzen",
                       zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei."),
        AttrappenRegel(aussage="fünf Jahre", fundstelle="archivierung.md › Aufbewahrung",
                       zitat="Belege werden zehn Jahre aufbewahrt, gerechnet ab dem Ende des Geschäftsjahres."),
        # Diese Regel darf NICHT greifen: der Auszug enthaelt das Zitat nicht -> verworfen (Leitplanke 7)
        AttrappenRegel(aussage="drei Werktage", fundstelle="freigaben.md › Fristen", zitat="Die Freigabe dauert eine Woche."),
    ]


def test_abgleich_findet_widersprueche_an_der_richtigen_wiki_stelle(tmp_path):
    import time

    from audioscribe.live.store import write_transcript
    from audioscribe.models import Segment

    write_transcript(tmp_path, [Segment(x["start"], x["end"], x["text"], x["speaker"]) for x in _segmente()],
                     duration_s=60, language="de", model="t", mode="live")
    s, hinweise = _souffleur(tmp_path, wiki=WIKI, ki=AttrappeKi(regeln=_regeln()))
    s.starte(tmp_path)
    ende = time.monotonic() + 10
    while s.status()["wiki"]["zustand"] == "laedt" and time.monotonic() < ende:
        time.sleep(0.05)
    assert s.status()["wiki"]["zustand"] == "ok" and s.status()["wiki"]["glossar_eintraege"] == 2
    for seg in _segmente():
        s.beobachte(seg, empfangen_mono=time.monotonic())
    s.abschliessen()

    je_segment = {h["segment_id"]: h for h in hinweise}
    w1 = je_segment[2]
    assert w1["art"] == "widerspruch" and w1["fundstelle"] == "wiki/freigaben.md › Grenzen"
    assert w1["wiki_zitat"] == "Rechnungen ab 5.000 Euro gibt die Teamleitung frei."
    assert w1["aussage"] == "ab 10.000 Euro" and w1["fundstellen"][0]["zeile"] == 5
    w2 = je_segment[8]
    assert w2["art"] == "widerspruch" and w2["fundstelle"] == "wiki/archivierung.md › Aufbewahrung"
    assert 3 not in je_segment  # passende Aussage (drei Werktage): Regel ohne gueltiges Zitat -> verworfen
    assert 6 not in je_segment  # "Fak Tura": Glossar korrigiert, kein Widerspruch
    f = je_segment[4]
    assert f["art"] == "frage" and f["ohne_befund"] is False and f["fundstelle"] == "wiki/stammdaten.md › Rollen"
    assert f["wiki_zitat"] == "Die Pflege der Lieferantenstammdaten liegt beim Einkauf."
    f2 = je_segment[9]
    assert f2["art"] == "frage" and f2["ohne_befund"] is True and f2["ki_text"] == ""
    assert {p["segment_id"] for p in s.offene_punkte()} == {7, 9}
    stand = s.stand()
    assert stand.bilanz["je_art"] == {"widerspruch": 2, "offener_punkt": 1, "frage": 2}
    assert stand.wiki["name"].startswith("Testwiki")
    # Verzoegerung je Hinweis ist gemessen und dokumentiert
    protokoll = (tmp_path / "souffleur-protokoll.md").read_text(encoding="utf-8")
    assert "freigaben.md › Grenzen" in protokoll and "Widerspruch" in protokoll
    assert stand.bilanz["verzoegerung_s"]["max"] is not None
    # A4: Uebergabe liegt im Uebergabeordner, nie im Wiki
    assert s.uebergabe is not None and s.uebergabe.ordner.parent == tmp_path / "ueb"
    assert s.status()["uebergabe"] == str(s.uebergabe.ordner)


def test_wiki_pfad_kaputt_meldet_zustand_und_laeuft_weiter(tmp_path):
    import time

    s, hinweise = _souffleur(tmp_path, wiki=tmp_path / "nicht-da")
    s.starte(tmp_path)
    ende = time.monotonic() + 10
    while s.status()["wiki"]["zustand"] == "laedt" and time.monotonic() < ende:
        time.sleep(0.05)
    assert s.status()["wiki"]["zustand"] == "fehler" and "nicht gefunden" in s.status()["wiki"]["meldung"]
    for seg in _segmente():
        s.beobachte(seg, empfangen_mono=time.monotonic())
    s.abschliessen()
    assert {h["art"] for h in hinweise} == {"frage", "offener_punkt"}
    assert s.status_text().startswith("Souffleur ohne Wiki")


# --- A4: Uebergabe ---------------------------------------------------------------------


def test_uebergabe_ist_anhaengend_bytegleich_und_nie_im_wiki(tmp_path):
    import filecmp

    from audioscribe.live.store import write_transcript
    from audioscribe.models import Segment
    from audioscribe.souffleur import markierung, uebergabe

    sitzung = tmp_path / "live-2026-01-06_10-00-00"
    sitzung.mkdir()
    segs = _segmente()
    write_transcript(sitzung, [Segment(s["start"], s["end"], s["text"], s["speaker"]) for s in segs],
                     duration_s=60, language="de", model="t", mode="live")
    m = markierung.Markierung(id=1, art="widerspruch", segment_id=2, t_start=5.0, t_end=12.0, sprecher="Sprecher 1",
                              aussage="ab 10.000 Euro", wiki_zitat="Rechnungen ab 5.000 Euro gibt die Teamleitung frei.",
                              fundstellen=[markierung.Fundstelle("wiki/freigaben.md", "Grenzen", 5, "…")], ki_text="weicht ab",
                              verzoegerung_s=4.2)
    stand = markierung.SouffleurStand(sitzung=sitzung.name, markierungen=[m])
    ziel = tmp_path / "ueb"
    u1 = uebergabe.schreibe(sitzung, stand, uebergabe_dir=ziel, wiki_dir=WIKI)
    u2 = uebergabe.schreibe(sitzung, stand, uebergabe_dir=ziel, wiki_dir=WIKI)
    assert u1.ordner == ziel / sitzung.name and u2.ordner == ziel / f"{sitzung.name}-2"
    assert u1.uebergabe_id != u2.uebergabe_id and u1.transkript_fassung == "live"
    assert filecmp.cmp(sitzung / "transkript.md", u1.ordner / "transkript.md", shallow=False)
    daten = json.loads((u1.ordner / "markierungen.json").read_text(encoding="utf-8"))
    assert daten["format_version"] == 1 and daten["markierungen"][0]["zeitstempel"] == "00:00:05"
    assert daten["markierungen"][0]["wiki"]["zitat"].startswith("Rechnungen ab 5.000")
    assert daten["markierungen"][0]["ki_erzeugt"] == {"text": "weicht ab"}
    assert (u1.ordner / "README.md").is_file() and "Widerspruch" in (u1.ordner / "markierungen.md").read_text(encoding="utf-8")
    assert not any(p.name == "souffleur-essenz.jsonl" for p in u1.ordner.iterdir())
    with pytest.raises(RuntimeError):
        uebergabe.schreibe(sitzung, stand, uebergabe_dir=WIKI / "eingang", wiki_dir=WIKI)
    assert not (WIKI / "eingang").exists()


# --- Ablageort der Einstellungen ------------------------------------------------------


def test_config_dir_je_plattform(monkeypatch):
    import sys

    from audioscribe import config

    monkeypatch.delenv("AUDIOSCRIBE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    assert config._config_dir() == Path(r"C:\Users\x\AppData\Roaming") / "audioscribe"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert config._config_dir() == Path.home() / "Library" / "Application Support" / "audioscribe"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
    assert config._config_dir() == Path("/tmp/xdg") / "audioscribe"
    monkeypatch.setenv("AUDIOSCRIBE_CONFIG_DIR", "/tmp/eigen")
    assert config._config_dir() == Path("/tmp/eigen")


def test_alte_einstellungsdatei_wird_uebernommen(tmp_path, monkeypatch):
    import dataclasses

    from audioscribe.config import settings
    from audioscribe.ui import state

    fake = dataclasses.replace(settings, cache_dir=tmp_path / "cache", config_dir=tmp_path / "config")
    monkeypatch.setattr(state, "settings", fake)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "ui-state.json").write_text(json.dumps({"wiki_dir": "/w", "theme": "dark"}), encoding="utf-8")
    assert state.load_state() == {"wiki_dir": "/w", "theme": "dark"}
    assert (tmp_path / "config" / "einstellungen.json").is_file()
    assert (tmp_path / "cache" / "ui-state.json").is_file()  # alte Datei bleibt liegen
    state.save_state({"theme": "light"})
    assert json.loads((tmp_path / "config" / "einstellungen.json").read_text(encoding="utf-8"))["theme"] == "light"
    assert json.loads((tmp_path / "cache" / "ui-state.json").read_text(encoding="utf-8"))["theme"] == "dark"


def test_doctor_souffleur_check(monkeypatch, tmp_path):
    from audioscribe import doctor
    from audioscribe.ui import state

    monkeypatch.setattr(state, "state_path", lambda config_dir=None: tmp_path / "e.json")
    r = doctor._check_souffleur()
    assert r.name == "Souffleur" and r.status in ("OK", "WARN") and "Kein Wiki" in r.detail
    state.save_state({"wiki_dir": str(WIKI), "souffleur_backend": "attrappe"})
    r = doctor._check_souffleur()
    assert r.status == "OK" and "4 Seiten" in r.detail and "attrappe" in r.detail
