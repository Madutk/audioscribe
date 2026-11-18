"""Auswertung je Meeting (REQ-12): Kennzahlen aus den vorhandenen Dateien einer Sitzung.

Liest ``souffleur.json``, ``souffleur-diagnose.jsonl``, ``souffleur-leitfaden.json``,
``souffleur-mitdenker.json`` sowie ``sitzung.json``, ``sitzung.journal.jsonl`` und ``bilanz.json``
und schreibt daraus zwei neue Begleitdateien: ``souffleur-auswertung.json`` (``version: 1``, je
Gruppe ein Objekt oder ``null``) und ``souffleur-auswertung.md`` (dieselben Zahlen, lesbar).

Leitplanken:

- Es wird **nichts Neues erfasst** und **keine vorhandene Datei geändert** - geschrieben werden
  nur die zwei Auswertungsdateien, jede atomar.
- **Kein Wortlaut**: In die Auswertung gehen nur Zahlen, Zeitangaben und feste Bezeichner (Arten,
  Gründe, Status, Dienst- und Modellname, Ordnername). Texte aus den Quelldateien sind Daten; sie
  werden gezählt, nie übernommen. Ein unbekannter Grund zählt nur dann unter seinem Namen, wenn er
  ein kurzer Bezeichner ist, sonst unter ``sonstige``.
- Fehlt die Quelle einer Gruppe, ist die Gruppe ``null`` ("nicht erfasst"), nie 0. Ist die Quelle
  da, aber nicht lesbar, ist die Gruppe ``{"nicht_lesbar": true}``; der Rest entsteht.
- Nur Standardbibliothek: kein Modell, kein KI-Dienst, kein Netz.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

AUSWERTUNG_DATEI = "souffleur-auswertung.json"
AUSWERTUNG_MD_DATEI = "souffleur-auswertung.md"
AUSWERTUNG_VERSION = 1

STAND_DATEI = "souffleur.json"
DIAGNOSE_DATEI = "souffleur-diagnose.jsonl"
LEITFADEN_DATEI = "souffleur-leitfaden.json"
MITDENKER_DATEI = "souffleur-mitdenker.json"
# Ohne eine dieser vier Dateien war der Souffleur nicht beteiligt - dann entsteht keine Auswertung.
QUELLDATEIEN: tuple[str, ...] = (STAND_DATEI, DIAGNOSE_DATEI, LEITFADEN_DATEI, MITDENKER_DATEI)

SITZUNG_DATEI = "sitzung.json"
JOURNAL_DATEI = "sitzung.journal.jsonl"
BILANZ_DATEI = "bilanz.json"

RICHTWERT_S = 15.0  # PRD NFR-22; gezählt wird "größer als", ohne Wertung
SPUR_MITDENKER = "mitdenker"
SONSTIGE = "sonstige"
NICHT_LESBAR = {"nicht_lesbar": True}

# Feste Reihenfolge der bekannten Bezeichner in der Ausgabe (Unbekanntes steht dahinter).
_ARTEN = ("widerspruch", "frage", "offener_punkt", "anknuepfen")
_STUFEN = ("hoch", "mittel")
_STATUS = ("offen", "angesprochen", "geklaert", "vertagt")
_KARTEN_ARTEN = ("bestaetigung", "erkenntnis", "gedanke")
_HERKUNFT = ("wiki", "gespraech", "allgemeinwissen")

_FEHLT = object()  # Quelldatei nicht vorhanden
_KAPUTT = object()  # vorhanden, aber nicht lesbar (kein JSON, falsche Form)

_BEZEICHNER = re.compile(r"\w{1,40}")
_NAME = re.compile(r"[\w.:/@+-]{1,80}")  # Dienst- und Modellnamen, z. B. "claude-agent", "qwen2.5:14b"


class KeineQuellenFehler(RuntimeError):  # noqa: N818 - deutsche Benennung: Fehler statt Error
    """Der Ordner fehlt oder enthält keine der vier Quelldateien des Souffleurs."""


# --- Lesen ------------------------------------------------------------------------------


def _lies_json(pfad: Path) -> object:
    """Inhalt der Datei, ``_FEHLT`` oder ``_KAPUTT``."""
    if not pfad.is_file():
        return _FEHLT
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _KAPUTT


def _lies_zeilen(pfad: Path) -> tuple[list[dict], int] | object:
    """JSON-Objekte einer ``.jsonl``-Datei und die Zahl der Zeilen, die keins sind.
    Leerzeilen zählen nicht. ``_FEHLT`` ohne Datei, ``_KAPUTT``, wenn sie sich nicht lesen lässt."""
    if not pfad.is_file():
        return _FEHLT
    try:
        roh = pfad.read_bytes()
    except OSError:
        return _KAPUTT
    zeilen: list[dict] = []
    unlesbar = 0
    for teil in roh.splitlines():
        if not teil.strip():
            continue
        try:
            wert = json.loads(teil.decode("utf-8"))
        except ValueError:
            unlesbar += 1
            continue
        if isinstance(wert, dict):
            zeilen.append(wert)
        else:
            unlesbar += 1
    return zeilen, unlesbar


def _liste_von_dicts(wert: object) -> list[dict] | None:
    if isinstance(wert, list) and all(isinstance(e, dict) for e in wert):
        return wert
    return None


# --- Kleine Helfer ----------------------------------------------------------------------


def _zahl(wert: object) -> float | int | None:
    """Nur echte Zahlen - ``True``/``False`` und Texte sind keine."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return wert


