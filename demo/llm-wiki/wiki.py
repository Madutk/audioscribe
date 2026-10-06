#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk"]
# ///
"""LLM-Wiki nach Karpathy-Muster: Ingest, Query und Lint über das Claude Agent SDK.

Das Skript liegt neben CLAUDE.md im Wurzelordner des Wikis.

    uv run wiki.py init                      Ordnerstruktur und Startseiten anlegen
    uv run wiki.py status                    neue Rohquellen und Strukturprüfung, ohne KI
    uv run wiki.py ingest                    alle neuen Rohquellen aus raw/ einarbeiten
    uv run wiki.py ingest raw/2026-10-06_ws  nur diese Rohquelle
    uv run wiki.py query "Frage"             Antwort aus dem Wiki mit Fundstellen
    uv run wiki.py query "Frage" --ablegen   Antwort zusätzlich als Analyse-Seite speichern
    uv run wiki.py lint                      Prüfbericht nach wiki/lint/ schreiben
    uv run wiki.py lint --fix                zusätzlich Strukturfehler beheben

Optionen vor dem Befehl: --wiki PFAD (Standard: Ordner des Skripts, oder WIKI_ROOT),
--model NAME (Standard: WIKI_MODEL, sonst Vorgabe des SDK).

Anmeldung: Umgebungsvariable ANTHROPIC_API_KEY oder eine bestehende Claude-Code-Anmeldung.
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
    "wiki/quellen",
    "wiki/prozesse",
    "wiki/anforderungen",
    "wiki/systeme",
    "wiki/rollen",
    "wiki/entscheidungen",
    "wiki/offene-punkte",
    "wiki/widersprueche",
    "wiki/analysen",
    "wiki/lint",
]

STARTSEITEN = {
    "wiki/index.md": (
        "# Index\n\n"
        "Höchste vergebene Nummern: Q-000 · PRO-000 · ANF-000 · SYS-000 · ROL-000 · "
        "ENT-000 · OP-000 · WID-000 · AN-000\n\n"
        "## Übergreifend\n\n"
        "- [[uebersicht]]: Lagebild der Domäne\n"
        "- [[glossar]]: Begriffe und Fehlerkennungen\n\n"
        "## Quellen\n\n## Prozesse\n\n## Anforderungen\n\n## Systeme\n\n## Rollen\n\n"
        "## Entscheidungen\n\n## Offene Punkte\n\n## Widersprüche\n\n## Analysen\n"
    ),
    "wiki/log.md": "# Log\n\nChronik aller Vorgänge, nur anhängend.\n",
    "wiki/uebersicht.md": (
        "# Übersicht Domäne Assistenz\n\n"
        "> KI-erzeugtes Lagebild auf Basis des Wiki-Stands.\n\n"
        "Noch keine Quellen eingearbeitet.\n"
    ),
    "wiki/glossar.md": (
        "# Glossar\n\n"
        "| Begriff | Bedeutung in der Domäne | Synonyme | Fehlerkennungen | Beleg |\n"
        "|---|---|---|---|---|\n"
    ),
}

LESEN = ["Read", "Glob", "Grep"]
SCHREIBEN = LESEN + ["Write", "Edit"]

SYSTEM_ZUSATZ = (
    "Du pflegst ein LLM-Wiki. Das Schema steht in CLAUDE.md im Arbeitsverzeichnis und ist "
    "verbindlich. Schreibe ausschließlich unter wiki/. Der Ordner raw/ und CLAUDE.md sind "
    "schreibgeschützt. Antworte auf Deutsch."
)

LINK = re.compile(r"\[\[([^\]|#]+)")
ROHQUELLE = re.compile(r"^rohquelle:\s*[\"']?raw/(.+?)/?[\"']?\s*$", re.MULTILINE)


# ---------------------------------------------------------------- ohne KI

def cmd_init(root: Path) -> int:
    for ordner in ORDNER:
        (root / ordner).mkdir(parents=True, exist_ok=True)
    for pfad, inhalt in STARTSEITEN.items():
        datei = root / pfad
        if not datei.exists():
            datei.write_text(inhalt, encoding="utf-8")
            print(f"angelegt: {pfad}")
    if not (root / "CLAUDE.md").exists():
        print("Hinweis: CLAUDE.md fehlt im Wurzelordner. Ohne sie kennt die KI das Schema nicht.")
    print(f"Wiki bereit: {root}")
    return 0


def rohquellen(root: Path) -> list[str]:
    raw = root / "raw"
    if not raw.is_dir():
        return []
    return sorted(p.name for p in raw.iterdir() if not p.name.startswith("."))


def eingearbeitet(root: Path) -> set[str]:
    namen: set[str] = set()
    for seite in (root / "wiki" / "quellen").glob("*.md"):
        namen.update(m.strip() for m in ROHQUELLE.findall(seite.read_text(encoding="utf-8")))
    return namen


def neue_rohquellen(root: Path) -> list[str]:
    fertig = eingearbeitet(root)
    return [name for name in rohquellen(root) if name not in fertig]


def strukturpruefung(root: Path) -> str:
    """Mechanische Prüfung: kaputte Verweise, Waisen, Index-Lücken, fehlende IDs."""
    wiki = root / "wiki"
    seiten = [p for p in wiki.rglob("*.md") if "lint" not in p.relative_to(wiki).parts]
    namen = {p.stem for p in seiten}
    ohne_pflicht = {"index", "log", "uebersicht", "glossar"}

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
            return f"{titel}: keine"
        return f"{titel} ({len(eintraege)}):\n" + "\n".join(f"  - {e}" for e in eintraege)

    return "\n".join([
        f"Seiten im Wiki: {len(seiten)}",
        block("Kaputte Verweise", sorted(kaputt)),
        block("Waisen ohne eingehenden Verweis", waisen),
        block("Nicht im Index", nicht_im_index),
        block("Seiten ohne id im Frontmatter", sorted(ohne_id)),
        block("Rohquellen ohne Quellenseite", offen),
    ])


def cmd_status(root: Path) -> int:
    print(strukturpruefung(root))
    return 0


# ---------------------------------------------------------------- mit KI

async def agent(root: Path, auftrag: str, werkzeuge: list[str],
                schreibpfade: list[str], model: str | None) -> int:
    try:
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, ClaudeSDKError, HookMatcher,
            ResultMessage, TextBlock, ToolUseBlock, query,
        )
    except ImportError:
        print("claude-agent-sdk fehlt. Mit 'uv run wiki.py ...' starten oder "
              "'pip install claude-agent-sdk' ausführen.")
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
                    "Schreibschutz: In diesem Lauf darf nur geschrieben werden unter "
                    + ", ".join(schreibpfade)
                ),
            }
        }

    optionen = ClaudeAgentOptions(
        cwd=str(root),
        system_prompt={"type": "preset", "preset": "claude_code", "append": SYSTEM_ZUSATZ},
        setting_sources=["project"],          # lädt CLAUDE.md aus dem Wurzelordner
        tools=werkzeuge,                      # nur diese Werkzeuge stehen bereit, kein Bash
        allowed_tools=werkzeuge,
        permission_mode="dontAsk",            # alles nicht Freigegebene wird abgelehnt
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
                print(f"\n[{nachricht.subtype}: {nachricht.num_turns} Schritte, "
                      f"{nachricht.duration_ms / 1000:.0f} s{kosten}]")
    except ClaudeSDKError as e:
        print(f"\nAbbruch durch das SDK: {e}")
        return 1
    return 1 if fehler else 0


async def cmd_ingest(root: Path, pfade: list[str], model: str | None) -> int:
    if pfade:
        namen = []
        for pfad in pfade:
            name = Path(pfad).name
            if not (root / "raw" / name).exists():
                print(f"Nicht gefunden: raw/{name}")
                return 2
            namen.append(name)
    else:
        namen = neue_rohquellen(root)
    if not namen:
        print("Keine neuen Rohquellen in raw/.")
        return 0

    for nr, name in enumerate(namen, 1):
        print(f"\n=== Ingest {nr}/{len(namen)}: raw/{name} ===")
        art = ("Sie ist ein Ordner: lies alle Dateien darin, Bilder eingeschlossen."
               if (root / "raw" / name).is_dir() else "Sie ist eine einzelne Datei.")
        auftrag = (
            f"Heute ist {date.today().isoformat()}. Führe den Arbeitsablauf INGEST aus CLAUDE.md "
            f"für genau diese Rohquelle aus: raw/{name}. {art} "
            f"Trage im Frontmatter der Quellenseite 'rohquelle: raw/{name}' ein. "
            "Schließe mit dem Abschlussbericht."
        )
        code = await agent(root, auftrag, SCHREIBEN, ["wiki"], model)
        if code != 0:
            return code
        if name not in eingearbeitet(root):
            print(f"Warnung: Für raw/{name} wurde keine Quellenseite gefunden. Lauf angehalten, "
                  "bitte wiki/quellen/ prüfen.")
            return 1
    return 0


async def cmd_query(root: Path, frage: str, ablegen: bool, model: str | None) -> int:
    auftrag = (
        f"Heute ist {date.today().isoformat()}. Führe den Arbeitsablauf QUERY aus CLAUDE.md aus. "
        f"Frage: {frage}\n"
    )
    if ablegen:
        auftrag += "Lege die Antwort zusätzlich als Analyse-Seite ab (Schritt 5)."
        return await agent(root, auftrag, SCHREIBEN,
                           ["wiki/analysen", "wiki/index.md", "wiki/log.md"], model)
    auftrag += "Lege nichts ab, antworte nur."
    return await agent(root, auftrag, LESEN, [], model)


async def cmd_lint(root: Path, fix: bool, model: str | None) -> int:
    heute = date.today().isoformat()
    auftrag = (
        f"Heute ist {heute}. Führe den Arbeitsablauf LINT aus CLAUDE.md aus und schreibe den "
        f"Bericht nach wiki/lint/lint-{heute}.md.\n\n"
        "Ergebnis der mechanischen Strukturprüfung, bereits durchgeführt, bitte übernehmen "
        f"und nicht wiederholen:\n\n{strukturpruefung(root)}\n\n"
    )
    if fix:
        auftrag += "Korrekturauftrag erteilt: Behebe, was CLAUDE.md für diesen Fall erlaubt."
        return await agent(root, auftrag, SCHREIBEN, ["wiki"], model)
    auftrag += "Kein Korrekturauftrag: nur Bericht und Log-Eintrag."
    return await agent(root, auftrag, SCHREIBEN, ["wiki/lint", "wiki/log.md"], model)


# ---------------------------------------------------------------- Aufruf

def main() -> int:
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="LLM-Wiki: Ingest, Query, Lint")
    p.add_argument("--wiki", default=os.environ.get("WIKI_ROOT") or Path(__file__).resolve().parent,
                   help="Wurzelordner des Wikis")
    p.add_argument("--model", default=os.environ.get("WIKI_MODEL"), help="Modellname")
    sub = p.add_subparsers(dest="befehl", required=True)
    sub.add_parser("init", help="Ordnerstruktur anlegen")
    sub.add_parser("status", help="neue Rohquellen und Strukturprüfung, ohne KI")
    s = sub.add_parser("ingest", help="Rohquellen einarbeiten")
    s.add_argument("pfade", nargs="*", help="Rohquellen unter raw/ (Standard: alle neuen)")
    s = sub.add_parser("query", help="Frage an das Wiki")
    s.add_argument("frage")
    s.add_argument("--ablegen", action="store_true", help="Antwort als Analyse-Seite speichern")
    s = sub.add_parser("lint", help="Wiki prüfen")
    s.add_argument("--fix", action="store_true", help="Strukturfehler beheben")
    a = p.parse_args()

    root = Path(a.wiki).resolve()
    if a.befehl == "init":
        return cmd_init(root)
    if not (root / "wiki").is_dir():
        print(f"Kein Wiki unter {root}. Zuerst 'init' ausführen.")
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
