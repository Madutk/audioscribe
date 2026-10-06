"""Absturzsicherung einer Live-Sitzung: Zustandsdatei, Journal und Lebenszeichen (PRD §21).

Drei Dateien im Sitzungsordner, alle vom Kindprozess (``audioscribe live``) geschrieben:

- ``sitzung.json``: Zustand (``laeuft | unterbrochen | beendet | verworfen``), stabile
  ``sitzung_id``, Titel, Sprache/Modell und die Aufnahme-Teile mit ihrem ``start_sample``.
  Atomar geschrieben; ``verworfen`` setzt der Server, nachdem das Kind beendet ist.
- ``sitzung.journal.jsonl``: je Segment und Standbild sofort eine Zeile, dazu Takt-Zeilen
  mit der Sitzungszeit. Daraus lässt sich das Transkript nach einem Absturz wiederherstellen,
  auch wenn ``transkript.md`` zuletzt vor 30 s geschrieben wurde. Tolerant gelesen wie
  ``diagnose.lies_diagnose`` - eine abgerissene letzte Zeile kostet nur diese Zeile.
- ``sitzung.lock``: das Kind hält darauf für seine Lebenszeit eine Sperre des Betriebssystems
  (``msvcrt.locking`` bzw. ``fcntl.flock``). Sie fällt bei jedem Tod des Prozesses weg, und
  eine wiederverwendete PID täuscht nichts vor. ``os.kill(pid, 0)`` ist unter Windows keine
  Probe, sondern beendet den Prozess - darum keine PID-Prüfung.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STATUS_DATEI = "sitzung.json"
JOURNAL_DATEI = "sitzung.journal.jsonl"
LOCK_DATEI = "sitzung.lock"
STATUS_VERSION = 1

LAEUFT = "laeuft"
UNTERBROCHEN = "unterbrochen"
BEENDET = "beendet"
VERWORFEN = "verworfen"

ART_SEGMENT = "segment"
ART_SHOT = "shot"
ART_TAKT = "takt"
ART_TEIL = "teil"


# --- Zustandsdatei -------------------------------------------------------------------


def lies_status(session_dir: str | Path) -> dict | None:
    """``sitzung.json`` oder ``None`` (fehlt, kaputt, kein Objekt)."""
    try:
        data = json.loads((Path(session_dir) / STATUS_DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def schreibe_status(session_dir: str | Path, **aenderungen: object) -> dict:
    """Mischt ``aenderungen`` in den Bestand und schreibt atomar; liefert den neuen Stand.

    Fehlende Pflichtfelder (``sitzung_id``, ``gestartet`` ...) werden ergänzt, damit auch der
    erste Aufruf eine vollständige Datei hinterlässt.
    """
    session_dir = Path(session_dir)
    stand = lies_status(session_dir) or {}
    stand.update(aenderungen)
    stand.setdefault("version", STATUS_VERSION)
    stand.setdefault("sitzung_id", uuid.uuid4().hex)
    stand.setdefault("status", LAEUFT)
    stand.setdefault("titel", "")
    stand.setdefault("gestartet", datetime.now().isoformat(timespec="seconds"))
    stand.setdefault("sprache", "")
    stand.setdefault("modell", "")
    stand.setdefault("replay", False)
    stand.setdefault("teile", [])
    stand["aktualisiert"] = datetime.now().isoformat(timespec="seconds")
    session_dir.mkdir(parents=True, exist_ok=True)
    pfad = session_dir / STATUS_DATEI
    tmp = pfad.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(stand, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, pfad)
    return stand


# --- Lebenszeichen -------------------------------------------------------------------


def _sperren(datei) -> bool:
    """Nicht blockierende Sperre auf dem ersten Byte; ``False``, wenn sie jemand hält."""
    try:
        datei.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(datei.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(datei.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _entsperren(datei) -> None:
    try:
        datei.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(datei.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(datei.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


class Sperre:
    """Die gehaltene Sperre einer Sitzung; ``gib_frei`` (oder das Prozessende) löst sie."""

    def __init__(self, datei) -> None:
        self._datei = datei

    def gib_frei(self) -> None:
        datei, self._datei = self._datei, None
        if datei is None:
            return
        _entsperren(datei)
        try:
            datei.close()
        except OSError:
            pass


def sperre(session_dir: str | Path) -> Sperre:
    """Sperrt die Sitzung für diesen Prozess; ``RuntimeError``, wenn sie schon jemand hält."""
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    datei = (session_dir / LOCK_DATEI).open("a+b")
    if not _sperren(datei):
        datei.close()
        raise RuntimeError(f"Die Sitzung läuft bereits in einem anderen Prozess: {session_dir}")
    return Sperre(datei)


def lebt(session_dir: str | Path) -> bool:
    """Hält gerade ein Prozess die Sitzung? (Probe: lässt sich die Sperre nehmen?)"""
    try:
        datei = (Path(session_dir) / LOCK_DATEI).open("r+b")
    except OSError:
        return False
    try:
        if _sperren(datei):
            _entsperren(datei)
            return False
        return True
    finally:
        datei.close()


# --- Journal ---------------------------------------------------------------------------


class Journal:
    """Anhängendes Journal; jede Zeile wird sofort geschrieben, Segmente zusätzlich ``fsync``.

    Threadsicher: Transkriptions-, Bildschirm- und Hauptthread schreiben gleichzeitig.
    """

    def __init__(self, session_dir: str | Path) -> None:
        self._pfad = Path(session_dir) / JOURNAL_DATEI
        self._lock = threading.Lock()
        self._datei = None

    def zeile(self, art: str, *, sicher: bool = False, **daten: object) -> None:
        with self._lock:
            try:
                if self._datei is None:
                    if not self._pfad.parent.is_dir():
                        return  # noch keine Sitzung auf der Platte - nichts zu sichern
                    self._oeffne()
                self._datei.write(json.dumps({"art": art, **daten}, ensure_ascii=False) + "\n")
                self._datei.flush()
                if sicher:
                    os.fsync(self._datei.fileno())
            except OSError:
                # Volle Platte o. Ä.: die Sitzung läuft weiter, nur die Sicherung fehlt.
                pass

    def segment(self, **daten: object) -> None:
        self.zeile(ART_SEGMENT, sicher=True, **daten)

    def shot(self, **daten: object) -> None:
        self.zeile(ART_SHOT, **daten)

    def takt(self, elapsed: float) -> None:
        self.zeile(ART_TAKT, elapsed=round(elapsed, 2))

    def close(self) -> None:
        with self._lock:
            if self._datei is not None:
                try:
                    self._datei.close()
                except OSError:
                    pass
                self._datei = None

    def _oeffne(self) -> None:
        """Aufrufer hält den Lock. Eine abgerissene letzte Zeile wird vorher abgeschlossen,
        sonst klebte der erste neue Datensatz an ihr und ginge mit verloren."""
        abgerissen = False
        try:
            with self._pfad.open("rb") as alt:
                alt.seek(0, os.SEEK_END)
                if alt.tell() > 0:
                    alt.seek(-1, os.SEEK_END)
                    abgerissen = alt.read(1) != b"\n"
        except OSError:
            pass
        self._datei = self._pfad.open("a", encoding="utf-8")
        if abgerissen:
            self._datei.write("\n")


@dataclass
class Bestand:
    """Was das Journal einer Sitzung hergibt."""

    segmente: list[dict] = field(default_factory=list)  # nach id eindeutig, in Schreibreihenfolge
    shots: list[dict] = field(default_factory=list)
    takt_s: float = 0.0  # letzte Takt-Zeile (Sitzungszeit)

    @property
    def letzte_id(self) -> int:
        return max((int(s.get("id") or 0) for s in self.segmente), default=0)

    @property
    def ende_s(self) -> float:
        """Spätester bekannter Zeitpunkt der Sitzung laut Journal."""
        return max(
            [self.takt_s]
            + [float(s.get("end") or 0.0) for s in self.segmente]
            + [float(s.get("t") or 0.0) for s in self.shots]
        )


def lies_journal(session_dir: str | Path) -> Bestand:
    """Liest das Journal; kaputte Zeilen werden übersprungen, doppelte IDs gewinnt die letzte."""
    pfad = Path(session_dir) / JOURNAL_DATEI
    bestand = Bestand()
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return bestand
    je_id: dict[int, dict] = {}
    shots: dict[str, dict] = {}
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        art = data.get("art")
        try:
            if art == ART_SEGMENT:
                seg_id = int(data["id"])
                float(data["start"]), float(data["end"])
                if str(data.get("text") or "").strip():
                    je_id[seg_id] = data
            elif art == ART_SHOT:
                float(data["t"])
                shots[str(data["png"])] = data
            elif art == ART_TAKT:
                bestand.takt_s = max(bestand.takt_s, float(data["elapsed"]))
        except (KeyError, TypeError, ValueError):
            continue
    bestand.segmente = list(je_id.values())
    bestand.shots = list(shots.values())
    return bestand


# --- Unterbrochene Sitzungen finden ----------------------------------------------------


def offene_sitzungen(basis_dir: str | Path) -> list[dict]:
    """Sitzungen unter ``basis_dir``, die nicht sauber beendet wurden - jüngste zuerst.

    Das sind Sitzungen im Zustand ``unterbrochen`` und solche im Zustand ``laeuft``, die kein
    Prozess mehr hält. Transkript-Replays (Demo/Test) werden nie fortgesetzt und fehlen hier.
    """
    basis = Path(basis_dir)
    out: list[dict] = []
    try:
        ordner = [p for p in basis.iterdir() if p.is_dir()]
    except OSError:
        return out
    for pfad in ordner:
        status = lies_status(pfad)
        if status is None or status.get("replay"):
            continue
        zustand = status.get("status")
        if zustand not in (LAEUFT, UNTERBROCHEN) or lebt(pfad):
            continue
        bestand = lies_journal(pfad)
        out.append(
            {
                "dir": str(pfad),
                "name": pfad.name,
                "sitzung_id": str(status.get("sitzung_id") or ""),
                "status": UNTERBROCHEN,
                "titel": str(status.get("titel") or ""),
                "gestartet": str(status.get("gestartet") or ""),
                "dauer_s": round(bestand.ende_s, 1),
                "segmente": len(bestand.segmente),
            }
        )
    out.sort(key=lambda e: (e["gestartet"], e["name"]), reverse=True)
    return out