def _bezeichner(wert: object) -> str:
    """Ein fester Bezeichner, wie er in der Datei steht - oder ``sonstige`` (kein Wortlaut)."""
    if isinstance(wert, str) and _BEZEICHNER.fullmatch(wert):
        return wert
    return SONSTIGE


def _name(wert: object) -> str | None:
    return wert if isinstance(wert, str) and _NAME.fullmatch(wert) else None


def _zaehle(werte, ordnung: tuple[str, ...] = ()) -> dict[str, int]:
    """Zählt Bezeichner. Nur was vorkommt, steht im Ergebnis - bekannte in fester Reihenfolge
    (``ordnung``) vorn, alle anderen dahinter, wie sie zuerst vorkamen."""
    zaehler: dict[str, int] = {}
    for wert in werte:
        schluessel = _bezeichner(wert)
        zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
    return {k: zaehler[k] for k in (*(o for o in ordnung if o in zaehler), *(k for k in zaehler if k not in ordnung))}


def _stat(werte: list[float]) -> dict:
    if not werte:
        return {"mittel": None, "median": None, "max": None}
    return {
        "mittel": round(statistics.fmean(werte), 2),
        "median": round(statistics.median(werte), 2),
        "max": round(max(werte), 2),
    }


def _mittel(werte: list[float]) -> float | None:
    return round(statistics.fmean(werte), 2) if werte else None


def _gruende(zeilen: list[dict], feld: str) -> dict[str, int]:
    """Zählt ``grund`` über die Listen ``feld`` der Zeilen (Einträge ohne Objektform: ``sonstige``)."""
    return _zaehle(
        (e.get("grund") if isinstance(e, dict) else None)
        for z in zeilen
        if isinstance(z.get(feld), list)
        for e in z[feld]
    )


# --- Gruppen ----------------------------------------------------------------------------


