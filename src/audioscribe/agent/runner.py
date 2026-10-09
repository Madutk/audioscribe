"""Analyse-Lauf mit dem Claude Agent SDK.

**Warum das Agent SDK und nicht die Messages API?** Das SDK steuert Claude Code und
benutzt dessen Anmeldung. Wer sich per ``claude`` mit seinem Pro-/Max-Abo angemeldet
hat, analysiert damit ueber das Abo - ein API-Key ist nicht noetig. Ist dagegen
``ANTHROPIC_API_KEY`` gesetzt, rechnet Claude Code ueber die API ab.

Abgrenzung des Laufs gegen die private Claude-Code-Umgebung des Nutzers:

* ``setting_sources=["project"]``: nur die Einstellungen des Arbeitsordners, also genau
  die dorthin kopierten Skills - keine User-Skills, keine globale CLAUDE.md.
* ``strict_mcp_config=True`` ohne eigene Server: keine MCP-Server/Connectoren.
* ``tools`` begrenzt die verfuegbaren Werkzeuge; alles, was schreibt, laeuft ueber
  ``can_use_tool`` -> ``guard.check_tool``.

``claude_agent_sdk`` wird erst in ``AnalyseSitzung.__aenter__`` importiert; ohne das
Extra ``agent`` bleibt der Rest von audioscribe benutzbar.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, TextIO

from audioscribe.agent import guard
from audioscribe.agent.fortschritt import PLAN_TOOLS, Fortschritt
from audioscribe.agent.manifest import Manifest, load_manifest, save_manifest
from audioscribe.agent.material import Auftrag, Material, copy_material
from audioscribe.agent.prompt import build_task_prompt, system_append
from audioscribe.agent.skills import Skill, install_skills
from audioscribe.souffleur.ki import BACKEND_OLLAMA
from audioscribe.verbrauch import Verbrauch, aus_ergebnis, aus_usage

LOG_NAME = "agent-log.txt"

# Vorab erlaubt sind nur die Skills (das SDK traegt sie selbst ein). Lesen im
# Arbeitsordner erlaubt Claude Code von sich aus; alles uebrige - Lesen ausserhalb,
# jedes Schreiben, Bash - landet in can_use_tool und damit bei guard.check_tool.
# Aufgabenliste: aktuelle Claude-Code-Versionen haben TaskCreate/TaskUpdate/TaskList/
# TaskGet, aeltere TodoWrite. Nicht vorhandene Namen ignoriert Claude Code.
_BASE_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "Skill",
    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TodoWrite",
]

INSTALL_HINT = (
    "Die KI-Analyse benoetigt das Claude Agent SDK. Installiere es mit:\n"
    "  uv sync --extra agent   (zusammen mit --extra cu124 bzw. --extra cpu)"
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sdk_env(dienst: str) -> dict[str, str]:
    """Umgebung fuer Claude Code je KI-Dienst. Bei ``ollama`` wird die Anthropic-kompatible
    Schnittstelle des lokalen Dienstes untergeschoben (``/v1/messages``); der Token ist
    Pflicht, wird lokal aber nicht geprueft. Die Ausgabe je Anfrage wird gedeckelt, damit ein
    Modell, das sich festdenkt, nach Minuten statt nie abbricht. Bei Claude bleibt die Umgebung
    unangetastet."""
    if dienst != BACKEND_OLLAMA:
        return {}
    from audioscribe.config import settings

    return {
        "ANTHROPIC_BASE_URL": settings.ollama_url,
        "ANTHROPIC_AUTH_TOKEN": "ollama",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(settings.ollama_max_ausgabe),
    }


def sdk_denken(dienst: str) -> dict[str, Any] | None:
    """Denkphase je KI-Dienst. Lokal standardmaessig aus: Ollama ignoriert ``budget_tokens``,
    nur ``disabled`` greift. Bei Claude entscheidet Claude Code selbst (``None``)."""
    if dienst != BACKEND_OLLAMA:
        return None
    from audioscribe.config import settings

    return None if settings.ollama_denken else {"type": "disabled"}


def pruefe_lokal(modell: str) -> str:
    """Vor einem lokalen Lauf: Dienst erreichbar, Modell geladen? Liefert eine Protokollzeile,
    sonst ``RuntimeError`` mit dem, was zu tun ist."""
    from audioscribe.config import settings
    from audioscribe.souffleur.ki_ollama import ANALYSE_MIN_CTX, ollama_sicherstellen

    # Läuft der Dienst nicht, startet ihn die App selbst (nur auf diesem Rechner).
    status = ollama_sicherstellen(settings.ollama_url, log_datei=settings.cache_dir / "ollama.log")
    if not status.erreichbar:
        raise RuntimeError(
            f"Lokale KI nicht erreichbar unter {settings.ollama_url} ({status.fehler}; 'ollama serve' starten)"
        )
    if not status.hat_modell(modell):
        raise RuntimeError(f"Lokales Modell {modell} nicht geladen - 'ollama pull {modell}'")
    return (
        f"[experimentell] lokales Modell {modell} ueber Ollama {status.version or '?'} "
        f"({settings.ollama_url}); der Dienst braucht OLLAMA_CONTEXT_LENGTH>={ANALYSE_MIN_CTX}. "
        "Verbrauch zaehlt nicht (lokal)."
    )


def tool_summary(name: str, tool_input: dict[str, Any]) -> str:
    """Einzeilige Beschreibung eines Werkzeugaufrufs fuer das Protokoll."""
    for key in ("file_path", "notebook_path", "path", "pattern", "skill", "command"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            value = " ".join(value.split())
            return f"{name}: {value[:160]}{'…' if len(value) > 160 else ''}"
    return name


class AnalyseSitzung:
    """Eine Agenten-Sitzung ueber einen Arbeitsordner.

    Heute nutzt die CLI genau einen Auftrag (``start``). ``nachricht`` ist die Stelle,
    an der ein spaeterer Dialogmodus Folgeanweisungen in dieselbe Sitzung gibt.
    """

    def __init__(
        self,
        auftrag: Auftrag,
        skills: Sequence[Skill],
        *,
        emit: Callable[[str], None] = print,
        status_zeilen: bool = False,
    ) -> None:
        """``status_zeilen``: maschinenlesbare ``[Agent-Status]``-Zeilen fuer die Oberflaeche."""
        self.auftrag = auftrag
        self.skills = list(skills)
        self.workspace = auftrag.workspace
        self._emit = emit
        self._logfile: TextIO | None = None
        self._client: Any = None
        self._material: Material | None = None
        self._started = time.monotonic()
        self._status_zeilen = status_zeilen
        self._lokal = auftrag.dienst == BACKEND_OLLAMA  # Verbrauch zaehlt nicht (FR-78)
        self.fortschritt = Fortschritt(self.workspace)
        self._tool_names: dict[str, str] = {}  # tool_use_id -> Werkzeug
        # KI-Verbrauch: der Dienst meldet je Ergebnis laufende Summen der Verbindung.
        self._stand = Verbrauch()  # zuletzt gemeldete Summe
        self._lauf = Verbrauch()  # Verbrauch dieses Laufs (abgeschlossene Nachrichten)
        self._vorlaeufig: dict[str, Verbrauch] = {}  # Zwischenstand je Antwort bis zum Ergebnis
        self.manifest = Manifest(
            name=auftrag.name,
            quelle=str(auftrag.quelle),
            skills=[s.name for s in self.skills],
            model=auftrag.model,
            gestartet=_now(),
        )

    # --- Protokoll ------------------------------------------------------------

    def log(self, line: str) -> None:
        self._emit(line)
        if self._logfile is not None:
            self._logfile.write(line + "\n")
            self._logfile.flush()

    def _ist_plan(self, tool_use_id: str) -> bool:
        return self._tool_names.get(tool_use_id) in PLAN_TOOLS

    def _fortschritt_melden(self, plan_geaendert: bool = False) -> None:
        if plan_geaendert:
            line = self.fortschritt.plan_line()
            if line:
                self.log(line)
        if self._status_zeilen:
            # Nur fuer die Oberflaeche, nicht ins agent-log.txt.
            self._emit(self.fortschritt.status_line())

    def _zwischenstand(self, msg: Any) -> bool:
        """Tokens einer Antwort vormerken, bis das Ergebnis die verbindlichen Zahlen bringt;
        ``True``, wenn sich der Stand geaendert hat."""
        if self._lokal:
            return False
        message_id = getattr(msg, "message_id", None)
        verbrauch = aus_usage(getattr(msg, "usage", None))
        if not message_id or not verbrauch.tokens or self._vorlaeufig.get(message_id) == verbrauch:
            return False
        self._vorlaeufig[message_id] = verbrauch
        self._verbrauch_melden()
        return True

    def _verbrauch_melden(self) -> None:
        stand = self._lauf
        for verbrauch in self._vorlaeufig.values():
            stand = stand + verbrauch
        self.fortschritt.verbrauch = {**stand.als_dict(), "vorlaeufig": bool(self._vorlaeufig)}

    # --- Lebenszyklus ------------------------------------------------------------

    async def __aenter__(self) -> AnalyseSitzung:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        except ModuleNotFoundError as exc:
            raise RuntimeError(INSTALL_HINT) from exc

        self.workspace.mkdir(parents=True, exist_ok=True)
        self._logfile = (self.workspace / LOG_NAME).open("a", encoding="utf-8")
        self.log(f"=== {_now()} Analyse '{self.auftrag.name}' -> {self.workspace}")
        try:
            await self._prepare(ClaudeAgentOptions, ClaudeSDKClient)
        except BaseException as exc:
            # __aexit__ laeuft nur nach erfolgreichem __aenter__ - Manifest und Log
            # hier selbst abschliessen.
            await self.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        return self

    async def _prepare(self, ClaudeAgentOptions: Any, ClaudeSDKClient: Any) -> None:  # noqa: N803
        frueher = load_manifest(self.workspace)
        if self.auftrag.resume:
            # Fortsetzung: Material und Skills liegen schon da, die Historie ebenfalls.
            if frueher is not None:
                self.manifest = frueher
                self.manifest.status = "laeuft"
                self.manifest.fehler = None
        else:
            install_skills(self.skills, self.workspace)
            self._material = copy_material(self.auftrag)
            self.fortschritt.frames_total = self._material.frames
            self.log(
                f"Material: {self._material.transkript}, {self._material.frames} Standbild(er); "
                f"Skills: {', '.join(s.name for s in self.skills) or '(keine)'}"
            )
            if frueher is not None:
                self.manifest.sitzungen = list(frueher.sitzungen)
        if self.auftrag.resume:
            frames = self.workspace / "material" / "frames"
            if frames.is_dir():
                self.fortschritt.frames_total = sum(1 for p in frames.iterdir() if p.is_file())
        save_manifest(self.workspace, self.manifest)
        self._fortschritt_melden()

        if self._lokal:
            self.log(pruefe_lokal(self.auftrag.model or ""))
        tools = list(_BASE_TOOLS) + (["Bash"] if self.auftrag.bash else [])
        options = ClaudeAgentOptions(
            cwd=str(self.workspace),
            tools=tools,
            skills=[s.name for s in self.skills],
            setting_sources=["project"],
            strict_mcp_config=True,
            permission_mode="default",
            can_use_tool=self._can_use_tool,
            system_prompt={
                "type": "preset", "preset": "claude_code", "append": system_append(lokal=self._lokal),
            },
            model=self.auftrag.model,
            max_turns=self.auftrag.max_turns,
            resume=self.auftrag.resume,
            env=sdk_env(self.auftrag.dienst),
            thinking=sdk_denken(self.auftrag.dienst),
            stderr=lambda line: self.log(f"[claude] {line.rstrip()}"),
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        try:
            if self._client is not None:
                await self._client.disconnect()
        finally:
            if exc is not None and self.manifest.status == "laeuft":
                abgebrochen = exc_type is not None and issubclass(
                    exc_type, (KeyboardInterrupt, _cancelled_exc())
                )
                self.manifest.status = "abgebrochen" if abgebrochen else "fehler"
                self.manifest.fehler = self.manifest.fehler or str(exc) or exc_type.__name__
            self.manifest.beendet = _now()
            self.manifest.dauer_s = round(time.monotonic() - self._started, 1)
            save_manifest(self.workspace, self.manifest)
            self.log(f"=== Status: {self.manifest.status}")
            if self._logfile is not None:
                self._logfile.close()
                self._logfile = None
        return False

    # --- Auftraege ---------------------------------------------------------------

    async def start(self) -> bool:
        """Erster Auftrag: das Material nach Vorgabe analysieren."""
        assert self._material is not None, "start() nur fuer neue Laeufe (nicht bei resume)"
        return await self.nachricht(build_task_prompt(self.auftrag, self._material, self.skills))

    async def nachricht(self, text: str) -> bool:
        """Eine Nachricht senden und die Antwort bis zum Ergebnis verarbeiten."""
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )

        self.manifest.status = "laeuft"
        await self._client.query(text)
        ok = False
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                if self._zwischenstand(msg):
                    self._fortschritt_melden()
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        for line in block.text.strip().splitlines():
                            self.log(f"[Agent] {line}")
                    elif isinstance(block, ToolUseBlock):
                        self._tool_names[block.id] = block.name
                        if block.name not in PLAN_TOOLS | {"TaskList", "TaskGet"}:
                            # Plan-Pflege erscheint als [Plan]-Zeile, nicht als Werkzeug.
                            self.log(f"[Werkzeug] {tool_summary(block.name, block.input)}")
                        if self.fortschritt.tool_use(block.id, block.name, block.input):
                            self._fortschritt_melden(plan_geaendert=block.name in PLAN_TOOLS)
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for block in msg.content:
                    if not isinstance(block, ToolResultBlock):
                        continue
                    if block.is_error:
                        detail = block.content if isinstance(block.content, str) else ""
                        self.log(f"[Werkzeug-Fehler] {' '.join(detail.split())[:300]}")
                    if self.fortschritt.tool_result(
                        block.tool_use_id, bool(block.is_error), block.content
                    ):
                        self._fortschritt_melden(plan_geaendert=self._ist_plan(block.tool_use_id))
            elif isinstance(msg, ResultMessage):
                ok = self._record_result(msg)
        if ok and self.auftrag.prozessbild:
            self._prozessbild()
        if ok and self.auftrag.bpmn:
            self._bpmn()
        return ok

    def _bpmn(self) -> None:
        """bpmn-modell.json -> .bpmn/.svg/.png; Probleme nur protokollieren (FR-36)."""
        from audioscribe.agent.bpmn import erzeuge_bpmn

        try:
            dateien = erzeuge_bpmn(self.workspace, self.auftrag.name, log=self.log)
        except Exception as exc:  # noqa: BLE001 - Zugabe, darf die Analyse nie kippen
            self.log(f"[BPMN] fehlgeschlagen: {type(exc).__name__}: {exc}")
            return
        neu = [d.name for d in dateien if d.name not in self.fortschritt.docs]
        if neu:
            self.fortschritt.docs.extend(neu)
            self._fortschritt_melden()

    def _prozessbild(self) -> None:
        """Mermaid-Diagramm -> prozessbild.png/.svg; Probleme nur protokollieren (FR-35)."""
        from audioscribe.agent.prozessbild import erzeuge_prozessbilder

        try:
            bilder = erzeuge_prozessbilder(self.workspace, self.fortschritt.docs, log=self.log)
        except Exception as exc:  # noqa: BLE001 - Zugabe, darf die Analyse nie kippen
            self.log(f"[Prozessbild] fehlgeschlagen: {type(exc).__name__}: {exc}")
            return
        neu = [b.name for b in bilder if b.name not in self.fortschritt.docs]
        if neu:
            self.fortschritt.docs.extend(neu)
            self._fortschritt_melden()

    def _record_result(self, msg: Any) -> bool:
        m = self.manifest
        m.session_id = msg.session_id
        if msg.session_id and msg.session_id not in m.sitzungen:
            m.sitzungen.append(msg.session_id)
        m.turns = (m.turns or 0) + (msg.num_turns or 0)
        # Der Dienst meldet laufende Summen der Verbindung: nur zaehlen, was dazukam.
        # Lokal (Ollama) zaehlt nichts - die gemeldeten Tokens sind nur eine Protokollnotiz.
        gesamt = aus_ergebnis(msg)
        dazu = Verbrauch() if self._lokal else gesamt.minus(self._stand)
        self._stand = gesamt
        self._lauf = self._lauf + dazu
        self._vorlaeufig.clear()
        self._verbrauch_melden()
        if dazu.kosten_usd is not None:
            m.kosten_usd = round((m.kosten_usd or 0.0) + dazu.kosten_usd, 4)
        if dazu.tokens:
            bisher = (Verbrauch.aus_dict(m.tokens) + dazu).als_dict()
            m.tokens = {k: bisher[k] for k in ("eingabe", "ausgabe", "cache_lesen", "cache_schreiben")}
        if msg.is_error:
            m.status = "fehler"
            m.fehler = "; ".join(msg.errors or []) or msg.result or msg.subtype
        else:
            m.status = "fertig"
        save_manifest(self.workspace, m)
        # Der Preis ist der Gegenwert zu API-Preisen - bei Abo-Anmeldung keine Rechnung, deshalb
        # steht "API-Gegenwert" dabei. Die Summe ueber alle Laeufe steht in analyse.json.
        self.log(f"[Ergebnis] {m.status}: {msg.num_turns} Runde(n), Session {msg.session_id}")
        if self._lokal:
            self.log(f"[Verbrauch] lokal, zaehlt nicht ({gesamt.tokens} Tokens gemeldet)")
        elif dazu.tokens:
            self.log(f"[Verbrauch] {dazu.text()}")
        self._fortschritt_melden()
        return not msg.is_error

    async def _can_use_tool(self, tool_name: str, tool_input: dict[str, Any], context: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        decision = guard.check_tool(
            tool_name, tool_input, self.workspace, bash=self.auftrag.bash
        )
        if decision.erlaubt:
            return PermissionResultAllow()
        self.log(f"[Verweigert] {tool_summary(tool_name, tool_input)} - {decision.grund}")
        return PermissionResultDeny(message=decision.grund)


def _cancelled_exc() -> type[BaseException]:
    try:
        import anyio

        return anyio.get_cancelled_exc_class()
    except Exception:  # noqa: BLE001 - ausserhalb einer Event-Loop
        return KeyboardInterrupt


async def _run(
    auftrag: Auftrag, skills: Sequence[Skill], emit: Callable[[str], None], status_zeilen: bool
) -> bool:
    async with AnalyseSitzung(auftrag, skills, emit=emit, status_zeilen=status_zeilen) as sitzung:
        if auftrag.resume:
            text = auftrag.kontext_text.strip() or (
                "Setze die Analyse fort und bringe alle Dokumente sowie INDEX.md auf den "
                "aktuellen Stand."
            )
            return await sitzung.nachricht(text)
        return await sitzung.start()


def run_analysis(
    auftrag: Auftrag,
    skills: Sequence[Skill],
    *,
    emit: Callable[[str], None] = print,
    status_zeilen: bool = False,
) -> int:
    """Synchroner Einstieg fuer die CLI; Exit-Code 0 bei Erfolg."""
    try:
        import anyio
        import claude_agent_sdk  # noqa: F401
    except ModuleNotFoundError:
        emit(INSTALL_HINT)
        return 1

    try:
        ok = anyio.run(_run, auftrag, skills, emit, status_zeilen)
    except RuntimeError as exc:
        emit(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - SDK-/CLI-Fehler lesbar melden
        emit(f"Analyse fehlgeschlagen: {type(exc).__name__}: {exc}")
        if type(exc).__name__ == "CLINotFoundError":
            emit("Claude Code nicht gefunden - 'audioscribe doctor' zeigt Details.")
        return 1
    if ok:
        emit(f"\nFertig. Ergebnisse: {auftrag.workspace}")
        index = auftrag.workspace / "INDEX.md"
        if index.exists():
            emit(f"Uebersicht: {index}")
    return 0 if ok else 1
