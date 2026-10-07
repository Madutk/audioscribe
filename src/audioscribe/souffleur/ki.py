"""KI-Dienst des Souffleurs: austauschbar per Konfiguration (Anforderungen §7).

Alles, was ein Sprachmodell braucht, läuft über ``KiDienst``. Welcher Dienst dahinter steht,
entscheidet ``make_ki`` anhand des Backends; Oberfläche und Ausgaben kennen nur „KI“.

- ``ClaudeAgentKi``: werkzeugloser Einzelaufruf über das Claude Agent SDK (nutzt die
  Anmeldung von Claude Code wie die KI-Analyse, PRD §16). Je Aufruf startet das SDK einen
  CLI-Prozess; die Startzeit wird getrennt gemessen (``KiAntwort.start_s``). Sitzungsdateien
  der CLI werden abgeschaltet (``--no-session-persistence``) und ersatzweise gelöscht, damit
  keine Transkript- oder Wiki-Auszüge auf der Platte bleiben.
- ``OllamaKi`` (``ki_ollama.py``): lokales Modell über Ollama auf diesem Rechner; ein
  Chat-Aufruf je Fenster mit Schema-Zwang, nichts verlässt den Rechner, Verbrauch zählt nicht.
- ``AttrappeKi``: deterministische Regeln ohne Netz - für Tests und als Notnagel, wenn kein
  Dienst erreichbar ist (dann sagt der Status das).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from audioscribe.verbrauch import Verbrauch, aus_ergebnis

BACKEND_CLAUDE = "claude-agent"
BACKEND_OLLAMA = "ollama"  # lokales Modell ueber Ollama, siehe souffleur/ki_ollama.py
BACKEND_ATTRAPPE = "attrappe"
BACKENDS: tuple[str, ...] = (BACKEND_CLAUDE, BACKEND_OLLAMA, BACKEND_ATTRAPPE)

# Reihenfolge = Vorschlagsliste in den Einstellungen; das erste ist der Default (Tempo).
SOUFFLEUR_MODELS: tuple[str, ...] = (
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
    "claude-opus-5",
    "claude-fable-5-1",
)
DEFAULT_MODEL = SOUFFLEUR_MODELS[0]
DEFAULT_TIMEOUT_S = 45.0

INSTALL_HINT = "KI-Dienst nicht verfügbar: Paket 'claude-agent-sdk' fehlt (uv sync --extra agent)."


class KiFehler(RuntimeError):
    """Ein KI-Aufruf ist gescheitert (Dienst, Zeitüberschreitung, unbrauchbare Antwort)."""


@dataclass(frozen=True)
class KiAuftrag:
    """Ein Auftrag an die KI. ``kontext`` sind die strukturierten Eingaben, aus denen der
    Prompt gebaut wurde - der echte Dienst ignoriert sie, die Attrappe rechnet damit."""

    system: str
    prompt: str
    schema: dict
    kontext: dict = field(default_factory=dict)
    timeout_s: float = DEFAULT_TIMEOUT_S


@dataclass(frozen=True)
class KiAntwort:
    daten: dict
    start_s: float  # Prozessstart: vom Aufruf bis zur ersten Nachricht des Dienstes
    antwort_s: float  # gesamt: vom Aufruf bis zum Ergebnis
    modell: str
    session_id: str | None = None
    verbrauch: Verbrauch | None = None  # None = lokal, nichts verbraucht


class KiDienst(Protocol):
    modell: str
    backend: str

    def antworte(self, auftrag: KiAuftrag) -> KiAntwort: ...


# --- Claude Agent SDK ------------------------------------------------------------------------


def _slug(pfad: Path) -> str:
    """Ordnername, unter dem die CLI Sitzungsdateien eines Arbeitsverzeichnisses ablegt."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(pfad))


def claude_config_dir() -> Path:
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(raw) if raw else Path.home() / ".claude"