def _rahmen(session_dir: Path, stand: object, journal: object) -> dict:
    sitzung = _lies_json(session_dir / SITZUNG_DATEI)
    sitzung = sitzung if isinstance(sitzung, dict) else {}
    gestartet = sitzung.get("gestartet")
    try:
        datetime.fromisoformat(gestartet)
    except (TypeError, ValueError):
        gestartet = None
    replay = sitzung.get("replay") if isinstance(sitzung.get("replay"), bool) else None

    bilanz = _lies_json(session_dir / BILANZ_DATEI)
    live = bilanz.get("live") if isinstance(bilanz, dict) else None
    aufnahme_s = _zahl(live.get("aufnahme_s")) if isinstance(live, dict) else None
    segmente = None
    if isinstance(journal, tuple):
        zeilen = journal[0]
        segment_zeilen = [z for z in zeilen if z.get("art") == "segment"]
        segmente = len({json.dumps(z["id"], sort_keys=True) for z in segment_zeilen if z.get("id") is not None})
        if aufnahme_s is None:
            zeiten = [_zahl(z.get("elapsed")) for z in zeilen if z.get("art") == "takt"]
            zeiten += [_zahl(z.get("end")) for z in segment_zeilen]
            zeiten = [t for t in zeiten if t is not None]
            aufnahme_s = max(zeiten) if zeiten else None

    stand = stand if isinstance(stand, dict) else {}
    ki, wiki = stand.get("ki"), stand.get("wiki")
    return {
        "sitzung": session_dir.name,
        "gestartet": gestartet,
        "aufnahme_s": None if aufnahme_s is None else round(float(aufnahme_s), 2),
        "segmente": segmente,
        "ki": {"backend": _name(ki.get("backend")), "modell": _name(ki.get("modell"))}
        if isinstance(ki, dict)
        else None,
        "wiki": {
            "zustand": _bezeichner(wiki.get("zustand")) if wiki.get("zustand") is not None else None,
            "seiten": _zahl(wiki.get("seiten")),
        }
        if isinstance(wiki, dict)
        else None,
        "replay": replay,
        "speed": None if _zahl(stand.get("speed")) is None else float(stand["speed"]),
        "erzeugt": datetime.now().isoformat(timespec="seconds"),
    }


def _hinweise(markierungen: list[dict], aufnahme_s: float | None) -> dict:
    gesamt = len(markierungen)
    return {
        "gesamt": gesamt,
        "je_art": _zaehle((m.get("art") for m in markierungen), _ARTEN),
        "je_sicherheit": _zaehle((m.get("sicherheit") for m in markierungen), _STUFEN),
        "ohne_befund": sum(1 for m in markierungen if m.get("ohne_befund") is True),
        "je_stunde": round(gesamt / (aufnahme_s / 3600), 1) if aufnahme_s else None,
    }


def _verzoegerung(markierungen: list[dict], speed: float | None) -> dict | None:
    menge = [m for m in markierungen if m.get("art") != "anknuepfen" and _zahl(m.get("verzoegerung_s")) is not None]
    if not menge:
        return None

    def werte(feld: str) -> list[float]:
        return [m[feld] for m in menge if _zahl(m.get(feld)) is not None]

    return {
        "n": len(menge),
        "sprachende": _stat(werte("verzoegerung_s")),
        "real": _stat(werte("verzoegerung_real_s")),
        "anteile_mittel": {
            "asr": _mittel(werte("anteil_asr_s")),
            "warten": _mittel(werte("anteil_warten_s")),
            "suche": _mittel(werte("anteil_suche_s")),
            "ki_start": _mittel(werte("ki_start_s")),
            "ki_antwort": _mittel(werte("ki_antwort_s")),
        },
        "ueber_15s": sum(1 for m in menge if m["verzoegerung_s"] > RICHTWERT_S),
        "gestreckt": speed is not None and speed != 1,
    }


def _erfolgreich(zeilen: list[dict]) -> list[dict]:
    return [z for z in zeilen if z.get("ki_antwort_s") is not None]


def _fenster(zeilen: list[dict], unlesbar: int) -> dict:
    fenster = [z for z in zeilen if "spur" not in z]
    erfolgreich = _erfolgreich(fenster)
    fehler = [z for z in fenster if "fehler" in z]
    ki_fehler = sum(1 for z in fehler if "treffer" in z)
    return {
        "gesamt": len(fenster),
        "ohne_ki_aufruf": _zaehle(z["uebergangen"] for z in fenster if isinstance(z.get("uebergangen"), str)),
        "ki_aufrufe": len(erfolgreich) + ki_fehler,
        "ki_fehler": ki_fehler,
        "abgebrochen": len(fehler) - ki_fehler,
        "verworfen": _gruende(erfolgreich, "verworfen"),
        "ki_uebergangen": _gruende(erfolgreich, "uebergangen"),
        "unlesbare_zeilen": unlesbar,
    }


