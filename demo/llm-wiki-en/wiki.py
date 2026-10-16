#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk"]
# ///
"""LLM wiki in the Karpathy pattern: ingest, query and lint via the Claude Agent SDK.

The script sits next to CLAUDE.md in the root folder of the wiki.

    uv run wiki.py init                      create folder structure and starter pages
    uv run wiki.py status                    new raw sources and structure check, no AI
    uv run wiki.py ingest                    incorporate all new raw sources from raw/
    uv run wiki.py ingest raw/2026-10-06_ws  only this raw source
    uv run wiki.py query "question"          answer from the wiki with citations
    uv run wiki.py query "question" --save   also save the answer as an analysis page
    uv run wiki.py lint                      write a check report to wiki/lint/
    uv run wiki.py lint --fix                additionally fix structural errors

Options before the command: --wiki PATH (default: the script's folder, or WIKI_ROOT),
--model NAME (default: WIKI_MODEL, otherwise the SDK default).

Login: environment variable ANTHROPIC_API_KEY or an existing Claude Code login.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

ORDNER = [
    "raw",
    "wiki/sources",
    "wiki/processes",
    "wiki/requirements",
    "wiki/systems",
    "wiki/roles",
    "wiki/decisions",
    "wiki/open-items",
    "wiki/contradictions",
    "wiki/analyses",
    "wiki/lint",
]

STARTSEITEN = {
    "wiki/index.md": (
        "# Index\n\n"
        "Highest assigned numbers: Q-000 · PRO-000 · ANF-000 · SYS-000 · ROL-000 · "
        "ENT-000 · OP-000 · WID-000 · AN-000\n\n"
        "## Cross-cutting\n\n"
        "- [[overview]]: Situation overview of the domain\n"
        "- [[glossary]]: Terms and misrecognitions\n\n"
        "## Sources\n\n## Processes\n\n## Requirements\n\n## Systems\n\n## Roles\n\n"
        "## Decisions\n\n## Open items\n\n## Contradictions\n\n## Analyses\n"
    ),
    "wiki/log.md": "# Log\n\nChronicle of all operations, append-only.\n",
    "wiki/overview.md": (
        "# Overview of the Assistant domain\n\n"
        "> AI-generated situation overview based on the state of the wiki.\n\n"
        "No sources incorporated yet.\n"
    ),
    "wiki/glossary.md": (
        "# Glossary\n\n"
        "| Term | Meaning in the domain | Synonyms | Misrecognitions | Source |\n"
        "|---|---|---|---|---|\n\n"
        "## Confirmed misrecognitions\n\n"
        "| Misrecognition | Correct |\n"
        "|---|---|\n"
    ),
}

LESEN = ["Read", "Glob", "Grep"]
SCHREIBEN = LESEN + ["Write", "Edit"]

SYSTEM_ZUSATZ = (
    "You maintain an LLM wiki. The schema is in CLAUDE.md in the working directory and is "
    "binding. Write only under wiki/. The raw/ folder and CLAUDE.md are "
    "read-only. Answer in English."
)

LINK = re.compile(r"\[\[([^\]|#]+)")
ROHQUELLE = re.compile(r"^rohquelle:\s*[\"']?raw/(.+?)/?[\"']?\s*$", re.MULTILINE)


# ---------------------------------------------------------------- without AI

def cmd_init(root: Path) -> int:
    for ordner in ORDNER:
        (root / ordner).mkdir(parents=True, exist_ok=True)
    for pfad, inhalt in STARTSEITEN.items():
        datei = root / pfad
        if not datei.exists():
            datei.write_text(inhalt, encoding="utf-8")
            print(f"created: {pfad}")
    if not (root / "CLAUDE.md").exists():
        print("Note: CLAUDE.md is missing from the root folder. Without it the AI does not know the schema.")
    print(f"Wiki ready: {root}")
    return 0


def rohquellen(root: Path) -> list[str]:
    raw = root / "raw"
    if not raw.is_dir():
        return []
    return sorted(p.name for p in raw.iterdir() if not p.name.startswith("."))


def eingearbeitet(root: Path) -> set[str]:
    namen: set[str] = set()
    for seite in (root / "wiki" / "sources").glob("*.md"):
        namen.update(m.strip() for m in ROHQUELLE.findall(seite.read_text(encoding="utf-8")))
    return namen


def neue_rohquellen(root: Path) -> list[str]:
    fertig = eingearbeitet(root)
    return [name for name in rohquellen(root) if name not in fertig]


def strukturpruefung(root: Path) -> str:
    """Mechanical check: broken links, orphans, index gaps, missing IDs."""
    wiki = root / "wiki"
    seiten = [p for p in wiki.rglob("*.md") if "lint" not in p.relative_to(wiki).parts]
    namen = {p.stem for p in seiten}
    ohne_pflicht = {"index", "log", "overview", "glossary"}

    kaputt: list[str] = []
    eingehend: dict[str, int] = {n: 0 for n in namen}
    im_index: set[str] = set()
    ohne_id: list[str] = []

    for seite in seiten:
        text = seite.read_text(encoding="utf-8")
        ziele = {z.strip() for z in LINK.findall(text)}
        if seite.stem == "index":
            im_index = ziele
        for ziel in ziele:
            if ziel not in namen:
                kaputt.append(f"{seite.relative_to(root).as_posix()} -> [[{ziel}]]")
            elif ziel != seite.stem and seite.stem not in ("index", "log"):
                eingehend[ziel] += 1
        if seite.parent != wiki and not re.search(r"^id:\s*\S+", text, re.MULTILINE):
            ohne_id.append(seite.relative_to(root).as_posix())

    waisen = sorted(n for n, zahl in eingehend.items() if zahl == 0 and n not in ohne_pflicht)
    nicht_im_index = sorted(n for n in namen if n not in im_index and n not in ("index", "log"))
    offen = neue_rohquellen(root)

    def block(titel: str, eintraege: list[str]) -> str:
        if not eintraege:
            return f"{titel}: none"
        return f"{titel} ({len(eintraege)}):\n" + "\n".join(f"  - {e}" for e in eintraege)

    return "\n".join([
        f"Pages in the wiki: {len(seiten)}",
        block("Broken links", sorted(kaputt)),
        block("Orphans without incoming link", waisen),
        block("Not in the index", nicht_im_index),
        block("Pages without id in frontmatter", sorted(ohne_id)),
        block("Raw sources without a source page", offen),
    ])


def cmd_status(root: Path) -> int:
    print(strukturpruefung(root))
    return 0


# ---------------------------------------------------------------- with AI

async def agent(root: Path, auftrag: str, werkzeuge: list[str],
                schreibpfade: list[str], model: str | None) -> int:
    try:
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, ClaudeSDKError, HookMatcher,
            ResultMessage, TextBlock, ToolUseBlock, query,
        )
    except ImportError:
        print("claude-agent-sdk is missing. Start with 'uv run wiki.py ...' or "
              "run 'pip install claude-agent-sdk'.")
        return 2

    erlaubt = [(root / p).resolve() for p in schreibpfade]

    async def schreibschutz(eingabe, tool_use_id, kontext):
        pfad = (eingabe.get("tool_input") or {}).get("file_path") or ""
        ziel = Path(pfad)
        if not ziel.is_absolute():
            ziel = root / ziel
        ziel = ziel.resolve()
        if any(ziel == e or e in ziel.parents for e in erlaubt):
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Write protection: in this run, writing is only allowed under "
                    + ", ".join(schreibpfade)
                ),
            }
        }

    optionen = ClaudeAgentOptions(
        cwd=str(root),
        system_prompt={"type": "preset", "preset": "claude_code", "append": SYSTEM_ZUSATZ},
        setting_sources=["project"],          # loads CLAUDE.md from the root folder
        tools=werkzeuge,                      # only these tools are available, no Bash
        allowed_tools=werkzeuge,
        permission_mode="dontAsk",            # anything not allowed is denied
        hooks={"PreToolUse": [HookMatcher(matcher="Write|Edit", hooks=[schreibschutz])]},
        model=model,
        max_turns=200,
    )

    fehler = False
    try:
        async for nachricht in query(prompt=auftrag, options=optionen):
            if isinstance(nachricht, AssistantMessage):
                for teil in nachricht.content:
                    if isinstance(teil, TextBlock) and teil.text.strip():
                        print(teil.text)
                    elif isinstance(teil, ToolUseBlock):
                        ziel = teil.input.get("file_path") or teil.input.get("pattern") or ""
                        print(f"  · {teil.name} {ziel}")
            elif isinstance(nachricht, ResultMessage):
                fehler = nachricht.is_error
                kosten = f", {nachricht.total_cost_usd:.2f} USD" if nachricht.total_cost_usd else ""
                print(f"\n[{nachricht.subtype}: {nachricht.num_turns} turns, "
                      f"{nachricht.duration_ms / 1000:.0f} s{kosten}]")
    except ClaudeSDKError as e:
        print(f"\nAborted by the SDK: {e}")
        return 1
    return 1 if fehler else 0


async def cmd_ingest(root: Path, pfade: list[str], model: str | None) -> int:
    if pfade:
        namen = []
        for pfad in pfade:
            name = Path(pfad).name
            if not (root / "raw" / name).exists():
                print(f"Not found: raw/{name}")
                return 2
            namen.append(name)
    else:
        namen = neue_rohquellen(root)
    if not namen:
        print("No new raw sources in raw/.")
        return 0

    for nr, name in enumerate(namen, 1):
        print(f"\n=== Ingest {nr}/{len(namen)}: raw/{name} ===")
        art = ("It is a folder: read all files in it, images included."
               if (root / "raw" / name).is_dir() else "It is a single file.")
        auftrag = (
            f"Today is {date.today().isoformat()}. Run the INGEST workflow from CLAUDE.md "
            f"for exactly this raw source: raw/{name}. {art} "
            f"Put 'rohquelle: raw/{name}' in the frontmatter of the source page. "
            "Finish with the final report."
        )
        code = await agent(root, auftrag, SCHREIBEN, ["wiki"], model)
        if code != 0:
            return code
        if name not in eingearbeitet(root):
            print(f"Warning: no source page was found for raw/{name}. Run stopped, "
                  "please check wiki/sources/.")
            return 1
    return 0


async def cmd_query(root: Path, frage: str, ablegen: bool, model: str | None) -> int:
    auftrag = (
        f"Today is {date.today().isoformat()}. Run the QUERY workflow from CLAUDE.md. "
        f"Question: {frage}\n"
    )
    if ablegen:
        auftrag += "Also save the answer as an analysis page (step 5)."
        return await agent(root, auftrag, SCHREIBEN,
                           ["wiki/analyses", "wiki/index.md", "wiki/log.md"], model)
    auftrag += "Do not save anything, just answer."
    return await agent(root, auftrag, LESEN, [], model)


async def cmd_lint(root: Path, fix: bool, model: str | None) -> int:
    heute = date.today().isoformat()
    auftrag = (
        f"Today is {heute}. Run the LINT workflow from CLAUDE.md and write the "
        f"report to wiki/lint/lint-{heute}.md.\n\n"
        "Result of the mechanical structure check, already done; please adopt it "
        f"and do not repeat it:\n\n{strukturpruefung(root)}\n\n"
    )
    if fix:
        auftrag += "Fix order given: fix what CLAUDE.md allows in this case."
        return await agent(root, auftrag, SCHREIBEN, ["wiki"], model)
    auftrag += "No fix order: report and log entry only."
    return await agent(root, auftrag, SCHREIBEN, ["wiki/lint", "wiki/log.md"], model)


# ---------------------------------------------------------------- entry point

def main() -> int:
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="LLM-Wiki: Ingest, Query, Lint")
    p.add_argument("--wiki", default=os.environ.get("WIKI_ROOT") or Path(__file__).resolve().parent,
                   help="root folder of the wiki")
    p.add_argument("--model", default=os.environ.get("WIKI_MODEL"), help="model name")
    sub = p.add_subparsers(dest="befehl", required=True)
    sub.add_parser("init", help="create folder structure")
    sub.add_parser("status", help="new raw sources and structure check, no AI")
    s = sub.add_parser("ingest", help="incorporate raw sources")
    s.add_argument("pfade", nargs="*", help="raw sources under raw/ (default: all new ones)")
    s = sub.add_parser("query", help="question to the wiki")
    s.add_argument("frage")
    s.add_argument("--save", dest="ablegen", action="store_true", help="save the answer as an analysis page")
    s = sub.add_parser("lint", help="check the wiki")
    s.add_argument("--fix", action="store_true", help="fix structural errors")
    a = p.parse_args()

    root = Path(a.wiki).resolve()
    if a.befehl == "init":
        return cmd_init(root)
    if not (root / "wiki").is_dir():
        print(f"No wiki at {root}. Run 'init' first.")
        return 2
    if a.befehl == "status":
        return cmd_status(root)
    if a.befehl == "ingest":
        return asyncio.run(cmd_ingest(root, a.pfade, a.model))
    if a.befehl == "query":
        return asyncio.run(cmd_query(root, a.frage, a.ablegen, a.model))
    return asyncio.run(cmd_lint(root, a.fix, a.model))


if __name__ == "__main__":
    sys.exit(main())
