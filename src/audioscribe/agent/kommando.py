"""``audioscribe analyze``: Eingaben einsammeln, pruefen und den Agenten starten."""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from audioscribe.agent.manifest import load_manifest
from audioscribe.agent.material import Auftrag, find_transcript
from audioscribe.agent.skills import Skill, discover_skills, select_skills


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def print_skills(skills: list[Skill], root: Path, preselected: tuple[str, ...]) -> None:
    if not skills:
        print(f"Keine Skills unter {root} gefunden (gesucht wird nach SKILL.md).")
        return
    print(f"Skills unter {root}  (* = Vorauswahl)")
    for s in skills:
        mark = "*" if s.name in preselected else " "
        desc = " ".join(s.description.split())
        print(f" {mark} {s.name:<28} {desc[:90]}{'…' if len(desc) > 90 else ''}")


def analyze(args: argparse.Namespace, resolve_out_dir: Callable[[str], Path]) -> int:
    from audioscribe.config import settings

    skills_root = Path(args.skills_dir).expanduser() if args.skills_dir else settings.agent_skills_dir
    available = discover_skills(skills_root)

    if args.list_skills:
        print_skills(available, skills_root, settings.agent_skills)
        return 0

    if not args.target:
        print("Bitte ORDNER|VIDEO angeben (Ergebnisordner eines 'audioscribe run').")
        return 2
    quelle = resolve_out_dir(args.target)
    interaktiv = sys.stdin.isatty()

    name = (args.name or "").strip()
    if not name and interaktiv:
        name = _ask("Prozessname", quelle.name)
    if not name:
        print("Bitte einen Prozessnamen angeben (--name).")
        return 2

    out = args.out
    if not out and interaktiv:
        out = _ask("Ausgabeordner", str(settings.agent_output_dir))
    ausgabe = Path(out).expanduser() if out else settings.agent_output_dir

    kontext_text = args.context_text or ""
    kontext_dateien = tuple(Path(p) for p in (args.context or []))

    resume: str | None = None
    workspace = Auftrag(name=name, quelle=quelle, ausgabe=ausgabe).workspace
    if args.resume:
        manifest = load_manifest(workspace)
        if manifest is None or not manifest.session_id:
            print(f"Keine fortsetzbare Sitzung in {workspace} (analyse.json ohne session_id).")
            return 1
        resume = manifest.session_id
        # Bei einer Fortsetzung gelten die Skills, die damals kopiert wurden.
        skills = discover_skills(workspace / ".claude" / "skills")
    else:
        try:
            find_transcript(quelle)
        except FileNotFoundError as exc:
            print(str(exc))
            return 1
        if args.no_skills:
            skills = []
        elif args.skill:
            try:
                skills = select_skills(available, args.skill)
            except KeyError as exc:
                print(exc.args[0])
                return 2
        else:
            known = {s.name for s in available}
            skills = select_skills(available, [n for n in settings.agent_skills if n in known])

    auftrag = Auftrag(
        name=name,
        quelle=quelle,
        ausgabe=ausgabe,
        kontext_text=kontext_text,
        kontext_dateien=kontext_dateien,
        skills=tuple(s.name for s in skills),
        model=args.model or settings.agent_model,
        max_turns=args.max_turns if args.max_turns is not None else settings.agent_max_turns,
        bash=not args.no_bash,
        prozessbild=settings.agent_prozessbild and not args.no_prozessbild,
        bpmn=settings.agent_bpmn and not args.no_bpmn,
        resume=resume,
    )

    print(f"Analyse '{auftrag.name}'")
    print(f"  Quelle:  {quelle}")
    print(f"  Ziel:    {auftrag.workspace}")
    print(f"  Modell:  {auftrag.model}")
    print(f"  Skills:  {', '.join(auftrag.skills) or '(keine)'}")
    if resume:
        print(f"  Fortsetzung der Sitzung {resume}")

    # Abbruch aus der Oberflaeche kommt als SIGTERM: in KeyboardInterrupt uebersetzen,
    # damit Manifest und Log sauber mit 'abgebrochen' abschliessen.
    def _sigterm(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sigterm)

    from audioscribe.agent.runner import run_analysis

    def emit(line: str) -> None:
        print(line, flush=True)

    try:
        # Die Oberflaeche setzt AUDIOSCRIBE_PROGRESS=1 (ui/jobs.child_env) und bekommt
        # dann zusaetzlich die [Agent-Status]-Zeilen fuer ihre Fortschrittsanzeige.
        return run_analysis(auftrag, skills, emit=emit, status_zeilen=settings.emit_progress)
    except KeyboardInterrupt:
        print("Analyse abgebrochen.")
        return 130


def prozessbild(args: argparse.Namespace, resolve_out_dir: Callable[[str], Path]) -> int:
    """``audioscribe prozessbild ORDNER``: Bilder neu aus prozessbild*.mmd (ohne Agent)."""
    from audioscribe.agent.prozessbild import erzeuge_prozessbilder, find_browser

    ordner = Path(args.target).expanduser()
    if not ordner.is_dir():
        ordner = resolve_out_dir(args.target)
    if not ordner.is_dir():
        print(f"Kein Ordner: {ordner}")
        return 1
    browser = Path(args.browser) if args.browser else find_browser()
    # Rueckfallebene ohne Agent-Protokoll: alle Markdown-Dokumente des Ordners.
    docs = [
        p.relative_to(ordner).as_posix()
        for p in sorted(ordner.rglob("*.md"))
        if p.relative_to(ordner).parts[0] not in ("material", "kontext", ".claude")
    ]
    bilder = erzeuge_prozessbilder(ordner, docs, log=print, browser=browser)
    return 0 if bilder else 1


def bpmn(args: argparse.Namespace, resolve_out_dir: Callable[[str], Path]) -> int:
    """``audioscribe bpmn ORDNER``: BPMN-Modell aus bpmn-modell.json (ohne Agent).

    ``--pruefen`` validiert nur (so prueft der Agent seine Datei vor dem Abschluss).
    """
    from audioscribe.agent import bpmn as bpmn_mod
    from audioscribe.agent.manifest import load_manifest

    ordner = Path(args.target).expanduser()
    if not ordner.is_dir():
        ordner = resolve_out_dir(args.target)
    if not ordner.is_dir():
        print(f"Kein Ordner: {ordner}")
        return 1
    if args.pruefen:
        fehler = bpmn_mod.pruefe(ordner)
        if fehler:
            for f in fehler:
                print(f"FEHLER: {f}")
            return 1
        print(f"OK: {bpmn_mod.JSON_NAME} ist gueltig.")
        return 0
    manifest = load_manifest(ordner)
    name = args.name or (manifest.name if manifest else ordner.name)
    browser = Path(args.browser) if args.browser else None
    dateien = bpmn_mod.erzeuge_bpmn(ordner, name, log=print, browser=browser, neu=args.neu)
    return 0 if dateien else 1