def _leitfaden(punkte: list[dict], diagnose: list[dict] | None) -> dict:
    urheber = {"ki": 0, "moderator": 0, "datei": 0}
    for p in punkte:
        von = p.get("gesetzt_von")
        schluessel = "ki" if von == "ki" else "moderator" if von == "nutzer" else "datei" if von is None else SONSTIGE
        urheber[schluessel] = urheber.get(schluessel, 0) + 1
    return {
        "gesamt": len(punkte),
        "je_status": _zaehle((p.get("status") for p in punkte), _STATUS),
        "muss_offen": sum(
            1 for p in punkte if p.get("prioritaet") == "muss" and p.get("status") not in ("geklaert", "vertagt")
        ),
        "gesetzt_von": urheber,
        "aus_hinweis": sum(
            1 for p in punkte if isinstance(p.get("herkunft"), str) and p["herkunft"].startswith("hinweis:")
        ),
        "ki_verworfen": None
        if diagnose is None
        else _gruende(_erfolgreich([z for z in diagnose if "spur" not in z]), "leitfaden_verworfen"),
    }


def _mitdenker(daten: dict, karten: list[dict], diagnose: list[dict] | None) -> dict:
    bilanz = daten.get("bilanz") if isinstance(daten.get("bilanz"), dict) else {}
    zeiten = [
        k["t_hinweis"] - k["t_end"]
        for k in karten
        if _zahl(k.get("t_hinweis")) is not None and _zahl(k.get("t_end")) is not None
    ]
    return {
        "laeufe": _zahl(bilanz.get("laeufe")),
        "gescheitert": _zahl(bilanz.get("fehler")),
        "karten": len(karten),
        "je_art": _zaehle((k.get("art") for k in karten), _KARTEN_ARTEN),
        # Eine Karte mit zwei Herkünften zählt bei beiden.
        "je_herkunft": _zaehle(
            (h for k in karten for h in (k["herkunft"] if isinstance(k.get("herkunft"), list) else [])), _HERKUNFT
        ),
        "je_relevanz": _zaehle((k.get("relevanz") for k in karten), _STUFEN),
        "verworfen": None
        if diagnose is None
        else _gruende([z for z in diagnose if z.get("spur") == SPUR_MITDENKER], "verworfen"),
        "zeit_bis_karte": _stat(zeiten),
    }


_VERBRAUCH_FELDER = ("aufrufe", "eingabe", "ausgabe", "cache_lesen", "cache_schreiben", "tokens")


def _verbrauch_spur(zeilen: list[dict]) -> dict | None:
    posten = [z["verbrauch"] for z in zeilen if isinstance(z.get("verbrauch"), dict)]
    if not posten:
        return None
    summe: dict = {feld: sum(w for p in posten if (w := _zahl(p.get(feld))) is not None) for feld in _VERBRAUCH_FELDER}
    kosten = [w for p in posten if (w := _zahl(p.get("kosten_usd"))) is not None]
    summe["kosten_usd"] = round(sum(kosten), 6) if kosten else None
    return summe


def _verbrauch(zeilen: list[dict]) -> dict | None:
    spuren = {
        "abgleich": _verbrauch_spur([z for z in zeilen if "spur" not in z]),
        "mitdenker": _verbrauch_spur([z for z in zeilen if z.get("spur") == SPUR_MITDENKER]),
    }
    return None if all(v is None for v in spuren.values()) else spuren


# --- Auswertung -------------------------------------------------------------------------


def hat_quellen(session_dir: str | Path) -> bool:
    """Liegt im Ordner mindestens eine der vier Quelldateien des Souffleurs?"""
    session_dir = Path(session_dir)
    return session_dir.is_dir() and any((session_dir / name).is_file() for name in QUELLDATEIEN)


