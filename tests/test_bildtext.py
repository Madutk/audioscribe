"""Bildtext als zweite Belegquelle des Souffleurs: Texterkennung der Standbilder, Prompt-Abschnitt
„Bildschirm“, Leitfaden-Punkt und Frage mit Beleg vom Bildschirm, Prüfung des Wortlauts."""

import json
import sys
import time

import pytest

from audioscribe.souffleur import bildtext as bt
from audioscribe.souffleur import leitfaden as lf_modul
from audioscribe.souffleur import markierung as mk
from audioscribe.souffleur import prompt as prompt_modul
from audioscribe.souffleur import uebergabe
from audioscribe.souffleur.kern import Souffleur
from audioscribe.souffleur.ki import KiAntwort, KiStatus
from audioscribe.souffleur.konfig import SouffleurKonfig

MD = """# Abstimmung
## Muss geklärt werden
- [ ] Wer gibt Rechnungen über der Freigabegrenze frei?
## Sollte
- [ ] Bis wann steht die Schulung?
"""

BILDTEXT = "Ticket JIRA-412: Freigabe Rechnungen\nZuständig: Bereichsleitung Einkauf\nFrist: 15.12.2026"


def _seg(i, start, text):
    return {"id": i, "start": start, "end": start + 4.0, "text": text, "speaker": "Sprecher 1", "delay": 0.0}


def _warte(bedingung, timeout=5.0):
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.05)
    return False


class _BildKi:
    """KI-Attrappe: klärt P1 per Bildschirm, beantwortet die Frage per Bildschirm, erfindet einmal."""

    backend = "attrappe"
    modell = "x"

    def __init__(self, *, erfinden=False):
        self.aufrufe = []
        self.erfinden = erfinden

    def antworte(self, auftrag):
        self.aufrufe.append(auftrag)
        bilder = auftrag.kontext.get("bilder") or []
        seg = auftrag.kontext["segmente"][0]
        if not bilder:
            return KiAntwort(daten={"befunde": [], "uebergangen": [], "punkte": []}, start_s=0.0, antwort_s=0.0, modell="x")
        zitat = "Zuständig: Bereichsleitung Einkauf" if not self.erfinden else "Zuständig ist die Teamleitung"
        return KiAntwort(daten={
            "befunde": [{"segment_id": seg["id"], "art": "frage", "aussage": seg["text"], "fundstelle_id": None,
                         "wiki_zitat": None, "ki_text": "Laut Bildschirm die Bereichsleitung Einkauf.", "sicherheit": "hoch",
                         "bild_id": bilder[0]["id"], "bild_zitat": zitat}],
            "uebergangen": [],
            "punkte": [{"punkt_id": "P1", "status": "geklaert", "segment_id": None, "bild_id": bilder[0]["id"],
                        "aussage": zitat, "stand": "Bereichsleitung Einkauf"}],
        }, start_s=0.0, antwort_s=0.0, modell="x")


def _souffleur(tmp_path, ki, *, erkenne=lambda pfad: BILDTEXT):
    konfig = SouffleurKonfig(wiki_dir=None, backend="attrappe", fenster_leerlauf_s=0.0)
    hinweise: list[dict] = []
    s = Souffleur(konfig, ki=ki, ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"),
                  on_hinweis=hinweise.append, leitfaden=lf_modul.parse(MD), erkenne=erkenne)
    (tmp_path / "frames").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frames" / "0001.jpg").write_bytes(b"x")
    return s, hinweise


def test_prompt_und_schema_mit_bildschirm():
    s = prompt_modul.schema(mit_leitfaden=True, mit_bildern=True)
    assert "bild_id" in s["properties"]["befunde"]["items"]["properties"]
    assert s["properties"]["punkte"]["items"]["properties"]["segment_id"]["type"] == ["integer", "null"]
    assert prompt_modul.schema() is prompt_modul.SCHEMA  # ohne Bilder und Leitfaden unverändert
    assert "bild_id" not in json.dumps(prompt_modul.schema(mit_leitfaden=True))
    text = prompt_modul.baue_prompt([_seg(1, 0.0, "Wer gibt frei?")], kontext=[], fundstellen=[],
                                    bilder=[{"id": "B1", "t": 75.0, "kind": "zwischenablage", "text": BILDTEXT}])
    assert "## Bildschirm" in text and "[B1] (00:01:15, Screenshot)" in text and "Bereichsleitung Einkauf" in text
    assert "Bildschirm" in prompt_modul.system_prompt(mit_bildern=True)
    assert "Bildschirm" not in prompt_modul.system_prompt()


