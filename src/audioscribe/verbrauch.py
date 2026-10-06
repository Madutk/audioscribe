"""KI-Verbrauch: Tokens und ungefährer Preis der Aufrufe, die das Haus verlassen.

Gezählt wird, was der KI-Dienst selbst meldet: das Claude Agent SDK liefert mit jedem
Ergebnis die Tokens und den Preis zu API-Tarifen (``total_cost_usd``). Eine eigene
Preistabelle gibt es deshalb nicht. Bei Anmeldung über ein Abo wird nichts abgerechnet -
der Preis ist dann nur ein Gegenwert und heißt in der Oberfläche auch so.

Lokale Arbeit (Transkription, Sprechertrennung, KI-Attrappe) verbraucht nichts und taucht
hier nicht auf. Das Modul kennt das SDK nicht; es liest nur dessen Felder.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

QUELLE_SOUFFLEUR = "souffleur"
QUELLE_ANALYSE = "analyse"
QUELLEN: tuple[str, ...] = (QUELLE_SOUFFLEUR, QUELLE_ANALYSE)

_TOKEN_FELDER = ("eingabe", "ausgabe", "cache_lesen", "cache_schreiben")
# Feldnamen des Dienstes: je Aufruf (``usage``) und je Modell (``model_usage``).
_USAGE = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
_MODEL_USAGE = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")


def _zahl(wert: object) -> int:
    return int(wert) if isinstance(wert, (int, float)) and not isinstance(wert, bool) and wert > 0 else 0


@dataclass(frozen=True)
class Verbrauch:
    eingabe: int = 0
    ausgabe: int = 0
    cache_lesen: int = 0
    cache_schreiben: int = 0
    kosten_usd: float | None = None  # Preis zu API-Tarifen; None = der Dienst nennt keinen
    aufrufe: int = 0

    @property
    def tokens(self) -> int:
        return self.eingabe + self.ausgabe + self.cache_lesen + self.cache_schreiben

    def __add__(self, other: Verbrauch) -> Verbrauch:
        kosten = None
        if self.kosten_usd is not None or other.kosten_usd is not None:
            kosten = (self.kosten_usd or 0.0) + (other.kosten_usd or 0.0)
        return Verbrauch(
            *(getattr(self, f) + getattr(other, f) for f in _TOKEN_FELDER),
            kosten_usd=kosten, aufrufe=self.aufrufe + other.aufrufe,
        )

    def minus(self, frueher: Verbrauch) -> Verbrauch:
        """Was seit ``frueher`` dazukam - für Dienste, die laufende Summen melden. Nie negativ;
        ``aufrufe`` bleibt, wie es ist."""
        kosten = self.kosten_usd
        if kosten is not None and frueher.kosten_usd is not None:
            kosten = max(0.0, kosten - frueher.kosten_usd)
        return Verbrauch(
            *(max(0, getattr(self, f) - getattr(frueher, f)) for f in _TOKEN_FELDER),
            kosten_usd=kosten, aufrufe=self.aufrufe,
        )

    def als_dict(self) -> dict:
        return {
            **{f: getattr(self, f) for f in _TOKEN_FELDER},
            "tokens": self.tokens,
            "kosten_usd": None if self.kosten_usd is None else round(self.kosten_usd, 6),
            "aufrufe": self.aufrufe,
        }

    @classmethod
    def aus_dict(cls, daten: object) -> Verbrauch:
        if not isinstance(daten, Mapping):
            return cls()
        kosten = daten.get("kosten_usd")
        return cls(
            *(_zahl(daten.get(f)) for f in _TOKEN_FELDER),
            kosten_usd=float(kosten) if isinstance(kosten, (int, float)) and not isinstance(kosten, bool) else None,
            aufrufe=_zahl(daten.get("aufrufe")),
        )

    def text(self) -> str:
        """Eine Zeile fürs Protokoll, z. B. ``182.340 Tokens, ca. 1,24 $ (API-Gegenwert)``."""
        tokens = f"{self.tokens:,}".replace(",", ".") + " Tokens"
        if self.kosten_usd is None:
            return tokens
        preis = "unter 0,01" if 0 < self.kosten_usd < 0.01 else f"{self.kosten_usd:.2f}".replace(".", ",")
        return f"{tokens}, ca. {preis} $ (API-Gegenwert)"


def aus_usage(usage: object) -> Verbrauch:
    """Tokens eines einzelnen Aufrufs (``usage`` einer Nachricht des Dienstes), ohne Preis."""
    if not isinstance(usage, Mapping):
        return Verbrauch()
    return Verbrauch(*(_zahl(usage.get(k)) for k in _USAGE))


def aus_ergebnis(msg: Any) -> Verbrauch:
    """Verbrauch aus dem Ergebnis eines Aufrufs (``ResultMessage`` des SDK).

    Die Tokens kommen aus ``model_usage`` (Summe über alle beteiligten Modelle), ersatzweise
    aus ``usage``; der Preis aus ``total_cost_usd``. In einer Verbindung mit mehreren
    Nachrichten sind das laufende Summen - dort zählt die Differenz (``minus``).
    """
    je_modell = getattr(msg, "model_usage", None)
    if isinstance(je_modell, Mapping) and je_modell:
        werte = [
            sum(_zahl(m.get(k)) for m in je_modell.values() if isinstance(m, Mapping)) for k in _MODEL_USAGE
        ]
        tokens = Verbrauch(*werte)
    else:
        tokens = aus_usage(getattr(msg, "usage", None))
    kosten = getattr(msg, "total_cost_usd", None)
    kosten = float(kosten) if isinstance(kosten, (int, float)) and not isinstance(kosten, bool) else None
    return Verbrauch(tokens.eingabe, tokens.ausgabe, tokens.cache_lesen, tokens.cache_schreiben, kosten, 1)


class Zaehler:
    """Verbrauch seit Programmstart, je Quelle getrennt nach laufender Aktivität (diese
    Sitzung, dieser Lauf) und allem davor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._aktuell = dict.fromkeys(QUELLEN, Verbrauch())
        self._abgeschlossen = dict.fromkeys(QUELLEN, Verbrauch())

    def beginne(self, quelle: str) -> None:
        """Eine neue Aktivität der Quelle beginnt; die vorige zählt ab jetzt zu „davor“."""
        with self._lock:
            self._abgeschlossen[quelle] = self._abgeschlossen[quelle] + self._aktuell[quelle]
            self._aktuell[quelle] = Verbrauch()

    def buche(self, quelle: str, verbrauch: Verbrauch) -> None:
        """Einen Aufruf zur laufenden Aktivität addieren."""
        with self._lock:
            self._aktuell[quelle] = self._aktuell[quelle] + verbrauch

    def setze(self, quelle: str, verbrauch: Verbrauch) -> None:
        """Den Stand der laufenden Aktivität ersetzen (für Quellen, die Summen melden)."""
        with self._lock:
            self._aktuell[quelle] = verbrauch

    def snapshot(self) -> dict:
        with self._lock:
            aktuell, davor = dict(self._aktuell), dict(self._abgeschlossen)
        gesamt = Verbrauch()
        quellen = {}
        for q in QUELLEN:
            summe = davor[q] + aktuell[q]
            gesamt = gesamt + summe
            quellen[q] = {"aktuell": aktuell[q].als_dict(), "gesamt": summe.als_dict()}
        return {"gesamt": gesamt.als_dict(), "quellen": quellen}