def werte_aus(session_dir: str | Path) -> dict:
    """Die Auswertung eines Sitzungsordners als Dict. Liest nur, schreibt nichts."""
    session_dir = Path(session_dir)
    stand = _lies_json(session_dir / STAND_DATEI)
    diagnose = _lies_zeilen(session_dir / DIAGNOSE_DATEI)
    journal = _lies_zeilen(session_dir / JOURNAL_DATEI)
    diagnose_zeilen = diagnose[0] if isinstance(diagnose, tuple) else None

    rahmen = _rahmen(session_dir, stand, journal)

    hinweise: dict | None
    verzoegerung: dict | None
    if stand is _FEHLT:
        hinweise = verzoegerung = None
    else:
        markierungen = _liste_von_dicts(stand.get("markierungen")) if isinstance(stand, dict) else None
        if markierungen is None:
            hinweise, verzoegerung = dict(NICHT_LESBAR), dict(NICHT_LESBAR)
        else:
            hinweise = _hinweise(markierungen, rahmen["aufnahme_s"])
            verzoegerung = _verzoegerung(markierungen, rahmen["speed"])

    fenster: dict | None
    verbrauch: dict | None
    if diagnose is _FEHLT:
        fenster = verbrauch = None
    elif diagnose_zeilen is None:
        fenster, verbrauch = dict(NICHT_LESBAR), dict(NICHT_LESBAR)
    else:
        fenster = _fenster(diagnose_zeilen, diagnose[1])
        verbrauch = _verbrauch(diagnose_zeilen)

    leitfaden: dict | None
    roh = _lies_json(session_dir / LEITFADEN_DATEI)
    if roh is _FEHLT:
        leitfaden = None
    else:
        punkte = _liste_von_dicts(roh.get("punkte")) if isinstance(roh, dict) else None
        leitfaden = dict(NICHT_LESBAR) if punkte is None else _leitfaden(punkte, diagnose_zeilen)

    mitdenker: dict | None
    roh = _lies_json(session_dir / MITDENKER_DATEI)
    if roh is _FEHLT:
        mitdenker = None
    else:
        karten = _liste_von_dicts(roh.get("karten")) if isinstance(roh, dict) else None
        mitdenker = dict(NICHT_LESBAR) if karten is None else _mitdenker(roh, karten, diagnose_zeilen)

    return {
        "version": AUSWERTUNG_VERSION,
        "rahmen": rahmen,
        "hinweise": hinweise,
        "verzoegerung": verzoegerung,
        "fenster": fenster,
        "leitfaden": leitfaden,
        "mitdenker": mitdenker,
        "verbrauch": verbrauch,
    }


# --- Ablage (nur die zwei Auswertungsdateien) ---------------------------------------------


def _atomar(pfad: Path, text: str) -> None:
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, pfad)
    finally:
        tmp.unlink(missing_ok=True)


def schreibe(session_dir: str | Path, daten: dict) -> Path:
    """``souffleur-auswertung.json`` und ``souffleur-auswertung.md`` schreiben (atomar). Mehr nicht."""
    session_dir = Path(session_dir)
    _atomar(session_dir / AUSWERTUNG_DATEI, json.dumps(daten, ensure_ascii=False, indent=2) + "\n")
    _atomar(session_dir / AUSWERTUNG_MD_DATEI, render_markdown(daten))
    return session_dir / AUSWERTUNG_MD_DATEI


def erzeuge(session_dir: str | Path) -> dict:
    """Auswertung rechnen und beide Dateien schreiben; liefert die Auswertung.
    ``KeineQuellenFehler``, wenn der Ordner fehlt oder keine der vier Quelldateien enthält."""
    session_dir = Path(session_dir)
    if not hat_quellen(session_dir):
        raise KeineQuellenFehler(str(session_dir))
    daten = werte_aus(session_dir)
    schreibe(session_dir, daten)
    return daten


def am_sitzungsende(session_dir: str | Path, protokoll: Callable[[str], None]) -> dict | None:
    """Am Ende einer sauber beendeten Sitzung: Auswertung schreiben, wenn der Souffleur beteiligt
    war. Liefert die Auswertung für den Sitzungszustand, ``None`` ohne Quelldateien. Jeder Fehler
    wird gefangen und als Zeile ans Protokoll der Oberfläche gegeben - die Sitzung endet trotzdem."""
    from audioscribe.i18n import tr

    try:
        if not hat_quellen(session_dir):
            return None
        return erzeuge(session_dir)
    except Exception as exc:  # noqa: BLE001 - die Auswertung darf das Sitzungsende nie verhindern
        protokoll(tr("Auswertung fehlgeschlagen: {fehler}", fehler=exc))
        return None


