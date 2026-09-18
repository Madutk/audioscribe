"""Fortschritt eines Analyse-Laufs aus den Werkzeugaufrufen des Agenten ableiten.

Einen Prozentwert kennt der Agent selbst nicht. Ehrlich ableitbar sind:

* sein **Plan**: Schritte mit Status pending/in_progress/completed. Aktuelle Claude-Code-
  Versionen fuehren ihn ueber ``TaskCreate``/``TaskUpdate`` (die ID vergibt erst das
  Ergebnis: ``Task #3 created successfully: …``), aeltere ueber ``TodoWrite`` (ganze
  Liste je Aufruf). Beides wird verstanden.
* der **aktive Skill** (letzter ``Skill``-Aufruf),
* die **angesehenen Standbilder** (erfolgreiche ``Read``-Aufrufe auf ``material/frames/``),
* die **geschriebenen Dokumente** (erfolgreiche ``Write``/``Edit`` im Ergebnisordner).

Reine Logik ohne SDK-Import. Der Runner fuettert ``tool_use``/``tool_result`` und gibt
bei Aenderungen eine maschinenlesbare Zeile ``[Agent-Status] {json}`` aus, die die
Oberflaeche auswertet (``parse_status_line``) statt sie ins Protokoll zu schreiben.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

STATUS_PREFIX = "[Agent-Status] "

_WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path"}
# Was audioscribe selbst anlegt, ist kein Dokument des Agenten.
_NO_DOC_DIRS = ("material", "kontext", ".claude")
_NO_DOC_FILES = ("agent-log.txt", "analyse.json")
_TODO_STATES = ("pending", "in_progress", "completed")
_TASK_CREATED_RE = re.compile(r"Task #(\w+) created")
PLAN_TOOLS = frozenset({"TodoWrite", "TaskCreate", "TaskUpdate"})


class Fortschritt:
    def __init__(self, workspace: Path, frames_total: int = 0) -> None:
        self.workspace = Path(workspace).resolve()
        self.frames_total = frames_total
        self.todos: list[dict[str, str]] = []
        self._task_ids: list[str | None] = []  # parallel zu todos (None bei TodoWrite)
        self.skill: str | None = None
        self.frames_seen: set[str] = set()
        self.docs: list[str] = []
        # tool_use_id -> (Art, Wert); erst ein fehlerfreies Ergebnis zaehlt.
        self._pending: dict[str, tuple[str, object]] = {}

    # --- Eingaenge -------------------------------------------------------------

    def tool_use(self, tool_id: str, name: str, tool_input: Mapping[str, object]) -> bool:
        """Werkzeugaufruf verbuchen; ``True``, wenn sich die Anzeige sofort aendert."""
        if name == "TodoWrite":
            todos = _clean_todos(tool_input.get("todos"))
            if todos is None or todos == self.todos:
                return False
            self.todos = todos
            self._task_ids = [None] * len(todos)
            return True
        if name == "TaskCreate":
            subject = tool_input.get("subject")
            if isinstance(subject, str) and subject.strip():
                active = tool_input.get("activeForm")
                self._pending[tool_id] = (
                    "task_create",
                    {
                        "content": subject.strip(),
                        "status": "pending",
                        "activeForm": active.strip() if isinstance(active, str) else "",
                    },
                )
            return False
        if name == "TaskUpdate":
            self._pending[tool_id] = ("task_update", dict(tool_input))
            return False
        if name == "Skill":
            skill = tool_input.get("skill")
            if isinstance(skill, str) and skill and skill != self.skill:
                self.skill = skill
                return True
            return False
        rel = self._rel(tool_input.get(_WRITE_TOOLS.get(name, "file_path")))
        if rel is None:
            return False
        if name == "Read" and rel.parent == Path("material/frames"):
            self._pending[tool_id] = ("frame", rel.name)
        elif name in _WRITE_TOOLS and _is_doc(rel):
            self._pending[tool_id] = ("doc", rel.as_posix())
        return False

    def tool_result(self, tool_id: str, is_error: bool, content: object = "") -> bool:
        """Ergebnis zu einem Aufruf; ``True``, wenn sich die Anzeige aendert."""
        entry = self._pending.pop(tool_id, None)
        if entry is None or is_error:
            return False
        kind, value = entry
        if kind == "task_create":
            match = _TASK_CREATED_RE.search(_text(content))
            self.todos.append(dict(value))  # type: ignore[arg-type]
            self._task_ids.append(match.group(1) if match else None)
            return True
        if kind == "task_update":
            return self._update_task(value)  # type: ignore[arg-type]
        if kind == "frame":
            if value in self.frames_seen:
                return False
            self.frames_seen.add(value)
            return True
        if value in self.docs:
            return False
        self.docs.append(value)
        return True

    # --- Ausgaenge -------------------------------------------------------------

    def snapshot(self) -> dict:
        done = sum(1 for t in self.todos if t["status"] == "completed")
        current = next((t for t in self.todos if t["status"] == "in_progress"), None)
        return {
            "todos": list(self.todos),
            "done": done,
            "total": len(self.todos),
            "current": (current.get("activeForm") or current["content"]) if current else None,
            "skill": self.skill,
            "frames_seen": len(self.frames_seen),
            "frames_total": self.frames_total,
            "docs": list(self.docs),
        }

    def plan_line(self) -> str | None:
        """Menschenlesbare Zeile fuers Protokoll, wenn es einen Plan gibt."""
        s = self.snapshot()
        if not s["total"]:
            return None
        now = f" – jetzt: {s['current']}" if s["current"] else ""
        return f"[Plan] {s['done']}/{s['total']} Schritte erledigt{now}"

    def status_line(self) -> str:
        return STATUS_PREFIX + json.dumps(self.snapshot(), ensure_ascii=False)

    # --- intern ----------------------------------------------------------------

    def _update_task(self, upd: Mapping[str, object]) -> bool:
        task_id = str(upd.get("taskId", ""))
        if task_id not in self._task_ids:
            return False
        i = self._task_ids.index(task_id)
        status = upd.get("status")
        if status == "deleted":
            del self.todos[i], self._task_ids[i]
            return True
        todo = dict(self.todos[i])
        if status in _TODO_STATES:
            todo["status"] = status  # type: ignore[assignment]
        for key, field in (("subject", "content"), ("activeForm", "activeForm")):
            value = upd.get(key)
            if isinstance(value, str) and value.strip():
                todo[field] = value.strip()
        if todo == self.todos[i]:
            return False
        self.todos[i] = todo
        return True

    def _rel(self, raw: object) -> Path | None:
        """Pfad relativ zum Ergebnisordner, ``None`` wenn ausserhalb oder ungueltig."""
        if not isinstance(raw, str) or not raw.strip():
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = self.workspace / p
        try:
            return p.resolve().relative_to(self.workspace)
        except (ValueError, OSError):
            return None


def _text(content: object) -> str:
    """Text eines Werkzeugergebnisses (String oder Liste von Text-Bloecken)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(b.get("text", "")) for b in content if isinstance(b, Mapping)
        )
    return ""


def _is_doc(rel: Path) -> bool:
    if not rel.parts or rel.parts[0] in _NO_DOC_DIRS:
        return False
    return rel.as_posix() not in _NO_DOC_FILES


def _clean_todos(raw: object) -> list[dict[str, str]] | None:
    if not isinstance(raw, list):
        return None
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        status = item.get("status")
        active = item.get("activeForm")
        out.append(
            {
                "content": content.strip(),
                "status": status if status in _TODO_STATES else "pending",
                "activeForm": active.strip() if isinstance(active, str) else "",
            }
        )
    return out


def parse_status_line(line: str) -> dict | None:
    """Gegenstueck zu ``Fortschritt.status_line``; ``None`` fuer jede andere Zeile."""
    if not line.startswith(STATUS_PREFIX):
        return None
    try:
        data = json.loads(line[len(STATUS_PREFIX):])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
