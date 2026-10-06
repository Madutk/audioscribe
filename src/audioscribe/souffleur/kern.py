"""Der Souffleur: hört die Segmente der Live-Sitzung mit und liefert dem Moderator Hinweise.

Läuft im Server-Prozess (ein Objekt je Sitzung, von ``ui.runner.LiveRunner`` gefüttert).
Nach außen gehen Markierungen über ``on_hinweis`` (als ``hinweis``-Ereignis an den Browser).

Ablauf je Fenster (A1–A3, B1, B2): Segmente werden gesammelt, bis das Fenster voll ist
(Sprechzeit, Anzahl oder Leerlauf). Dann sucht der Souffleur lokal im Wiki, ruft die KI
EINMAL mit Fenster, Kontext, Auszügen und Glossar und prüft die Befunde lokal nach:
Aussage muss im Segment stehen, Zitat im gelieferten Auszug, ein Widerspruch braucht ein
Zitat. Erst dann wird markiert. Verzögerungen werden je Hinweis gemessen.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from audioscribe.souffleur import essenz as essenz_modul
from audioscribe.souffleur import markierung as mk
from audioscribe.souffleur import prompt as prompt_modul
from audioscribe.souffleur import wiki as wiki_modul
from audioscribe.souffleur.ki import KiAuftrag, KiDienst, KiFehler, KiStatus
from audioscribe.souffleur.konfig import SouffleurKonfig
from audioscribe.souffleur.uhr import SitzungsUhr

Log = Callable[[str], None]

DIAGNOSE_DATEI = "souffleur-diagnose.jsonl"
_TICK_S = 0.25
_MIN_INHALTSWOERTER = 4
_FEHLER_PAUSE_S = 60.0
_FEHLER_FOLGE_MAX = 3
_DEDUP_FENSTER_S = 180.0
_DEDUP_AEHNLICH = 0.6


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _inhaltswoerter(text: str) -> int:
    return len(wiki_modul.tokenisiere(text))


class Souffleur:
    def __init__(
        self,
        konfig: SouffleurKonfig,
        *,
        ki: KiDienst | None,
        ki_status: KiStatus,
        on_hinweis: Callable[[dict], None] | None = None,
        log: Log | None = None,
    ) -> None:
        self.konfig = konfig
        self.ki = ki
        self.ki_status = ki_status
        self.on_hinweis: Callable[[dict], None] = on_hinweis or (lambda h: None)
        self._log = log or (lambda m: None)
        self.uhr = SitzungsUhr(konfig.speed)
        self._lock = threading.RLock()
        self._segmente: list[dict] = []  # Felder des segment-Ereignisses + "empfangen_mono"
        self._fenster: list[dict] = []  # noch nicht beurteilte Segmente
        self._fenster_id = 0
        self._markierungen: list[mk.Markierung] = []
        self._essenzen: list[essenz_modul.Essenz] = []
        self._aktiv = konfig.aktiv
        self.session_dir: Path | None = None
        self._wiki: wiki_modul.WikiIndex | None = None
        self._wiki_status = wiki_modul.status_keins()
        self._wiki_laedt = False
        self._ki_aufrufe = 0
        self._ki_fehler = 0
        self._fehler_folge = 0
        self._pause_bis = 0.0
        self._ki_meldung = ""
        self._gestartet = False
        self._beendet = False
        self._worker: threading.Thread | None = None
        self._wecker = threading.Event()
        self._letzte_verzoegerung: float | None = None

    # --- Lebenszyklus --------------------------------------------------------------

    def starte(self, session_dir: Path) -> None:
        with self._lock:
            if self._gestartet:
                return
            self._gestartet = True
            self.session_dir = Path(session_dir)
        self._uebernehme_stand()
        self._log(f"Souffleur: {self.ki_status.meldung}")
        if self.konfig.wiki_dir is not None:
            self._wiki_laedt = True
            threading.Thread(target=self._lade_wiki, name="souffleur-wiki", daemon=True).start()
        else:
            self._log(f"Souffleur: {self._wiki_status.meldung}")
        self._worker = threading.Thread(target=self._arbeite, name="souffleur", daemon=True)
        self._worker.start()

    def _uebernehme_stand(self) -> None:
        """Wiederaufnahme (PRD §21): liegt im Sitzungsordner schon ein Stand, werden seine
        Markierungen übernommen und erneut gemeldet. Ohne das überschriebe der Abschluss die
        Hinweise der unterbrochenen Sitzung."""
        stand = mk.lade(self.session_dir) if self.session_dir is not None else None
        if stand is None or not stand.markierungen:
            return
        with self._lock:
            self._markierungen = list(stand.markierungen)
            self._ki_aufrufe = int(stand.bilanz.get("ki_aufrufe") or 0)
            self._ki_fehler = int(stand.bilanz.get("ki_fehler") or 0)
            self._fenster_id = int(stand.bilanz.get("fenster") or 0)
        self._log(f"Souffleur: {len(stand.markierungen)} Markierungen der unterbrochenen Sitzung übernommen")
        for m in stand.markierungen:
            self.on_hinweis(m.als_dict())

    def _lade_wiki(self) -> None:
        t0 = time.monotonic()
        try:
            index = wiki_modul.WikiIndex.laden(self.konfig.wiki_dir)
            with self._lock:
                self._wiki, self._wiki_status = index, index.status
            self._log(f"Souffleur: Wiki geladen in {time.monotonic() - t0:.1f} s - {index.status.meldung}")
            for w in index.status.warnungen:
                self._log(f"Souffleur: Wiki-Warnung: {w}")
        except Exception:  # noqa: BLE001 - jeder Fehler wird zum Zustand, nie zum Absturz
            status = wiki_modul.pruefe_wiki(self.konfig.wiki_dir)
            with self._lock:
                self._wiki, self._wiki_status = None, status
            self._log(f"Souffleur: Wiki nicht nutzbar - {status.meldung}")
        finally:
            self._wiki_laedt = False
            self._wecker.set()

    def abschliessen(self) -> None:
        """Rest beurteilen, Begleitdateien schreiben, Thread beenden."""
        with self._lock:
            if self._beendet:
                return
            self._beendet = True
        self._wecker.set()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=self.konfig.ki_timeout_s + 10)
        self._schreibe_stand()

    def stop(self) -> None:
        """Harter Abbruch (Reset): keine Spätresultate mehr nach außen, nicht lange warten."""
        self.on_hinweis = lambda h: None
        with self._lock:
            self._beendet = True
            self._fenster.clear()
        self._wecker.set()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=1.0)

    # --- Eingang --------------------------------------------------------------------

    def uhr_sync(self, elapsed: float) -> None:
        self.uhr.sync(elapsed)

    def beobachte(self, segment: dict, *, empfangen_mono: float | None = None) -> None:
        """Ein fertiges Segment aus dem Live-Prozess (Felder des ``segment``-Ereignisses)."""
        if not str(segment.get("text", "")).strip():
            return
        eintrag = {**segment, "empfangen_mono": empfangen_mono if empfangen_mono is not None else time.monotonic()}
        with self._lock:
            self._segmente.append(eintrag)
            self._segmente.sort(key=lambda s: (float(s["start"]), int(s.get("id", 0))))
            if self._aktiv and not self._beendet:
                self._fenster.append(eintrag)
        jetzt = self.uhr.jetzt()
        if jetzt is None or jetzt < float(segment["end"]):
            self.uhr.sync(float(segment["end"]) + float(segment.get("delay") or 0.0))
        self._wecker.set()

    def uebernehme(self, segment: dict) -> None:
        """Ein wiederhergestelltes Segment (Wiederaufnahme): nur Kontext für Abgleich und Essenz -
        es wird nicht erneut beurteilt und stellt die Uhr nicht."""
        if not str(segment.get("text", "")).strip():
            return
        with self._lock:
            self._segmente.append({**segment, "empfangen_mono": None})
            self._segmente.sort(key=lambda s: (float(s["start"]), int(s.get("id", 0))))

    def setze_aktiv(self, aktiv: bool) -> None:
        with self._lock:
            self._aktiv = bool(aktiv)
            if not aktiv:
                self._fenster.clear()
        self._log(f"Souffleur: {'eingeschaltet' if aktiv else 'ausgeschaltet'}")

    # --- Fensterung und Abgleich ------------------------------------------------------

    def _arbeite(self) -> None:
        while True:
            self._wecker.wait(_TICK_S)
            self._wecker.clear()
            with self._lock:
                beendet = self._beendet
            fenster = self._naechstes_fenster(final=beendet)
            if fenster:
                try:
                    self._verarbeite(fenster)
                except Exception as exc:  # noqa: BLE001 - ein Fenster darf den Souffleur nicht beenden
                    self._log(f"Souffleur: Fenster übersprungen: {exc}")
                    self._diagnose({"fenster_id": self._fenster_id, "fehler": str(exc)})
                continue
            if beendet:
                return

    def _naechstes_fenster(self, *, final: bool) -> list[dict]:
        k = self.konfig
        with self._lock:
            if not self._fenster:
                return []
            if self._wiki_laedt and not final:
                return []  # erst mit Wiki beurteilen - sonst liefe der Anfang ohne Belege
            erstes, letztes = self._fenster[0], self._fenster[-1]
            sprechzeit = float(letztes["end"]) - float(erstes["start"])
            jetzt = self.uhr.jetzt() or float(letztes["end"])
            leerlauf = jetzt - float(letztes["end"])
            voll = len(self._fenster) >= k.fenster_max_segmente or sprechzeit >= k.fenster_max_s
            if not (final or voll or leerlauf >= k.fenster_leerlauf_s):
                return []
            # Nie mehr als ein volles Fenster je Aufruf: die KI darf nur wenige Befunde melden,
            # ein überfülltes Fenster verschluckt sonst Fragen. Bei Rückstand folgen die
            # Fenster einfach dicht aufeinander.
            n = min(len(self._fenster), k.fenster_max_segmente)
            fenster, self._fenster = self._fenster[:n], self._fenster[n:]
            return fenster

    def _verarbeite(self, fenster: list[dict]) -> None:
        with self._lock:
            self._fenster_id += 1
            fenster_id = self._fenster_id
            wiki = self._wiki
            alle = list(self._segmente)
        t_verarbeitung = self.uhr.jetzt()
        diag: dict = {
            "fenster_id": fenster_id, "t_von": float(fenster[0]["start"]), "t_bis": float(fenster[-1]["end"]),
            "segment_ids": [int(s["id"]) for s in fenster], "t_verarbeitung": t_verarbeitung,
        }
        text = " ".join(str(s["text"]) for s in fenster)
        # Vorfilter gegen Smalltalk-Fetzen - eine Frage ist aber immer einen Aufruf wert.
        if "?" not in text and _inhaltswoerter(text) < _MIN_INHALTSWOERTER:
            self._diagnose({**diag, "uebergangen": "zu_kurz"})
            return
        if self.ki is None:
            self._diagnose({**diag, "uebergangen": "keine_ki"})
            return
        if time.monotonic() < self._pause_bis:
            self._diagnose({**diag, "uebergangen": "ki_pause"})
            return

        von = float(fenster[0]["start"])
        kontext = [s for s in alle if von - self.konfig.kontext_s <= float(s["start"]) < von]
        fundstellen: list[mk.Fundstelle] = []
        suche_s = 0.0
        glossar: list[tuple[str, str]] = []
        if wiki is not None:
            t0 = time.monotonic()
            fundstellen = wiki.suche(text, top_k=self.konfig.top_k)
            suche_s = time.monotonic() - t0
            glossar = wiki.glossar.eintraege
        fmit = prompt_modul.fundstellen_mit_ids(fundstellen)
        auftrag = KiAuftrag(
            system=prompt_modul.system_prompt(),
            prompt=prompt_modul.baue_prompt(
                fenster, kontext=kontext, fundstellen=fmit, glossar=glossar, wiki_verknuepft=wiki is not None
            ),
            schema=prompt_modul.SCHEMA,
            kontext={"art": "abgleich", "segmente": fenster, "fundstellen": fmit, "glossar": glossar},
            timeout_s=self.konfig.ki_timeout_s,
        )
        try:
            antwort = self.ki.antworte(auftrag)
        except KiFehler as exc:
            with self._lock:
                self._ki_aufrufe += 1
                self._ki_fehler += 1
                self._fehler_folge += 1
                self._ki_meldung = str(exc)
                if self._fehler_folge >= _FEHLER_FOLGE_MAX:
                    self._pause_bis = time.monotonic() + _FEHLER_PAUSE_S
                    self._ki_meldung = f"KI-Fehler ({self._fehler_folge} in Folge), Pause {_FEHLER_PAUSE_S:.0f} s: {exc}"
            self._log(f"Souffleur: {self._ki_meldung}")
            self._diagnose({**diag, "treffer": len(fundstellen), "suche_s": round(suche_s, 3), "fehler": str(exc)})
            return
        with self._lock:
            self._ki_aufrufe += 1
            self._fehler_folge = 0
            self._ki_meldung = ""

        je_id = {int(s["id"]): s for s in fenster}
        fund_je_id = {f["id"]: (f, fundstellen[i]) for i, f in enumerate(fmit)}
        neue: list[mk.Markierung] = []
        verworfen: list[dict] = []
        for befund in antwort.daten.get("befunde", []):
            m = self._pruefe_befund(befund, je_id, fund_je_id)
            if m is None:
                verworfen.append({"segment_id": befund.get("segment_id"), "art": befund.get("art"), "grund": "ungueltig"})
                continue
            if self._ist_dublette(m):
                verworfen.append({"segment_id": m.segment_id, "art": m.art, "grund": "dublette"})
                continue
            self._bemesse(m, je_id[m.segment_id], t_verarbeitung=t_verarbeitung, suche_s=suche_s,
                          ki_start_s=antwort.start_s, ki_antwort_s=antwort.antwort_s, fenster_id=fenster_id)
            with self._lock:
                m.id = len(self._markierungen) + 1
                self._markierungen.append(m)
                self._letzte_verzoegerung = m.verzoegerung_s
            neue.append(m)
        for m in neue:
            self._log(
                f"Souffleur: {mk.ART_LABEL.get(m.art, m.art)} bei {m.t_start:.0f} s "
                f"(Hinweis nach {m.verzoegerung_s or 0:.1f} s, KI {m.ki_antwort_s or 0:.1f} s"
                f"{f', Start {m.ki_start_s:.1f} s' if m.ki_start_s else ''})"
            )
            try:
                self.on_hinweis(m.als_dict())
            except Exception as exc:  # noqa: BLE001
                self._log(f"Souffleur: Hinweis nicht zugestellt: {exc}")
        self._diagnose({
            **diag, "treffer": len(fundstellen), "suche_s": round(suche_s, 3),
            "ki_start_s": round(antwort.start_s, 3), "ki_antwort_s": round(antwort.antwort_s, 3),
            "befunde": len(antwort.daten.get("befunde", [])), "markiert": [m.id for m in neue], "verworfen": verworfen,
            "uebergangen": antwort.daten.get("uebergangen", []),
        })
        if neue:
            self._schreibe_stand()

    def _pruefe_befund(self, befund: dict, je_id: dict[int, dict], fund_je_id: dict) -> mk.Markierung | None:
        """Lokale Validierung: nichts gilt, was nicht im Segment bzw. im gelieferten Auszug steht."""
        if not isinstance(befund, dict):
            return None
        try:
            segment_id = int(befund.get("segment_id"))
        except (TypeError, ValueError):
            return None
        seg = je_id.get(segment_id)
        art = str(befund.get("art", ""))
        if seg is None or art not in mk.ARTEN:
            return None
        aussage = str(befund.get("aussage") or "").strip()
        if not aussage or _norm(aussage) not in _norm(str(seg["text"])):
            return None
        fund_id = befund.get("fundstelle_id")
        fundstellen: list[mk.Fundstelle] = []
        zitat: str | None = None
        if fund_id and fund_id in fund_je_id:
            fdict, fobj = fund_je_id[fund_id]
            fundstellen = [fobj]
            roh = str(befund.get("wiki_zitat") or "").strip()
            if roh and _norm(roh) in _norm(fdict["auszug"]):
                zitat = roh
        if art == mk.ART_WIDERSPRUCH and (not fundstellen or not zitat):
            return None  # Leitplanke 7: kein Widerspruch ohne Beleg
        sicherheit = str(befund.get("sicherheit") or "hoch")
        if sicherheit == "mittel" and not self.konfig.sensibel:
            return None
        ki_text = str(befund.get("ki_text") or "")[:240]
        ohne_befund = art == mk.ART_FRAGE and not fundstellen
        if ohne_befund:
            ki_text = ""  # nichts im Wiki: dann kein KI-Ersatztext (Leitplanke 7)
        return mk.Markierung(
            id=0, art=art, segment_id=segment_id, t_start=float(seg["start"]), t_end=float(seg["end"]),
            sprecher=seg.get("speaker"), aussage=aussage, fundstellen=fundstellen, wiki_zitat=zitat,
            ki_text=ki_text, ohne_befund=ohne_befund or (art == mk.ART_OFFEN and not fundstellen),
            sicherheit=sicherheit,
        )

    def _ist_dublette(self, m: mk.Markierung) -> bool:
        woerter = set(wiki_modul.tokenisiere(m.aussage))
        fund = m.fundstellen[0].kurz if m.fundstellen else ""
        with self._lock:
            alte = list(self._markierungen)
        for alt in alte:
            if alt.art != m.art or abs(alt.t_start - m.t_start) > _DEDUP_FENSTER_S:
                continue
            if (alt.fundstellen[0].kurz if alt.fundstellen else "") != fund:
                continue
            alt_w = set(wiki_modul.tokenisiere(alt.aussage))
            if not woerter or not alt_w:
                continue
            if len(woerter & alt_w) / len(woerter | alt_w) >= _DEDUP_AEHNLICH:
                return True
        return False

    def _bemesse(self, m: mk.Markierung, seg: dict, *, t_verarbeitung: float | None, suche_s: float,
                 ki_start_s: float, ki_antwort_s: float, fenster_id: int) -> None:
        jetzt = self.uhr.jetzt()
        delay = float(seg.get("delay") or 0.0)
        if jetzt is None:
            jetzt = m.t_end + delay + ki_antwort_s * self.konfig.speed
        m.t_hinweis = round(jetzt, 2)
        m.verzoegerung_s = round(max(0.0, jetzt - m.t_end), 2)
        m.anteil_asr_s = round(delay, 2)
        if t_verarbeitung is not None:
            m.anteil_warten_s = round(max(0.0, t_verarbeitung - (m.t_end + delay)), 2)
        m.anteil_suche_s = round(suche_s, 3)
        m.ki_start_s = round(ki_start_s, 2)
        m.ki_antwort_s = round(ki_antwort_s, 2)
        empfangen = seg.get("empfangen_mono")
        if empfangen is not None:
            m.verzoegerung_real_s = round(time.monotonic() - float(empfangen), 2)
        m.fenster_id = fenster_id

    # --- C1 Essenz -----------------------------------------------------------------

    def essenz(self, minuten: int) -> essenz_modul.Essenz:
        """Essenz der letzten ``minuten`` Minuten - synchron, eigener KI-Aufruf."""
        if self.ki is None:
            raise KiFehler(self.ki_status.meldung)
        jetzt = self.uhr.jetzt()
        with self._lock:
            segmente = [dict(s) for s in self._segmente]
        if jetzt is None:
            jetzt = max((float(s["end"]) for s in segmente), default=0.0)
        ergebnis = essenz_modul.erzeuge(self.ki, segmente, jetzt=jetzt, minuten=minuten, timeout_s=self.konfig.essenz_timeout_s)
        with self._lock:
            self._essenzen.append(ergebnis)
            ziel = self.session_dir
        if ziel is not None:
            essenz_modul.anhaengen(ziel, ergebnis)
        self._log(f"Souffleur: Essenz {ergebnis.fenster} erzeugt ({ergebnis.ki_s:.1f} s, KI)")
        return ergebnis

    # --- Ergebnisse -------------------------------------------------------------------

    def markierungen(self) -> list[mk.Markierung]:
        with self._lock:
            return list(self._markierungen)

    def offene_punkte(self) -> list[dict]:
        return [m.als_dict() for m in self.markierungen() if m.ist_offener_punkt]

    def stand(self) -> mk.SouffleurStand:
        with self._lock:
            markierungen = list(self._markierungen)
            sitzung = self.session_dir.name if self.session_dir else ""
            return mk.SouffleurStand(
                sitzung=sitzung, speed=self.konfig.speed, wiki=self._wiki_status.als_dict(),
                ki={"backend": self.ki_status.backend, "modell": self.ki_status.modell, "zustand": self._ki_zustand()},
                markierungen=markierungen,
                bilanz=mk.bilanz(markierungen, ki_aufrufe=self._ki_aufrufe, ki_fehler=self._ki_fehler, fenster=self._fenster_id),
            )

    def _schreibe_stand(self) -> None:
        with self._lock:
            ziel = self.session_dir
        if ziel is None:
            return
        try:
            mk.schreibe(ziel, self.stand())
        except OSError as exc:
            self._log(f"Souffleur: Begleitdatei nicht schreibbar: {exc}")

    def _diagnose(self, zeile: dict) -> None:
        with self._lock:
            ziel = self.session_dir
        if ziel is None:
            return
        try:
            with (ziel / DIAGNOSE_DATEI).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(zeile, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- Zustand --------------------------------------------------------------------

    def _ki_zustand(self) -> str:
        if self.ki is None:
            return "fehlt"
        if time.monotonic() < self._pause_bis:
            return "pause"
        if self._fehler_folge:
            return "fehler"
        return "bereit"

    def status(self) -> dict:
        with self._lock:
            zustand = self._ki_zustand()
            return {
                "aktiv": self._aktiv,
                "beendet": self._beendet,
                "wiki": self._wiki_status.als_dict() if not self._wiki_laedt else {
                    **self._wiki_status.als_dict(), "zustand": "laedt", "meldung": "Wiki wird gelesen …"},
                "ki": {
                    "zustand": zustand,
                    "modell": self.ki_status.modell,
                    "meldung": self._ki_meldung or self.ki_status.meldung,
                    "aufrufe": self._ki_aufrufe,
                    "fehler": self._ki_fehler,
                },
                "segmente": len(self._segmente),
                "hinweise": len(self._markierungen),
                "offene_punkte": sum(1 for m in self._markierungen if m.ist_offener_punkt),
                "rueckstand_segmente": len(self._fenster),
                "letzte_verzoegerung_s": self._letzte_verzoegerung,
                "essenzen": len(self._essenzen),
                "uhr": self.uhr.jetzt(),
            }

    def status_text(self) -> str:
        s = self.status()
        if not s["aktiv"]:
            return "Souffleur pausiert"
        if s["wiki"]["zustand"] != wiki_modul.ZUSTAND_OK:
            return "Souffleur ohne Wiki – nur Fragen und Essenz"
        return "Souffleur läuft"

    def __getstate__(self):  # Sicherheit gegen versehentliches Pickling der Threads
        raise TypeError("Souffleur ist nicht serialisierbar")

    @staticmethod
    def markierung_als_dict(m: mk.Markierung) -> dict:
        return {**asdict(m), "label": mk.ART_LABEL.get(m.art, m.art)}
