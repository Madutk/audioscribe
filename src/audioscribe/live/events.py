"""Ereignisprotokoll zwischen ``audioscribe live`` und der Oberfläche.

Der Live-Prozess schreibt je Ereignis eine Zeile ``[Live] {json}`` auf stdout; alles
andere ist gewöhnliches Protokoll. Gleiches Muster wie ``[Agent-Status]`` der KI-Analyse.
"""

from __future__ import annotations

import json
import threading

PREFIX = "[Live] "

# Ereignistypen
STATE = "state"  # phase, session, dir, model, device, step (nur während "laden"), sitzung_id, titel, fortgesetzt
SEGMENT = "segment"  # id, track, speaker, start, end, text, delay; restored=True nach Wiederaufnahme
PARTIAL = "partial"  # track, start, text (leerer Text = Vorschau zurücknehmen)
SHOT = "shot"  # id, t, file; restored=True nach Wiederaufnahme
DOWNLOAD = "download"  # model, done, total (Bytes; nur wenn das Modell noch nicht im Cache liegt)
STATS = "stats"  # elapsed, backlog, delay, level_mic, level_sys, partials_paused, rtf, catchup
FAZIT = "fazit"  # teil ("live" | "nachschaerfen") + Felder der jeweiligen Bilanz (live/bilanz.py)


def event_line(typ: str, **data: object) -> str:
    return PREFIX + json.dumps({"type": typ, **data}, ensure_ascii=False)


# print() schreibt Text und Zeilenende getrennt; aus mehreren Threads gerieten sonst zwei
# Ereignisse in eine Zeile und wären für den Parser verloren.
_print_lock = threading.Lock()

# Stirbt der Server, bricht die stdout-Pipe: jedes weitere print wirft dann OSError - mitten
# im Aufräumen, vor dem Schließen der WAV-Dateien. Darum schluckt log() den Fehler an dieser
# einen Stelle, merkt sich "stdout tot" und ruft einmal den gemeldeten Rückruf auf; die
# Sitzung macht daraufhin einen geordneten Notabschluss (PRD §21).
_stdout_tot = threading.Event()
_bei_tot: list = []


def stdout_tot() -> bool:
    return _stdout_tot.is_set()


def bei_stdout_tot(rueckruf) -> None:
    """Meldet einen Rückruf an, der einmal läuft, sobald stdout nicht mehr schreibbar ist."""
    _bei_tot.append(rueckruf)


def log(message: str) -> None:
    if _stdout_tot.is_set():
        return
    try:
        with _print_lock:
            print(message, flush=True)
    except (OSError, ValueError):
        if _stdout_tot.is_set():
            return
        _stdout_tot.set()
        rueckrufe, _bei_tot[:] = list(_bei_tot), []
        for rueckruf in rueckrufe:
            try:
                rueckruf()
            except Exception:  # noqa: BLE001 - der Notabschluss darf hier nie scheitern
                pass


def emit(typ: str, **data: object) -> None:
    log(event_line(typ, **data))


def parse_event(line: str) -> dict | None:
    """Ereignis einer Zeile oder ``None`` für gewöhnliche Protokollzeilen."""
    if not line.startswith(PREFIX):
        return None
    try:
        data = json.loads(line[len(PREFIX) :])
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("type"), str) else None
