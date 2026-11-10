"""``audioscribe ingest``: eine Rohquelle per Claude-Agent ins LLM-Wiki einarbeiten.

Der Lauf arbeitet **im Wiki** (``cwd`` = Wiki-Wurzel): ``setting_sources=["project"]`` lädt
dessen ``CLAUDE.md`` (das verbindliche Schema) und die Skills unter ``<wiki>/.claude/skills``
(etwa ``wiki-ingest``). audioscribe bringt keine eigenen Ingest-Regeln mit - wie eingearbeitet
wird, bestimmt das Wiki selbst.

Zugriff (``guard.check_wiki_tool``): lesen im ganzen Wiki, schreiben nur unter ``wiki/``,
``raw/`` und ``CLAUDE.md`` bleiben unberührt, kein Bash.

**Rückfragen**: Ruft der Agent ``AskUserQuestion`` auf, schreibt der Lauf eine Zeile
``[Agent-Frage] {json}`` auf stdout und wartet auf die Antwort als JSON-Zeile auf stdin
(``{"id": …, "answers": {Frage: Antwort}}`` oder ``{"id": …, "ablehnen": true}``). Die
Oberfläche (``ui/einarbeitung.py``) zeigt die Frage und reicht die Antwort durch.

**Nachfassen und Fortsetzen**: Jeder Lauf ist ein Prozess für eine Nachricht. Die Session-ID
steht ab dem ersten Moment in ``analyse.json`` des Arbeitsordners; eine Folgenachricht oder die
Fortsetzung nach einem Abbruch (``--fortsetzen``) setzt dieselbe Claude-Sitzung fort.
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audioscribe.agent import guard
from audioscribe.agent.fortschritt import Fortschritt
from audioscribe.agent.manifest import load_manifest, save_manifest
from audioscribe.agent.material import Auftrag
from audioscribe.agent.runner import (
    SDK_PUFFER,
    AnalyseSitzung,
    _now,
    install_hint,
    pruefe_lokal,
    sdk_denken,
    sdk_env,
    tool_summary,
)
from audioscribe.i18n import tr

FRAGE_PREFIX = "[Agent-Frage] "
SCHEMA_DATEI = "CLAUDE.md"

# Lesen/Schreiben (Guard), Plan (Fortschritt), Skills des Wikis, Rückfrage an den Menschen.
WIKI_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "Skill",
    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TodoWrite",
    guard.FRAGE_TOOL,
]

_ROHQUELLE_RE = re.compile(r"^rohquelle:\s*(.+?)\s*$", re.M)

LiesAntwort = Callable[[str], Awaitable[dict | None]]


@dataclass(frozen=True)
class WikiAuftrag:
    """Alles, was ein Einarbeitungs-Lauf von außen bekommt."""

    arbeitsordner: Path  # Protokoll und analyse.json des Auftrags (nicht im Wiki)
    wiki_dir: Path  # Wiki-Wurzel mit CLAUDE.md, raw/ und wiki/
    rohquelle: str  # relativ zur Wiki-Wurzel, POSIX: raw/meetings/<stamm>.md oder raw/<ordner>
    seiten_dir: Path | None = None  # Default: <wiki>/wiki
    assets: Path | None = None  # Bilder der Sitzung (falls außerhalb von raw/)
    model: str | None = None
    dienst: str = "claude-agent"
    max_turns: int | None = None
    resume: str | None = None  # Session-ID: Folgenachricht oder Fortsetzung
    nachricht: str = ""  # Folgenachricht des Nutzers (sonst Auftrag bzw. Fortsetzung)
    unterbrochen: bool = False  # der vorige Lauf brach ab (Neustart, Absturz)

    @property
    def seiten(self) -> Path:
        return self.seiten_dir if self.seiten_dir is not None else self.wiki_dir / "wiki"


def system_zusatz() -> str:
    return tr(
        "Du pflegst ein LLM-Wiki. Das Schema steht in CLAUDE.md im Arbeitsordner und ist "
        "verbindlich. Schreibe nur unter wiki/. Der Ordner raw/ und CLAUDE.md sind "
        "schreibgeschützt. Erfinde nichts. Ein Mensch verfolgt den Lauf und kann Rückfragen "
        "beantworten: Nutze AskUserQuestion nur für Punkte, die du nach CLAUDE.md nicht selbst "
        "entscheiden darfst oder ohne die das Ergebnis falsch würde - wenige, gebündelte Fragen. "
        "Antworte in der Sprache des Wikis."
    )


def ingest_prompt(auftrag: WikiAuftrag) -> str:
    teile = [
        tr("# Einarbeiten: {quelle}", quelle=auftrag.rohquelle),
        "",
        tr(
            "Führe den INGEST-Ablauf aus CLAUDE.md für genau diese Rohquelle aus: `{quelle}`. "
            "Gibt es dafür einen Skill (z. B. wiki-ingest), nutze ihn.",
            quelle=auftrag.rohquelle,
        ),
        tr(
            "Trage in die Frontmatter der Quellseite exakt `rohquelle: {quelle}` ein - daran "
            "wird die Quelle als eingearbeitet erkannt.",
            quelle=auftrag.rohquelle,
        ),
    ]
    if auftrag.assets is not None:
        teile.append(tr("Die Bilder der Sitzung liegen unter `{ordner}`.", ordner=_rel_oder_abs(auftrag.assets, auftrag.wiki_dir)))
    teile.append(tr("Schließe mit dem Abschlussbericht aus CLAUDE.md ab."))
    return "\n".join(teile)


def fortsetzen_prompt(auftrag: WikiAuftrag) -> str:
    return tr(
        "Der vorige Lauf wurde unterbrochen (z. B. durch einen Neustart). Setze das Einarbeiten "
        "von `{quelle}` fort: Prüfe zuerst, welche Seiten schon geschrieben oder nur halb fertig "
        "sind, vervollständige sie, und schließe mit dem Abschlussbericht aus CLAUDE.md ab.",
        quelle=auftrag.rohquelle,
    )


def _rel_oder_abs(pfad: Path, wurzel: Path) -> str:
    try:
        return Path(pfad).resolve().relative_to(Path(wurzel).resolve()).as_posix()
    except ValueError:
        return str(pfad)


def quellseite(wiki_dir: Path, rohquelle: str, seiten_dir: Path | None = None) -> Path | None:
    """Die Wiki-Seite, deren Frontmatter ``rohquelle: <rohquelle>`` trägt - ``None``, wenn die
    Quelle (noch) nicht eingearbeitet ist."""
    seiten = Path(seiten_dir) if seiten_dir is not None else Path(wiki_dir) / "wiki"
    gesucht = rohquelle.strip().strip("/")
    try:
        dateien = sorted(seiten.rglob("*.md"))
    except OSError:
        return None
    for datei in dateien:
        if ".claude" in datei.relative_to(seiten).parts:
            continue
        try:
            kopf = datei.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if not kopf.startswith("---"):
            continue
        ende = kopf.find("\n---", 3)
        frontmatter = kopf[: ende if ende > 0 else len(kopf)]
        for m in _ROHQUELLE_RE.finditer(frontmatter):
            if m.group(1).strip().strip("\"'").strip("/") == gesucht:
                return datei
    return None


def parse_frage_line(line: str) -> dict | None:
    """Gegenstück zur ``[Agent-Frage]``-Zeile; ``None`` für jede andere Zeile."""
    if not line.startswith(FRAGE_PREFIX):
        return None
    try:
        data = json.loads(line[len(FRAGE_PREFIX):])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("questions"), list):
        return None
    return data


def _antwort_text(antworten: dict) -> str:
    return " · ".join(f"{k} → {v}" for k, v in antworten.items())


class WikiSitzung(AnalyseSitzung):
    """Agenten-Sitzung über dem Wiki; Protokoll und Manifest im Arbeitsordner des Auftrags."""

    def __init__(
        self,
        auftrag: WikiAuftrag,
        *,
        emit: Callable[[str], None] = print,
        status_zeilen: bool = False,
        lies_antwort: LiesAntwort | None = None,
    ) -> None:
        basis = Auftrag(
            name=auftrag.arbeitsordner.name,
            quelle=Path(auftrag.rohquelle),
            ausgabe=auftrag.arbeitsordner.parent,
            model=auftrag.model,
            dienst=auftrag.dienst,
            max_turns=auftrag.max_turns,
            bash=False,
            prozessbild=False,
            bpmn=False,
            resume=auftrag.resume,
        )
        super().__init__(basis, [], emit=emit, status_zeilen=status_zeilen)
        self.wiki = auftrag
        self.workspace = auftrag.arbeitsordner
        # Geschriebene Dokumente = Wiki-Seiten, relativ zur Wiki-Wurzel (wiki/…).
        self.fortschritt = Fortschritt(auftrag.wiki_dir)
        self.manifest.name = auftrag.rohquelle
        self.manifest.quelle = auftrag.rohquelle
        self._lies_antwort = lies_antwort

    def _kopfzeile(self) -> str:
        return tr(
            "=== {zeit} Einarbeiten '{quelle}' ins Wiki {wiki}",
            zeit=_now(), quelle=self.wiki.rohquelle, wiki=self.wiki.wiki_dir,
        )

    async def _prepare(self, ClaudeAgentOptions: Any, ClaudeSDKClient: Any) -> None:  # noqa: N803
        frueher = load_manifest(self.workspace)
        if frueher is not None:
            self.manifest = frueher
            self.manifest.status = "laeuft"
            self.manifest.fehler = None
        save_manifest(self.workspace, self.manifest)
        self._fortschritt_melden()
        if self._lokal:
            self.log(pruefe_lokal(self.auftrag.model or ""))
        options = ClaudeAgentOptions(
            cwd=str(self.wiki.wiki_dir),
            tools=list(WIKI_TOOLS),
            skills="all",
            setting_sources=["project"],
            strict_mcp_config=True,
            permission_mode="default",
            can_use_tool=self._can_use_tool,
            system_prompt={"type": "preset", "preset": "claude_code", "append": system_zusatz()},
            model=self.auftrag.model,
            max_turns=self.auftrag.max_turns,
            resume=self.auftrag.resume,
            env=sdk_env(self.auftrag.dienst),
            thinking=sdk_denken(self.auftrag.dienst),
            max_buffer_size=SDK_PUFFER,
            stderr=lambda line: self.log(f"[claude] {line.rstrip()}"),
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()

    async def _can_use_tool(self, tool_name: str, tool_input: dict[str, Any], context: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        if tool_name == guard.FRAGE_TOOL:
            return await self._frage(tool_input)
        read_roots = [self.wiki.assets] if self.wiki.assets is not None else []
        decision = guard.check_wiki_tool(
            tool_name, tool_input, self.wiki.wiki_dir, seiten_dir=self.wiki.seiten, read_roots=read_roots
        )
        if decision.erlaubt:
            return PermissionResultAllow()
        self.log(tr("[Verweigert] {aufruf} - {grund}", aufruf=tool_summary(tool_name, tool_input), grund=decision.grund))
        return PermissionResultDeny(message=decision.grund)

    async def _frage(self, tool_input: dict[str, Any]):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        fragen = [q for q in (tool_input.get("questions") or []) if isinstance(q, dict)]
        texte = " / ".join(str(q.get("question", "")) for q in fragen)
        self.log(tr("[Frage] {text}", text=texte))
        if self._lies_antwort is None:
            return PermissionResultDeny(
                message=tr("Niemand kann gerade antworten. Vermerke den Punkt als offen und arbeite weiter.")
            )
        frage_id = uuid.uuid4().hex[:8]
        self._emit(FRAGE_PREFIX + json.dumps({"id": frage_id, "questions": fragen}, ensure_ascii=False))
        antwort = await self._lies_antwort(frage_id)
        if not antwort or antwort.get("ablehnen") or not isinstance(antwort.get("answers"), dict):
            self.log(tr("[Antwort] (keine)"))
            return PermissionResultDeny(
                message=tr(
                    "Der Nutzer beantwortet diese Frage jetzt nicht. Entscheide nicht selbst - "
                    "vermerke den Punkt als offen und arbeite weiter."
                )
            )
        antworten = {str(k): str(v) for k, v in antwort["answers"].items()}
        self.log(tr("[Antwort] {text}", text=_antwort_text(antworten)))
        return PermissionResultAllow(updated_input={**tool_input, "answers": antworten})


async def _stdin_antwort(frage_id: str) -> dict | None:
    """Wartet auf die Antwortzeile zur Frage ``frage_id``; ``None`` bei Ende der Eingabe."""
    import anyio

    while True:
        zeile = await anyio.to_thread.run_sync(sys.stdin.readline, abandon_on_cancel=True)
        if not zeile:
            return None
        try:
            data = json.loads(zeile)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("id") == frage_id:
            return data


async def _run(auftrag: WikiAuftrag, emit: Callable[[str], None], status_zeilen: bool, lies_antwort: LiesAntwort | None) -> bool:
    async with WikiSitzung(auftrag, emit=emit, status_zeilen=status_zeilen, lies_antwort=lies_antwort) as sitzung:
        if auftrag.nachricht.strip():
            text = auftrag.nachricht.strip()
        elif auftrag.unterbrochen:
            text = fortsetzen_prompt(auftrag)
        else:
            text = ingest_prompt(auftrag)
        return await sitzung.nachricht(text)


def run_einarbeitung(
    auftrag: WikiAuftrag,
    *,
    emit: Callable[[str], None] = print,
    status_zeilen: bool = False,
    lies_antwort: LiesAntwort | None = None,
) -> int:
    try:
        import anyio
        import claude_agent_sdk  # noqa: F401
    except ModuleNotFoundError:
        emit(install_hint())
        return 1
    import warnings

    # Skill ist ohnehin frei (guard.FREE_TOOLS) - der Hinweis des SDK gehört nicht ins Protokoll.
    warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")
    try:
        ok = anyio.run(_run, auftrag, emit, status_zeilen, lies_antwort)
    except RuntimeError as exc:
        emit(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - SDK-/CLI-Fehler lesbar melden
        emit(tr("Einarbeiten fehlgeschlagen: {art}: {fehler}", art=type(exc).__name__, fehler=exc))
        return 1
    return 0 if ok else 1


def ingest(args: argparse.Namespace) -> int:
    """CLI-Einstieg ``audioscribe ingest``."""
    from audioscribe.config import settings
    from audioscribe.souffleur.ki import modell_fuer

    wiki_dir = Path(args.wiki).expanduser()
    if not (wiki_dir / SCHEMA_DATEI).is_file():
        print(tr("Im Wiki {ordner} fehlt {datei} - ohne Schema kann nicht eingearbeitet werden.", ordner=wiki_dir, datei=SCHEMA_DATEI))
        return 1
    rohquelle = args.rohquelle.strip().strip("/")
    if not (wiki_dir / rohquelle).exists():
        print(tr("Rohquelle nicht gefunden: {pfad}", pfad=wiki_dir / rohquelle))
        return 1
    arbeitsordner = Path(args.arbeitsordner).expanduser()
    arbeitsordner.mkdir(parents=True, exist_ok=True)

    resume = None
    unterbrochen = bool(args.fortsetzen)
    if args.fortsetzen or args.nachricht:
        manifest = load_manifest(arbeitsordner)
        resume = manifest.session_id if manifest is not None else None
        if resume is None and args.nachricht:
            print(tr("Keine fortsetzbare Sitzung in {ordner} (analyse.json ohne session_id).", ordner=arbeitsordner))
            return 1
        # Ohne Session (Abbruch vor dem ersten Schritt) beginnt der Lauf neu - mit dem Hinweis,
        # schon Geschriebenes zu prüfen.
    dienst = args.ki_dienst or "claude-agent"
    auftrag = WikiAuftrag(
        arbeitsordner=arbeitsordner,
        wiki_dir=wiki_dir,
        rohquelle=rohquelle,
        seiten_dir=Path(args.seiten).expanduser() if args.seiten else None,
        assets=Path(args.assets).expanduser() if args.assets else None,
        model=modell_fuer(dienst, args.model or settings.agent_model),
        dienst=dienst,
        max_turns=args.max_turns if args.max_turns is not None else settings.agent_max_turns,
        resume=resume,
        nachricht=args.nachricht or "",
        unterbrochen=unterbrochen,
    )
    print(tr("Einarbeiten '{quelle}'", quelle=rohquelle))
    print(tr("  Wiki:    {wiki}", wiki=wiki_dir))
    print(tr("  Modell:  {modell}", modell=auftrag.model))
    if resume:
        print(tr("  Fortsetzung der Sitzung {sitzung}", sitzung=resume))

    def _sigterm(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sigterm)

    def emit(line: str) -> None:
        print(line, flush=True)

    # Rückfragen gehen nur, wenn jemand am anderen Ende der Eingabe sitzt: die Oberfläche
    # (Pipe) oder ein Terminal. Ohne beides (z. B. </dev/null) wird abgelehnt statt gewartet.
    lies = _stdin_antwort if (args.fragen and sys.stdin is not None) else None
    try:
        return run_einarbeitung(auftrag, emit=emit, status_zeilen=settings.emit_progress, lies_antwort=lies)
    except KeyboardInterrupt:
        print(tr("Einarbeiten abgebrochen."))
        return 130
