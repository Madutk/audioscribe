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


def _s(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f}".replace(".", ",") + " s"


def _hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _tempo(value: float | None) -> str:
    return "" if value is None else f" ({value:.2f}× Echtzeit)".replace(".", ",")


def beschreibe_live(b: LiveBilanz) -> str:
    rechenzeit = f"Rechenzeit {_s(b.rechenzeit_s)}{_tempo(b.tempo)}"
    if b.vorschau_n:
        rechenzeit += f" · {b.vorschau_n} Vorschauen {_s(b.vorschau_s)}{_tempo(b.tempo_inkl_vorschau)}"
    teile = [f"Aufnahme {_hms(b.aufnahme_s)}", f"Modelle {_s(b.laden_s)}", rechenzeit]
    if b.abschnitte:
        teile.append(
            f"Verzögerung Ø {_s(b.verzoegerung_mittel_s)} / max {_s(b.verzoegerung_max_s)}"
        )
    abschnitte = f"{b.abschnitte} Abschnitte"
    if b.zusammengelegt:
        abschnitte += f" ({b.zusammengelegt} zusammengelegt)"
    if b.eco_abschnitte:
        abschnitte += f" ({b.eco_abschnitte} sparsam)"
    teile.append(abschnitte)
    if b.aufholmodus_s:
        anteil = f" ({round(b.aufholmodus_anteil * 100)} %)" if b.aufholmodus_anteil else ""
        teile.append(f"Aufholmodus {_s(b.aufholmodus_s)}{anteil}")
    teile.append(f"Abschluss {_s(b.abschluss_s)}")
    if b.backend or b.geraet:
        teile.append("/".join(t for t in (b.modell, b.backend, b.geraet) if t))
    return "Fazit: " + " · ".join(teile)


def beschreibe_refine(b: RefineBilanz) -> str:
    stufen = ", ".join(f"{st['name']} {_s(st['dauer_s'])}" for st in b.stufen)
    return f"Fazit Nachschärfen: {_hms(b.gesamt_s)}{_tempo(b.tempo)}" + (f" · {stufen}" if stufen else "")
