"""Leitfaden (Meeting-Vorbereitung als Checkliste des Souffleurs): Parser, Status, Prompt,
Abgleich mit KI-Attrappe, Anstoß „anknüpfen“, Wiederaufnahme, Wiki-Ablage und Routen."""

import json
import time
from pathlib import Path

import pytest

from audioscribe.souffleur import leitfaden as lf_modul
from audioscribe.souffleur.kern import Souffleur
from audioscribe.souffleur.ki import AttrappeKi, KiAntwort, KiStatus
from audioscribe.souffleur.konfig import SouffleurKonfig

MD = """---
titel: Abstimmung Freigabe
art: abstimmung
---
# Ziel
Freigabe-Verantwortung festlegen.

## Muss geklärt werden
- [ ] Wer gibt Rechnungen über der Freigabegrenze frei? (Wiki: ENT-003)
  - Laut PRO-004 bisher die Teamleitung.
- [x] Termin für den Start steht

## Sollte angesprochen werden
* [ ] Wer übernimmt die Schulung für das Portal?

## Hintergrund
- [ ] das ist kein Punkt
Freier Text.
"""


def _lf() -> lf_modul.Leitfaden:
    return lf_modul.parse(MD, quelle="vorbereitung.md")


# --- Parser ---------------------------------------------------------------------------


def test_parser_liest_punkte_prioritaet_notiz_und_frontmatter():
    lf = _lf()
    assert [p.id for p in lf.punkte] == ["P1", "P2", "P3"]
    p1, p2, p3 = lf.punkte
    assert p1.prioritaet == "muss" and p1.notiz == "Laut PRO-004 bisher die Teamleitung."
    assert p1.begriffe == ["ENT-003", "PRO-004"]
    assert p2.status == "geklaert" and p2.gesetzt_von is None  # [x] in der Datei
    assert p3.prioritaet == "sollte" and p3.abschnitt == "Sollte angesprochen werden"
    assert lf.titel == "Abstimmung Freigabe" and lf.art == "abstimmung"
    assert lf.ziel == "Freigabe-Verantwortung festlegen." and "Freier Text." in lf.hintergrund
    assert lf.bilanz() == {"punkte": 3, "offen": 2, "angesprochen": 0, "geklaert": 1, "vertagt": 0, "muss_offen": 1}


def test_parser_ohne_punkte_und_mit_kaputtem_markdown():
    with pytest.raises(lf_modul.LeitfadenFehler):
        lf_modul.parse("# Nur Text\n\nKeine Checkliste.\n")
    lf = lf_modul.parse("ohne Frontmatter\n```\n- [ ] im Codeblock\n```\n- [ ] echter Punkt\n---\nkaputt: ja")
    assert [p.text for p in lf.punkte] == ["echter Punkt"] and lf.titel == ""


def test_lade_datei_prueft_endung(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    with pytest.raises(lf_modul.LeitfadenFehler):
        lf_modul.lade_datei(tmp_path / "a.pdf")
    (tmp_path / "v.md").write_text(MD, encoding="utf-8")
    assert lf_modul.lade_datei(tmp_path / "v.md").quelle == str(tmp_path / "v.md")


def test_vorbereitungen_im_raw_ordner(tmp_path):
    ordner = tmp_path / "raw" / "vorbereitung"
    ordner.mkdir(parents=True)
    (ordner / "README.md").write_text("x", encoding="utf-8")
    (ordner / "2026-11-01_a.md").write_text(MD, encoding="utf-8")
    (ordner / "2026-11-03_b.md").write_text(MD, encoding="utf-8")
    assert [d["name"] for d in lf_modul.vorbereitungen(tmp_path)] == ["2026-11-03_b.md", "2026-11-01_a.md"]
    assert lf_modul.vorbereitungen(None) == [] and lf_modul.vorbereitungen(tmp_path / "nix") == []


def test_wiki_index_liest_die_vorbereitung_nicht(tmp_path):
    """Die Vorbereitung ist kein Wissen: unter raw/ findet die Wiki-Suche sie nicht."""
    from audioscribe.souffleur.wiki import WikiIndex

    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "seite.md").write_text("# Freigabe\n\nDie Teamleitung gibt frei.\n", encoding="utf-8")
    (tmp_path / "raw" / "vorbereitung").mkdir(parents=True)
    (tmp_path / "raw" / "vorbereitung" / "v.md").write_text(MD, encoding="utf-8")
    treffer = WikiIndex.laden(tmp_path).suche("Rechnungen Freigabegrenze Schulung Portal", top_k=6)
    assert all("vorbereitung" not in f.datei for f in treffer)


# --- Status ---------------------------------------------------------------------------