class ClaudeAgentKi:
    backend = BACKEND_CLAUDE

    def __init__(
        self,
        modell: str,
        *,
        cwd: Path,
        log: Callable[[str], None] | None = None,
        on_verbrauch: Callable[[Verbrauch], None] | None = None,
    ) -> None:
        self.modell = modell
        # Ein leerer, eigener Ordner - nie der Wiki-Pfad und nie ein Transkriptordner: die CLI
        # legt Sitzungsdateien nach dem Arbeitsverzeichnis ab.
        self.cwd = Path(cwd)
        self._log = log or (lambda msg: None)
        self._on_verbrauch = on_verbrauch or (lambda verbrauch: None)

    def antworte(self, auftrag: KiAuftrag) -> KiAntwort:
        import anyio

        self.cwd.mkdir(parents=True, exist_ok=True)
        try:
            return anyio.run(self._frage, auftrag)
        except KiFehler:
            raise
        except Exception as exc:  # noqa: BLE001 - jede SDK-/Prozess-Ausnahme wird zum KiFehler
            raise KiFehler(f"KI-Aufruf gescheitert: {type(exc).__name__}: {exc}") from exc

    async def _frage(self, auftrag: KiAuftrag) -> KiAntwort:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        options = ClaudeAgentOptions(
            model=self.modell,
            tools=[],  # keine Werkzeuge: nur lesen, was im Prompt steht
            system_prompt=auftrag.system,
            setting_sources=[],  # keine CLAUDE.md, keine Skills, keine Projekt-Einstellungen
            strict_mcp_config=True,
            max_turns=1,
            cwd=str(self.cwd),
            output_format={"type": "json_schema", "schema": auftrag.schema},
            thinking={"type": "disabled"},
            effort="low",
            extra_args={"no-session-persistence": None},
            stderr=lambda line: self._log(f"[KI] {line.rstrip()}"),
        )
        t0 = time.monotonic()
        start_s: float | None = None
        ergebnis: ResultMessage | None = None
        try:
            with anyio.fail_after(auftrag.timeout_s):
                async for msg in query(prompt=auftrag.prompt, options=options):
                    if start_s is None:
                        start_s = time.monotonic() - t0
                    if isinstance(msg, ResultMessage):
                        ergebnis = msg
        except TimeoutError as exc:
            raise KiFehler(f"KI-Aufruf nach {auftrag.timeout_s:.0f} s abgebrochen") from exc
        antwort_s = time.monotonic() - t0
        if ergebnis is None:
            raise KiFehler("KI-Aufruf ohne Ergebnis")
        self._loesche_sitzungsdatei(ergebnis.session_id)
        # Vor der Fehlerprüfung: auch ein gescheiterter Aufruf hat Tokens verbraucht.
        verbrauch = aus_ergebnis(ergebnis)
        self._on_verbrauch(verbrauch)
        if ergebnis.is_error:
            raise KiFehler(f"KI-Dienst meldet Fehler: {ergebnis.result or ergebnis.subtype}")
        daten = ergebnis.structured_output
        if not isinstance(daten, dict):
            raise KiFehler("KI-Antwort ohne strukturierte Daten")
        return KiAntwort(
            daten=daten, start_s=start_s if start_s is not None else antwort_s, antwort_s=antwort_s,
            modell=self.modell, session_id=ergebnis.session_id, verbrauch=verbrauch,
        )

    def _loesche_sitzungsdatei(self, session_id: str | None) -> None:
        """Ersatz, falls ``--no-session-persistence`` nicht greift: die Sitzungsdatei der CLI
        zu diesem Aufruf entfernen. Es wird nur die Datei zur eigenen Sitzungs-ID angefasst."""
        if not session_id:
            return
        ordner = claude_config_dir() / "projects" / _slug(self.cwd.resolve())
        for pfad in (ordner / f"{session_id}.jsonl",):
            try:
                pfad.unlink()
                self._log(f"[KI] Sitzungsdatei entfernt: {pfad.name}")
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._log(f"[KI] Sitzungsdatei nicht entfernbar: {pfad}: {exc}")


# --- Attrappe ---------------------------------------------------------------------------------

_RHETORISCH = ("oder?", "nicht wahr?", "stimmt's?", "ne?", "gell?", "doch klar")
_OFFEN = ("noch offen", "ungeklärt", "noch unklar", "muss jemand prüfen", "klären wir noch", "nicht geklärt")
_STOPP = {
    "der", "die", "das", "und", "oder", "ist", "sind", "ein", "eine", "wir", "bei", "uns", "von", "im", "in",
    "mit", "für", "auf", "zu", "den", "dem", "des", "es", "sich", "auch", "nicht", "ab", "an", "wer", "wie",
    "was", "gibt", "eigentlich", "doch", "noch", "dann", "nach", "aus", "als", "werden", "wird", "macht",
}


