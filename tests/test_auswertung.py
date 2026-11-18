"""Auswertung je Meeting (REQ-12): Kennzahlen aus den Dateien einer Sitzung, Kommando, Sitzungsende.

Die Beispielordner unter ``tests/data/auswertung/`` sind erfunden; jeder Text darin beginnt mit
``ERFUNDEN``. Die erwarteten Zahlen stehen im Work Package WP-12.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from audioscribe.cli import main
from audioscribe.souffleur import SOUFFLEUR_DATEIEN, auswertung
from audioscribe.souffleur.kern import Souffleur
from audioscribe.souffleur.ki import AttrappeKi, KiStatus
from audioscribe.souffleur.konfig import SouffleurKonfig
from audioscribe.ui.jobs import LiveJobOptions
from audioscribe.ui.runner import LiveRunner

DATA = Path(__file__).parent / "data" / "auswertung"
MEETING = Path(__file__).parent / "data" / "souffleur" / "meeting"
SRC = Path(__file__).resolve().parents[1] / "src" / "audioscribe"
JSON_DATEI = "souffleur-auswertung.json"
MD_DATEI = "souffleur-auswertung.md"


def _kopie(tmp_path: Path, name: str) -> Path:
    ziel = tmp_path / name
    shutil.copytree(DATA / name, ziel)
    return ziel


def _kaputt(tmp_path: Path) -> Path:
    """Fall 3: Leitfaden kein JSON, zwei unlesbare Zeilen im Diagnose-Log."""
    ordner = _kopie(tmp_path, "session-full")
    (ordner / "souffleur-leitfaden.json").write_text("{kaputt", encoding="utf-8")
    with (ordner / "souffleur-diagnose.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("kein json\n[1, 2\n")
    return ordner


def _gelesen(ordner: Path) -> dict:
    return json.loads((ordner / JSON_DATEI).read_text(encoding="utf-8"))


def _ohne_erzeugt(daten: dict) -> dict:
    return {**daten, "rahmen": {k: v for k, v in daten["rahmen"].items() if k != "erzeugt"}}


def _pruefsummen(ordner: Path) -> dict[str, str]:
    return {
        p.relative_to(ordner).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(ordner.rglob("*"))
        if p.is_file()
    }


# --- Fall 1: session-full -----------------------------------------------------------------

FULL = {
    "hinweise": {
        "gesamt": 7,
        "je_art": {"widerspruch": 2, "frage": 2, "offener_punkt": 2, "anknuepfen": 1},
        "je_sicherheit": {"hoch": 6, "mittel": 1},
        "ohne_befund": 1,
        "je_stunde": 14.0,
    },
    "verzoegerung": {
        "n": 6,
        "sprachende": {"mittel": 12.0, "median": 11.0, "max": 20.0},
        "real": {"mittel": 10.83, "median": 10.0, "max": 18.0},
        "anteile_mittel": {"asr": 2.67, "warten": 2.33, "suche": 0.02, "ki_start": 1.92, "ki_antwort": 6.5},
        "ueber_15s": 2,
        "gestreckt": False,
    },
    "fenster": {
        "gesamt": 13,
        "ohne_ki_aufruf": {"zu_kurz": 3, "ki_pause": 1},
        "ki_aufrufe": 8,
        "ki_fehler": 1,
        "abgebrochen": 1,
        "verworfen": {"ungueltig": 3, "dublette": 1},
        "ki_uebergangen": {
            "smalltalk": 3,
            "organisatorisch": 2,
            "passt_zum_wiki": 1,
            "rhetorische_frage": 1,
            "unverstaendlich": 1,
        },
        "unlesbare_zeilen": 0,
    },
    "leitfaden": {
        "gesamt": 8,
        "je_status": {"offen": 2, "angesprochen": 3, "geklaert": 2, "vertagt": 1},
        "muss_offen": 2,
        "gesetzt_von": {"ki": 3, "moderator": 2, "datei": 3},
        "aus_hinweis": 1,
        "ki_verworfen": {"ohne_beleg": 2, "unveraendert": 1, "unbekannt": 1},
    },
    "mitdenker": {
        "laeufe": 4,
        "gescheitert": 1,
        "karten": 3,
        "je_art": {"bestaetigung": 1, "erkenntnis": 1, "gedanke": 1},
        "je_herkunft": {"wiki": 1, "gespraech": 2, "allgemeinwissen": 1},
        "je_relevanz": {"hoch": 2, "mittel": 1},
        "verworfen": {"relevanz_mittel": 2, "dublette": 1, "ohne_zitat": 1},
        "zeit_bis_karte": {"mittel": 60.0, "median": 45.0, "max": 95.0},
    },
    "verbrauch": {
        "abgleich": {
            "aufrufe": 7,
            "eingabe": 7450,
            "ausgabe": 730,
            "cache_lesen": 28900,
            "cache_schreiben": 200,
            "tokens": 37280,
            "kosten_usd": 0.077,
        },
        "mitdenker": {
            "aufrufe": 3,
            "eingabe": 16500,
            "ausgabe": 2700,
            "cache_lesen": 16500,
            "cache_schreiben": 8500,
            "tokens": 44200,
            "kosten_usd": 0.27,
        },
    },
}
FULL_RAHMEN = {
    "sitzung": "session-full",
    "gestartet": "2026-01-15T10:00:00",
    "aufnahme_s": 1800.0,
    "segmente": 40,
    "ki": {"backend": "claude-agent", "modell": "erfunden-modell"},
    "wiki": {"zustand": "ok", "seiten": 12},
    "replay": False,
    "speed": 1.0,
}


def test_fall_1_session_full(tmp_path):
    ordner = _kopie(tmp_path, "session-full")
    auswertung.erzeuge(ordner)
    daten = _gelesen(ordner)
    assert daten["version"] == 1
    assert list(daten) == [
        "version",
        "rahmen",
        "hinweise",
        "verzoegerung",
        "fenster",
        "leitfaden",
        "mitdenker",
        "verbrauch",
    ]
    rahmen = dict(daten["rahmen"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", rahmen.pop("erzeugt"))
    assert rahmen == FULL_RAHMEN
    for gruppe, erwartet in FULL.items():
        assert daten[gruppe] == erwartet, gruppe

    md = (ordner / MD_DATEI).read_text(encoding="utf-8")
    assert md.startswith("# Auswertung – session-full\n")
    kopf = md.splitlines()[2]
    assert "Aufnahme 30:00 · 40 Segmente · claude-agent (erfunden-modell) · Wiki ok, 12 Seiten" in kopf
    assert "Replay" not in kopf
    # Zahlen deutsch formatiert, dieselben wie in der JSON-Datei.
    assert "7 Hinweise (14,0 je Stunde): 2 Widerspruch · 2 Frage · 2 offener Punkt · 1 Anknüpfen" in md
    assert "Median 11,0 s · Mittel 12,0 s · Maximum 20,0 s · 2 von 6 über 15 s" in md
    assert "13 Fenster · 4 ohne KI-Aufruf (zu kurz 3, KI-Pause 1) · 8 KI-Aufrufe, 1 Fehler" in md
    assert "8 Punkte: 2 offen · 3 angesprochen · 2 geklärt · 1 vertagt · 2 Pflichtpunkte offen" in md
    assert "4 Läufe, 1 gescheitert · 3 Karten: 1 Bestätigung · 1 Erkenntnis · 1 Gedanke" in md
    assert "Abgleich: 7 Aufrufe · 37.280 Tokens" in md and "0,27 USD" in md
    # Vermerke der Kriterien 11 und 14; ohne gestreckte Uhr kein Vermerk dazu (Kriterium 10).
    assert "ungültig enthält auch Befunde mit Sicherheit mittel, die wegen der Einstellung nicht gezeigt wurden" in md
    assert "## Verbrauch (ohne gescheiterte Aufrufe und ohne Essenz)" in md
    assert "gestreckt" not in md and "nicht erfasst" not in md and "nicht lesbar" not in md


# --- Fall 2: session-old ------------------------------------------------------------------


def test_fall_2_session_old(tmp_path):
    ordner = _kopie(tmp_path, "session-old")
    auswertung.erzeuge(ordner)
    daten = _gelesen(ordner)
    rahmen = dict(daten["rahmen"])
    rahmen.pop("erzeugt")
    assert rahmen == {
        "sitzung": "session-old",
        "gestartet": None,
        "aufnahme_s": None,
        "segmente": None,
        "ki": {"backend": "ollama", "modell": "erfunden-lokal"},
        "wiki": {"zustand": "keins", "seiten": 0},
        "replay": None,
        "speed": 4.0,
    }
    assert daten["hinweise"] == {
        "gesamt": 2,
        "je_art": {"frage": 1, "offener_punkt": 1},
        "je_sicherheit": {"hoch": 2},
        "ohne_befund": 0,
        "je_stunde": None,
    }
    assert daten["verzoegerung"] == {
        "n": 2,
        "sprachende": {"mittel": 10.0, "median": 10.0, "max": 11.0},
        "real": {"mittel": 9.0, "median": 9.0, "max": 10.0},
        "anteile_mittel": {"asr": 2.0, "warten": 1.5, "suche": 0.01, "ki_start": 0.0, "ki_antwort": 6.5},
        "ueber_15s": 0,
        "gestreckt": True,
    }
    assert daten["fenster"] == {
        "gesamt": 3,
        "ohne_ki_aufruf": {"zu_kurz": 1},
        "ki_aufrufe": 2,
        "ki_fehler": 0,
        "abgebrochen": 0,
        "verworfen": {},
        "ki_uebergangen": {"smalltalk": 1},
        "unlesbare_zeilen": 0,
    }
    assert daten["leitfaden"] is None and daten["mitdenker"] is None and daten["verbrauch"] is None

    md = (ordner / MD_DATEI).read_text(encoding="utf-8")
    for titel in ("## Leitfaden", "## Mitdenker", "## Verbrauch (ohne gescheiterte Aufrufe und ohne Essenz)"):
        assert f"{titel}\nnicht erfasst\n" in md
    assert "Abspieltempo 4×: Die Sitzungsuhr ist gestreckt" in md


# --- Fall 3: kaputt -----------------------------------------------------------------------


def test_fall_3_kaputte_quellen(tmp_path):
    ordner = _kaputt(tmp_path)
    auswertung.erzeuge(ordner)
    daten = _gelesen(ordner)
    assert daten["leitfaden"] == {"nicht_lesbar": True}
    assert daten["fenster"] == {**FULL["fenster"], "unlesbare_zeilen": 2}
    for gruppe in ("hinweise", "verzoegerung", "mitdenker", "verbrauch"):
        assert daten[gruppe] == FULL[gruppe], gruppe
    md = (ordner / MD_DATEI).read_text(encoding="utf-8")
    assert "## Leitfaden\nnicht lesbar\n" in md
    assert "Unlesbare Zeilen im Diagnose-Log: 2" in md


def test_falsche_form_ist_nicht_lesbar_und_fehlendes_log_laesst_felder_leer(tmp_path):
    ordner = _kopie(tmp_path, "session-full")
    (ordner / "souffleur.json").write_text('{"markierungen": "nein"}', encoding="utf-8")
    (ordner / "souffleur-mitdenker.json").write_text("[]", encoding="utf-8")
    (ordner / "souffleur-diagnose.jsonl").unlink()
    daten = auswertung.erzeuge(ordner)
    assert daten["hinweise"] == daten["verzoegerung"] == daten["mitdenker"] == {"nicht_lesbar": True}
    assert daten["fenster"] is None and daten["verbrauch"] is None
    # Fehlt nur das Diagnose-Log, bleibt der Leitfaden - ohne die verworfenen KI-Meldungen.
    assert daten["leitfaden"] == {**FULL["leitfaden"], "ki_verworfen": None}
    assert "Verworfene KI-Meldungen: nicht erfasst" in (ordner / MD_DATEI).read_text(encoding="utf-8")


def test_unbekannter_grund_zaehlt_unter_sonstige(tmp_path):
    """Kriterium 16: ein unbekannter Wert - auch ein kurzer Bezeichner - steht in keiner der zwei
    Dateien und nicht im Ergebnis; er zählt unter „sonstige“."""
    ordner = tmp_path / "s"
    ordner.mkdir()
    zeilen = [
        {"fenster_id": 1, "uebergangen": "neuer_grund"},
        {"fenster_id": 2, "uebergangen": "ERFUNDEN ein ganzer Satz statt eines Grundes"},
        {"fenster_id": 3, "uebergangen": "zu_kurz"},
        {"fenster_id": 4, "ki_antwort_s": 1.0, "verworfen": [{"grund": "x" * 41}, {"grund": "neu_2"}, "kein objekt"]},
        {"fenster_id": 5, "ki_antwort_s": 1.0, "verworfen": [{"grund": "dublette"}, {"grund": "ohne_beleg"}]},
    ]
    (ordner / "souffleur-diagnose.jsonl").write_text("".join(json.dumps(z) + "\n" for z in zeilen), encoding="utf-8")
    daten = auswertung.erzeuge(ordner)
    assert daten["fenster"]["ohne_ki_aufruf"] == {"zu_kurz": 1, "sonstige": 2}
    # "ohne_beleg" ist ein Grund des Leitfadens, kein Grund für verworfene Befunde.
    assert daten["fenster"]["verworfen"] == {"dublette": 1, "sonstige": 4}
    for text in _alle_fassungen(ordner, daten):
        assert "neuer_grund" not in text and "neu_2" not in text and "xxxx" not in text and "ERFUNDEN" not in text


def _alle_fassungen(ordner: Path, daten: dict) -> list[str]:
    """JSON-Datei, Markdown-Datei und das Ergebnis, wie es in den Sitzungszustand geht."""
    return [
        (ordner / JSON_DATEI).read_text(encoding="utf-8"),
        (ordner / MD_DATEI).read_text(encoding="utf-8"),
        json.dumps(daten, ensure_ascii=False),
    ]


def _fremd(tmp_path: Path) -> Path:
    """session-full mit je einem fremden Wort in ``art``, ``wiki.zustand``, ``ki.backend``,
    ``herkunft``, einem Status, einer Relevanz und Gründen der KI."""
    ordner = _kopie(tmp_path, "session-full")
    stand = json.loads((ordner / "souffleur.json").read_text(encoding="utf-8"))
    stand["markierungen"][0]["art"] = "FREMDART"
    stand["markierungen"][1]["sicherheit"] = "FREMDSICHER"
    stand["wiki"]["zustand"] = "FREMDZUSTAND"
    stand["ki"]["backend"] = "FREMDDIENST"
    (ordner / "souffleur.json").write_text(json.dumps(stand), encoding="utf-8")
    karten = json.loads((ordner / "souffleur-mitdenker.json").read_text(encoding="utf-8"))
    karten["karten"][0]["herkunft"] = ["wiki", "FREMDHERKUNFT"]
    karten["karten"][1]["art"] = "FREMDKARTE"
    karten["karten"][2]["relevanz"] = "FREMDRELEVANZ"
    (ordner / "souffleur-mitdenker.json").write_text(json.dumps(karten), encoding="utf-8")
    punkte = json.loads((ordner / "souffleur-leitfaden.json").read_text(encoding="utf-8"))
    punkte["punkte"][0]["status"] = "FREMDSTATUS"
    punkte["punkte"][1]["gesetzt_von"] = "FREMDURHEBER"
    (ordner / "souffleur-leitfaden.json").write_text(json.dumps(punkte), encoding="utf-8")
    with (ordner / "souffleur-diagnose.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "fenster_id": 14,
                    "ki_antwort_s": 1.0,
                    "verworfen": [{"grund": "FREMDVERWORFEN"}],
                    "uebergangen": [{"segment_id": 1, "grund": "FREMDGRUND"}],
                    "leitfaden_verworfen": [{"punkt_id": "P1", "grund": "FREMDMELDUNG"}],
                }
            )
            + "\n"
            + json.dumps({"spur": "mitdenker", "verworfen": [{"art": "gedanke", "grund": "FREMDKARTENGRUND"}]})
            + "\n"
        )
    return ordner


def test_fremde_woerter_stehen_weder_in_json_noch_markdown_noch_im_zustand(tmp_path):
    ordner = _fremd(tmp_path)
    daten = auswertung.erzeuge(ordner)
    for text in _alle_fassungen(ordner, daten):
        assert "FREMD" not in text
    assert daten["hinweise"]["je_art"] == {
        "widerspruch": 1,
        "frage": 2,
        "offener_punkt": 2,
        "anknuepfen": 1,
        "sonstige": 1,
    }
    assert daten["hinweise"]["je_sicherheit"] == {"hoch": 5, "mittel": 1, "sonstige": 1}
    assert daten["rahmen"]["wiki"] == {"zustand": None, "seiten": 12}
    assert daten["rahmen"]["ki"] == {"backend": None, "modell": "erfunden-modell"}
    assert daten["fenster"]["verworfen"] == {"ungueltig": 3, "dublette": 1, "sonstige": 1}
    assert daten["fenster"]["ki_uebergangen"]["sonstige"] == 1
    assert daten["leitfaden"]["je_status"] == {
        "offen": 2,
        "angesprochen": 3,
        "geklaert": 1,
        "vertagt": 1,
        "sonstige": 1,
    }
    assert daten["leitfaden"]["gesetzt_von"] == {"ki": 2, "moderator": 2, "datei": 3, "sonstige": 1}
    assert daten["leitfaden"]["ki_verworfen"] == {"ohne_beleg": 2, "unbekannt": 1, "unveraendert": 1, "sonstige": 1}
    assert daten["mitdenker"]["je_art"] == {"bestaetigung": 1, "gedanke": 1, "sonstige": 1}
    assert daten["mitdenker"]["je_herkunft"] == {"wiki": 1, "gespraech": 1, "allgemeinwissen": 1, "sonstige": 1}
    assert daten["mitdenker"]["je_relevanz"] == {"hoch": 2, "sonstige": 1}
    assert daten["mitdenker"]["verworfen"]["sonstige"] == 1


def test_fremde_woerter_gelangen_nicht_in_den_sitzungszustand(tmp_path):
    sitzung = _fremd(tmp_path)
    runner = LiveRunner()
    _starte(runner, sitzung, souffleur=None)
    snap = _beendet(runner)
    assert snap["auswertung"]["hinweise"]["je_art"]["sonstige"] == 1
    assert "FREMD" not in json.dumps(snap["auswertung"], ensure_ascii=False)
    assert "FREMD" not in "\n".join(snap["lines"])


def _literale(muster: str, text: str) -> set[str]:
    return {w for fund in re.findall(muster, text) for w in ([fund] if isinstance(fund, str) else fund)}


def test_feste_listen_stimmen_mit_dem_produktcode_ueberein():
    """Listen ohne Konstante im Produktcode: gegen Antwortschemata und Diagnosezeilen geprüft."""
    from audioscribe.souffleur import ki, leitfaden, markierung, mitdenker, prompt, wiki

    def enums(knoten) -> list[list[str]]:
        if isinstance(knoten, dict):
            eigene = [knoten["enum"]] if isinstance(knoten.get("enum"), list) else []
            return eigene + [e for wert in knoten.values() for e in enums(wert)]
        if isinstance(knoten, list):
            return [e for wert in knoten for e in enums(wert)]
        return []

    # Importierte Listen: dieselben Werte wie die Konstanten des Produkts.
    assert set(auswertung.HINWEIS_ARTEN) == set(markierung.ALLE_ARTEN)
    assert auswertung.PUNKT_STATUS == leitfaden.STATUS and auswertung.KARTEN_ARTEN == mitdenker.ARTEN
    assert set(auswertung.KARTEN_HERKUNFT) == set(mitdenker.HERKUNFT_LABEL)
    assert auswertung.KI_DIENSTE == ki.BACKENDS
    assert set(auswertung.WIKI_ZUSTAENDE) == {wiki.ZUSTAND_KEINS, wiki.ZUSTAND_OK, wiki.ZUSTAND_FEHLER, "laedt"}

    kern_text = (SRC / "souffleur" / "kern.py").read_text(encoding="utf-8")
    mitdenker_text = (SRC / "souffleur" / "mitdenker.py").read_text(encoding="utf-8")
    assert '"zustand": "laedt"' in kern_text

    # Antwortschemata der KI: Sicherheit, Relevanz und die Gründe für übergangene Segmente.
    schema = enums(prompt.SCHEMA)
    assert list(auswertung.STUFEN) in schema and list(auswertung.KI_UEBERGANGEN) in schema
    assert list(auswertung.STUFEN) in enums([v for v in vars(mitdenker).values() if isinstance(v, dict)])

    # Diagnosezeilen: was kern.py und mitdenker.py als Grund schreiben.
    assert _literale(r'"uebergangen": "(\w+)"', kern_text) == set(auswertung.OHNE_KI_AUFRUF)
    gruende_kern = _literale(r'"grund": "(\w+)"', kern_text) | _literale(
        r'grund = "(\w+)" if [^\n]* else "(\w+)"', kern_text
    )
    assert gruende_kern == set(auswertung.BEFUND_VERWORFEN) | set(auswertung.LEITFADEN_VERWORFEN)
    assert _literale(r'"art": \S+ "grund": "(\w+)"', kern_text) == set(auswertung.BEFUND_VERWORFEN)
    assert _literale(r'"punkt_id": pid, "grund": "(\w+)"', kern_text) | _literale(
        r'grund = "(\w+)" if [^\n]* else "(\w+)"', kern_text
    ) == set(auswertung.LEITFADEN_VERWORFEN)
    gruende_karten = _literale(r'return None, "(\w+)"', mitdenker_text) | _literale(r'"grund": "(\w+)"', mitdenker_text)
    assert gruende_karten == set(auswertung.KARTEN_VERWORFEN)
    # Jeder Bezeichner hat eine deutsche Bezeichnung für die Markdown-Datei.
    listen = (
        auswertung.HINWEIS_ARTEN,
        auswertung.PUNKT_STATUS,
        auswertung.KARTEN_ARTEN,
        auswertung.KARTEN_HERKUNFT,
        auswertung.STUFEN,
        auswertung.OHNE_KI_AUFRUF,
        auswertung.BEFUND_VERWORFEN,
        auswertung.KI_UEBERGANGEN,
        auswertung.LEITFADEN_VERWORFEN,
        auswertung.KARTEN_VERWORFEN,
    )
    stufen_und_status = {"hoch", "mittel", "offen", "angesprochen", "vertagt", "unbekannt"}
    assert {b for liste in listen for b in liste} - set(auswertung._LABEL) == stufen_und_status


# --- Nicht endliche und übergroße Zahlen, tiefe Verschachtelung ------------------------------


def test_nan_gilt_als_fehlender_wert_und_die_datei_bleibt_gueltiges_json(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.responses import JSONResponse

    ordner = _kopie(tmp_path, "session-full")
    pfad = ordner / "souffleur.json"
    text = pfad.read_text(encoding="utf-8")
    assert text.count('"verzoegerung_s": 8.0') == 1 and text.count('"verzoegerung_real_s": 9.0') == 1
    text = text.replace('"verzoegerung_s": 8.0', '"verzoegerung_s": NaN')
    text = text.replace('"verzoegerung_real_s": 9.0', '"verzoegerung_real_s": Infinity')
    pfad.write_text(text.replace('"speed": 1.0', '"speed": -Infinity'), encoding="utf-8")
    with (ordner / "souffleur-diagnose.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            '{"fenster_id": 14, "ki_antwort_s": 1.0, "verbrauch": {"aufrufe": 1, "kosten_usd": NaN, "tokens": Infinity}}\n'
        )

    daten = auswertung.erzeuge(ordner)

    def streng(wert):
        raise AssertionError(f"nicht endliche Zahl in der Datei: {wert}")

    assert json.loads((ordner / JSON_DATEI).read_text(encoding="utf-8"), parse_constant=streng) == daten
    # Der Hinweis mit NaN fehlt in der Grundmenge; der mit Infinity nur in der realen Verzögerung.
    v = daten["verzoegerung"]
    assert v["n"] == 5 and v["sprachende"] == {"mittel": 12.8, "median": 12.0, "max": 20.0}
    assert v["real"] == {"mittel": 12.25, "median": 13.0, "max": 18.0} and v["gestreckt"] is False
    assert daten["rahmen"]["speed"] is None and daten["hinweise"] == FULL["hinweise"]
    assert daten["verbrauch"]["abgleich"] == {**FULL["verbrauch"]["abgleich"], "aufrufe": 8}
    JSONResponse(daten)  # wirft bei NaN oder Infinity
    md = (ordner / MD_DATEI).read_text(encoding="utf-8").lower()
    assert "nan" not in md and "inf" not in md


@pytest.mark.parametrize("gift", ["1e999", "9" * 400, "[" * 100_000], ids=["1e999", "400-stellen", "tief"])
def test_uebergrosse_zahlen_und_tiefe_verschachtelung_machen_nur_die_gruppe_unlesbar(tmp_path, capsys, gift):
    ordner = _kopie(tmp_path, "session-full")
    if gift.startswith("["):
        (ordner / "souffleur-leitfaden.json").write_text(gift, encoding="utf-8")
    else:
        pfad = ordner / "souffleur-leitfaden.json"
        text = pfad.read_text(encoding="utf-8")
        assert '"version": 1' in text
        pfad.write_text(text.replace('"version": 1', f'"version": {gift}'), encoding="utf-8")
        mit = ordner / "souffleur-mitdenker.json"
        text = mit.read_text(encoding="utf-8")
        assert text.count('"t_hinweis": 120.0') == 1
        mit.write_text(text.replace('"t_hinweis": 120.0', f'"t_hinweis": {gift}'), encoding="utf-8")
    with (ordner / "souffleur-diagnose.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(gift + "\n")
        fh.write(f'{{"fenster_id": 15, "ki_antwort_s": {gift[:400]}}}\n' if not gift.startswith("[") else "\n")

    # Das Kommando endet nie mit einem Traceback.
    assert main(["auswertung", str(ordner)]) == 0
    assert "Traceback" not in capsys.readouterr().err
    daten = _gelesen(ordner)
    assert (ordner / MD_DATEI).is_file()
    assert daten["hinweise"] == FULL["hinweise"] and daten["verzoegerung"] == FULL["verzoegerung"]
    if gift.startswith("["):
        assert daten["leitfaden"] == {"nicht_lesbar": True}
        assert daten["fenster"] == {**FULL["fenster"], "unlesbare_zeilen": 1}
        assert daten["mitdenker"] == FULL["mitdenker"]
    else:
        # Die Zahl steht in einem Feld, das nicht gezählt wird, bzw. gilt als fehlender Wert.
        assert daten["leitfaden"] == FULL["leitfaden"]
        assert daten["mitdenker"]["karten"] == 3
        assert daten["mitdenker"]["zeit_bis_karte"] == {"mittel": 70.0, "median": 70.0, "max": 95.0}
        assert daten["fenster"]["unlesbare_zeilen"] == 1 and daten["fenster"]["gesamt"] == 14
        # ki_antwort_s ohne endlichen Wert: die Zeile gilt nicht als erfolgreicher Aufruf.
        assert daten["fenster"]["ki_aufrufe"] == FULL["fenster"]["ki_aufrufe"]


def test_kommando_meldet_jeden_fehler_ohne_traceback(tmp_path, capsys, monkeypatch):
    ordner = _kopie(tmp_path, "session-full")

    def wirft(session_dir):
        raise RecursionError("zu tief")

    monkeypatch.setattr(auswertung, "erzeuge", wirft)
    assert main(["auswertung", str(ordner)]) != 0
    err = capsys.readouterr().err
    assert "Auswertung fehlgeschlagen" in err and "Traceback" not in err
    assert not list(ordner.glob("souffleur-auswertung*"))


# --- Atomar schreiben ---------------------------------------------------------------------


def test_schreibt_nie_durch_einen_symlink_und_laesst_keine_zwischendatei(tmp_path):
    ordner = _kopie(tmp_path, "session-full")
    fremd = tmp_path / "fremd.txt"
    fremd.write_text("bleibt", encoding="utf-8")
    try:
        (ordner / JSON_DATEI).symlink_to(fremd)
        (ordner / (JSON_DATEI + ".tmp")).symlink_to(fremd)  # der frühere feste Zwischenname
    except OSError:
        pytest.skip("Symlinks hier nicht erlaubt")
    vorher = sorted(p.name for p in ordner.iterdir())
    auswertung.erzeuge(ordner)
    assert fremd.read_text(encoding="utf-8") == "bleibt"
    assert not (ordner / JSON_DATEI).is_symlink() and _gelesen(ordner)["hinweise"] == FULL["hinweise"]
    assert sorted(p.name for p in ordner.iterdir()) == sorted({*vorher, MD_DATEI})


def test_fehler_beim_schreiben_raeumt_die_zwischendatei_auf(tmp_path, monkeypatch):
    ordner = _kopie(tmp_path, "session-full")
    vorher = sorted(p.name for p in ordner.iterdir())

    def kaputt(quelle, ziel):
        raise OSError("Platte voll")

    monkeypatch.setattr(auswertung.os, "replace", kaputt)
    with pytest.raises(OSError, match="Platte voll"):
        auswertung.erzeuge(ordner)
    assert sorted(p.name for p in ordner.iterdir()) == vorher


# --- Segmente zählen wie das Journal ----------------------------------------------------------


def test_segmente_zaehlen_wie_lies_journal(tmp_path):
    from audioscribe.live import journal

    ordner = _kopie(tmp_path, "session-full")
    assert len(journal.lies_journal(ordner).segmente) == 40
    (ordner / "bilanz.json").unlink()
    with (ordner / "sitzung.journal.jsonl").open("a", encoding="utf-8") as fh:
        for zeile in (
            {"art": "segment", "id": 40, "start": 680.0, "end": 689.0, "text": "ERFUNDEN doppelte Nummer"},
            {"art": "segment", "id": 41, "start": 700.0, "end": 705.0, "text": "   "},  # ohne Text
            {"art": "segment", "id": 42, "start": "x", "end": 9999.0, "text": "ERFUNDEN ohne Zeit"},
            {"art": "segment", "start": 1.0, "end": 9999.0, "text": "ERFUNDEN ohne Nummer"},
            {"art": "segment", "id": "43", "start": 1900.0, "end": 1905.5, "text": "ERFUNDEN Nummer als Text"},
            {"art": "takt", "elapsed": "kaputt"},
        ):
            fh.write(json.dumps(zeile) + "\n")
        fh.write("kein json\n")
    rahmen = auswertung.erzeuge(ordner)["rahmen"]
    assert rahmen["segmente"] == len(journal.lies_journal(ordner).segmente) == 41
    # Ohne bilanz.json: der größte Wert aus Takt und Segmentende der gültigen Zeilen.
    assert rahmen["aufnahme_s"] == 1905.5


# --- a bis g ------------------------------------------------------------------------------


def test_a_quelldateien_bleiben_byte_gleich(tmp_path):
    ordner = _kopie(tmp_path, "session-full")
    vorher = _pruefsummen(ordner)
    auswertung.erzeuge(ordner)
    nachher = _pruefsummen(ordner)
    assert set(nachher) - set(vorher) == {JSON_DATEI, MD_DATEI}
    assert {k: nachher[k] for k in vorher} == vorher
    assert not list(ordner.rglob("*.tmp"))


def test_b_zweimal_erzeugt_ist_bis_auf_den_zeitpunkt_gleich(tmp_path):
    ordner = _kopie(tmp_path, "session-full")
    auswertung.erzeuge(ordner)
    erste = _gelesen(ordner)
    auswertung.erzeuge(ordner)  # liest die eigenen zwei Dateien nicht mit
    assert _ohne_erzeugt(_gelesen(ordner)) == _ohne_erzeugt(erste)
    assert sorted(p.name for p in ordner.iterdir() if "auswertung" in p.name) == [JSON_DATEI, MD_DATEI]


@pytest.mark.parametrize("fall", ["session-full", "session-old", "kaputt"])
def test_c_kein_wortlaut_in_der_auswertung(tmp_path, fall):
    ordner = _kaputt(tmp_path) if fall == "kaputt" else _kopie(tmp_path, fall)
    auswertung.erzeuge(ordner)
    for name in (JSON_DATEI, MD_DATEI):
        assert "ERFUNDEN" not in (ordner / name).read_text(encoding="utf-8"), name


def test_d_kommando_schreibt_beide_dateien(tmp_path, capsys):
    ordner = _kopie(tmp_path, "session-full")
    assert main(["auswertung", str(ordner)]) == 0
    assert str(ordner / MD_DATEI) in capsys.readouterr().out
    assert (ordner / JSON_DATEI).is_file() and (ordner / MD_DATEI).is_file()
    assert _gelesen(ordner)["hinweise"] == FULL["hinweise"]


def test_e_kommando_ohne_quelldateien_schreibt_nichts(tmp_path, capsys):
    leer = tmp_path / "leer"
    leer.mkdir()
    (leer / "transkript.md").write_text("# nichts vom Souffleur\n", encoding="utf-8")
    for ziel in (leer, tmp_path / "gibt-es-nicht"):
        assert main(["auswertung", str(ziel)]) != 0
        assert "Keine Auswertung" in capsys.readouterr().err
    assert [p.name for p in leer.iterdir()] == ["transkript.md"]
    assert not (tmp_path / "gibt-es-nicht").exists()


def test_f_kommando_laedt_kein_modell_und_keinen_ki_dienst(tmp_path):
    ordner = _kopie(tmp_path, "session-full")
    code = (
        "import json, sys\n"
        "from audioscribe.cli import main\n"
        "ende = main(['auswertung', sys.argv[1]])\n"
        "geladen = [m for m in ('torch', 'whisperx', 'claude_agent_sdk') if m in sys.modules]\n"
        "print('ERGEBNIS ' + json.dumps({'code': ende, 'geladen': geladen}))\n"
    )
    lauf = subprocess.run(
        [sys.executable, "-c", code, str(ordner)], capture_output=True, text=True, timeout=120, check=False
    )
    assert lauf.returncode == 0, lauf.stderr
    zeile = next(z for z in lauf.stdout.splitlines() if z.startswith("ERGEBNIS "))
    assert json.loads(zeile.removeprefix("ERGEBNIS ")) == {"code": 0, "geladen": []}
    assert (ordner / JSON_DATEI).is_file()


def test_g_sitzung_ohne_hinweise_hat_null_hinweise_nicht_nichts(tmp_path):
    ordner = tmp_path / "ohne-hinweise"
    ordner.mkdir()
    (ordner / "souffleur.json").write_text(
        json.dumps({"version": 1, "sitzung": "ohne-hinweise", "speed": 1.0, "markierungen": []}), encoding="utf-8"
    )
    daten = auswertung.erzeuge(ordner)
    assert daten["hinweise"]["gesamt"] == 0 and daten["hinweise"]["je_art"] == {}
    assert daten["verzoegerung"] is None
    assert daten["fenster"] is None and daten["leitfaden"] is None and daten["mitdenker"] is None
    md = (ordner / MD_DATEI).read_text(encoding="utf-8")
    assert "## Hinweise\n0 Hinweise\n" in md and "## Verzögerung (Sprachende bis Hinweis)\nnicht erfasst\n" in md


# --- h bis k, m: Sitzungsende über den Runner ------------------------------------------------

# Ein Kind, das wie ``audioscribe live`` spricht (Muster: tests/test_souffleur_ui.py). Segmente ab
# der Nummer in argv[2]; mit argv[3] == "warten" bleibt es bis "stop" auf stdin stehen.
KIND = r"""
import json, sys, time
def ev(**d): print('[Live] ' + json.dumps(d, ensure_ascii=False), flush=True)
d, ab = sys.argv[1], int(sys.argv[2])
warten = len(sys.argv) > 3 and sys.argv[3] == 'warten'
t = 300.0 * (ab - 1)
frage = 'Wer pflegt eigentlich die Lieferantenstammdaten?' if ab == 1 else 'Welches Budget gilt für das Hotel in Hamburg?'
ev(type='state', phase='laden', session='live-x', dir=d, model='m', device='cpu')
ev(type='state', phase='laeuft', session='live-x', dir=d, model='m', device='cpu')
ev(type='stats', elapsed=t + 1.0, backlog=0.0, delay=0.5)
ev(type='segment', id=ab, track='system', speaker='Sprecher 1', start=t, end=t + 4.0, text='Guten Morgen zusammen, schön dass alle da sind.', delay=0.5)
ev(type='segment', id=ab + 1, track='mic', speaker='Ich', start=t + 5.0, end=t + 9.0, text=frage, delay=0.5)
ev(type='stats', elapsed=t + 10.0, backlog=0.0, delay=0.5)
if warten:
    for line in sys.stdin:
        if line.strip() == 'stop':
            break
