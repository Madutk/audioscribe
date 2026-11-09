"""Warteschlange „Ins Wiki einarbeiten“: Aufträge für ``audioscribe ingest`` im Hintergrund.

* **Ein Auftrag zur Zeit**, in der Reihenfolge des Einreihens - die Läufe teilen sich das
  Claude-Abo und dürfen nicht gleichzeitig in dasselbe Wiki schreiben.
* **Unabhängig vom geöffneten Projekt**: ein Auftrag kennt seinen Wiki-Ordner selbst; Projekt
  wechseln oder neu anlegen hält ihn nicht an.
* **Auf der Platte** (``<config_dir>/wiki-einarbeitung/``): ``auftraege.json`` plus je Auftrag
  ein Ordner mit ``protokoll.txt`` (alles, was die Oberfläche zeigt) und ``analyse.json``
  (Session-ID, Status des Agenten). Nach einem Neustart wird ein Auftrag, der lief oder auf
  eine Antwort wartete, in derselben Claude-Sitzung fortgesetzt.
* **Rückfragen**: Der Lauf meldet ``[Agent-Frage] {json}``; der Auftrag steht dann auf
  ``frage``, bis die Oberfläche antwortet (``antworte``) - die Antwort geht über stdin ins Kind.
* **Nachfassen**: Nach dem Lauf reiht ``nachricht`` eine Folgenachricht in dieselbe Sitzung ein.

Reine Standardbibliothek plus ``ui.jobs``/``ui.runner`` - das Agentenpaket wird nur im Kind
geladen (Variante cloud-compliant).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from audioscribe.i18n import tr
from audioscribe.ui.jobs import child_env, cli_prefix
from audioscribe.verbrauch import QUELLE_WIKI, Verbrauch, Zaehler

WARTET = "wartet"
LAEUFT = "laeuft"
FRAGE = "frage"
FERTIG = "fertig"
FEHLER = "fehler"
ABGEBROCHEN = "abgebrochen"
STATUS: tuple[str, ...] = (WARTET, LAEUFT, FRAGE, FERTIG, FEHLER, ABGEBROCHEN)
OFFEN: frozenset[str] = frozenset({WARTET, LAEUFT, FRAGE})

# Was der nächste Lauf eines Auftrags tut.
ART_NEU = "neu"
ART_FORTSETZEN = "fortsetzen"
ART_NACHRICHT = "nachricht"

LISTE = "auftraege.json"
PROTOKOLL = "protokoll.txt"
_FRAGE_PREFIX = "[Agent-Frage] "  # = agent.einarbeitung.FRAGE_PREFIX (hier ohne Agent-Import)
_STATUS_PREFIX = "[Agent-Status] "  # = agent.fortschritt.STATUS_PREFIX
_MAX_ZEILEN = 20000  # Obergrenze je Abruf (die Datei selbst bleibt vollständig)


def _jetzt() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Eintrag:
    id: str
    wiki_dir: str
    rohquelle: str  # relativ zur Wiki-Wurzel (POSIX)
    seiten_dir: str | None = None
    assets: str | None = None
    projekt: str = ""  # Name des Projekts beim Einreihen (nur Anzeige)
    titel: str = ""
    modell: str | None = None
    dienst: str = "claude-agent"
    status: str = WARTET
    art: str = ART_NEU  # nächster bzw. laufender Lauf
    nachricht: str = ""  # Text einer Folgenachricht (art == nachricht)
    eingereiht: str = ""
    gestartet: str | None = None
    beendet: str | None = None
    session_id: str | None = None
    frage: dict | None = None  # offene Rückfrage {"id", "questions"}
    quellseite: str | None = None  # Wiki-Seite mit "rohquelle: …" nach dem Lauf
    fehler: str | None = None
    hinweis: str | None = None  # z. B. "nach Neustart fortgesetzt"
    verbrauch: dict | None = None  # letzter Lauf
    laeufe: int = 0
    pid: int | None = None

    @classmethod
    def aus_dict(cls, data: dict) -> Eintrag | None:
        bekannt = {f.name for f in fields(cls)}
        try:
            e = cls(**{k: v for k, v in data.items() if k in bekannt})
        except TypeError:
            return None
        return e if e.status in STATUS else None


def build_ingest_argv(e: Eintrag, ordner: Path, *, prefix: Sequence[str] | None = None) -> list[str]:
    """Der ``audioscribe ingest``-Aufruf für den nächsten Lauf des Auftrags."""
    argv = list(prefix if prefix is not None else cli_prefix())
    argv += [
        "ingest",
        f"--wiki={e.wiki_dir}",
        f"--rohquelle={e.rohquelle}",
        f"--arbeitsordner={ordner}",
        "--fragen",
    ]
    if e.seiten_dir:
        argv.append(f"--seiten={e.seiten_dir}")
    if e.assets:
        argv.append(f"--assets={e.assets}")
    if e.modell:
        argv.append(f"--model={e.modell}")
    if e.dienst and e.dienst != "claude-agent":
        argv.append(f"--ki-dienst={e.dienst}")
    if e.art == ART_FORTSETZEN:
        argv.append("--fortsetzen")
    elif e.art == ART_NACHRICHT:
        argv.append(f"--nachricht={e.nachricht}")
    return argv


def _lebt(pid: int | None, auftrag_id: str) -> bool:
    """Läuft der Agent dieses Auftrags noch (Server abgestürzt, Kind übrig)? Nur ein Prozess,
    dessen Kommandozeile den Arbeitsordner des Auftrags nennt - nach einem Neustart des
    Rechners kann die Nummer längst einem fremden Prozess gehören."""
    if not pid or os.name == "nt":
        return False
    try:
        os.kill(pid, 0)
        ausgabe = subprocess.run(  # noqa: S603, S607 - festes Kommando
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "ingest" in ausgabe and auftrag_id in ausgabe


class Warteschlange:
    """Die Aufträge und der eine Arbeiter-Thread, der sie nacheinander ausführt."""

    def __init__(
        self,
        basis: Path,
        *,
        zaehler: Zaehler | None = None,
        argv_builder: Callable[[Eintrag, Path], list[str]] = build_ingest_argv,
        quellseite: Callable[[Eintrag], str | None] | None = None,
        starten: bool = True,
    ) -> None:
        self.basis = Path(basis)
        self._zaehler = zaehler
        self._argv = argv_builder
        self._quellseite = quellseite or _quellseite_suchen
        self._lock = threading.Lock()
        self._wecker = threading.Condition(self._lock)
        self._auftraege: list[Eintrag] = []
        self._fortschritt: dict[str, dict] = {}  # id -> letzter [Agent-Status]
        self._proc: subprocess.Popen[str] | None = None
        self._aktiv: str | None = None
        self._abbruch: set[str] = set()
        self._ende = False
        self._thread: threading.Thread | None = None
        self._laden()
        if starten:
            self.starte()

    # --- Persistenz -------------------------------------------------------------------------

    def ordner(self, auftrag_id: str) -> Path:
        return self.basis / auftrag_id

    def _laden(self) -> None:
        try:
            data = json.loads((self.basis / LISTE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        for item in data if isinstance(data, list) else []:
            e = Eintrag.aus_dict(item) if isinstance(item, dict) else None
            if e is None:
                continue
            if e.status in (LAEUFT, FRAGE):
                # Das Programm endete mitten im Lauf (Neustart, Absturz): fortsetzen.
                if _lebt(e.pid, e.id):
                    _beende_pid(e.pid)
                e.status = WARTET
                if e.art != ART_NACHRICHT:
                    e.art = ART_FORTSETZEN
                e.frage = None
                e.hinweis = tr("Unterbrochen (Programm beendet) – wird fortgesetzt.")
                self._protokoll(e.id, "\n" + tr("— Unterbrochen: AudioScribe wurde beendet. Der Lauf wird fortgesetzt."))
            e.pid = None
            self._auftraege.append(e)
        self._speichern()

    def _speichern(self) -> None:
        """Aufrufer hält den Lock (oder ist der Konstruktor)."""
        try:
            self.basis.mkdir(parents=True, exist_ok=True)
            ziel = self.basis / LISTE
            tmp = ziel.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(e) for e in self._auftraege], ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, ziel)
        except OSError:
            pass  # die Warteschlange läuft im Speicher weiter; beim nächsten Schreiben neu versuchen

    def _protokoll(self, auftrag_id: str, zeile: str) -> None:
        try:
            ordner = self.ordner(auftrag_id)
            ordner.mkdir(parents=True, exist_ok=True)
            with (ordner / PROTOKOLL).open("a", encoding="utf-8") as f:
                f.write(zeile.rstrip("\n") + "\n")
        except OSError:
            pass

    def _zeilen(self, auftrag_id: str, offset: int) -> tuple[list[str], int]:
        try:
            alle = (self.ordner(auftrag_id) / PROTOKOLL).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return [], 0
        start = max(0, min(offset, len(alle)))
        return alle[start : start + _MAX_ZEILEN], min(len(alle), start + _MAX_ZEILEN)

    # --- Abfragen ----------------------------------------------------------------------------

    def _finde(self, auftrag_id: str) -> Eintrag:
        for e in self._auftraege:
            if e.id == auftrag_id:
                return e
        raise KeyError(auftrag_id)

    def eintrag(self, auftrag_id: str) -> dict:
        with self._lock:
            return asdict(self._finde(auftrag_id))

    def uebersicht(self) -> dict:
        with self._lock:
            liste = [asdict(e) for e in self._auftraege]
            fortschritt = dict(self._fortschritt)
        zaehler = {s: 0 for s in STATUS}
        for e in liste:
            zaehler[e["status"]] += 1
            e.pop("pid", None)
            p = fortschritt.get(e["id"])
            e["fortschritt"] = _kurzfortschritt(p) if p else None
        # Neueste zuerst für die Liste; die Reihenfolge der Abarbeitung steht in "position".
        wartend = [e["id"] for e in liste if e["status"] == WARTET]
        for e in liste:
            e["position"] = wartend.index(e["id"]) + 1 if e["id"] in wartend else None
        return {"auftraege": list(reversed(liste)), "zaehler": zaehler}

    def detail(self, auftrag_id: str, offset: int = 0) -> dict:
        with self._lock:
            e = asdict(self._finde(auftrag_id))
            fortschritt = self._fortschritt.get(auftrag_id)
        e.pop("pid", None)
        zeilen, neu = self._zeilen(auftrag_id, offset)
        return {**e, "fortschritt": fortschritt, "offset": neu, "lines": zeilen}

    def aktiv_fuer_wiki(self, wiki_dir: Path) -> bool:
        """Läuft oder wartet ein Auftrag auf diesem Wiki?"""
        ziel = _norm(wiki_dir)
        with self._lock:
            return any(e.status in OFFEN and _norm(e.wiki_dir) == ziel for e in self._auftraege)

    def offen_fuer(self, wiki_dir: Path, rohquelle: str) -> dict | None:
        ziel = _norm(wiki_dir)
        with self._lock:
            for e in self._auftraege:
                if e.status in OFFEN and _norm(e.wiki_dir) == ziel and e.rohquelle == rohquelle:
                    return asdict(e)
        return None

    def letzter_fuer(self, wiki_dir: Path, rohquelle: str) -> dict | None:
        """Der jüngste Auftrag zu dieser Rohquelle (für die Karten nach der Aufnahme)."""
        ziel = _norm(wiki_dir)
        with self._lock:
            for e in reversed(self._auftraege):
                if _norm(e.wiki_dir) == ziel and e.rohquelle == rohquelle:
                    d = asdict(e)
                    d.pop("pid", None)
                    return d
        return None

    # --- Aktionen ----------------------------------------------------------------------------

    def einreihen(
        self,
        *,
        wiki_dir: Path,
        rohquelle: str,
        seiten_dir: Path | None = None,
        assets: Path | None = None,
        projekt: str = "",
        titel: str = "",
        modell: str | None = None,
        dienst: str = "claude-agent",
    ) -> dict:
        """Neuen Auftrag anhängen - oder den offenen zur selben Rohquelle zurückgeben."""
        rohquelle = rohquelle.strip().strip("/")
        if offen := self.offen_fuer(wiki_dir, rohquelle):
            return offen
        e = Eintrag(
            id=datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
            wiki_dir=str(wiki_dir),
            rohquelle=rohquelle,
            seiten_dir=str(seiten_dir) if seiten_dir is not None else None,
            assets=str(assets) if assets is not None else None,
            projekt=projekt,
            titel=titel,
            modell=modell,
            dienst=dienst,
            eingereiht=_jetzt(),
        )
        self._protokoll(e.id, tr("Eingereiht: {quelle} → {wiki}", quelle=rohquelle, wiki=wiki_dir))
        with self._wecker:
            self._auftraege.append(e)
            self._speichern()
            self._wecker.notify_all()
            return asdict(e)

    def antworte(self, auftrag_id: str, frage_id: str, antworten: dict[str, str] | None) -> None:
        """Antwort auf die offene Rückfrage an den laufenden Agenten geben; ``None`` = ablehnen."""
        with self._lock:
            e = self._finde(auftrag_id)
            if e.status != FRAGE or not e.frage or e.frage.get("id") != frage_id:
                raise RuntimeError(tr("Diese Frage ist nicht mehr offen."))
            proc = self._proc if self._aktiv == auftrag_id else None
            if proc is None or proc.stdin is None or proc.poll() is not None:
                raise RuntimeError(tr("Der Lauf ist nicht mehr aktiv."))
            daten = {"id": frage_id, "answers": antworten} if antworten is not None else {"id": frage_id, "ablehnen": True}
            try:
                proc.stdin.write(json.dumps(daten, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except OSError as exc:
                raise RuntimeError(tr("Antwort nicht übermittelt: {fehler}", fehler=exc)) from exc
            e.status = LAEUFT
            e.frage = None
            self._speichern()

    def nachricht(self, auftrag_id: str, text: str) -> dict:
        """Folgenachricht in dieselbe Sitzung einreihen (nach dem Lauf)."""
        text = text.strip()
        if not text:
            raise ValueError(tr("Bitte eine Nachricht eingeben."))
        with self._wecker:
            e = self._finde(auftrag_id)
            if e.status in OFFEN:
                raise RuntimeError(tr("Der Auftrag läuft noch – nachfassen geht danach."))
            if not e.session_id:
                raise RuntimeError(tr("Zu diesem Auftrag gibt es keine fortsetzbare Sitzung."))
            e.status = WARTET
            e.art = ART_NACHRICHT
            e.nachricht = text
            e.eingereiht = _jetzt()
            e.fehler = e.hinweis = None
            self._speichern()
            self._wecker.notify_all()
            d = asdict(e)
        self._protokoll(auftrag_id, "\n" + tr("[Du] {text}", text=text))
        return d

    def wiederholen(self, auftrag_id: str) -> dict:
        """Fehlgeschlagenen oder abgebrochenen Auftrag erneut einreihen (fortsetzen, wenn möglich)."""
        with self._wecker:
            e = self._finde(auftrag_id)
            if e.status not in (FEHLER, ABGEBROCHEN):
                raise RuntimeError(tr("Nur fehlgeschlagene oder abgebrochene Aufträge lassen sich wiederholen."))
            e.status = WARTET
            e.art = ART_FORTSETZEN if e.session_id else ART_NEU
            e.eingereiht = _jetzt()
            e.fehler = e.hinweis = None
            self._speichern()
            self._wecker.notify_all()
            return asdict(e)

    def abbrechen(self, auftrag_id: str) -> None:
        with self._lock:
            e = self._finde(auftrag_id)
            if e.status == WARTET:
                e.status = ABGEBROCHEN
                e.beendet = _jetzt()
                self._speichern()
                proc = None
            elif e.status in (LAEUFT, FRAGE):
                self._abbruch.add(auftrag_id)
                proc = self._proc if self._aktiv == auftrag_id else None
            else:
                return
        if proc is not None and proc.poll() is None:
            self._protokoll(auftrag_id, tr("Abbruch angefordert – beende den Agenten …"))
            from audioscribe.ui.runner import _terminate

            _terminate(proc)

    def entfernen(self, auftrag_id: str) -> None:
        with self._lock:
            e = self._finde(auftrag_id)
            if e.status in OFFEN:
                raise RuntimeError(tr("Laufende oder wartende Aufträge erst abbrechen."))
            self._auftraege.remove(e)
            self._fortschritt.pop(auftrag_id, None)
            self._speichern()
        _loesche(self.ordner(auftrag_id))

    # --- Arbeiter ----------------------------------------------------------------------------

    def starte(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ende = False
        self._thread = threading.Thread(target=self._arbeite, name="audioscribe-wiki", daemon=True)
        self._thread.start()

    def beende(self) -> None:
        """Beim Herunterfahren: Arbeiter stoppen, laufenden Agenten beenden - der Auftrag bleibt
        als laufend vermerkt und wird beim nächsten Start fortgesetzt."""
        with self._wecker:
            self._ende = True
            proc = self._proc
            self._wecker.notify_all()
        if proc is not None and proc.poll() is None:
            from audioscribe.ui.runner import _terminate

            _terminate(proc)

    def warte_leer(self, timeout: float = 10.0) -> bool:
        """Für Tests: bis kein Auftrag mehr offen ist (oder einer auf eine Antwort wartet)."""
        ende = time.monotonic() + timeout
        while time.monotonic() < ende:
            with self._lock:
                if not any(e.status in (WARTET, LAEUFT) for e in self._auftraege):
                    return True
            time.sleep(0.05)
        return False

    def _naechster(self) -> Eintrag | None:
        wartend = [e for e in self._auftraege if e.status == WARTET]
        return min(wartend, key=lambda e: e.eingereiht) if wartend else None

    def _arbeite(self) -> None:
        while True:
            with self._wecker:
                while not self._ende and self._naechster() is None:
                    self._wecker.wait()
                if self._ende:
                    return
                e = self._naechster()
                assert e is not None
                e.status = LAEUFT
                e.gestartet = _jetzt()
                e.beendet = None
                e.fehler = None
                e.laeufe += 1
                self._aktiv = e.id
                self._speichern()
                argv = self._argv(e, self.ordner(e.id))
                auftrag_id = e.id
            try:
                self._lauf(auftrag_id, argv)
            except Exception as exc:  # noqa: BLE001 - der Arbeiter darf nie sterben
                self._protokoll(auftrag_id, tr("Interner Fehler: {fehler}", fehler=exc))
                with self._lock:
                    try:
                        x = self._finde(auftrag_id)
                    except KeyError:
                        continue
                    x.status, x.fehler, x.beendet = FEHLER, str(exc), _jetzt()
                    self._aktiv = None
                    self._speichern()

    def _lauf(self, auftrag_id: str, argv: list[str]) -> None:
        if self._zaehler is not None:
            self._zaehler.beginne(QUELLE_WIKI)
        self._protokoll(auftrag_id, "")
        try:
            proc = subprocess.Popen(  # noqa: S603 - Kommando aus build_ingest_argv
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=child_env(),
                start_new_session=True,
            )
        except OSError as exc:
            self._protokoll(auftrag_id, tr("Prozessstart fehlgeschlagen: {fehler}", fehler=exc))
            self._abschluss(auftrag_id, -1)
            return
        with self._lock:
            self._proc = proc
            self._finde(auftrag_id).pid = proc.pid
            self._speichern()
            # Abbruch kam, während der Prozess startete: gleich beenden.
            sofort_beenden = auftrag_id in self._abbruch or self._ende
        if sofort_beenden:
            from audioscribe.ui.runner import _terminate

            _terminate(proc)
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.startswith(_STATUS_PREFIX):
                try:
                    progress = json.loads(line[len(_STATUS_PREFIX):])
                except ValueError:
                    progress = None
                if isinstance(progress, dict):
                    with self._lock:
                        self._fortschritt[auftrag_id] = progress
                    if self._zaehler is not None and progress.get("verbrauch"):
                        self._zaehler.setze(QUELLE_WIKI, Verbrauch.aus_dict(progress["verbrauch"]))
                continue
            if line.startswith(_FRAGE_PREFIX):
                try:
                    frage = json.loads(line[len(_FRAGE_PREFIX):])
                except ValueError:
                    frage = None
                if isinstance(frage, dict) and isinstance(frage.get("id"), str):
                    with self._lock:
                        e = self._finde(auftrag_id)
                        e.status = FRAGE
                        e.frage = {"id": frage["id"], "questions": frage.get("questions") or []}
                        self._speichern()
                continue
            self._protokoll(auftrag_id, line)
        code = proc.wait()
        self._abschluss(auftrag_id, code)

    def _abschluss(self, auftrag_id: str, code: int) -> None:
        manifest = _lies_manifest(self.ordner(auftrag_id))
        with self._lock:
            ende = self._ende
            self._proc = None
            self._aktiv = None
            try:
                e = self._finde(auftrag_id)
            except KeyError:
                return
            if ende and auftrag_id not in self._abbruch:
                # Herunterfahren: als laufend vermerkt lassen - der nächste Start setzt fort.
                return
            abgebrochen = auftrag_id in self._abbruch
            self._abbruch.discard(auftrag_id)
            e.pid = None
            e.frage = None
            e.beendet = _jetzt()
            if manifest.get("session_id"):
                e.session_id = manifest["session_id"]
            p = self._fortschritt.get(auftrag_id) or {}
            e.verbrauch = p.get("verbrauch")
            if abgebrochen:
                e.status = ABGEBROCHEN
            elif code == 0:
                e.status = FERTIG
            else:
                e.status = FEHLER
                e.fehler = manifest.get("fehler") or tr("Exit-Code {code}", code=code)
            kopie = Eintrag(**asdict(e))
            self._speichern()
        if kopie.status == FERTIG:
            seite = self._quellseite(kopie)
            with self._lock:
                e.quellseite = seite
                if seite is None and kopie.art != ART_NACHRICHT:
                    e.hinweis = tr("Keine Quellseite mit „rohquelle: {quelle}“ gefunden – bitte das Protokoll prüfen.", quelle=kopie.rohquelle)
                self._speichern()
        meldung = {
            FERTIG: tr("Einarbeiten fertig."),
            FEHLER: tr("Einarbeiten mit Fehler beendet (Exit-Code {code}).", code=code),
            ABGEBROCHEN: tr("Einarbeiten abgebrochen."),
        }[kopie.status]
        self._protokoll(auftrag_id, "\n" + meldung)
        with self._wecker:
            self._wecker.notify_all()


def _kurzfortschritt(p: dict) -> dict:
    return {k: p.get(k) for k in ("done", "total", "current", "skill", "verbrauch")}


def _quellseite_suchen(e: Eintrag) -> str | None:
    from audioscribe.agent.einarbeitung import quellseite

    seite = quellseite(Path(e.wiki_dir), e.rohquelle, Path(e.seiten_dir) if e.seiten_dir else None)
    return str(seite) if seite is not None else None


def _lies_manifest(ordner: Path) -> dict:
    try:
        data = json.loads((ordner / "analyse.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _norm(pfad: str | Path) -> str:
    try:
        return str(Path(pfad).expanduser().resolve())
    except OSError:
        return str(pfad)


def _beende_pid(pid: int | None) -> None:
    import signal

    if not pid:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def _loesche(ordner: Path) -> None:
    import shutil

    shutil.rmtree(ordner, ignore_errors=True)


__all__ = [
    "ABGEBROCHEN", "ART_FORTSETZEN", "ART_NACHRICHT", "ART_NEU", "FEHLER", "FERTIG", "FRAGE",
    "LAEUFT", "OFFEN", "WARTET", "Eintrag", "Warteschlange", "build_ingest_argv",
]