# --- Markdown ---------------------------------------------------------------------------

NICHT_ERFASST = "nicht erfasst"
NICHT_LESBAR_TEXT = "nicht lesbar"

# Deutsche Bezeichnungen der bekannten Bezeichner; ein unbekannter steht, wie er in der Datei steht.
_LABEL = {
    "widerspruch": "Widerspruch",
    "frage": "Frage",
    "offener_punkt": "offener Punkt",
    "anknuepfen": "Anknüpfen",
    "zu_kurz": "zu kurz",
    "keine_ki": "keine KI",
    "ki_pause": "KI-Pause",
    "ungueltig": "ungültig",
    "dublette": "Dublette",
    "smalltalk": "Smalltalk",
    "organisatorisch": "Organisatorisches",
    "passt_zum_wiki": "passt zum Wiki",
    "rhetorische_frage": "rhetorische Frage",
    "unverstaendlich": "unverständlich",
    "geklaert": "geklärt",
    "ohne_beleg": "ohne Beleg",
    "unveraendert": "unverändert",
    "abweichung_ohne_beleg": "Abweichung ohne Beleg",
    "bestaetigung": "Bestätigung",
    "erkenntnis": "Erkenntnis",
    "gedanke": "Gedanke",
    "wiki": "Wiki",
    "gespraech": "Gespräch",
    "allgemeinwissen": "KI-Wissen",
    "relevanz_mittel": "Relevanz mittel",
    "ohne_zitat": "ohne Zitat",
    "moderator": "Moderator",
    "datei": "Datei",
    "ki": "KI",
}


def _label(bezeichner: str) -> str:
    return _LABEL.get(bezeichner, bezeichner)


def _n(wert: object) -> str:
    """Ganze Zahl mit Tausenderpunkt; ``None`` als "nicht erfasst"."""
    if _zahl(wert) is None:
        return NICHT_ERFASST
    return f"{wert:,.0f}".replace(",", ".")


def _komma(wert: float, stellen: int = 1) -> str:
    return f"{wert:,.{stellen}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _s(wert: float | None, stellen: int = 1) -> str:
    """Sekunden deutsch formatiert, wie ``markierung._s``."""
    return "–" if wert is None else f"{_komma(wert, stellen)} s"


def _dauer(sekunden: float) -> str:
    s = round(sekunden)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def _mz(n: int, einzahl: str, mehrzahl: str) -> str:
    return f"{_n(n)} {einzahl if n == 1 else mehrzahl}"


def _zahl_label(zaehler: dict, trenner: str = " · ") -> str:
    """Zahl vor Bezeichnung: "2 Widerspruch · 3 Frage"."""
    return trenner.join(f"{_n(n)} {_label(k)}" for k, n in zaehler.items()) or "–"


def _label_zahl(zaehler: dict, trenner: str = ", ") -> str:
    """Bezeichnung vor Zahl: "zu kurz 29, KI-Pause 2"."""
    return trenner.join(f"{_label(k)} {_n(n)}" for k, n in zaehler.items())


def _stat_text(stat: dict, stellen: int = 1) -> str:
    return (
        f"Median {_s(stat.get('median'), stellen)} · Mittel {_s(stat.get('mittel'), stellen)} · "
        f"Maximum {_s(stat.get('max'), stellen)}"
    )


def _abschnitt(titel: str, gruppe: dict | None, zeilen: Callable[[dict], list[str]]) -> list[str]:
    if gruppe is None:
        inhalt = [NICHT_ERFASST]
    elif gruppe.get("nicht_lesbar"):
        inhalt = [NICHT_LESBAR_TEXT]
    else:
        inhalt = zeilen(gruppe)
    return [f"## {titel}", *inhalt, ""]