else:
    time.sleep(0.2)
ev(type='fazit', teil='live', abschnitte=2)
ev(type='state', phase='fertig', session='live-x', dir=d, model='m', device='cpu')
"""


def _attrappe(opts=None) -> Souffleur:
    konfig = SouffleurKonfig(wiki_dir=None, backend="attrappe")
    return Souffleur(konfig, ki=AttrappeKi(), ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"))


def _warte(bedingung, timeout: float = 20.0):
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        wert = bedingung()
        if wert:
            return wert
        time.sleep(0.05)
    raise AssertionError("Zeit abgelaufen")


def _beendet(runner: LiveRunner) -> dict:
    return _warte(lambda: (s := runner.snapshot()) and not s["running"] and s)


def _starte(
    runner: LiveRunner,
    sitzung: Path,
    *,
    ab: int = 1,
    warten: bool = False,
    souffleur=_attrappe,
    **optionen,
) -> None:
    """Eine Sitzung über den Runner, ohne Nachlauf (``on_ende``) - wie Testmodus und Demo."""
    sitzung.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-c", KIND, str(sitzung), str(ab), *(["warten"] if warten else [])]
    runner.start(
        LiveJobOptions(output_dir=sitzung.parent, refine=False, **optionen),
        argv_builder=lambda o: argv,
        souffleur_factory=souffleur,
    )


def test_h_sitzungsende_schreibt_die_auswertung_vor_beendet(tmp_path, monkeypatch):
    sitzung = tmp_path / "live-x"
    runner, gesehen = LiveRunner(), {}
    erzeuge = auswertung.erzeuge

    def beobachtet(session_dir):
        daten = erzeuge(session_dir)
        snap = runner.snapshot()
        gesehen.update(
            running=snap["running"],
            phase=snap["phase"],
            souffleur_beendet=snap["souffleur"]["beendet"],
            dateien=sorted(p.name for p in Path(session_dir).iterdir() if "auswertung" in p.name),
        )
        return daten

    monkeypatch.setattr(auswertung, "erzeuge", beobachtet)
    _starte(runner, sitzung)
    snap = _beendet(runner)
    # Beide Dateien lagen im Ordner, als die Oberfläche noch "abschluss" meldete - nach dem
    # Abschluss des Souffleurs, vor "beendet".
    assert gesehen == {
        "running": True,
        "phase": "abschluss",
        "souffleur_beendet": True,
        "dateien": [JSON_DATEI, MD_DATEI],
    }
    assert snap["phase"] == "beendet" and snap["nachlauf"] is None
    # Der Zustand trägt die Auswertung - dieselben Zahlen wie die Datei.
    assert snap["auswertung"] == _gelesen(sitzung)
    daten = snap["auswertung"]
    assert daten["rahmen"]["sitzung"] == "live-x" and daten["rahmen"]["ki"]["backend"] == "attrappe"
    assert daten["hinweise"]["gesamt"] == 1 and daten["hinweise"]["je_art"] == {"frage": 1}
    assert daten["fenster"]["gesamt"] >= 1 and daten["leitfaden"] is None
    assert not any("Auswertung fehlgeschlagen" in z for z in snap["lines"])
    assert {p.name for p in sitzung.iterdir() if p.is_file()} <= set(SOUFFLEUR_DATEIEN)


def test_i_fehler_in_der_auswertung_haelt_das_ende_nicht_auf(tmp_path, monkeypatch):
    def wirft(session_dir):
        raise RuntimeError("Platte voll")

    monkeypatch.setattr(auswertung, "erzeuge", wirft)
    sitzung = tmp_path / "live-x"
    runner = LiveRunner()
    _starte(runner, sitzung)
    snap = _beendet(runner)
    assert snap["phase"] == "beendet" and snap["returncode"] == 0
    assert [z for z in snap["lines"] if "Auswertung fehlgeschlagen: Platte voll" in z]
    assert snap["auswertung"] is None and snap["nachlauf"] is None
    assert not list(sitzung.glob("souffleur-auswertung*"))


class _HaengenderAbschluss(Souffleur):
    """Souffleur, dessen Abschluss stehen bleibt, bis er gestoppt wird - so lässt sich eine Sitzung
    in der Phase „abschluss“ verwerfen, nachdem der Aufnahmeprozess schon mit 0 geendet hat."""

    def __init__(self) -> None:
        konfig = SouffleurKonfig(wiki_dir=None, backend="attrappe")
        super().__init__(konfig, ki=AttrappeKi(), ki_status=KiStatus("bereit", "attrappe", "attrappe", "Attrappe"))
        self.im_abschluss = threading.Event()
        self.gestoppt = threading.Event()

    def abschliessen(self) -> None:
        self.im_abschluss.set()
        assert self.gestoppt.wait(20), "Sitzung wurde nicht verworfen"

    def stop(self) -> None:
        self.gestoppt.set()
        super().stop()


def test_j_verworfene_sitzung_bekommt_keine_auswertung(tmp_path, monkeypatch):
    """Verworfen bei Exit-Code 0: Zurücksetzen während der Phase „abschluss“. Ohne die Prüfung auf
    „verworfen“ im Runner entstünde hier die Auswertung."""
    sitzung = _kopie(tmp_path, "session-full")  # Quelldateien liegen schon da
    aufrufe = []
    erzeuge = auswertung.erzeuge
    monkeypatch.setattr(auswertung, "erzeuge", lambda d: aufrufe.append(d) or erzeuge(d))
    souffleur = _HaengenderAbschluss()
    runner = LiveRunner()
    _starte(runner, sitzung, souffleur=lambda opts: souffleur)
    assert souffleur.im_abschluss.wait(20)
    snap = runner.snapshot()
    assert snap["running"] is True and snap["phase"] == "abschluss"  # das Kind ist schon mit 0 beendet
    assert runner.reset() == sitzung
    snap = runner.snapshot()
    assert snap["running"] is False and "auswertung" not in snap
    assert aufrufe == [] and not list(sitzung.glob("souffleur-auswertung*"))

    # Gegenprobe: dieselbe Sitzung ohne Verwerfen bekommt die Auswertung.
    _starte(runner, sitzung, souffleur=None)
    assert _beendet(runner)["auswertung"]["hinweise"] == FULL["hinweise"] and len(aufrufe) == 1


def test_k_sitzung_ohne_souffleur_dateien_bleibt_ohne_auswertung_und_ohne_fehler(tmp_path):
    sitzung = tmp_path / "live-x"
    runner = LiveRunner()
    _starte(runner, sitzung, souffleur=None)
    snap = _beendet(runner)
    assert snap["phase"] == "beendet" and snap["souffleur"] is None
    assert snap["auswertung"] is None and snap["nachlauf"] is None
    assert list(sitzung.iterdir()) == []
    assert not any("Auswertung" in z for z in snap["lines"])


def test_m_fortgesetzte_sitzung_schreibt_die_auswertung_neu(tmp_path):
    sitzung = tmp_path / "live-x"
    runner = LiveRunner()
    _starte(runner, sitzung)
    erste = _beendet(runner)["auswertung"]
    zeilen_1 = len((sitzung / "souffleur-diagnose.jsonl").read_text(encoding="utf-8").splitlines())
    assert erste["hinweise"]["gesamt"] == 1 and erste["fenster"]["gesamt"] == zeilen_1

    # Zweiter Teil derselben Sitzung: der Souffleur übernimmt den Stand, das Log wächst weiter.
    runner.reset()
    _starte(runner, sitzung, ab=3, resume_dir=sitzung)
    zweite = _beendet(runner)["auswertung"]
    zeilen_2 = len((sitzung / "souffleur-diagnose.jsonl").read_text(encoding="utf-8").splitlines())
    assert zeilen_2 > zeilen_1
    assert zweite["fenster"]["gesamt"] == zeilen_2  # die Zeilen aller Teile
    assert zweite["hinweise"]["gesamt"] == 2 and zweite["verzoegerung"]["n"] == 2
    assert _gelesen(sitzung) == zweite
    assert "2 Hinweise" in (sitzung / MD_DATEI).read_text(encoding="utf-8")


# --- h über die Routen: Replay-Sitzung, Kriterien 1, 3, 6 --------------------------------------


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


def test_replay_sitzung_bekommt_die_auswertung_und_das_kommando_liefert_dasselbe(client, tmp_path):
    from audioscribe.ui import state

    state.save_state({"souffleur_backend": "attrappe"})
    body = {"output_dir": str(tmp_path / "aus"), "replay_transcript": str(MEETING), "replay_speed": 50}
    assert client.post("/api/live/start", json=body).status_code == 200
    try:
        snap = _warte(lambda: (s := client.get("/api/live/status").json()) and not s["running"] and s, timeout=40)
        assert snap["phase"] == "beendet", snap.get("error")
        sitzung = Path(snap["dir"])
        automatisch = _gelesen(sitzung)
        assert snap["auswertung"] == automatisch
        # Als Replay gekennzeichnet, mit gestreckter Sitzungsuhr (Kriterien 6 und 10).
        assert automatisch["rahmen"]["replay"] is True and automatisch["rahmen"]["speed"] == 50.0
        # Ein abgespieltes Transkript führt kein Journal - die Segmentzahl ist dann "nicht erfasst".
        assert not (sitzung / "sitzung.journal.jsonl").exists() and automatisch["rahmen"]["segmente"] is None
        assert automatisch["rahmen"]["aufnahme_s"] > 0 and automatisch["hinweise"]["je_stunde"] > 0
        stand = json.loads((sitzung / "souffleur.json").read_text(encoding="utf-8"))
        assert automatisch["hinweise"]["gesamt"] == len(stand["markierungen"]) > 0
        assert automatisch["verzoegerung"]["gestreckt"] is True
        md = (sitzung / MD_DATEI).read_text(encoding="utf-8")
        assert "· Replay 50× ·" in md.splitlines()[2] and "Die Sitzungsuhr ist gestreckt" in md
        # Ein abgespieltes Transkript geht weiterhin nie von selbst ins Wiki.
        assert snap["nachlauf"] is None and not (sitzung / "LLM-Wiki").exists()
        # Kriterium 3: das Kommando liefert bis auf den Zeitpunkt dasselbe.
        assert main(["auswertung", str(sitzung)]) == 0
        assert _ohne_erzeugt(_gelesen(sitzung)) == _ohne_erzeugt(automatisch)
    finally:
        client.post("/api/live/reset")
    # Zurücksetzen: der Zustand trägt die Auswertung nicht mehr - der Block verschwindet.
    assert "auswertung" not in client.get("/api/live/status").json()


# --- l: nicht in Ablage und Analyse ---------------------------------------------------------


def test_l_auswertung_geht_weder_ins_wiki_noch_ins_analyse_material(projekt, sitzung, tmp_path):
    from dataclasses import replace

    from audioscribe.agent.material import Auftrag, copy_material
    from audioscribe.live import llm_wiki
    from audioscribe.projekt import modell, wiki_ablage

    auswertung.erzeuge(sitzung)
    assert (sitzung / JSON_DATEI).is_file() and (sitzung / MD_DATEI).is_file()

    wiki_ablage.speichere_sitzung(sitzung, projekt, markierungen=True)
    meetings = replace(projekt, wiki_format=modell.FORMAT_MEETINGS)
    wiki_ablage.speichere_sitzung(sitzung, meetings, art="workshop", markierungen=True)
    llm_wiki.erzeuge(sitzung)
    copy_material(Auftrag(name="Analyse", quelle=sitzung, ausgabe=tmp_path / "analyse"))

    ziele = [projekt.wiki_dir, sitzung / "LLM-Wiki", tmp_path / "analyse"]
    assert all(z.is_dir() and any(z.rglob("*")) for z in ziele)
    funde = [str(p) for z in ziele for p in z.rglob("*") if "auswertung" in p.name.lower()]
    assert funde == []
    for z in ziele:
        for p in z.rglob("*.md"):
            assert "souffleur-auswertung" not in p.read_text(encoding="utf-8"), p.name


# --- n, o -------------------------------------------------------------------------------


def test_n_jeder_text_des_blocks_hat_einen_englischen_eintrag():
    from audioscribe import i18n

    static = SRC / "ui" / "static"
    en: dict[str, str] = {}
    for datei in sorted((static / "js" / "en").glob("*.js")):
        if datei.name != "index.js":
            en.update(json.loads(datei.read_text(encoding="utf-8").strip()[len("export default ") : -1]))
    assert "auswertung.js" in (static / "js" / "en" / "index.js").read_text(encoding="utf-8")

    live_js = (static / "js" / "live.js").read_text(encoding="utf-8")
    anfang = live_js.index("function auswertungName(")
    block = live_js[anfang : live_js.index("\nfunction openLightbox(", anfang)]
    texte = re.findall(r"\btr\('((?:\\.|[^'\\])*)'", block)
    assert {"Auswertung", "Hinweise", "Verzögerung", "Fenster", "Leitfaden", "Mitdenker", "Kosten"} <= set(texte)
    assert "nicht erfasst" in texte and "nicht lesbar" in texte
    fehlend = [t for t in texte if t not in en or (en[t] == t and t != "Mitdenker")]
    assert not fehlend, fehlend
    assert 'id="liveAuswertung"' in (static / "index.html").read_text(encoding="utf-8")
    # Die Protokollzeile bei einem Fehler am Sitzungsende.
    assert i18n.woerterbuch("en")["Auswertung fehlgeschlagen: {fehler}"] == "Evaluation failed: {fehler}"


def test_o_auswertungsdateien_stehen_in_souffleur_dateien():
    assert {auswertung.AUSWERTUNG_DATEI, auswertung.AUSWERTUNG_MD_DATEI} == {JSON_DATEI, MD_DATEI}
    assert {JSON_DATEI, MD_DATEI} <= set(SOUFFLEUR_DATEIEN)
    assert not set(auswertung.QUELLDATEIEN) & {JSON_DATEI, MD_DATEI}
