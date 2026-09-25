"""Ereignisprotokoll zwischen ``audioscribe live`` und der Oberfläche.

Der Live-Prozess schreibt je Ereignis eine Zeile ``[Live] {json}`` auf stdout; alles
andere ist gewöhnliches Protokoll. Gleiches Muster wie ``[Agent-Status]`` der KI-Analyse.
"""

from __future__ import annotations

import json
import threading

PREFIX = "[Live] "

# Ereignistypen
STATE = "state"  # phase, session, dir, model, device, step (nur während "laden")
SEGMENT = "segment"  # id, track, speaker, start, end, text, delay
PARTIAL = "partial"  # track, start, text (leerer Text = Vorschau zurücknehmen)
SHOT = "shot"  # id, t, file
DOWNLOAD = "download"  # model, done, total (Bytes; nur wenn das Modell noch nicht im Cache liegt)
STATS = "stats"  # elapsed, backlog, delay, level_mic, level_sys, partials_paused, rtf, catchup
FAZIT = "fazit"  # teil ("live" | "nachschaerfen") + Felder der jeweiligen Bilanz (live/bilanz.py)


def event_line(typ: str, **data: object) -> str:
    return PREFIX + json.dumps({"type": typ, **data}, ensure_ascii=False)


# print() schreibt Text und Zeilenende getrennt; aus mehreren Threads gerieten sonst zwei
# Ereignisse in eine Zeile und wären für den Parser verloren.
_print_lock = threading.Lock()


def log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


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
