"""Bildtext: was auf einem Standbild steht - per Texterkennung, als zweite Belegquelle des Souffleurs.

Ein Standbild (abgetastet oder aus der Zwischenablage) zeigt oft, was gesprochen nie fällt: das
Ticket mit der Zuständigkeit, die Folie mit der Frist, die Chat-Antwort. Der Souffleur liest den
Text des Bildes und kann damit einen Leitfaden-Punkt klären oder eine Frage beantworten - immer
als „vom Bildschirm“ gekennzeichnet, nie als gesagt, und nur mit wörtlichem Beleg aus dem Bildtext.

Erkennung: macOS über Vision (``VNRecognizeTextRequest``, genau, Deutsch und Englisch) - lokal,
ohne Netz. Auf anderen Systemen bleibt der Text leer; der Souffleur arbeitet dann nur mit dem
Gesagten.

Ergebnis im Sitzungsordner: ``souffleur-bildtext.json`` (``{"version": 1, "bilder": [...]}``).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DATEI = "souffleur-bildtext.json"
VERSION = 1
TEXT_MAX = 4000  # Zeichen je Bild, gespeichert
SPRACHEN = ["de-DE", "en-US"]


@dataclass
class Bild:
    id: str  # B1, B2, ... in Reihenfolge der Erkennung
    mark_id: int  # ID des Standbilds (marks.json)
    t: float  # Sitzungsuhr
    datei: str  # Dateiname unter frames/
    kind: str = ""  # "auto" | "zwischenablage" | ...
    text: str = ""

    def als_dict(self) -> dict:
        return asdict(self)


def verfuegbar() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def erkenne(pfad: Path) -> str:
    """Text des Bildes, Zeilen von oben nach unten. Leer, wenn nichts erkannt wurde oder die
    Erkennung hier nicht verfügbar ist. Wirft nie."""
    if not verfuegbar():
        return ""
    try:
        import objc
        import Vision
        from Foundation import NSURL

        with objc.autorelease_pool():
            url = NSURL.fileURLWithPath_(str(Path(pfad).resolve()))
            handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
            anfrage = Vision.VNRecognizeTextRequest.alloc().init()
            anfrage.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            anfrage.setRecognitionLanguages_(SPRACHEN)
            anfrage.setUsesLanguageCorrection_(True)
            ok, _fehler = handler.performRequests_error_([anfrage], None)
            if not ok:
                return ""
            zeilen = []
            for beob in anfrage.results() or []:
                kandidaten = beob.topCandidates_(1)
                if not kandidaten:
                    continue
                box = beob.boundingBox()
                # Vision: Ursprung unten links - oben zuerst, dann von links nach rechts.
                zeilen.append((-round(box.origin.y + box.size.height, 2), box.origin.x, str(kandidaten[0].string())))
            zeilen.sort()
            return "\n".join(z[2] for z in zeilen if z[2].strip())[:TEXT_MAX]
    except Exception:  # noqa: BLE001 - die Erkennung darf den Souffleur nie stören
        return ""


def schreibe(session_dir: Path, bilder: list[Bild]) -> None:
    pfad = Path(session_dir) / DATEI
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    daten = {"version": VERSION, "bilder": [b.als_dict() for b in bilder]}
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, pfad)


def lade(session_dir: Path) -> list[Bild]:
    try:
        daten = json.loads((Path(session_dir) / DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for roh in daten.get("bilder") or [] if isinstance(daten, dict) else []:
        if isinstance(roh, dict) and roh.get("id") and roh.get("datei"):
            out.append(Bild(**{k: v for k, v in roh.items() if k in Bild.__dataclass_fields__}))
    return out
