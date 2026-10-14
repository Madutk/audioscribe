"""Verknüpfung „Sofort aufnehmen“ (PRD §21): ``audioscribe ui --aufnahme`` startet die Oberfläche
im Modus „Aufnahme ohne Projekt“ und beginnt die Aufnahme sofort - mit den Geräten und
Einstellungen, die beim letzten Start gemerkt wurden.

Hier steht die reine Logik ohne FastAPI: die Übersetzung des gemerkten Stands in die
Startparameter und der Weg zu einem schon laufenden Server (zweiter Doppelklick).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Mapping

from audioscribe.config import settings

# Adresse der Live-Ansicht ohne Projekt (ui/static/js/kontext.js: HOME.aufnahme).
ROUTE_AUFNAHME = "#/aufnahme"


def _geraet(saved: Mapping[str, object], key: str, inventar: Mapping[str, object], liste: str) -> tuple[str, str]:
    """Gemerkter Gerätename -> (Index als Text | "default" | "none", Name). Ein nicht mehr
    vorhandenes Gerät wird zu "default", der Name bleibt - damit der nächste Start ihn weiter
    vorschlägt, statt ihn mit "default" zu überschreiben."""
    wert = str(saved.get(key) or "default")
    if wert in ("default", "none"):
        return wert, ""
    for d in inventar.get(liste) or []:
        if isinstance(d, Mapping) and d.get("name") == wert:
            return str(d["index"]), wert
    return "default", wert


def _bildquelle(saved: Mapping[str, object], inventar: Mapping[str, object]) -> tuple[int, int, str]:
    """(monitor, window, window_label) wie ``pickLiveSource`` in live.js: Fenster über
    „Prozess – Titel“ (ersatzweise nur den Prozess), sonst Monitor; ein Fenster, das es nicht
    mehr gibt, wird zum Monitor. Der Testmodus (Transkript abspielen) startet nie automatisch."""
    quelle = str(saved.get("live_source") or "monitor")
    fenster = [w for w in (inventar.get("windows") or []) if isinstance(w, Mapping)]
    if quelle == "window" and fenster:
        gemerkt = str(saved.get("live_window") or "")
        label = lambda w: f"{w.get('process', '')} – {w.get('title', '')}"
        treffer = next((w for w in fenster if label(w) == gemerkt), None) or next(
            (w for w in fenster if gemerkt.startswith(f"{w.get('process', '')} – ")), None
        )
        if treffer is not None:
            return 0, int(treffer["hwnd"]), label(treffer)
    if quelle == "none":
        return 0, 0, ""
    monitore = [m for m in (inventar.get("monitors") or []) if isinstance(m, Mapping)]
    gemerkt_monitor = str(saved.get("live_monitor") or "1")
    if any(str(m.get("index")) == gemerkt_monitor for m in monitore):
        return int(gemerkt_monitor), 0, ""
    if gemerkt_monitor == "0" or not monitore:
        return 0, 0, ""
    return int(monitore[0]["index"]), 0, ""


def aus_einstellungen(saved: Mapping[str, object], inventar: Mapping[str, object], *, sprache: str) -> dict:
    """Startparameter (Felder von ``LiveStartIn``) aus dem gemerkten Stand und der
    Bestandsaufnahme der Geräte (``live.kommando.inventory``)."""
    mic, mic_name = _geraet(saved, "live_mic", inventar, "mics")
    loopback, loopback_name = _geraet(saved, "live_loopback", inventar, "loopbacks")
    monitor, window, window_label = _bildquelle(saved, inventar)
    return {
        "output_dir": "",  # im Modus „aufnahme“ bestimmt der Server den Eingangsordner
        "titel": "",
        "resume": "",
        "replay_transcript": "",
        "monitor": monitor,
        "window": window,
        "window_label": window_label,
        "mic": mic,
        "loopback": loopback,
        "mic_name": mic_name,
        "loopback_name": loopback_name,
        "model": str(saved.get("live_model") or "auto"),
        "language": sprache,
        "device": str(saved.get("live_device") or settings.device),
        "sensitivity": str(saved.get("live_sensitivity") or settings.screen_sensitivity),
        "format": str(saved.get("live_format") or settings.screen_format),
        "partials": bool(saved.get("live_partials", True)),
        "speakers": bool(saved.get("live_speakers", True)),
        "refine": bool(saved.get("live_refine", True)),
        "refine_model": str(saved.get("live_refine_model") or settings.whisper_model),
    }


# --- Zweiter Doppelklick: ein Server läuft schon ---------------------------------------------


def _url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"


def server_antwortet(host: str, port: int, timeout_s: float = 1.0) -> bool:
    """Läuft unter dieser Adresse schon AudioScribe? Nur eine JSON-Antwort mit ``modus`` zählt -
    ein fremder Dienst auf dem Port gilt als „niemand da“ (dann scheitert der Start wie bisher)."""
    try:
        with urllib.request.urlopen(_url(host, port) + "api/kontext", timeout=timeout_s) as antwort:
            daten = json.loads(antwort.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return isinstance(daten, dict) and "modus" in daten


def an_laufenden_server(host: str, port: int, *, open_browser: bool = True, timeout_s: float = 30.0) -> bool:
    """Bittet einen laufenden Server, sofort aufzunehmen, und öffnet den Browser dort.
    ``False``, wenn kein Server antwortet - dann startet der Aufrufer selbst einen."""
    if not server_antwortet(host, port):
        return False
    url = _url(host, port)
    anfrage = urllib.request.Request(
        url + "api/aufnahme/sofort", data=b"{}", method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        # Die Antwort dauert, solange die Geräte ermittelt werden.
        with urllib.request.urlopen(anfrage, timeout=timeout_s):
            pass
        print(f"AudioScribe laeuft bereits auf {url} - Aufnahme gestartet.")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
        except (ValueError, AttributeError):
            detail = ""
        print(f"AudioScribe laeuft bereits auf {url} - Aufnahme nicht gestartet: {detail or exc}", file=sys.stderr)
    except (urllib.error.URLError, OSError) as exc:
        print(f"AudioScribe laeuft bereits auf {url} - keine Antwort: {exc}", file=sys.stderr)
    if open_browser:
        try:
            webbrowser.open(url + ROUTE_AUFNAHME)
        except Exception:  # noqa: BLE001
            pass
    return True