def _woerter(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]+", text.lower()) if len(w) > 2 and w not in _STOPP}


@dataclass(frozen=True)
class AttrappenRegel:
    """Ein Widerspruch, den die Attrappe melden soll, wenn ``aussage`` im Segment und
    ``fundstelle`` in einer der gelieferten Fundstellen (Datei › Überschrift) vorkommt."""

    aussage: str
    fundstelle: str
    zitat: str
    ki_text: str = "Die Angaben weichen voneinander ab."


class AttrappeKi:
    """Regelbasierter Ersatz ohne Netz: Fragen am Fragezeichen, offene Punkte an Signalwörtern,
    Widersprüche nur über eingespeiste Regeln. Antworten sind reproduzierbar."""

    backend = BACKEND_ATTRAPPE

    def __init__(self, modell: str = "attrappe", regeln: list[AttrappenRegel] | None = None) -> None:
        self.modell = modell
        self.regeln = list(regeln or [])
        self.aufrufe: list[KiAuftrag] = []

    def antworte(self, auftrag: KiAuftrag) -> KiAntwort:
        self.aufrufe.append(auftrag)
        t0 = time.monotonic()
        art = auftrag.kontext.get("art")
        if art == "essenz":
            daten = self._essenz(auftrag.kontext)
        else:
            daten = self._befunde(auftrag.kontext)
        return KiAntwort(daten=daten, start_s=0.0, antwort_s=time.monotonic() - t0, modell=self.modell)

    def _befunde(self, kontext: dict) -> dict:
        befunde: list[dict] = []
        uebergangen: list[dict] = []
        fundstellen: list[dict] = kontext.get("fundstellen", [])
        for seg in kontext.get("segmente", []):
            text = str(seg.get("text", "")).strip()
            unten = text.lower()
            regel = next((r for r in self.regeln if r.aussage.lower() in unten), None)
            if regel is not None:
                treffer = next(
                    (f for f in fundstellen if regel.fundstelle.lower() in f"{f['datei']} › {f['ueberschrift']}".lower()),
                    None,
                )
                befunde.append({
                    "segment_id": seg["id"], "art": "widerspruch", "aussage": regel.aussage,
                    "fundstelle_id": treffer["id"] if treffer else None,
                    "wiki_zitat": regel.zitat if treffer else None, "ki_text": regel.ki_text,
                    "suchbegriffe": [], "sicherheit": "hoch",
                })
                continue
            if text.endswith("?"):
                if any(unten.endswith(r) or r in unten for r in _RHETORISCH):
                    uebergangen.append({"segment_id": seg["id"], "grund": "rhetorische_frage"})
                    continue
                treffer = self._beste_fundstelle(text, fundstellen)
                befunde.append({
                    "segment_id": seg["id"], "art": "frage", "aussage": text,
                    "fundstelle_id": treffer["id"] if treffer else None,
                    "wiki_zitat": _erster_satz(treffer["auszug"]) if treffer else None,
                    "ki_text": "Im Wiki steht dazu etwas." if treffer else "Im Wiki liegt dazu nichts vor.",
                    "suchbegriffe": sorted(_woerter(text))[:3], "sicherheit": "hoch",
                })
                continue
            if any(s in unten for s in _OFFEN):
                befunde.append({
                    "segment_id": seg["id"], "art": "offener_punkt", "aussage": text, "fundstelle_id": None,
                    "wiki_zitat": None, "ki_text": "Wurde als ungeklärt benannt.", "suchbegriffe": [],
                    "sicherheit": "hoch",
                })
                continue
            grund = "smalltalk" if len(_woerter(text)) < 4 else "passt_zum_wiki"
            uebergangen.append({"segment_id": seg["id"], "grund": grund})
        # Hoechstens vier je Aufruf (Schema): Widersprueche vor offenen Punkten vor Fragen.
        rang = {"widerspruch": 0, "offener_punkt": 1, "frage": 2}
        befunde.sort(key=lambda b: rang.get(b["art"], 9))
        return {"befunde": befunde[:4], "uebergangen": uebergangen}

    @staticmethod
    def _beste_fundstelle(text: str, fundstellen: list[dict]) -> dict | None:
        woerter = _woerter(text)
        beste, score = None, 0
        for f in fundstellen:
            gemeinsam = len(woerter & _woerter(f"{f['ueberschrift']} {f['auszug']}"))
            if gemeinsam > score:
                beste, score = f, gemeinsam
        return beste if score >= 1 else None

    @staticmethod
    def _essenz(kontext: dict) -> dict:
        saetze = [_erster_satz(str(s.get("text", ""))) for s in kontext.get("segmente", [])]
        saetze = [s for s in saetze if len(_woerter(s)) >= 3]
        return {"essenz": [{"punkt": s} for s in saetze[:5]], "offen": []}


