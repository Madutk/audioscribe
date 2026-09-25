"""Fazit einer Live-Sitzung und ihres Nachschärfens: Rechendauer und Latenz (FR-46).

Der Zähler sammelt während der Sitzung je Abschnitt Audiolänge, Rechenzeit und Verzögerung;
am Ende wird daraus eine ``LiveBilanz``. Das Nachschärfen misst seine Stufen und liefert
eine ``RefineBilanz``. Beide landen als ``bilanz.json`` im Sitzungsordner (atomar geschrieben
wie ``analyse.json``), als Zeile im Protokoll und als ``fazit``-Ereignis in der Oberfläche.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
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
    rueckstand_max_s: float = 0.0
    aufholmodus_s: float = 0.0  # Zeit im Sparmodus


@dataclass
class RefineBilanz:
    gesamt_s: float
    audio_s: float  # längste Spur
    tempo: float | None = None  # Gesamtzeit je Audiosekunde
    modell: str | None = None
    stufen: list[dict] = field(default_factory=list)  # {"name", "dauer_s"}


class Zaehler:
    """Sammelt die Messwerte einer Sitzung; threadsicher, weil Schnitt- und
    Transkriptions-Thread und Hauptschleife gleichzeitig melden."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._audio_s = 0.0
        self._spent_s = 0.0
        self._abschnitte = 0
        self._zusammengelegt = 0
        self._delays: list[float] = []
        self._vorschau_n = 0
        self._vorschau_s = 0.0
        self._rueckstand_max = 0.0
        self._aufhol_s = 0.0
        self._aufhol_seit: float | None = None

    def final(self, audio_s: float, spent_s: float, delay_s: float | None, parts: int = 1) -> None:
        with self._lock:
            self._audio_s += audio_s
            self._spent_s += spent_s
            if delay_s is not None:
                self._abschnitte += 1
                self._delays.append(delay_s)
                if parts > 1:
                    self._zusammengelegt += 1

    def partial(self, spent_s: float) -> None:
        with self._lock:
            self._vorschau_n += 1
            self._vorschau_s += spent_s

    def rueckstand(self, backlog_s: float) -> None:
        with self._lock:
            self._rueckstand_max = max(self._rueckstand_max, backlog_s)

    def aufholmodus(self, an: bool, now: float) -> None:
        with self._lock:
            if an and self._aufhol_seit is None:
                self._aufhol_seit = now
            elif not an and self._aufhol_seit is not None:
                self._aufhol_s += now - self._aufhol_seit
                self._aufhol_seit = None

    def bilanz(
        self, *, laden_s: float, aufnahme_s: float, abschluss_s: float, gesamt_s: float, now: float
    ) -> LiveBilanz:
        with self._lock:
            aufhol = self._aufhol_s + (now - self._aufhol_seit if self._aufhol_seit is not None else 0.0)
            delays = list(self._delays)
            return LiveBilanz(
                laden_s=round(laden_s, 1),
                aufnahme_s=round(aufnahme_s, 1),
                abschluss_s=round(abschluss_s, 1),
                gesamt_s=round(gesamt_s, 1),
                abschnitte=self._abschnitte,
                zusammengelegt=self._zusammengelegt,
                audio_s=round(self._audio_s, 1),
                rechenzeit_s=round(self._spent_s, 1),
                tempo=round(self._spent_s / self._audio_s, 2) if self._audio_s > 0 else None,
                vorschau_n=self._vorschau_n,
                vorschau_s=round(self._vorschau_s, 1),
                verzoegerung_mittel_s=round(statistics.fmean(delays), 1) if delays else None,
                verzoegerung_median_s=round(statistics.median(delays), 1) if delays else None,
                verzoegerung_max_s=round(max(delays), 1) if delays else None,
                rueckstand_max_s=round(self._rueckstand_max, 1),
                aufholmodus_s=round(aufhol, 1),
            )


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
    teile = [
        f"Aufnahme {_hms(b.aufnahme_s)}",
        f"Modelle {_s(b.laden_s)}",
        f"Rechenzeit {_s(b.rechenzeit_s)}{_tempo(b.tempo)}",
    ]
    if b.abschnitte:
        teile.append(
            f"Verzögerung Ø {_s(b.verzoegerung_mittel_s)} / max {_s(b.verzoegerung_max_s)}"
        )
    abschnitte = f"{b.abschnitte} Abschnitte"
    if b.zusammengelegt:
        abschnitte += f" ({b.zusammengelegt} zusammengelegt)"
    teile.append(abschnitte)
    if b.aufholmodus_s:
        teile.append(f"Aufholmodus {_s(b.aufholmodus_s)}")
    teile.append(f"Abschluss {_s(b.abschluss_s)}")
    return "Fazit: " + " · ".join(teile)


def beschreibe_refine(b: RefineBilanz) -> str:
    stufen = ", ".join(f"{st['name']} {_s(st['dauer_s'])}" for st in b.stufen)
    return f"Fazit Nachschärfen: {_hms(b.gesamt_s)}{_tempo(b.tempo)}" + (f" · {stufen}" if stufen else "")