def test_bildschirm_klaert_punkt_und_beantwortet_frage(tmp_path):
    ki = _BildKi()
    s, hinweise = _souffleur(tmp_path, ki)
    s.starte(tmp_path)
    s.beobachte_bild({"id": 1, "t": 2.0, "file": "0001.jpg", "kind": "zwischenablage"})
    assert _warte(lambda: (tmp_path / bt.DATEI).is_file())
    s.beobachte(_seg(1, 3.0, "Wer gibt denn die großen Rechnungen frei?"))
    assert _warte(lambda: (s.leitfaden() or {}).get("bilanz", {}).get("geklaert") == 1)
    s.abschliessen()
    p1 = s.leitfaden()["punkte"][0]
    assert p1["status"] == "geklaert" and p1["segment_id"] is None
    assert p1["bild"] == {"id": "B1", "t": 2.0, "datei": "0001.jpg"} and p1["aussage"] == "Zuständig: Bereichsleitung Einkauf"
    frage = next(h for h in hinweise if h["art"] == "frage")
    assert frage["bild"]["zitat"] == "Zuständig: Bereichsleitung Einkauf" and not frage["ohne_befund"]
    assert not frage["offener_punkt"] and frage["ki_text"]  # vom Bildschirm beantwortet: kein offener Punkt
    assert "## Bildschirm" in ki.aufrufe[0].prompt
    md = (tmp_path / lf_modul.MD_DATEI).read_text(encoding="utf-8")
    assert "Beleg vom Bildschirm (00:00:02), `frames/0001.jpg`" in md
    gespeichert = json.loads((tmp_path / bt.DATEI).read_text(encoding="utf-8"))
    assert gespeichert["bilder"][0]["id"] == "B1" and "JIRA-412" in gespeichert["bilder"][0]["text"]
    stand = mk.lade(tmp_path)
    daten = uebergabe.daten(stand, sitzung="x", transkript_fassung="live")
    assert daten["markierungen"][0]["bildschirm"]["datei"] == "frames/0001.jpg"
    assert "## Vom Bildschirm belegt (1)" in uebergabe.render_md("x", stand, "live")


def test_bildbeleg_ohne_wortlaut_zaehlt_nicht(tmp_path):
    s, hinweise = _souffleur(tmp_path, _BildKi(erfinden=True))
    s.starte(tmp_path)
    s.beobachte_bild({"id": 1, "t": 2.0, "file": "0001.jpg"})
    assert _warte(lambda: (tmp_path / bt.DATEI).is_file())
    s.beobachte(_seg(1, 3.0, "Wer gibt denn die großen Rechnungen frei?"))
    s.abschliessen()
    assert s.leitfaden()["punkte"][0]["status"] == "offen"
    frage = next(h for h in hinweise if h["art"] == "frage")
    assert frage["bild"] is None and frage["ohne_befund"] and frage["ki_text"] == ""
    diag = [json.loads(z) for z in (tmp_path / "souffleur-diagnose.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(v.get("grund") == "ohne_beleg" for d in diag for v in d.get("leitfaden_verworfen", []))


def test_bild_ohne_text_und_abgeschaltet(tmp_path):
    ki = _BildKi()
    s, _ = _souffleur(tmp_path, ki, erkenne=lambda pfad: "")
    s.starte(tmp_path)
    s.beobachte_bild({"id": 1, "t": 2.0, "file": "0001.jpg"})
    assert _warte(lambda: (tmp_path / bt.DATEI).is_file())
    s.beobachte(_seg(1, 3.0, "Wer gibt denn die großen Rechnungen frei?"))
    s.abschliessen()
    assert ki.aufrufe and "## Bildschirm" not in ki.aufrufe[0].prompt  # leerer Bildtext geht nicht in den Prompt

    aus = Souffleur(SouffleurKonfig(wiki_dir=None, backend="attrappe", bildtext=False), ki=None,
                    ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"), erkenne=lambda p: BILDTEXT)
    aus.beobachte_bild({"id": 1, "t": 2.0, "file": "0001.jpg"})
    assert aus._bild_worker is None


def test_wiederaufnahme_liest_bilder_nicht_neu(tmp_path):
    bt.schreibe(tmp_path, [bt.Bild(id="B1", mark_id=1, t=2.0, datei="0001.jpg", text=BILDTEXT)])
    gelesen = []
    s, _ = _souffleur(tmp_path, _BildKi(), erkenne=lambda pfad: gelesen.append(pfad) or BILDTEXT)
    s.starte(tmp_path)
    s.beobachte_bild({"id": 1, "t": 2.0, "file": "0001.jpg", "restored": True})
    s.abschliessen()
    assert gelesen == [] and len(bt.lade(tmp_path)) == 1


@pytest.mark.skipif(sys.platform != "darwin" or not bt.verfuegbar(), reason="Texterkennung nur mit macOS Vision")
def test_vision_liest_text_aus_einem_bild(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 200), "white")
    try:
        schrift = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except OSError:
        pytest.skip("keine Systemschrift")
    zeichnen = ImageDraw.Draw(img)
    zeichnen.text((30, 30), "Zuständig: Bereichsleitung Einkauf", fill="black", font=schrift)
    zeichnen.text((30, 110), "Frist: 15.12.2026", fill="black", font=schrift)
    pfad = tmp_path / "bild.png"
    img.save(pfad)
    text = bt.erkenne(pfad)
    assert "Bereichsleitung Einkauf" in text and text.index("Zuständig") < text.index("Frist")
    assert bt.erkenne(tmp_path / "fehlt.png") == ""