def _erster_satz(text: str) -> str:
    teil = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return teil.strip()


# --- Factory ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class KiStatus:
    zustand: str  # "bereit" | "fehlt" | "aus"
    backend: str
    modell: str
    meldung: str


def sdk_verfuegbar() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def modell_fuer(backend: str, modell: str | None) -> str:
    """Das Modell, das zum Dienst passt. Nach einem Dienstwechsel steht in den Einstellungen
    oft noch das Modell des anderen Dienstes - dann gilt der Default des neuen Dienstes."""
    backend = (backend or BACKEND_CLAUDE).strip().lower()
    m = (modell or "").strip()
    if backend == BACKEND_OLLAMA:
        from audioscribe.souffleur.ki_ollama import lokales_modell

        return lokales_modell(m)
    # Ollama-Tags tragen einen Doppelpunkt (qwen3.6:35b-a3b); Claude-IDs und Aliase nie.
    return m if m and ":" not in m else DEFAULT_MODEL


def make_ki(
    backend: str,
    modell: str,
    *,
    cache_dir: Path,
    log: Callable[[str], None] | None = None,
    regeln: list[AttrappenRegel] | None = None,
    on_verbrauch: Callable[[Verbrauch], None] | None = None,
) -> tuple[Any | None, KiStatus]:
    """Den konfigurierten Dienst bauen. Fehlt er, kommt ``None`` und ein Status, der das sagt -
    der Souffleur läuft dann ohne KI weiter (Fragen-Erkennung und Essenz entfallen)."""
    backend = (backend or BACKEND_CLAUDE).strip().lower()
    modell = modell_fuer(backend, modell)
    if backend == BACKEND_ATTRAPPE:
        return AttrappeKi(regeln=regeln), KiStatus("bereit", backend, "attrappe", "KI-Attrappe (regelbasiert, ohne Netz)")
    if backend == BACKEND_OLLAMA:
        return _make_ollama(modell, log=log)
    if backend != BACKEND_CLAUDE:
        return None, KiStatus("fehlt", backend, modell, f"Unbekanntes KI-Backend: {backend}")
    if not sdk_verfuegbar():
        return None, KiStatus("fehlt", backend, modell, INSTALL_HINT)
    ki = ClaudeAgentKi(modell, cwd=Path(cache_dir) / "souffleur", log=log, on_verbrauch=on_verbrauch)
    return ki, KiStatus("bereit", backend, modell, f"KI bereit (Modell {modell})")


def _make_ollama(modell: str, *, log: Callable[[str], None] | None) -> tuple[Any | None, KiStatus]:
    """Lokaler Dienst: erst prüfen, ob er läuft und das Modell geladen ist - sonst sagt der
    Status, was zu tun ist, statt dass jedes Fenster scheitert."""
    from audioscribe.config import settings
    from audioscribe.souffleur.ki_ollama import OllamaKi, ollama_status

    status = ollama_status(settings.ollama_url)
    if not status.erreichbar:
        return None, KiStatus(
            "fehlt", BACKEND_OLLAMA, modell,
            f"Lokale KI nicht erreichbar unter {settings.ollama_url} ('ollama serve' starten)",
        )
    if not status.hat_modell(modell):
        return None, KiStatus(
            "fehlt", BACKEND_OLLAMA, modell, f"Lokales Modell {modell} nicht geladen - 'ollama pull {modell}'"
        )
    ki = OllamaKi(modell, url=settings.ollama_url, keep_alive=settings.ollama_keep_alive, log=log)
    return ki, KiStatus("bereit", BACKEND_OLLAMA, modell, f"KI bereit (lokal auf diesem Rechner, Modell {modell})")
