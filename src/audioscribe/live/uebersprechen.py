"""Übersprechen: Mikrofon-Abschnitte erkennen, die nur das Lautsprecher-Echo der System-Spur sind.

Spielt die Gegenseite über Lautsprecher, hört das Mikrofon sie mit - derselbe Satz stünde
dann doppelt im Transkript, einmal als „Ich“. Es gibt keine Echo-Unterdrückung, aber beide
Spuren liegen auf derselben Sitzungsuhr: Ist die Lautstärke-Hüllkurve eines Mikrofon-
Abschnitts (mit kleinem Zeitversatz) fast dieselbe wie die der System-Spur, ist er Echo.

Hüllkurve statt Wellenform: Lautsprecher, Raum und Mikrofon verbiegen das Signal, die
Silbenrhythmik bleibt. Logarithmisch (dB), damit nicht die zwei lautesten Silben alles
bestimmen, und trendbereinigt, damit zwei beliebige „jemand redet gerade“-Verläufe nicht
schon über den gemeinsamen An- und Abstieg korrelieren.

Vorzeichen: ``lag > 0`` heißt, das Mikrofon hört den Inhalt später als die System-Spur
(Ausgabe- und Eingangslatenz plus Luftweg, typisch 50-250 ms). Zu ``mic[t0:t1]`` gehört
daher ``system[t0 - lag_max : t1 - lag_min]``; dieses Fenster liefert der Aufrufer.

Alles hier ist rein (numpy/scipy) und läuft live wie beim Nachschärfen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from audioscribe.live.track import SAMPLE_RATE

HOP_S = 0.02  # Hüllkurven-Raster
FENSTER_S = 0.04  # RMS-Fenster je Rasterpunkt
LAG_MIN_S = -0.16  # Mikrofon früher als System (Drift, Pufferung); 8 Raster
LAG_MAX_S = 0.5  # Mikrofon später: Ausgabe- und Eingangslatenz, Luftweg, Drift; 25 Raster
STILLE_RMS = 1e-3  # ca. -60 dBFS: ein so leises System kann kein Echo verursachen
MIN_DAUER_S = 0.8  # kürzere Abschnitte haben zu wenig Hüllkurve und werden nie verworfen
TREND_S = 0.4  # gleitender Mittelwert, der von der Hüllkurve abgezogen wird
BODEN_DB = -60.0  # Hüllkurven-Boden unter dem Maximum des Fensters
# Schwelle: Korrelation, ab der ein Abschnitt als Echo gilt (0 = aus). Die Basis gilt ab
# ZUSCHLAG_BIS_S Länge; kürzere Abschnitte haben weniger Hüllkurve, da wird das Maximum über
# die Lags zufällig hoch - je fehlender Sekunde kommt ZUSCHLAG_JE_S dazu. Kalibriert an
# synthetischer Silbensprache: fremde Sprache und Doppelsprechen bleiben in allen Längen
# unter 0,3 % falscher Verwerfungen, Echo ab 2 s wird zu ~90 %, ab 3 s vollständig erkannt.
SCHWELLE = 0.7
ZUSCHLAG_BIS_S = 3.0
ZUSCHLAG_JE_S = 0.1

VERWORFEN = "verworfen"
BEHALTEN = "behalten"
GRUND_ZU_KURZ = "zu_kurz"
GRUND_OHNE_SYSTEM = "ohne_system"


@dataclass(frozen=True)
class Pruefung:
    score: float  # beste normierte Korrelation der Hüllkurven (-1..1)
    lag_s: float  # Zeitversatz, bei dem sie erreicht wurde
    dauer_s: float
    abdeckung: float  # Anteil des Abschnitts, für den System-Audio vorlag (live < 1 möglich)
    verworfen: bool
    schwelle: float = 0.0  # die für diese Länge geltende Schwelle
    grund: str = ""  # "" | zu_kurz | ohne_system

    @property
    def entscheidung(self) -> str:
        return VERWORFEN if self.verworfen else BEHALTEN


def schwelle_fuer(dauer_s: float, basis: float = SCHWELLE) -> float:
    """Geltende Schwelle für einen Abschnitt dieser Länge (siehe ``SCHWELLE``)."""
    if basis <= 0:
        return 0.0
    return round(basis + max(0.0, ZUSCHLAG_BIS_S - dauer_s) * ZUSCHLAG_JE_S, 3)


def _hop() -> int:
    return int(round(HOP_S * SAMPLE_RATE))


def lag_samples(lag_min_s: float = LAG_MIN_S, lag_max_s: float = LAG_MAX_S) -> tuple[int, int]:
    """Lag-Fenster in Samples, auf das Hüllkurven-Raster gerundet - damit Aufrufer und
    ``uebersprech_score`` dasselbe Fenster meinen."""
    hop = _hop()
    return int(round(lag_min_s / HOP_S)) * hop, int(round(lag_max_s / HOP_S)) * hop


def _rms_raster(audio: np.ndarray, hop: int, fenster: int) -> np.ndarray:
    """RMS je Rasterpunkt (Fenster beginnt am Rasterpunkt, am Ende verkürzt)."""
    n = len(audio) // hop
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    x = np.asarray(audio, dtype=np.float64)
    cs = np.concatenate([[0.0], np.cumsum(x * x)])
    starts = np.arange(n) * hop
    ends = np.minimum(starts + fenster, len(x))
    return np.sqrt((cs[ends] - cs[starts]) / np.maximum(ends - starts, 1))


def huellkurve(audio: np.ndarray, *, hop_s: float = HOP_S, fenster_s: float = FENSTER_S, trend_s: float = TREND_S) -> np.ndarray:
    """Trendbereinigte dB-Hüllkurve: ein Wert je ``hop_s``."""
    from scipy.ndimage import uniform_filter1d

    hop = int(round(hop_s * SAMPLE_RATE))
    rms = _rms_raster(audio, hop, int(round(fenster_s * SAMPLE_RATE)))
    if not len(rms):
        return np.zeros(0, dtype=np.float32)
    db = 20.0 * np.log10(np.maximum(rms, 1e-9))
    db = np.maximum(db, db.max() + BODEN_DB)
    trend = max(1, int(round(trend_s / hop_s)))
    if len(db) > 1:
        db = db - uniform_filter1d(db, size=trend, mode="nearest")
    return db.astype(np.float32)


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    norm = float(np.sqrt((a @ a) * (b @ b)))
    return float(a @ b) / norm if norm > 0 else 0.0


def uebersprech_score(
    mic: np.ndarray, system: np.ndarray, *, lag_min_s: float = LAG_MIN_S, lag_max_s: float = LAG_MAX_S
) -> tuple[float, float]:
    """Beste Hüllkurven-Korrelation über das Lag-Fenster und der Lag dazu.

    ``system`` muss ``[t0 - lag_max, t1 - lag_min]`` abdecken, wenn ``mic`` ``[t0, t1]`` ist
    (am Ende darf es kürzer sein - dann zählt nur der überlappende Teil). Ein praktisch
    stilles System ergibt ``(0.0, 0.0)``: da kann nichts durchgesprochen haben."""
    hop = _hop()
    if len(mic) < hop or len(system) < hop:
        return 0.0, 0.0
    if _rms_raster(system, hop, int(round(FENSTER_S * SAMPLE_RATE))).max() < STILLE_RMS:
        return 0.0, 0.0
    e_m = huellkurve(mic)
    e_s = huellkurve(system)
    lag_min_f = int(round(lag_min_s / HOP_S))
    lag_max_f = int(round(lag_max_s / HOP_S))
    best, best_lag = 0.0, 0.0
    for lag_f in range(lag_min_f, lag_max_f + 1):
        # Mikrofon-Raster i hört System-Zeit t0 + i*hop - lag; das System-Fenster beginnt
        # bei t0 - lag_max, also liegt der Wert bei Index i + lag_max_f - lag_f.
        offset = lag_max_f - lag_f
        n = min(len(e_m), len(e_s) - offset)
        if n < 2:
            continue
        score = _pearson(e_m[:n], e_s[offset : offset + n])
        if score > best:
            best, best_lag = score, lag_f * HOP_S
    return round(best, 4), round(best_lag, 3)


def pruefe(
    mic: np.ndarray,
    system_fenster: np.ndarray,
    *,
    dauer_s: float,
    schwelle: float,
    abdeckung: float = 1.0,
    lag_min_s: float = LAG_MIN_S,
    lag_max_s: float = LAG_MAX_S,
) -> Pruefung:
    """Die Entscheidung an einer Stelle: Echo, wenn lang genug und Korrelation über der Schwelle.

    ``schwelle`` ist die Basis (siehe ``SCHWELLE``); was für diese Länge gilt, steht im Ergebnis."""
    gilt = schwelle_fuer(dauer_s, schwelle)
    if not len(system_fenster):
        return Pruefung(0.0, 0.0, round(dauer_s, 2), round(abdeckung, 2), False, gilt, GRUND_OHNE_SYSTEM)
    score, lag_s = uebersprech_score(mic, system_fenster, lag_min_s=lag_min_s, lag_max_s=lag_max_s)
    zu_kurz = dauer_s < MIN_DAUER_S
    verworfen = gilt > 0 and not zu_kurz and score >= gilt
    return Pruefung(
        score, lag_s, round(dauer_s, 2), round(abdeckung, 2), verworfen, gilt, GRUND_ZU_KURZ if zu_kurz else ""
    )


def ausschnitt(audio: np.ndarray, start: int, end: int, *, basis: int = 0) -> np.ndarray:
    """``[start, end)`` in absoluten Samples aus einem Array, das bei ``basis`` beginnt;
    außerhalb Nullen (für die kompletten WAVs beim Nachschärfen)."""
    out = np.zeros(max(0, end - start), dtype=np.float32)
    lo = max(start, basis)
    hi = min(end, basis + len(audio))
    if hi > lo:
        out[lo - start : hi - start] = audio[lo - basis : hi - basis]
    return out


class Rueckblick:
    """Ringpuffer über absolute Sample-Positionen: die letzten ``dauer_s`` einer Spur.

    ``Track.take`` gibt sein Audio nur einmal heraus; für den Vergleich mit dem anderen
    Kanal braucht der Schnitt-Thread es noch, wenn der Abschnitt fertig ist. 40 s decken
    den längsten Abschnitt (``max_chunk_s``) samt Lag-Fenster reichlich ab."""

    def __init__(self, dauer_s: float = 40.0) -> None:
        self._n = max(1, int(dauer_s * SAMPLE_RATE))
        self._buf = np.zeros(self._n, dtype=np.float32)
        self.ende = 0  # höchste geschriebene Position, exklusiv
        self._anfang: int | None = None  # erste geschriebene Position

    def feed(self, start: int, samples: np.ndarray) -> None:
        if self._anfang is None:
            self._anfang = int(start)
        if start > self.ende and self.ende > 0:
            # Lücke nullen, sonst stünde dort noch Audio von einer Runde zuvor.
            self._schreibe(self.ende, np.zeros(min(start - self.ende, self._n), dtype=np.float32))
        if len(samples):
            self._schreibe(int(start), np.asarray(samples, dtype=np.float32))
        self.ende = max(self.ende, int(start) + len(samples))

    def _schreibe(self, start: int, samples: np.ndarray) -> None:
        if len(samples) > self._n:
            start += len(samples) - self._n
            samples = samples[-self._n :]
        pos = start % self._n
        erster = min(self._n - pos, len(samples))
        self._buf[pos : pos + erster] = samples[:erster]
        self._buf[: len(samples) - erster] = samples[erster:]
        self.ende = max(self.ende, start + len(samples))

    def ausschnitt(self, start: int, end: int) -> np.ndarray:
        """``[start, end)`` absolut; was nicht (mehr) im Ring liegt, ist null."""
        out = np.zeros(max(0, end - start), dtype=np.float32)
        lo = max(start, self.ende - self._n, self._anfang or 0)
        hi = min(end, self.ende)
        if hi <= lo:
            return out
        pos = lo % self._n
        erster = min(self._n - pos, hi - lo)
        out[lo - start : lo - start + erster] = self._buf[pos : pos + erster]
        rest = hi - lo - erster
        if rest:
            out[lo - start + erster : hi - start] = self._buf[:rest]
        return out


def schaetze_lag(
    mic: np.ndarray, system: np.ndarray, *, lag_min_s: float = LAG_MIN_S, lag_max_s: float = LAG_MAX_S
) -> tuple[float, float]:
    """Globaler Zeitversatz zweier kompletter Spuren derselben Zeitleiste: ``(lag_s, score)``.

    Zur Einordnung im Fazit - ein hoher Score heißt, die Sitzung lief über Lautsprecher."""
    lag_min, lag_max = lag_samples(lag_min_s, lag_max_s)
    n = min(len(mic), len(system))
    a, b = lag_max, n + lag_min
    if b - a < SAMPLE_RATE:
        return 0.0, 0.0
    score, lag_s = uebersprech_score(mic[a:b], system[:n], lag_min_s=lag_min_s, lag_max_s=lag_max_s)
    return lag_s, score


def gleiche_ab(live_zeilen: list[dict], offline: list[tuple[float, float, bool]]) -> dict[str, int]:
    """Live-Entscheidungen gegen die Offline-Prüfung des Nachschärfens halten.

    ``offline``: ``(start_s, end_s, verworfen)`` je Mikrofon-Segment des Nachschärfens.
    Je Live-Zeile zählen alle zeitlich überlappenden Segmente; offline „verworfen“ heißt,
    alle davon wurden verworfen. Zurückgeholt = live verworfen, offline behalten: der
    Text steht durch die Neutranskription wieder im Transkript."""
    zaehler = {"bestaetigt": 0, "zurueckgeholt": 0, "nachtraeglich_entfernt": 0, "ohne_text": 0}
    for zeile in live_zeilen:
        s = float(zeile.get("start_s") or 0.0)
        e = float(zeile.get("end_s") or 0.0)
        treffer = [v for a, b, v in offline if a < e and b > s]
        if not treffer:
            zaehler["ohne_text"] += 1
            continue
        live_weg = zeile.get("entscheidung") == VERWORFEN
        offline_weg = all(treffer)
        if live_weg and offline_weg:
            zaehler["bestaetigt"] += 1
        elif live_weg:
            zaehler["zurueckgeholt"] += 1
        elif offline_weg:
            zaehler["nachtraeglich_entfernt"] += 1
    return zaehler
