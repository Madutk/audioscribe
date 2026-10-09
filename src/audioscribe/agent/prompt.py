"""Systemanweisung und Arbeitsauftrag fuer den Analyse-Agenten.

Die feste Anweisung (Arbeitsregeln) liegt als ``prompts/system.md`` im Paket und wird
an den Claude-Code-Systemprompt angehaengt; der Auftrag je Lauf (Name, Material,
Kontext, Skills) ist die erste Nutzernachricht.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from audioscribe.agent.material import Auftrag, Material
from audioscribe.agent.skills import Skill

_PROMPT_DIR = Path(__file__).parent / "prompts"


_LOKAL_HINWEIS = (
    "Hinweis: Du läufst als lokales Modell auf diesem Rechner (experimentell). Standbilder "
    "ansehen kann je nach Modell scheitern - schlägt das Read-Werkzeug auf einem Bild fehl, "
    "arbeite ohne Bilder weiter und vermerke das in den Dokumenten. Halte dich streng an echte "
    "Werkzeugaufrufe; erfinde keine Dateien und keine Werkzeugergebnisse."
)


def system_append(python: str | None = None, *, lokal: bool = False) -> str:
    """Feste Arbeitsregeln (Anhang an den Claude-Code-Systemprompt).

    ``python``: Interpreter fuer Skill-Skripte, Default der laufende (audioscribe-venv).
    Ein nacktes ``python`` gibt es unter WSL/Ubuntu nicht (nur ``python3``), unter
    Windows oft nur den Store-Platzhalter - der Agent verbrannte sonst Runden mit Raten.
    ``lokal``: Zusatz fuer ein lokales Modell (Ollama), das Bilder evtl. nicht lesen kann.
    """
    text = (_PROMPT_DIR / "system.md").read_text(encoding="utf-8").strip()
    text = text.replace("{python}", python or sys.executable)
    return f"{text}\n\n{_LOKAL_HINWEIS}" if lokal else text


def build_task_prompt(auftrag: Auftrag, material: Material, skills: Sequence[Skill]) -> str:
    """Erste Nachricht an den Agenten: was analysiert wird und womit."""
    teile: list[str] = [f"# Analyseauftrag: {auftrag.name}", ""]

    teile += ["## Material", f"- Haupttranskript: `{material.transkript}`"]
    weitere = [d for d in material.dateien if d != material.transkript]
    if weitere:
        teile.append("- Weitere Dateien: " + ", ".join(f"`{d}`" for d in weitere))
    if material.frames:
        teile.append(f"- Standbilder: {material.frames} Dateien unter `material/frames/`")
    else:
        teile.append("- Standbilder: keine (reine Audioaufnahme oder ohne --frames erzeugt)")
    teile.append("")

    kontext = auftrag.kontext_text.strip()
    if kontext or material.kontext_inline or material.kontext_dateien:
        teile += ["## Kontext vom Auftraggeber"]
        if kontext:
            teile += [kontext, ""]
        for name, inhalt in material.kontext_inline:
            teile += [f"### `{name}`", "", inhalt.strip(), ""]
        if material.kontext_dateien:
            teile.append(
                "Weitere Kontextdateien (bitte selbst lesen): "
                + ", ".join(f"`{d}`" for d in material.kontext_dateien)
            )
            teile.append("")

    if skills:
        teile += ["## Bereitgestellte Skills"]
        teile += [f"- **{s.name}**: {_kurz(s.description)}" for s in skills]
        teile += [
            "",
            "Wende die passenden Skills in sinnvoller Reihenfolge an (zum Beispiel erst "
            "Begriffe im Transkript normalisieren, dann den Prozess rekonstruieren, dann "
            "die Qualität prüfen, dann Ableitungen erstellen).",
            "",
        ]

    teile += [
        "## Ergebnis",
        f"Erstelle alle Dokumente zum Prozess „{auftrag.name}“ im aktuellen Arbeitsordner "
        "und schließe mit `INDEX.md` ab.",
    ]
    return "\n".join(teile).strip() + "\n"


def _kurz(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
