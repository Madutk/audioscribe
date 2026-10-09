"""Lokaler KI-Dienst über Ollama (Stufe 2 der austauschbaren KI, PRD §20.2).

Ollama läuft als eigener Prozess auf diesem Rechner (``ollama serve``) und spricht HTTP auf
``localhost:11434``. Je Auftrag geht ein Chat-Aufruf mit JSON-Schema (``format``) hinaus -
Ollama erzwingt die Struktur selbst, Denken (``think``) ist aus, Temperatur 0. Nichts
verlässt den Rechner; der Verbrauch zählt darum nicht (FR-78, ``KiAntwort.verbrauch=None``).

Nur Standardbibliothek: ``urllib`` reicht für drei Endpunkte (``/api/version``, ``/api/tags``,
``/api/chat``). Der HTTP-Aufruf ist injizierbar (``post``), damit Tests ohne Dienst auskommen.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from audioscribe.souffleur.ki import BACKEND_OLLAMA, KiAntwort, KiAuftrag, KiFehler

# Reihenfolge = Vorschlagsliste in den Einstellungen; das erste ist der Default.
# MLX-Builds (Apple Silicon); der letzte Eintrag ist der GGUF-Rückfall über llama.cpp.
OLLAMA_MODELLE: tuple[str, ...] = (
    "qwen3.6:35b-a3b-nvfp4",
    "gemma4:26b-mlx",
    "qwen3.6:27b-mlx",
    "qwen3.6:35b-a3b",
)
DEFAULT_OLLAMA_MODELL = OLLAMA_MODELLE[0]
DEFAULT_URL = "http://localhost:11434"
# Souffleur-Prompts sind klein (Fenster + Kontext + Auszüge, wenige KB); 8k reicht mit Luft.
NUM_CTX = 8192
# Mindestkontext, den Claude Code für die KI-Analyse braucht (OLLAMA_CONTEXT_LENGTH).
ANALYSE_MIN_CTX = 32768

PostFn = Callable[[str, dict | None, float], dict]


class _HttpFehler(Exception):
    """HTTP-Problem beim Dienst: ``code`` None = nicht erreichbar / Zeitüberschreitung."""

    def __init__(self, code: int | None, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


def _http_json(url: str, body: dict | None, timeout_s: float) -> dict:
    """GET (``body`` None) oder POST mit JSON; Antwort als Dict. Fehler -> ``_HttpFehler``."""
    daten = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=daten, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as antwort:  # noqa: S310 - localhost
            roh = antwort.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise _HttpFehler(exc.code, str(detail or exc.reason)) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        grund = getattr(exc, "reason", exc)
        if isinstance(grund, (socket.timeout, TimeoutError)) or "timed out" in str(grund):
            raise _HttpFehler(None, "Zeitüberschreitung") from exc
        raise _HttpFehler(None, str(grund)) from exc
    try:
        ergebnis = json.loads(roh) if roh.strip() else {}
    except json.JSONDecodeError as exc:
        raise _HttpFehler(None, "Antwort ist kein JSON") from exc
    return ergebnis if isinstance(ergebnis, dict) else {}


# --- Status -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class OllamaStatus:
    erreichbar: bool
    version: str | None = None
    modelle: tuple[str, ...] = ()
    fehler: str | None = None

    def hat_modell(self, modell: str) -> bool:
        kandidaten = {modell} if ":" in modell else {modell, f"{modell}:latest"}
        return any(m in kandidaten for m in self.modelle)


def ollama_status(url: str = DEFAULT_URL, *, timeout_s: float = 2.0, post: PostFn = _http_json) -> OllamaStatus:
    """Läuft der Dienst, welche Version, welche Modelle sind geladen? Wirft nie."""
    basis = url.rstrip("/")
    try:
        version = post(f"{basis}/api/version", None, timeout_s).get("version")
        tags = post(f"{basis}/api/tags", None, timeout_s).get("models", [])
    except _HttpFehler as exc:
        return OllamaStatus(False, fehler=exc.text)
    except Exception as exc:  # noqa: BLE001 - Status darf nie kippen
        return OllamaStatus(False, fehler=f"{type(exc).__name__}: {exc}")
    namen = tuple(str(m.get("name") or m.get("model") or "") for m in tags if isinstance(m, dict))
    return OllamaStatus(True, version=str(version) if version else None, modelle=tuple(n for n in namen if n))


# --- Dienst starten ---------------------------------------------------------------------------

# Kontextfenster für 'ollama serve' (README): reicht für die KI-Analyse (>= ANALYSE_MIN_CTX).
SERVE_CONTEXT_LENGTH = 65536
# Wo 'ollama' liegt, wenn es nicht im PATH des Servers steht (Finder-Start, Doppelklick).
OLLAMA_KANDIDATEN: tuple[str, ...] = (
    "~/.local/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
)


def ollama_binary() -> str | None:
    """Pfad zu ``ollama`` - PATH zuerst, dann die üblichen Installationsorte."""
    pfad = shutil.which("ollama")
    if pfad:
        return pfad
    for kandidat in OLLAMA_KANDIDATEN:
        voll = os.path.expanduser(kandidat)
        if os.path.isfile(voll) and os.access(voll, os.X_OK):
            return voll
    return None


def ist_lokal(url: str) -> bool:
    """Zeigt die Dienst-Adresse auf diesen Rechner? Nur dann darf die App ihn selbst starten."""
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def ollama_sicherstellen(
    url: str = DEFAULT_URL,
    *,
    log: Callable[[str], None] | None = None,
    log_datei: Path | None = None,
    timeout_s: float = 20.0,
    post: PostFn = _http_json,
    binary: str | None = None,
    spawn: Callable[..., Any] = subprocess.Popen,
    schlaf: Callable[[float], None] = time.sleep,
) -> OllamaStatus:
    """Dienst erreichbar machen: läuft er nicht, ``ollama serve`` selbst starten und warten.

    Wer die lokale KI wählt, soll nichts von Hand starten müssen. Der Dienst wird als
    eigene Sitzung gestartet und lebt weiter, wenn AudioScribe endet - so wie ein von Hand
    gestartetes ``ollama serve``; das Modell bleibt dann für den nächsten Start warm.
    Nur für Adressen auf diesem Rechner; bei fremder Adresse oder ohne ``ollama``-Programm
    bleibt der bisherige Status mit seinem Fehlertext. Wirft nie.
    """
    status = ollama_status(url, post=post)
    if status.erreichbar or not ist_lokal(url):
        return status
    exe = binary if binary is not None else ollama_binary()
    if not exe:
        return OllamaStatus(False, fehler=f"{status.fehler}; 'ollama' nicht gefunden (brew install ollama / ollama.com)")
    env = dict(os.environ)
    env.setdefault("OLLAMA_CONTEXT_LENGTH", str(SERVE_CONTEXT_LENGTH))
    if log:
        log(f"Lokale KI: Dienst läuft nicht - starte '{exe} serve' (Kontext {env['OLLAMA_CONTEXT_LENGTH']}) ...")
    ausgabe: Any = subprocess.DEVNULL
    try:
        if log_datei is not None:
            log_datei.parent.mkdir(parents=True, exist_ok=True)
            ausgabe = open(log_datei, "ab")  # noqa: SIM115 - gehört dem Kindprozess
        spawn(
            [exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=ausgabe,
            stderr=subprocess.STDOUT if ausgabe is not subprocess.DEVNULL else subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        return OllamaStatus(False, fehler=f"'ollama serve' startet nicht: {exc}")
    finally:
        if ausgabe is not subprocess.DEVNULL:
            ausgabe.close()
    schritte = max(1, int(timeout_s / 0.5))
    for _ in range(schritte):
        schlaf(0.5)
        status = ollama_status(url, post=post, timeout_s=1.0)
        if status.erreichbar:
            if log:
                log(f"Lokale KI: Ollama {status.version or ''} läuft unter {url}".rstrip())
            return status
    return OllamaStatus(False, fehler=f"'ollama serve' gestartet, aber nach {timeout_s:.0f} s nicht erreichbar")


def lokales_modell(modell: str | None) -> str:
    """Ein brauchbarer Ollama-Tag: Claude-IDs (nach dem Umschalten noch gespeichert) oder
    Leeres fallen auf den Default zurück."""
    m = (modell or "").strip()
    if not m or m.lower().startswith("claude"):
        return DEFAULT_OLLAMA_MODELL
    return m


# --- Dienst -----------------------------------------------------------------------------------


class OllamaKi:
    """Ein Chat-Aufruf je Auftrag gegen ``/api/chat`` mit Schema-Zwang."""

    backend = BACKEND_OLLAMA

    def __init__(
        self,
        modell: str,
        *,
        url: str = DEFAULT_URL,
        keep_alive: str = "30m",
        log: Callable[[str], None] | None = None,
        post: PostFn = _http_json,
    ) -> None:
        self.modell = lokales_modell(modell)
        self.url = url.rstrip("/")
        self.keep_alive = keep_alive
        self._log = log or (lambda msg: None)
        self._post = post

    def anfrage(self, auftrag: KiAuftrag) -> dict:
        """Der Rumpf des Aufrufs - getrennt, damit Tests ihn prüfen können."""
        return {
            "model": self.modell,
            "messages": [
                {"role": "system", "content": auftrag.system},
                {"role": "user", "content": auftrag.prompt},
            ],
            "stream": False,
            "format": auftrag.schema,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
        }

    def antworte(self, auftrag: KiAuftrag) -> KiAntwort:
        t0 = time.monotonic()
        try:
            ergebnis = self._post(f"{self.url}/api/chat", self.anfrage(auftrag), auftrag.timeout_s)
        except _HttpFehler as exc:
            if exc.code == 404:
                raise KiFehler(f"Lokales Modell {self.modell} nicht vorhanden - 'ollama pull {self.modell}'") from exc
            if exc.code is None and exc.text == "Zeitüberschreitung":
                raise KiFehler(f"KI-Aufruf nach {auftrag.timeout_s:.0f} s abgebrochen") from exc
            if exc.code is None:
                raise KiFehler(f"Lokale KI nicht erreichbar unter {self.url} - 'ollama serve'") from exc
            raise KiFehler(f"Lokale KI meldet HTTP {exc.code}: {exc.text}") from exc
        except KiFehler:
            raise
        except Exception as exc:  # noqa: BLE001 - jede weitere Ausnahme wird zum KiFehler
            raise KiFehler(f"KI-Aufruf gescheitert: {type(exc).__name__}: {exc}") from exc
        antwort_s = time.monotonic() - t0

        nachricht = ergebnis.get("message") if isinstance(ergebnis, dict) else None
        inhalt = nachricht.get("content") if isinstance(nachricht, dict) else None
        if not isinstance(inhalt, str) or not inhalt.strip():
            grund = ergebnis.get("done_reason") if isinstance(ergebnis, dict) else None
            raise KiFehler(f"KI-Antwort leer{f' ({grund})' if grund else ''}")
        try:
            daten = json.loads(inhalt)
        except json.JSONDecodeError as exc:
            raise KiFehler("KI-Antwort ist kein gültiges JSON") from exc
        pflicht = auftrag.schema.get("required", []) if isinstance(auftrag.schema, dict) else []
        if not isinstance(daten, dict) or any(k not in daten for k in pflicht):
            raise KiFehler("KI-Antwort ohne gültige Struktur")

        ein = int(ergebnis.get("prompt_eval_count") or 0)
        aus = int(ergebnis.get("eval_count") or 0)
        laden_s = float(ergebnis.get("load_duration") or 0) / 1e9
        self._log(
            f"[KI lokal] {self.modell}: {ein} Tokens ein, {aus} aus, {antwort_s:.1f} s"
            + (f" (davon Modell laden {laden_s:.1f} s)" if laden_s >= 0.5 else "")
        )
        return KiAntwort(
            daten=daten, start_s=round(laden_s, 3), antwort_s=antwort_s, modell=self.modell,
            session_id=None, verbrauch=None,
        )
