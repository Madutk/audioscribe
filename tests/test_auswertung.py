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


def test_unbekannter_grund_zaehlt_nur_als_kurzer_bezeichner(tmp_path):
    """Kriterium 16: ein Grund, der kein kurzer Bezeichner ist, zählt unter „sonstige“."""
    ordner = tmp_path / "s"
    ordner.mkdir()
    zeilen = [
        {"fenster_id": 1, "uebergangen": "neuer_grund"},
        {"fenster_id": 2, "uebergangen": "ERFUNDEN ein ganzer Satz statt eines Grundes"},
        {"fenster_id": 3, "ki_antwort_s": 1.0, "verworfen": [{"grund": "x" * 41}, {"grund": "neu_2"}, "kein objekt"]},
    ]
    (ordner / "souffleur-diagnose.jsonl").write_text("".join(json.dumps(z) + "\n" for z in zeilen), encoding="utf-8")
    fenster = auswertung.erzeuge(ordner)["fenster"]
    assert fenster["ohne_ki_aufruf"] == {"neuer_grund": 1, "sonstige": 1}
    assert fenster["verworfen"] == {"sonstige": 2, "neu_2": 1}
    assert "ERFUNDEN" not in (ordner / JSON_DATEI).read_text(encoding="utf-8")
    assert "ERFUNDEN" not in (ordner / MD_DATEI).read_text(encoding="utf-8")


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


def test_j_verworfene_sitzung_bekommt_keine_auswertung(tmp_path):
    sitzung = _kopie(tmp_path, "session-full")  # Quelldateien liegen schon da
    runner = LiveRunner()
    _starte(runner, sitzung, warten=True)
    _warte(lambda: runner.snapshot().get("stats"))
    assert runner.reset() == sitzung
    snap = runner.snapshot()
    assert snap["running"] is False and "auswertung" not in snap
    assert not list(sitzung.glob("souffleur-auswertung*"))


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
