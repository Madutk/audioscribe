"""Fazit einer Live-Sitzung und ihres Nachschärfens: Rechendauer und Latenz (FR-46).

Die ``LiveBilanz`` wird am Ende aus dem Diagnose-Log abgeleitet (``live/diagnose.py``,
FR-47). Das Nachschärfen misst seine Stufen und liefert eine ``RefineBilanz``. Beide landen
als ``bilanz.json`` im Sitzungsordner (atomar geschrieben wie ``analyse.json``), als Zeile im
Protokoll und als ``fazit``-Ereignis in der Oberfläche.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from audioscribe.i18n import sprache, tr

BILANZ_NAME = "bilanz.json"
BILANZ_VERSION = 1

TEIL_LIVE = "live"
TEIL_REFINE = "nachschaerfen"


@dataclass
class LiveBilanz:
    laden_s: float  # Whisper + VAD laden, bis die Sitzungsuhr startet
    aufnahme_s: float  # Stand der Sitzungsuhr beim Stopp
    abschluss_s: float  # Warten auf die letzten Abschnitte nach dem Stopp
    gesamt_s: float  # Prozesszeit vom Start bis zum Speichern
    abschnitte: int = 0  # fertige Abschnitte mit Text
    zusammengelegt: int = 0  # davon aus mehreren Teilen (Aufholmodus)
    audio_s: float = 0.0  # dekodierte Audiosekunden fertiger Abschnitte
    rechenzeit_s: float = 0.0  # Dekodierzeit fertiger Abschnitte samt Sprecherlabel
    tempo: float | None = None  # Rechenzeit je Audiosekunde über die ganze Sitzung
    vorschau_n: int = 0  # dekodierte Vorschauen
    vorschau_s: float = 0.0  # ihre Rechenzeit
    verzoegerung_mittel_s: float | None = None  # Ende des Abschnitts bis Text steht
    verzoegerung_median_s: float | None = None
    verzoegerung_max_s: float | None = None
    rueckstand_max_s: float = 0.0  # wartendes Audio (ohne den gerade gerechneten Abschnitt)
    aufholmodus_s: float = 0.0  # Zeit, in der der Rückstand über einer Chunk-Länge lag
    sprecher_s: float = 0.0  # davon Sprecher-Label (in rechenzeit_s enthalten)
    tempo_inkl_vorschau: float | None = None  # (Dekodieren + Sprecher + Vorschau) je Audiosekunde
    aufholmodus_anteil: float = 0.0  # aufholmodus_s / aufnahme_s
    eco_abschnitte: int = 0  # sparsam dekodierte Abschnitte (Beam 1, kein Fallback)
    # Übersprechen: Mikrofon-Abschnitte, die gegen die System-Spur geprüft wurden, und
    # wie viele davon als Lautsprecher-Echo verworfen wurden (``live/uebersprechen.py``).
    uebersprechen_geprueft: int = 0
    uebersprechen_verworfen: int = 0
    backend: str = ""  # faster-whisper | mlx (FR-52)
    geraet: str = ""  # cuda | mps | cpu
    modell: str = ""


@dataclass
class RefineBilanz:
    gesamt_s: float
    audio_s: float  # längste Spur
    tempo: float | None = None  # Gesamtzeit je Audiosekunde
    modell: str | None = None
    stufen: list[dict] = field(default_factory=list)  # {"name", "dauer_s"}
    # Übersprechen offline geprüft (beide Spuren vorhanden): geprueft, verworfen, lag_s,
    # lag_score und der Abgleich mit den Live-Entscheidungen (bestaetigt, zurueckgeholt,
    # nachtraeglich_entfernt, ohne_text). None ohne System-Spur oder bei Schwelle 0.
    uebersprechen: dict | None = None


# --- Datei ---------------------------------------------------------------------------


def bilanz_path(session_dir: Path) -> Path:
    return Path(session_dir) / BILANZ_NAME


def load_bilanz(session_dir: Path) -> dict | None:
    """Vorhandene Bilanz lesen; ``None`` wenn keine da oder unlesbar."""
    try:
        data = json.loads(bilanz_path(session_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_bilanz(session_dir: Path, teil: str, daten: LiveBilanz | RefineBilanz | dict) -> Path:
    """Einen Teil (``live`` oder ``nachschaerfen``) ablegen, die anderen bleiben erhalten.
    Atomar geschrieben - ein Abbruch hinterlässt nie halbes JSON."""
    data = load_bilanz(session_dir) or {}
    data["version"] = BILANZ_VERSION
    data[teil] = daten if isinstance(daten, dict) else asdict(daten)
    path = bilanz_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# --- Protokollzeile ------------------------------------------------------------------


def _komma(text: str) -> str:
    """Dezimalkomma für die deutsche Oberfläche, Punkt für die englische."""
    return text.replace(".", ",") if sprache() == "de" else text


def _s(value: float | None) -> str:
    return "–" if value is None else _komma(f"{value:.1f}") + " s"


def _hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _tempo(value: float | None) -> str:
    return "" if value is None else tr(" ({wert}× Echtzeit)", wert=_komma(f"{value:.2f}"))


def beschreibe_live(b: LiveBilanz) -> str:
    rechenzeit = tr("Rechenzeit {dauer}", dauer=_s(b.rechenzeit_s)) + _tempo(b.tempo)
    if b.vorschau_n:
        rechenzeit += tr(" · {anzahl} Vorschauen {dauer}", anzahl=b.vorschau_n, dauer=_s(b.vorschau_s)) + _tempo(
            b.tempo_inkl_vorschau
        )
    teile = [tr("Aufnahme {dauer}", dauer=_hms(b.aufnahme_s)), tr("Modelle {dauer}", dauer=_s(b.laden_s)), rechenzeit]
    if b.abschnitte:
        teile.append(
            tr("Verzögerung Ø {mittel} / max {max}", mittel=_s(b.verzoegerung_mittel_s), max=_s(b.verzoegerung_max_s))
        )
    abschnitte = tr("{anzahl} Abschnitte", anzahl=b.abschnitte)
    if b.zusammengelegt:
        abschnitte += tr(" ({anzahl} zusammengelegt)", anzahl=b.zusammengelegt)
    if b.eco_abschnitte:
        abschnitte += tr(" ({anzahl} sparsam)", anzahl=b.eco_abschnitte)
    teile.append(abschnitte)
    if b.uebersprechen_verworfen:
        teile.append(tr("Übersprechen {anzahl} verworfen", anzahl=b.uebersprechen_verworfen))
    if b.aufholmodus_s:
        anteil = f" ({round(b.aufholmodus_anteil * 100)} %)" if b.aufholmodus_anteil else ""
        teile.append(tr("Aufholmodus {dauer}", dauer=_s(b.aufholmodus_s)) + anteil)
    teile.append(tr("Abschluss {dauer}", dauer=_s(b.abschluss_s)))
    if b.backend or b.geraet:
        teile.append("/".join(t for t in (b.modell, b.backend, b.geraet) if t))
    return tr("Fazit: ") + " · ".join(teile)


def beschreibe_refine(b: RefineBilanz) -> str:
    stufen = ", ".join(f"{st['name']} {_s(st['dauer_s'])}" for st in b.stufen)
    text = tr("Fazit Nachschärfen: {dauer}", dauer=_hms(b.gesamt_s)) + _tempo(b.tempo) + (f" · {stufen}" if stufen else "")
    if b.uebersprechen and b.uebersprechen.get("geprueft"):
        text += " · " + beschreibe_uebersprechen(b.uebersprechen)
    return text


def beschreibe_uebersprechen(u: dict) -> str:
    """Eine Zeile zum Offline-Abgleich: ``Übersprechen 3 von 12 verworfen (live bestätigt 2, ...)``."""
    namen = {
        "bestaetigt": tr("live bestätigt"),
        "zurueckgeholt": tr("zurückgeholt"),
        "nachtraeglich_entfernt": tr("nachträglich entfernt"),
    }
    abgleich = [f"{name} {u[key]}" for key, name in namen.items() if u.get(key)]
    text = tr("Übersprechen {verworfen} von {geprueft} verworfen", verworfen=u.get("verworfen", 0), geprueft=u.get("geprueft", 0))
    if abgleich:
        text += f" ({', '.join(abgleich)})"
    return text