def _md_kopf(r: dict) -> str:
    teile = ["Erzeugt " + str(r.get("erzeugt") or "–").replace("T", " ")[:16]]
    if r.get("replay"):
        speed = r.get("speed")
        teile.append("Replay" if speed in (None, 1) else f"Replay {speed:g}×")
    if r.get("gestartet"):
        teile.append("Start " + str(r["gestartet"]).replace("T", " ")[:16])
    aufnahme = r.get("aufnahme_s")
    teile.append("Aufnahme " + (NICHT_ERFASST if aufnahme is None else _dauer(aufnahme)))
    segmente = r.get("segmente")
    teile.append("Segmente " + NICHT_ERFASST if segmente is None else _mz(segmente, "Segment", "Segmente"))
    ki = r.get("ki")
    if ki is None:
        teile.append("KI " + NICHT_ERFASST)
    else:
        teile.append(f"{ki.get('backend') or 'KI'} ({ki.get('modell') or '–'})")
    wiki = r.get("wiki")
    if wiki is None:
        teile.append("Wiki " + NICHT_ERFASST)
    else:
        seiten = wiki.get("seiten")
        teile.append(
            f"Wiki {wiki.get('zustand') or '–'}, "
            + ("Seiten " + NICHT_ERFASST if seiten is None else _mz(seiten, "Seite", "Seiten"))
        )
    return " · ".join(teile)


def _md_hinweise(h: dict) -> list[str]:
    je_stunde = "" if h.get("je_stunde") is None else f" ({_komma(h['je_stunde'])} je Stunde)"
    arten = f": {_zahl_label(h['je_art'])}" if h.get("je_art") else ""
    return [
        f"{_mz(h['gesamt'], 'Hinweis', 'Hinweise')}{je_stunde}{arten}",
        f"Sicherheit: {_zahl_label(h.get('je_sicherheit') or {})} · ohne Befund: {_n(h.get('ohne_befund'))}",
    ]


def _md_verzoegerung(v: dict, speed: float | None) -> list[str]:
    a = v["anteile_mittel"]
    zeilen = [
        f"{_stat_text(v['sprachende'])} · {_n(v['ueber_15s'])} von {_n(v['n'])} über 15 s",
        f"real: {_stat_text(v['real'])}",
        f"Anteile im Mittel: Spracherkennung {_s(a['asr'])} · Warten {_s(a['warten'])} · Suche {_s(a['suche'])} · "
        f"KI-Start {_s(a['ki_start'])} · KI-Antwort {_s(a['ki_antwort'])}",
    ]
    if v.get("gestreckt"):
        zeilen.append(
            f"Replay mit Abspieltempo {speed:g}×: Die Sitzungsuhr ist gestreckt – die Verzögerung Sprachende bis "
            "Hinweis ist entsprechend länger, die reale nicht."
        )
    return zeilen


def _md_fenster(f: dict) -> list[str]:
    ohne = f["ohne_ki_aufruf"]
    klammer = f" ({_label_zahl(ohne)})" if ohne else ""
    verworfen, uebergangen = f["verworfen"], f["ki_uebergangen"]
    zeilen = [
        f"{_n(f['gesamt'])} Fenster · {_n(sum(ohne.values()))} ohne KI-Aufruf{klammer} · "
        f"{_mz(f['ki_aufrufe'], 'KI-Aufruf', 'KI-Aufrufe')}, {_n(f['ki_fehler'])} Fehler · "
        f"{_n(f['abgebrochen'])} abgebrochen",
        f"Verworfene Befunde: {_zahl_label(verworfen, ', ') if verworfen else '0'} "
        "(ungültig enthält auch Befunde mit Sicherheit mittel, die wegen der Einstellung nicht gezeigt wurden)",
        f"Von der KI übergangen: {_mz(sum(uebergangen.values()), 'Segment', 'Segmente')}"
        + (f" ({_label_zahl(uebergangen)})" if uebergangen else ""),
    ]
    if f.get("unlesbare_zeilen"):
        zeilen.append(f"Unlesbare Zeilen im Diagnose-Log: {_n(f['unlesbare_zeilen'])} (übersprungen)")
    return zeilen


