"""Sprache der Oberfläche: Deutsch (Quelle) oder Englisch.

Die deutschen Texte im Code bleiben die Quelle - ``tr("Die Demo läuft bereits.")`` liefert
bei englischer Oberfläche die Übersetzung aus ``i18n/en/*.json``, sonst den Text selbst.
Platzhalter stehen in geschweiften Klammern und werden nach der Übersetzung eingesetzt:
``tr("Demo nicht startbar: {fehler}", fehler=exc)``.

Die Sprache ist eine globale Einstellung (``ui_sprache`` im Einstellungsstand, ``ui/state.py``).
Fehlt eine Übersetzung, erscheint der deutsche Text - ein Test prüft, dass das nicht vorkommt.
"""

from __future__ import annotations

import json
from pathlib import Path

SPRACHEN: tuple[str, ...] = ("de", "en")
STANDARD = "de"

_ORDNER = Path(__file__).parent

_woerterbuch: dict[str, dict[str, str]] = {}
_stand: tuple[object, str] | None = None  # (Kennung der Einstellungsdatei, Sprache)


def woerterbuch(sprache: str) -> dict[str, str]:
    """Alle Übersetzungen einer Sprache (deutscher Text -> Übersetzung), zusammengeführt aus
    den Dateien je Bereich."""
    if sprache not in _woerterbuch:
        alle: dict[str, str] = {}
        for datei in sorted((_ORDNER / sprache).glob("*.json")):
            alle.update(json.loads(datei.read_text(encoding="utf-8")))
        _woerterbuch[sprache] = alle
    return _woerterbuch[sprache]


def sprache() -> str:
    """Die eingestellte Sprache der Oberfläche; gelesen wird nur, wenn sich die
    Einstellungsdatei geändert hat."""
    global _stand
    from audioscribe.ui import state

    pfad = state.state_path()
    try:
        kennung: object = (pfad, pfad.stat().st_mtime_ns)
    except OSError:
        kennung = (pfad, None)
    if _stand is None or _stand[0] != kennung:
        wert = state.load_state().get("ui_sprache", STANDARD) if kennung[1] is not None else STANDARD
        _stand = (kennung, wert if wert in SPRACHEN else STANDARD)
    return _stand[1]


def tr(text: str, /, **werte: object) -> str:
    """Text in der Sprache der Oberfläche; ``werte`` füllen die Platzhalter ``{name}``."""
    sp = sprache()
    if sp != STANDARD:
        text = woerterbuch(sp).get(text, text)
    return text.format(**werte) if werte else text