def test_ki_hebt_nur_an_und_der_mensch_hat_das_letzte_wort():
    lf = _lf()
    assert lf.melde_ki("P1", "angesprochen", segment_id=3, aussage="a", stand="Grenze offen", t=10.0)
    assert lf.punkt("P1").status == "angesprochen" and lf.punkt("P1").t_angesprochen == 10.0
    assert not lf.melde_ki("P2", "angesprochen", segment_id=4, aussage="b", stand="", t=11.0)  # schon geklärt
    assert not lf.melde_ki("P1", "offen", segment_id=4, aussage="b", stand="", t=11.0)  # KI darf nicht zurück
    assert not lf.melde_ki("PX", "geklaert", segment_id=4, aussage="b", stand="", t=11.0)
    lf.setze("P3", "vertagt")
    assert not lf.melde_ki("P3", "geklaert", segment_id=5, aussage="c", stand="", t=12.0)
    assert lf.melde_ki("P1", "geklaert", segment_id=6, aussage="d", stand="Teamleitung ab 5.000 €", t=20.0)
    p1 = lf.punkt("P1")
    assert p1.status == "geklaert" and p1.t_geklaert == 20.0 and p1.t_angesprochen == 10.0 and p1.gesetzt_von == "ki"
    lf.setze("P1", "offen")
    assert p1.status == "offen" and p1.gesetzt_von == "nutzer" and p1.t_angesprochen is None
    with pytest.raises(ValueError):
        lf.setze("P1", "erledigt")
    with pytest.raises(KeyError):
        lf.setze("P9", "offen")


def test_anstoss_einmal_nach_ruhezeit():
    lf = _lf()
    lf.melde_ki("P1", "angesprochen", segment_id=3, aussage="a", stand="", t=10.0)
    assert lf.faellige_anstoesse(50.0, 90.0) == []
    lf.melde_ki("P1", "angesprochen", segment_id=4, aussage="b", stand="", t=60.0)  # erneut erwähnt
    assert lf.faellige_anstoesse(120.0, 90.0) == []
    assert [p.id for p in lf.faellige_anstoesse(151.0, 90.0)] == ["P1"]
    assert lf.faellige_anstoesse(500.0, 90.0) == []  # nur einmal
    assert lf.suchbegriffe() == ["ENT-003", "PRO-004"]


def test_prompt_abschnitt_nur_offene_pflicht_zuerst_und_gedeckelt():
    lf = _lf()
    lf.punkte.insert(0, lf_modul.Punkt(id="P9", text="Sollte-Punkt vorne", prioritaet="sollte"))
    text = lf_modul.prompt_abschnitt(lf)
    zeilen = text.splitlines()
    assert zeilen[0].startswith("Ziel:") and zeilen[1].startswith("[P1] (muss, offen)")
    assert "P2" not in text and "Notiz: Laut PRO-004" in text
    lf.punkte += [lf_modul.Punkt(id=f"Q{i}", text="x" * 200) for i in range(30)]
    assert len(lf_modul.prompt_abschnitt(lf)) <= lf_modul.PROMPT_MAX + 250


def test_prompt_und_schema_nur_mit_leitfaden():
    from audioscribe.souffleur import prompt

    assert "punkte" not in prompt.schema()["properties"]
    s = prompt.schema(mit_leitfaden=True)
    assert "punkte" in s["required"] and "punkte" not in prompt.SCHEMA["properties"]  # Original unverändert
    assert "Leitfaden" not in prompt.system_prompt()
    assert "Leitfaden" in prompt.system_prompt(mit_leitfaden=True)
    p = prompt.baue_prompt([{"id": 1, "start": 0.0, "text": "x"}], kontext=[], fundstellen=[], leitfaden="[P1] (muss, offen) y")
    assert "## Leitfaden" in p and "[P1] (muss, offen) y" in p


# --- Souffleur mit Leitfaden ------------------------------------------------------------


def _souffleur(lf, *, ki=None, **extra):
    konfig = SouffleurKonfig(wiki_dir=None, backend="attrappe", fenster_leerlauf_s=0.0, **extra)
    hinweise: list[dict] = []
    s = Souffleur(konfig, ki=ki or AttrappeKi(), ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"),
                  on_hinweis=hinweise.append, leitfaden=lf)
    return s, hinweise


def _seg(i, start, text):
    return {"id": i, "start": start, "end": start + 4.0, "text": text, "speaker": "Sprecher 1", "delay": 0.0}


def _warte(bedingung, timeout=5.0):
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.05)
    return False


