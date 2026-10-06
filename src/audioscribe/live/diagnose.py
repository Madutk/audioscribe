"""Diagnose-Log einer Live-Sitzung: je Abschnitt und je Vorschau eine JSON-Zeile (FR-47).

``diagnose.jsonl`` liegt im Sitzungsordner. Das Fazit (``LiveBilanz``, FR-46) wird am Ende
aus genau diesen Datensätzen abgeleitet - es gibt keine zweite Buchführung, die vom Log
abweichen könnte.

Zeiten: ``t_*``, ``wartezeit_s`` und ``latenz_s`` laufen auf der Sitzungsuhr (Sekunden seit
Aufnahmestart); ``rechenzeit_s`` und ``sprecher_s`` sind reale Sekunden. Bei einem
WAV-Replay mit Tempo 1 ist beides gleich.
"""

from __future__ import annotations

import json
import statistics
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from audioscribe.live.bilanz import LiveBilanz

DIAGNOSE_NAME = "diagnose.jsonl"

ART_ABSCHNITT = "abschnitt"
ART_VORSCHAU = "vorschau"


@dataclass
class Abschnitt:
    """Ein fertiger Abschnitt, wie er den Transkriptions-Thread durchlaufen hat."""

    chunk_index: int
    track: str
    audio_start_s: float
    audio_end_s: float
    audio_dauer_s: float
    t_abgeschlossen: float  # Schnitt-Thread hat den Abschnitt geschlossen
    t_start: float  # Dekodieren beginnt
    t_ende: float  # Text steht
    wartezeit_s: float  # t_abgeschlossen -> t_start
    rechenzeit_s: float  # nur transcribe()
    sprecher_s: float  # Sprecher-Label (Embedding; beim ersten Mal samt Warten aufs Modell)
    latenz_s: float  # audio_end_s -> t_ende
    latenz_max_s: float  # ab Ende des ERSTEN Teils (zusammengelegt), sonst = latenz_s
    modell: str
    eco: bool
    parts: int
    anzahl_woerter: int
    schluss: str  # "pause" | "zeitlimit" | "flush"
    naht: str | None = None  # initial_prompt an der Naht (FR-50)
    naht_wiederholt: bool = False
    segmente: list[dict] = field(default_factory=list)  # avg_logprob, compression_ratio, ...


@dataclass
class Vorschau:
    track: str
    t_start: float
    fenster_s: float  # Länge des offenen Abschnitts, der komplett neu dekodiert wurde
    rechenzeit_s: float
    modell: str