def _md_leitfaden(lf: dict) -> list[str]:
    muss = lf["muss_offen"]
    status = f": {_zahl_label(lf['je_status'])}" if lf.get("je_status") else ""
    verworfen = lf.get("ki_verworfen")
    return [
        f"{_mz(lf['gesamt'], 'Punkt', 'Punkte')}{status} · {_mz(muss, 'Pflichtpunkt', 'Pflichtpunkte')} offen",
        f"Status gesetzt von: {_label_zahl(lf['gesetzt_von'], ' · ')} · aus Hinweis übernommen: {_n(lf['aus_hinweis'])}",
        "Verworfene KI-Meldungen: "
        + (NICHT_ERFASST if verworfen is None else _zahl_label(verworfen, ", ") if verworfen else "0"),
    ]


def _md_mitdenker(m: dict) -> list[str]:
    arten = f": {_zahl_label(m['je_art'])}" if m.get("je_art") else ""
    verworfen = m.get("verworfen")
    zeit = m["zeit_bis_karte"]
    return [
        ("Läufe " + NICHT_ERFASST if m.get("laeufe") is None else _mz(m["laeufe"], "Lauf", "Läufe"))
        + ", "
        + ("gescheiterte " + NICHT_ERFASST if m.get("gescheitert") is None else f"{_n(m['gescheitert'])} gescheitert")
        + f" · {_mz(m['karten'], 'Karte', 'Karten')}{arten}",
        f"Herkunft: {_label_zahl(m['je_herkunft'], ' · ') or '–'} · Relevanz: {_zahl_label(m['je_relevanz'])}",
        "Verworfen: "
        + (NICHT_ERFASST if verworfen is None else _zahl_label(verworfen, ", ") if verworfen else "0")
        + " · Zeit bis zur Karte: "
        + ("–" if zeit.get("median") is None else _stat_text(zeit, 0)),
    ]


def _md_verbrauch(v: dict) -> list[str]:
    zeilen = []
    for spur, name in (("abgleich", "Abgleich"), ("mitdenker", "Mitdenker")):
        s = v.get(spur)
        if s is None:
            zeilen.append(f"{name}: {NICHT_ERFASST}")
            continue
        kosten = NICHT_ERFASST if s.get("kosten_usd") is None else f"{_komma(s['kosten_usd'], 2)} USD"
        zeilen.append(
            f"{name}: {_mz(s['aufrufe'], 'Aufruf', 'Aufrufe')} · {_n(s['tokens'])} Tokens "
            f"(Eingabe {_n(s['eingabe'])} · Ausgabe {_n(s['ausgabe'])} · Cache gelesen {_n(s['cache_lesen'])} · "
            f"Cache geschrieben {_n(s['cache_schreiben'])}) · Kosten {kosten}"
        )
    return zeilen


def render_markdown(daten: dict) -> str:
    """Die Auswertung lesbar - dieselben Zahlen wie in der JSON-Datei, deutsch formatiert."""
    r = daten["rahmen"]
    zeilen = [f"# Auswertung – {r['sitzung']}", "", _md_kopf(r), ""]
    zeilen += _abschnitt("Hinweise", daten["hinweise"], _md_hinweise)
    zeilen += _abschnitt(
        "Verzögerung (Sprachende bis Hinweis)", daten["verzoegerung"], lambda v: _md_verzoegerung(v, r.get("speed"))
    )
    zeilen += _abschnitt("Übergangen und verworfen", daten["fenster"], _md_fenster)
    zeilen += _abschnitt("Leitfaden", daten["leitfaden"], _md_leitfaden)
    zeilen += _abschnitt("Mitdenker", daten["mitdenker"], _md_mitdenker)
    zeilen += _abschnitt("Verbrauch (ohne gescheiterte Aufrufe und ohne Essenz)", daten["verbrauch"], _md_verbrauch)
    return "\n".join(zeilen).rstrip("\n") + "\n"
