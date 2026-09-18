"""Skills finden und in den Arbeitsordner eines Analyse-Laufs uebernehmen.

Ein Skill ist ein Ordner mit ``SKILL.md`` (YAML-Frontmatter mit ``name`` und
``description``) plus optionalen ``scripts/``, ``references/``, ``assets/``.

Gesucht wird bewusst rekursiv: Die mit claude.ai synchronisierten Skills liegen nicht
direkt in ``~/.claude/skills``, sondern eine Ebene tiefer unter
``synced/<konto-id>/<skill>/``.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Tiefe relativ zum Suchordner, in der ein SKILL.md noch gefunden wird
# (synced/<konto-id>/<skill>/SKILL.md liegt auf Ebene 3).
_MAX_DEPTH = 3


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path  # Ordner, der SKILL.md enthaelt


def parse_frontmatter(text: str) -> dict[str, str]:
    """Liest die einfachen ``schluessel: wert``-Zeilen des YAML-Frontmatters.

    Kein YAML-Parser: die Felder, die hier gebraucht werden (name, description), sind
    Skalare - einzeilig oder als Block (``>``/``|``) mit eingerueckten Folgezeilen.
    Umschliessende Anfuehrungszeichen werden entfernt.
    """
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return {k: v.strip() for k, v in out.items()}
        if line[:1].isspace() and key is not None:
            out[key] += " " + line.strip()  # Folgezeile eines Block-Skalars
            continue
        key = None
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        value = value.strip()
        if value in (">", "|", ">-", "|-"):
            value = ""
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        key = name.strip()
        out[key] = value
    return {}  # Frontmatter nie geschlossen -> ungueltig


def read_skill(folder: Path) -> Skill | None:
    """Skill aus einem Ordner lesen; ``None`` ohne lesbares SKILL.md."""
    try:
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    meta = parse_frontmatter(text)
    # Ohne Frontmatter-Name gilt der Ordnername (so macht es Claude Code auch).
    name = meta.get("name") or folder.name
    return Skill(name=name, description=meta.get("description", ""), path=folder)


def discover_skills(root: Path) -> list[Skill]:
    """Alle Skills unterhalb von ``root`` (bis Tiefe 3), nach Name sortiert.

    Bei doppelten Namen gewinnt der zuerst gefundene (flachere) Ordner.
    """
    root = Path(root).expanduser()
    if not root.is_dir():
        return []
    found: dict[str, Skill] = {}
    level = [root]
    for _ in range(_MAX_DEPTH + 1):
        nxt: list[Path] = []
        for folder in level:
            if (folder / "SKILL.md").is_file():
                skill = read_skill(folder)
                if skill is not None:
                    found.setdefault(skill.name, skill)
                continue  # in einen Skill nicht weiter hineinsuchen
            try:
                children = sorted(p for p in folder.iterdir() if p.is_dir())
            except OSError:
                continue
            nxt += [c for c in children if not c.name.startswith(".") or c.name == ".claude"]
        level = nxt
    return sorted(found.values(), key=lambda s: s.name.casefold())


def select_skills(available: Iterable[Skill], names: Iterable[str]) -> list[Skill]:
    """Die gewuenschten Skills in der gewuenschten Reihenfolge; unbekannte -> ``KeyError``."""
    by_name = {s.name: s for s in available}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise KeyError(
            "Skill(s) nicht gefunden: " + ", ".join(missing) + ". Verfuegbar: "
            + (", ".join(sorted(by_name)) or "(keine)")
        )
    seen: set[str] = set()
    out: list[Skill] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(by_name[n])
    return out


def install_skills(skills: Iterable[Skill], workspace: Path) -> list[Path]:
    """Kopiert die Skills nach ``<workspace>/.claude/skills/<name>/``.

    Eine vorhandene Kopie wird ersetzt, damit ein erneuter Lauf den aktuellen Stand
    des Skills benutzt. Die Kopie dokumentiert zugleich, womit analysiert wurde.
    """
    target_root = Path(workspace) / ".claude" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for skill in skills:
        target = target_root / skill.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill.path, target, ignore=shutil.ignore_patterns("__pycache__"))
        out.append(target)
    return out