def test_souffleur_hakt_ab_stoesst_an_und_schreibt_ergebnis(tmp_path):
    s, hinweise = _souffleur(_lf(), leitfaden_anstoss_s=30.0)
    s.starte(tmp_path)
    s.beobachte(_seg(1, 0.0, "Wer die Schulung für das Portal übernimmt, machen wir so: das Team Einkauf."))
    s.beobachte(_seg(2, 5.0, "Bei Rechnungen über der Freigabegrenze müssen wir noch schauen."))
    assert _warte(lambda: (s.leitfaden() or {}).get("bilanz", {}).get("angesprochen") == 1)
    lf = s.leitfaden()
    p1, _, p3 = lf["punkte"]
    assert p3["status"] == "geklaert" and p3["segment_id"] == 1 and p3["gesetzt_von"] == "ki"
    assert p1["status"] == "angesprochen" and p1["aussage"].startswith("Bei Rechnungen")
    # Das Gespräch zieht weiter: nach der Ruhezeit kommt einmal "anknüpfen".
    s.beobachte(_seg(3, 60.0, "Kommen wir zum Wetter am Wochenende und zur Kantine."))
    assert _warte(lambda: any(h["art"] == "anknuepfen" for h in hinweise))
    s.abschliessen()
    an = [h for h in hinweise if h["art"] == "anknuepfen"]
    assert len(an) == 1 and an[0]["punkt_id"] == "P1" and an[0]["segment_id"] == 2 and an[0]["label"] == "Anknüpfen"
    assert not an[0]["offener_punkt"]
    assert s.status()["leitfaden"]["bilanz"]["muss_offen"] == 1
    gespeichert = json.loads((tmp_path / lf_modul.STAND_DATEI).read_text(encoding="utf-8"))
    assert gespeichert["punkte"][2]["status"] == "geklaert"
    md = (tmp_path / lf_modul.MD_DATEI).read_text(encoding="utf-8")
    assert "- [x] **P3**" in md and "- [~] **P1**" in md and "## Für das Folgemeeting (1)" in md
    # Die KI hat den Leitfaden im Prompt und im Schema bekommen.
    auftrag = s.ki.aufrufe[0]
    assert "## Leitfaden" in auftrag.prompt and "punkte" in auftrag.schema["required"]


class _Erfinder:
    """KI, die einen Punkt ohne wörtlichen Beleg abhaken will."""

    backend = "attrappe"
    modell = "x"

    def __init__(self):
        self.aufrufe = []

    def antworte(self, auftrag):
        self.aufrufe.append(auftrag)
        seg = auftrag.kontext["segmente"][0]
        return KiAntwort(daten={"befunde": [], "uebergangen": [], "punkte": [
            {"punkt_id": "P1", "status": "geklaert", "segment_id": seg["id"], "aussage": "die Teamleitung gibt frei", "stand": "x"},
            {"punkt_id": "P7", "status": "geklaert", "segment_id": seg["id"], "aussage": seg["text"], "stand": "x"},
        ]}, start_s=0.0, antwort_s=0.0, modell="x")


def test_kurze_zusage_schliesst_einen_angesprochenen_punkt(tmp_path):
    """Der Vorfilter gegen Smalltalk darf die kurze Einigung nicht verschlucken."""
    s, _ = _souffleur(_lf())
    s.starte(tmp_path)
    s.beobachte(_seg(1, 0.0, "Wer übernimmt eigentlich die Schulung für das Portal?"))
    assert _warte(lambda: s.leitfaden()["punkte"][2]["status"] == "angesprochen")
    s.beobachte(_seg(2, 10.0, "Schulung Portal: abgemacht."))
    s.abschliessen()
    assert s.leitfaden()["punkte"][2]["status"] == "geklaert"


def test_punkt_ohne_wortlaut_wird_nicht_abgehakt(tmp_path):
    s, _ = _souffleur(_lf(), ki=_Erfinder())
    s.starte(tmp_path)
    s.beobachte(_seg(1, 0.0, "Über die Freigabegrenze reden wir später ausführlich."))
    assert _warte(lambda: s.status()["ki"]["aufrufe"] >= 1)
    s.abschliessen()
    assert s.leitfaden()["punkte"][0]["status"] == "offen"
    diag = [json.loads(z) for z in (tmp_path / "souffleur-diagnose.jsonl").read_text(encoding="utf-8").splitlines()]
    gruende = {v["punkt_id"]: v["grund"] for d in diag for v in d.get("leitfaden_verworfen", [])}
    assert gruende == {"P1": "ohne_beleg", "P7": "unbekannt"}


def test_ohne_leitfaden_bleibt_alles_wie_bisher(tmp_path):
    s, _ = _souffleur(None)
    s.starte(tmp_path)
    s.beobachte(_seg(1, 0.0, "Wer pflegt eigentlich die Lieferantenstammdaten?"))
    s.abschliessen()
    assert s.leitfaden() is None and s.status()["leitfaden"] is None
    auftrag = s.ki.aufrufe[0]
    assert "Leitfaden" not in auftrag.prompt and "punkte" not in auftrag.schema["properties"]
    assert not (tmp_path / lf_modul.STAND_DATEI).exists()


