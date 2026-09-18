"""Zugriffsregeln des Analyse-Agenten (NFR-12): schreiben nur im Arbeitsordner.

Reine Funktion ohne SDK-Bezug. Der Runner ruft sie aus dem ``can_use_tool``-Callback
des Agent SDK auf - also fuer jeden Werkzeugaufruf, der nicht vorab erlaubt ist.

Grenze der Regel: ``Bash`` laesst sich nicht pfadgenau pruefen. Es ist nur dabei, weil
die Skills Python-Skripte starten; wer das nicht will, schaltet es mit ``--no-bash`` ab.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Werkzeug -> Name des Pfad-Parameters.
WRITE_TOOLS: dict[str, str] = {
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}
READ_TOOLS: dict[str, str] = {"Read": "file_path", "Glob": "path", "Grep": "path"}
# Ohne Pfadbezug, immer erlaubt.
FREE_TOOLS: frozenset[str] = frozenset(
    {"Skill", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
)


@dataclass(frozen=True)
class Entscheidung:
    erlaubt: bool
    grund: str = ""


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve(raw: object, workspace: Path) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = workspace / p
    # resolve() loest '..' und Symlinks auf - ein Link im Arbeitsordner, der nach
    # draussen zeigt, gilt damit als draussen.
    return p.resolve()


def check_tool(
    tool: str,
    tool_input: Mapping[str, object],
    workspace: Path,
    *,
    read_roots: Sequence[Path] = (),
    bash: bool = True,
) -> Entscheidung:
    """Darf der Agent dieses Werkzeug mit dieser Eingabe benutzen?"""
    ws = Path(workspace).resolve()

    if tool in FREE_TOOLS:
        return Entscheidung(True)

    if tool == "Bash":
        if bash:
            return Entscheidung(True)
        return Entscheidung(False, "Bash ist fuer diesen Lauf abgeschaltet (--no-bash).")

    if tool in WRITE_TOOLS:
        target = _resolve(tool_input.get(WRITE_TOOLS[tool]), ws)
        if target is None:
            return Entscheidung(False, "Kein Zielpfad angegeben.")
        if not _inside(target, ws):
            return Entscheidung(
                False, f"Schreiben nur im Ergebnisordner erlaubt ({ws}), nicht in {target}."
            )
        if _inside(target, ws / ".claude"):
            return Entscheidung(False, "Die Skill-Kopien unter .claude/ sind schreibgeschuetzt.")
        return Entscheidung(True)

    if tool in READ_TOOLS:
        target = _resolve(tool_input.get(READ_TOOLS[tool]), ws)
        if target is None:  # Glob/Grep ohne Pfad -> Arbeitsordner
            return Entscheidung(True)
        roots = [ws, *(Path(r).resolve() for r in read_roots)]
        if any(_inside(target, r) for r in roots):
            return Entscheidung(True)
        return Entscheidung(False, f"Lesen nur im Ergebnisordner erlaubt, nicht in {target}.")

    return Entscheidung(False, f"Werkzeug '{tool}' ist fuer die Analyse nicht freigegeben.")