class Diagnose:
    """Sammelt die Datensätze, schreibt sie sofort weg und leitet am Ende das Fazit ab.

    Threadsicher: Schnitt-, Transkriptions- und Hauptthread melden gleichzeitig.
    ``path=None`` hält alles nur im Speicher (Tests)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._file = None
        self.abschnitte: list[Abschnitt] = []
        self.vorschauen: list[Vorschau] = []
        self.rueckstand_proben: list[tuple[float, float]] = []  # (t, backlog_s)

    # --- schreiben ---------------------------------------------------------------

    def abschnitt(self, a: Abschnitt) -> None:
        with self._lock:
            self.abschnitte.append(a)
            self._write({"art": ART_ABSCHNITT, **asdict(a)})

    def vorschau(self, v: Vorschau) -> None:
        with self._lock:
            self.vorschauen.append(v)
            self._write({"art": ART_VORSCHAU, **asdict(v)})

    def rueckstand(self, t: float, backlog_s: float) -> None:
        """Stichprobe der Hauptschleife (einmal je Sekunde) - fürs Fazit, nicht ins Log."""
        with self._lock:
            self.rueckstand_proben.append((t, backlog_s))

    def zeile(self, art: str, **daten: object) -> None:
        """Beliebiger Datensatz (Nachschärfen: Stufen und Segmente)."""
        with self._lock:
            self._write({"art": art, **daten})

    def uebernehme(self, zeilen: list[dict]) -> int:
        """Wiederaufnahme (PRD §21): Abschnitte und Vorschauen eines früheren Teils in den
        Speicher holen, ohne sie erneut zu schreiben - sonst zählte das Fazit nur den letzten
        Teil. Zeilen anderer Art (Nachschärfen) bleiben außen vor. Liefert den höchsten
        ``chunk_index`` (0 ohne Abschnitte)."""
        felder_a = {f.name for f in fields(Abschnitt)}
        felder_v = {f.name for f in fields(Vorschau)}
        with self._lock:
            for z in zeilen:
                try:
                    if z.get("art") == ART_ABSCHNITT:
                        self.abschnitte.append(Abschnitt(**{k: v for k, v in z.items() if k in felder_a}))
                    elif z.get("art") == ART_VORSCHAU:
                        self.vorschauen.append(Vorschau(**{k: v for k, v in z.items() if k in felder_v}))
                except TypeError:
                    continue
            return max((int(a.chunk_index) for a in self.abschnitte), default=0)

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            elif self._path is not None and not self._path.exists():
                # Auch eine Sitzung ohne Abschnitte hinterlässt die Datei - leer, nicht fehlend.
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.touch()

    def _write(self, zeile: dict) -> None:
        """Aufrufer hält den Lock."""
        if self._path is None:
            return
        if self._file is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Nach einem Absturz kann die letzte Zeile abgerissen sein - abschließen, sonst
            # klebte der erste neue Datensatz an ihr und ginge mit verloren.
            abgerissen = False
            try:
                with self._path.open("rb") as alt:
                    alt.seek(0, 2)
                    if alt.tell() > 0:
                        alt.seek(-1, 2)
                        abgerissen = alt.read(1) != b"\n"
            except OSError:
                pass
            self._file = self._path.open("a", encoding="utf-8")
            if abgerissen:
                self._file.write("\n")
        self._file.write(json.dumps(zeile, ensure_ascii=False) + "\n")
        self._file.flush()

    # --- auswerten ---------------------------------------------------------------

    def tempo_letzte(self, n: int = 10) -> float | None:
        """Rechenzeit je Audiosekunde über die letzten ``n`` Abschnitte (None ohne Messung)."""
        with self._lock:
            letzte = self.abschnitte[-n:]
        audio_s = sum(a.audio_dauer_s for a in letzte)
        spent_s = sum(a.rechenzeit_s + a.sprecher_s for a in letzte)
        return round(spent_s / audio_s, 2) if audio_s > 0 else None

    def bilanz(
        self, *, laden_s: float, aufnahme_s: float, abschluss_s: float, gesamt_s: float, schwelle_s: float
    ) -> LiveBilanz:
        """Fazit aus den Datensätzen; ``schwelle_s`` = eine Chunk-Länge (Aufholmodus)."""
        with self._lock:
            abschnitte = list(self.abschnitte)
            vorschauen = list(self.vorschauen)
            proben = list(self.rueckstand_proben)

        mit_text = [a for a in abschnitte if a.anzahl_woerter > 0]
        audio_s = sum(a.audio_dauer_s for a in abschnitte)
        rechen_s = sum(a.rechenzeit_s for a in abschnitte)
        sprecher_s = sum(a.sprecher_s for a in abschnitte)
        vorschau_s = sum(v.rechenzeit_s for v in vorschauen)
        delays = [a.latenz_max_s for a in mit_text]
        aufhol_s = _zeit_ueber(proben, schwelle_s)

        return LiveBilanz(
            laden_s=round(laden_s, 1),
            aufnahme_s=round(aufnahme_s, 1),
            abschluss_s=round(abschluss_s, 1),
            gesamt_s=round(gesamt_s, 1),
            abschnitte=len(mit_text),
            zusammengelegt=sum(1 for a in mit_text if a.parts > 1),
            audio_s=round(audio_s, 1),
            rechenzeit_s=round(rechen_s + sprecher_s, 1),
            tempo=round(rechen_s / audio_s, 2) if audio_s > 0 else None,
            vorschau_n=len(vorschauen),
            vorschau_s=round(vorschau_s, 1),
            verzoegerung_mittel_s=round(statistics.fmean(delays), 1) if delays else None,
            verzoegerung_median_s=round(statistics.median(delays), 1) if delays else None,
            verzoegerung_max_s=round(max(delays), 1) if delays else None,
            rueckstand_max_s=round(max((b for _, b in proben), default=0.0), 1),
            aufholmodus_s=round(aufhol_s, 1),
            sprecher_s=round(sprecher_s, 1),
            tempo_inkl_vorschau=(
                round((rechen_s + sprecher_s + vorschau_s) / audio_s, 2) if audio_s > 0 else None
            ),
            aufholmodus_anteil=round(aufhol_s / aufnahme_s, 2) if aufnahme_s > 0 else 0.0,
            eco_abschnitte=sum(1 for a in abschnitte if a.eco),
        )


def _zeit_ueber(proben: list[tuple[float, float]], schwelle_s: float) -> float:
    """Sekunden, in denen der Rückstand über der Schwelle lag - Stichprobe bis zur nächsten."""
    gesamt = 0.0
    for (t, backlog), (t_next, _) in zip(proben, proben[1:]):
        if backlog > schwelle_s:
            gesamt += t_next - t
    return gesamt


def lies_diagnose(session_dir: Path) -> list[dict]:
    """Alle Zeilen einer ``diagnose.jsonl``; kaputte Zeilen werden übersprungen."""
    path = Path(session_dir) / DIAGNOSE_NAME
    if not path.is_file():
        return []
    zeilen: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            zeilen.append(data)
    return zeilen