def test_wiederaufnahme_uebernimmt_den_stand(tmp_path):
    lf = _lf()
    lf.setze("P1", "vertagt")
    lf_modul.schreibe(tmp_path, lf)
    s, _ = _souffleur(None)  # beim Fortsetzen kommt kein Pfad mit - der Ordner weiß es
    s.starte(tmp_path)
    s.abschliessen()
    assert s.leitfaden()["punkte"][0]["status"] == "vertagt"
    s.setze_punkt("P1", "geklaert")
    assert lf_modul.lade_stand(tmp_path).punkt("P1").status == "geklaert"


# --- Wiki-Ablage ----------------------------------------------------------------------


def test_ergebnis_geht_mit_den_markierungen_ins_wiki(projekt, sitzung):
    from dataclasses import replace

    from audioscribe.projekt import modell, wiki_ablage

    lf_modul.schreibe(sitzung, _lf())
    ohne = wiki_ablage.speichere_sitzung(sitzung, projekt)
    assert not (Path(ohne.ordner) / "leitfaden.md").exists()
    mit = wiki_ablage.speichere_sitzung(sitzung, projekt, markierungen=True)
    assert "- [x] **P2**" in (Path(mit.ordner) / "leitfaden.md").read_text(encoding="utf-8")
    assert "leitfaden.md" in (Path(mit.ordner) / "README.md").read_text(encoding="utf-8")
    meetings = replace(projekt, wiki_format=modell.FORMAT_MEETINGS)
    ablage = wiki_ablage.speichere_sitzung(sitzung, meetings, art="workshop", markierungen=True)
    stamm = Path(ablage.ordner).stem
    assert (Path(ablage.ordner).parent / f"{stamm}.leitfaden.md").is_file()


# --- Routen ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server, state

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "ui-state.json")
    monkeypatch.setattr(
        "audioscribe.live.kommando.inventory",
        lambda: {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": []},
    )
    return TestClient(server.create_app())


def test_routen_liste_vorschau_und_status(client, tmp_path):
    from audioscribe.ui import state

    wiki = tmp_path / "wiki"
    (wiki / "wiki").mkdir(parents=True)
    (wiki / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    ordner = wiki / "raw" / "vorbereitung"
    ordner.mkdir(parents=True)
    (ordner / "2026-11-02_freigabe.md").write_text(MD, encoding="utf-8")
    (tmp_path / "leer.md").write_text("# nichts\n", encoding="utf-8")
    state.save_state({"wiki_dir": str(wiki), "souffleur_backend": "attrappe"})

    liste = client.get("/api/leitfaden/liste").json()
    assert liste["ordner"] == str(ordner) and [d["name"] for d in liste["dateien"]] == ["2026-11-02_freigabe.md"]
    pfad = liste["dateien"][0]["pfad"]
    vorschau = client.get("/api/leitfaden/vorschau", params={"pfad": pfad}).json()
    assert vorschau["titel"] == "Abstimmung Freigabe" and len(vorschau["punkte"]) == 3
    assert client.get("/api/leitfaden/vorschau", params={"pfad": str(tmp_path / "leer.md")}).status_code == 400
    assert client.get("/api/leitfaden/vorschau", params={"pfad": str(tmp_path / "nix.md")}).status_code == 400
    assert client.post("/api/leitfaden/status", json={"punkt_id": "P1", "status": "geklaert"}).status_code == 409

    meeting = Path(__file__).parent / "data" / "souffleur" / "meeting"
    body = {"output_dir": str(tmp_path / "out"), "replay_transcript": str(meeting), "replay_speed": 1, "leitfaden": pfad}
    assert client.post("/api/live/start", json={**body, "leitfaden": str(tmp_path / "leer.md")}).status_code == 400
    assert client.post("/api/live/start", json=body).status_code == 200
    try:
        assert _warte(lambda: (client.get("/api/live/status").json().get("souffleur") or {}).get("leitfaden") is not None)
        assert client.post("/api/leitfaden/status", json={"punkt_id": "P1", "status": "kaputt"}).status_code == 400
        assert client.post("/api/leitfaden/status", json={"punkt_id": "P9", "status": "offen"}).status_code == 404
        r = client.post("/api/leitfaden/status", json={"punkt_id": "P3", "status": "vertagt"})
        assert r.status_code == 200 and r.json()["punkte"][2]["status"] == "vertagt"
        snap = client.get("/api/live/status").json()
        assert snap["souffleur"]["leitfaden"]["punkte"][2]["gesetzt_von"] == "nutzer"
    finally:
        client.post("/api/live/stop")
        _warte(lambda: not client.get("/api/live/status").json()["running"], timeout=20)
