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
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path

from audioscribe.i18n import tr
from audioscribe.models import format_timecode
from audioscribe.souffleur import bildtext as bt
from audioscribe.souffleur import essenz as essenz_modul
from audioscribe.souffleur import leitfaden as lf_modul
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
_BILD_PROMPT_MAX = 600  # Zeichen Bildtext je Standbild im Prompt
_BILD_SUCHE_MAX = 300  # davon in die Wiki-Suche
_BILD_NACHLAUF_S = 5.0  # ein Bild kurz nach dem Fenster gehört noch dazu


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
        leitfaden: lf_modul.Leitfaden | None = None,
        erkenne: Callable[[Path], str] | None = None,
    ) -> None:
        self.konfig = konfig
        # Vorbereitung des Moderators (leitfaden.py) - Checkliste, kein Wissen.
        self._leitfaden = leitfaden
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
        self._wiki_laedt = False  # erstes Laden: bis dahin wird nicht beurteilt (sonst ohne Belege)
        self._wiki_wechselt = False  # Wechsel mitten in der Sitzung: nur Anzeige, der alte Index gilt weiter
        self._wiki_gen = 0  # Generation des Ladevorgangs - der letzte Wechsel gewinnt
        self._ki_aufrufe = 0
        self._ki_fehler = 0
        self._fehler_folge = 0
        self._pause_bis = 0.0
        self._ki_meldung = ""
        self._gestartet = False
        self._beendet = False
        self._worker: threading.Thread | None = None
        self._wecker = threading.Event()
        # Standbilder (bildtext.py): Texterkennung im eigenen Thread, Ergebnis als B1, B2, ...
        self._erkenne = erkenne or bt.erkenne
        self._bilder: list[bt.Bild] = []
        self._bilder_gezeigt: set[str] = set()  # schon einmal im Prompt gewesen
        self._bild_q: queue.Queue = queue.Queue()
        self._bild_worker: threading.Thread | None = None
        self._lf_gekappt_gemeldet = False  # Hinweis "Leitfaden zu lang" nur einmal je Sitzung
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
        with self._lock:
            pfad = self.konfig.wiki_dir
            self._wiki_gen += 1
            gen = self._wiki_gen
        if pfad is not None:
            self._wiki_laedt = True
            threading.Thread(target=self._lade_wiki, args=(gen, pfad), name="souffleur-wiki", daemon=True).start()
        else:
            self._log(f"Souffleur: {self._wiki_status.meldung}")
        self._worker = threading.Thread(target=self._arbeite, name="souffleur", daemon=True)
        self._worker.start()

    def _uebernehme_stand(self) -> None:
        """Wiederaufnahme (PRD §21): liegt im Sitzungsordner schon ein Stand, werden seine
        Markierungen übernommen und erneut gemeldet. Ohne das überschriebe der Abschluss die
        Hinweise der unterbrochenen Sitzung."""
        if self.session_dir is not None:
            bilder = bt.lade(self.session_dir)
            if bilder:
                with self._lock:
                    self._bilder = bilder
                    self._bilder_gezeigt = {b.id for b in bilder}
            lf = lf_modul.lade_stand(self.session_dir)
            if lf is not None:
                with self._lock:
                    self._leitfaden = lf
                self._log(tr("Souffleur: Leitfaden der unterbrochenen Sitzung übernommen ({n} Punkte)", n=len(lf.punkte)))
            elif self._leitfaden is not None:
                self._schreibe_leitfaden()
        stand = mk.lade(self.session_dir) if self.session_dir is not None else None
        if stand is None or not stand.markierungen:
            return
        with self._lock:
            self._markierungen = list(stand.markierungen)
            self._ki_aufrufe = int(stand.bilanz.get("ki_aufrufe") or 0)
            self._ki_fehler = int(stand.bilanz.get("ki_fehler") or 0)
            self._fenster_id = int(stand.bilanz.get("fenster") or 0)
        self._log(tr("Souffleur: {anzahl} Markierungen der unterbrochenen Sitzung übernommen", anzahl=len(stand.markierungen)))
        for m in stand.markierungen:
            self.on_hinweis(m.als_dict())

    def _lade_wiki(self, gen: int, pfad: Path) -> None:
        """Index laden; das Ergebnis zählt nur, wenn inzwischen kein neuerer Wechsel kam."""
        t0 = time.monotonic()
        try:
            index = wiki_modul.WikiIndex.laden(pfad)
            with self._lock:
                if gen != self._wiki_gen:
                    return
                self._wiki, self._wiki_status = index, index.status
            self._verknuepfe_leitfaden(index)
            dauer = f"{time.monotonic() - t0:.1f}"
            if gen > 1:
                self._log(tr("Souffleur: Wiki gewechselt in {dauer} s - {meldung}", dauer=dauer, meldung=index.status.meldung))
            else:
                self._log(tr("Souffleur: Wiki geladen in {dauer} s - {meldung}", dauer=dauer, meldung=index.status.meldung))
            for w in index.status.warnungen:
                self._log(tr("Souffleur: Wiki-Warnung: {warnung}", warnung=w))
        except Exception:  # noqa: BLE001 - jeder Fehler wird zum Zustand, nie zum Absturz
            status = wiki_modul.pruefe_wiki(pfad)
            with self._lock:
                if gen != self._wiki_gen:
                    return
                self._wiki, self._wiki_status = None, status
            self._log(tr("Souffleur: Wiki nicht nutzbar - {meldung}", meldung=status.meldung))
        finally:
            with self._lock:
                if gen == self._wiki_gen:
                    self._wiki_laedt = False
                    self._wiki_wechselt = False
            self._wecker.set()

    def wechsle_wiki(self, pfad: Path | None) -> None:
        """Wiki wechseln oder lösen - auch mitten in der Sitzung. Der bisherige Index gilt weiter,
        bis der neue steht; der Status zeigt derweil „laedt“. Vor dem Start wird nur die
        Konfiguration gesetzt (``starte`` lädt dann), nach dem Ende passiert nichts mehr."""
        with self._lock:
            self.konfig = replace(self.konfig, wiki_dir=Path(pfad) if pfad is not None else None)
            if not self._gestartet or self._beendet:
                return
            self._wiki_gen += 1
            gen = self._wiki_gen
            if pfad is None:
                self._wiki, self._wiki_status = None, wiki_modul.status_keins()
                self._wiki_laedt = self._wiki_wechselt = False
                self._log(tr("Souffleur: Wiki gelöst - weiter ohne Belege"))
                self._wecker.set()
            else:
                self._wiki_wechselt = True
        if pfad is None:
            self._verknuepfe_leitfaden(None)
            return
        threading.Thread(target=self._lade_wiki, args=(gen, Path(pfad)), name="souffleur-wiki", daemon=True).start()

    def abschliessen(self) -> None:
        """Rest beurteilen, Begleitdateien schreiben, Thread beenden."""
        with self._lock:
            if self._beendet:
                return
            bild_worker = self._bild_worker
        if bild_worker is not None:
            self._bild_q.put(None)
            bild_worker.join(timeout=15.0)  # angefangene Bilder noch lesen - sie gehen ins letzte Fenster
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
        self._bild_q.put(None)
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

    def beobachte_bild(self, shot: dict) -> None:
        """Ein Standbild aus dem Live-Prozess (Felder des ``shot``-Ereignisses: id, t, file, kind).
        Die Texterkennung läuft im eigenen Thread; das Fenster wartet nicht darauf."""
        if not self.konfig.bildtext or not shot.get("file"):
            return
        with self._lock:
            if self._beendet or any(b.datei == shot["file"] for b in self._bilder):
                return
            if self._bild_worker is None:
                self._bild_worker = threading.Thread(target=self._lies_bilder, name="souffleur-bildtext", daemon=True)
                self._bild_worker.start()
        self._bild_q.put(dict(shot))

    def _lies_bilder(self) -> None:
        while True:
            shot = self._bild_q.get()
            if shot is None:
                return
            with self._lock:
                ziel = self.session_dir
            if ziel is None:
                continue
            try:
                text = self._erkenne(ziel / "frames" / str(shot["file"]))
            except Exception:  # noqa: BLE001 - ein Bild darf den Souffleur nicht stören
                text = ""
            with self._lock:
                if any(b.datei == shot["file"] for b in self._bilder):
                    continue
                bild = bt.Bild(id=f"B{len(self._bilder) + 1}", mark_id=int(shot.get("id") or 0),
                               t=float(shot.get("t") or 0.0), datei=str(shot["file"]), kind=str(shot.get("kind") or ""),
                               text=text)
                self._bilder.append(bild)
                if shot.get("restored"):
                    self._bilder_gezeigt.add(bild.id)
                bilder = list(self._bilder)
            try:
                bt.schreibe(ziel, bilder)
            except OSError as exc:
                self._log(tr("Souffleur: Begleitdatei nicht schreibbar: {fehler}", fehler=exc))
            if text.strip():
                self._log(tr("Souffleur: Bild {bild} gelesen ({n} Zeichen)", bild=bild.id, n=len(text)))
            self._wecker.set()

    def _bilder_fuer(self, von: float, bis: float) -> tuple[list[bt.Bild], bool]:
        """Bilder fürs Fenster: neue (noch nie im Prompt) bis kurz nach dem Fensterende, dazu
        bereits gezeigte aus dem Kontextzeitraum - die jüngsten ``bilder_im_prompt``. Aufruf unter Lock.
        Zweiter Wert: ob ein neues dabei ist."""
        kandidaten = [
            b for b in self._bilder
            if b.text.strip() and b.t <= bis + _BILD_NACHLAUF_S
            and (b.id not in self._bilder_gezeigt or b.t >= von - self.konfig.kontext_s)
        ][-max(0, self.konfig.bilder_im_prompt):] if self.konfig.bilder_im_prompt > 0 else []
        neu = any(b.id not in self._bilder_gezeigt for b in kandidaten)
        self._bilder_gezeigt.update(b.id for b in kandidaten)
        return kandidaten, neu

    def setze_aktiv(self, aktiv: bool) -> None:
        with self._lock:
            self._aktiv = bool(aktiv)
            if not aktiv:
                self._fenster.clear()
        self._log(tr("Souffleur: eingeschaltet") if aktiv else tr("Souffleur: ausgeschaltet"))

    # --- Fensterung und Abgleich ------------------------------------------------------

    def _arbeite(self) -> None:
        while True:
            self._wecker.wait(_TICK_S)
            self._wecker.clear()
            with self._lock:
                beendet = self._beendet
            if not beendet:
                self._pruefe_anstoesse()
            fenster = self._naechstes_fenster(final=beendet)
            if fenster:
                try:
                    self._verarbeite(fenster)
                except Exception as exc:  # noqa: BLE001 - ein Fenster darf den Souffleur nicht beenden
                    self._log(tr("Souffleur: Fenster übersprungen: {fehler}", fehler=exc))
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
        text = " ".join(str(s["text"]) for s in fenster)
        with self._lock:
            self._fenster_id += 1
            fenster_id = self._fenster_id
            wiki = self._wiki
            alle = list(self._segmente)
            lf = self._leitfaden
            lf_wiki = lf.wiki_im_gespraech(text) if lf is not None and wiki is not None else {}
            lf_begriffe = lf.suchbegriffe() if lf is not None else []
            lf_punkte = [{"id": p.id, "text": p.text, "status": p.status} for p in lf.offene()] if lf is not None else []
            bilder, bild_neu = self._bilder_fuer(float(fenster[0]["start"]), float(fenster[-1]["end"]))
        mit_lf = bool(lf_punkte)
        mit_bildern = bool(bilder)
        bilder_prompt = [{"id": b.id, "t": b.t, "kind": b.kind, "text": b.text[:_BILD_PROMPT_MAX]} for b in bilder]
        t_verarbeitung = self.uhr.jetzt()
        diag: dict = {
            "fenster_id": fenster_id, "t_von": float(fenster[0]["start"]), "t_bis": float(fenster[-1]["end"]),
            "segment_ids": [int(s["id"]) for s in fenster], "t_verarbeitung": t_verarbeitung,
            **({"bilder": [b.id for b in bilder]} if bilder else {}),
        }
        # Vorfilter gegen Smalltalk-Fetzen - eine Frage ist aber immer einen Aufruf wert, und
        # solange ein Leitfaden-Punkt angesprochen ist, auch eine kurze Zusage ("machen wir so").
        schwebend = any(p["status"] == lf_modul.ANGESPROCHEN for p in lf_punkte)
        if "?" not in text and not schwebend and not bild_neu and _inhaltswoerter(text) < _MIN_INHALTSWOERTER:
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
            # Angesprochene Leitfaden-Punkte schärfen die Suche (Wiki-Kennungen wie ENT-003).
            # Neue Bildtexte gehen mit in die Suche - was gezeigt wird, kann im Wiki stehen.
            bild_suche = [b.text[:_BILD_SUCHE_MAX] for b in bilder]
            fundstellen = wiki.suche(" ".join([text, *lf_begriffe, *bild_suche]), top_k=self.konfig.top_k)
            # Was das Wiki zu den Punkten im Gespräch festhält, gehört dazu - sonst kann die KI
            # ein Ergebnis nicht gegen das Wiki halten (Abweichung).
            vorhanden = {(f.datei, f.zeile) for f in fundstellen}
            for eintraege in lf_wiki.values():
                for w in eintraege:
                    schluessel = (str(w.get("datei")), int(w.get("zeile") or 0))
                    if schluessel not in vorhanden and (f := wiki.abschnitt(*schluessel)) is not None:
                        fundstellen.append(f)
                        vorhanden.add(schluessel)
            suche_s = time.monotonic() - t0
            glossar = wiki.glossar.eintraege
        fmit = prompt_modul.fundstellen_mit_ids(fundstellen)
        f_id = {(f.datei, f.zeile): fmit[i]["id"] for i, f in enumerate(fundstellen)}
        wiki_ids = {pid: [f_id[k] for w in ws if (k := (str(w.get("datei")), int(w.get("zeile") or 0))) in f_id]
                    for pid, ws in lf_wiki.items()}
        lf_text, ausgelassen = "", 0
        if lf is not None and mit_lf:
            with self._lock:
                lf_text, ausgelassen = lf_modul.prompt_abschnitt_mit_rest(
                    lf, englisch=prompt_modul.sprache() == "en", wiki_ids=wiki_ids, vorrang=lf.im_fenster(text))
        if ausgelassen and not self._lf_gekappt_gemeldet:
            self._lf_gekappt_gemeldet = True
            self._log(tr("Souffleur: Leitfaden zu lang für ein Fenster – je Fenster gehen die passendsten offenen "
                         "Punkte mit, diesmal ohne {n}", n=ausgelassen))
        if ausgelassen:
            diag["leitfaden_ausgelassen"] = ausgelassen
        auftrag = KiAuftrag(
            system=prompt_modul.system_prompt(mit_leitfaden=mit_lf, mit_bildern=mit_bildern),
            prompt=prompt_modul.baue_prompt(
                fenster, kontext=kontext, fundstellen=fmit, glossar=glossar, wiki_verknuepft=wiki is not None,
                leitfaden=lf_text if mit_lf else "", bilder=bilder_prompt,
            ),
            schema=prompt_modul.schema(mit_leitfaden=mit_lf, mit_bildern=mit_bildern),
            kontext={"art": "abgleich", "segmente": fenster, "fundstellen": fmit, "glossar": glossar,
                     **({"leitfaden": lf_punkte} if mit_lf else {}),
                     **({"bilder": bilder_prompt} if mit_bildern else {})},
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
                    self._ki_meldung = tr(
                        "KI-Fehler ({anzahl} in Folge), Pause {pause} s: {fehler}",
                        anzahl=self._fehler_folge, pause=f"{_FEHLER_PAUSE_S:.0f}", fehler=exc,
                    )
            self._log(f"Souffleur: {self._ki_meldung}")
            self._diagnose({**diag, "treffer": len(fundstellen), "suche_s": round(suche_s, 3), "fehler": str(exc)})
            return
        with self._lock:
            self._ki_aufrufe += 1
            self._fehler_folge = 0
            self._ki_meldung = ""

        je_id = {int(s["id"]): s for s in fenster}
        fund_je_id = {f["id"]: (f, fundstellen[i]) for i, f in enumerate(fmit)}
        bild_je_id = {b.id: b for b in bilder}
        neue: list[mk.Markierung] = []
        verworfen: list[dict] = []
        for befund in antwort.daten.get("befunde", []):
            m = self._pruefe_befund(befund, je_id, fund_je_id, bild_je_id)
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
        punkte_neu, punkte_verworfen = (
            self._uebernehme_punkte(antwort.daten.get("punkte") or [], je_id, bild_je_id, fund_je_id) if mit_lf else ([], []))
        for m in neue:
            start = tr(", Start {start} s", start=f"{m.ki_start_s:.1f}") if m.ki_start_s else ""
            self._log(tr(
                "Souffleur: {art} bei {t} s (Hinweis nach {verzoegerung} s, KI {ki} s{start})",
                art=mk.art_label(m.art), t=f"{m.t_start:.0f}", verzoegerung=f"{m.verzoegerung_s or 0:.1f}",
                ki=f"{m.ki_antwort_s or 0:.1f}", start=start,
            ))
            try:
                self.on_hinweis(m.als_dict())
            except Exception as exc:  # noqa: BLE001
                self._log(tr("Souffleur: Hinweis nicht zugestellt: {fehler}", fehler=exc))
        self._diagnose({
            **diag, "treffer": len(fundstellen), "suche_s": round(suche_s, 3),
            "ki_start_s": round(antwort.start_s, 3), "ki_antwort_s": round(antwort.antwort_s, 3),
            "befunde": len(antwort.daten.get("befunde", [])), "markiert": [m.id for m in neue], "verworfen": verworfen,
            "uebergangen": antwort.daten.get("uebergangen", []),
            **({"leitfaden": punkte_neu, "leitfaden_verworfen": punkte_verworfen} if mit_lf else {}),
            **({"verbrauch": antwort.verbrauch.als_dict()} if antwort.verbrauch is not None else {}),
        })
        if neue:
            self._schreibe_stand()
        elif punkte_neu:
            self._schreibe_leitfaden()

    # --- Leitfaden (Meeting-Vorbereitung) ------------------------------------------------

    def _uebernehme_punkte(self, roh: list, je_id: dict[int, dict], bild_je_id: dict[str, bt.Bild] | None = None,
                           fund_je_id: dict | None = None) -> tuple[list[dict], list[dict]]:
        """Leitfaden-Meldungen der KI prüfen wie Befunde: der Punkt muss existieren, die Aussage
        wörtlich im genannten Segment stehen - oder, als Beleg vom Bildschirm, wörtlich im Text des
        genannten Standbilds. Erst dann ändert sich der Status."""
        neu: list[dict] = []
        verworfen: list[dict] = []
        bild_je_id = bild_je_id or {}
        for eintrag in roh:
            if not isinstance(eintrag, dict):
                continue
            pid = str(eintrag.get("punkt_id") or "")
            status = str(eintrag.get("status") or "")
            aussage = str(eintrag.get("aussage") or "").strip()
            try:
                segment_id: int | None = int(eintrag.get("segment_id"))
            except (TypeError, ValueError):
                segment_id = None
            seg = je_id.get(segment_id) if segment_id is not None else None
            bild = bild_je_id.get(str(eintrag.get("bild_id") or ""))
            beleg_bild: dict | None = None
            if seg is not None and aussage and _norm(aussage) in _norm(str(seg["text"])):
                t = float(seg["start"])
            elif bild is not None and aussage and _norm(aussage) in _norm(bild.text):
                seg, segment_id, t = None, None, bild.t
                beleg_bild = {"id": bild.id, "t": bild.t, "datei": bild.datei}
            else:
                grund = "ungueltig" if segment_id is None and bild is None else "ohne_beleg"
                verworfen.append({"punkt_id": pid, "grund": grund})
                continue
            # Abweichung vom Wiki: nur mit wörtlichem Satz aus genau dem gelieferten Auszug.
            abweichung: dict | None = None
            abw_id = str(eintrag.get("abweichung_fundstelle_id") or "")
            abw_zitat = str(eintrag.get("abweichung_zitat") or "").strip()
            if abw_id:
                treffer = (fund_je_id or {}).get(abw_id)
                if treffer is not None and abw_zitat and _norm(abw_zitat) in _norm(treffer[0]["auszug"]):
                    f = treffer[1]
                    abweichung = {"datei": f.datei, "ueberschrift": f.ueberschrift, "zeile": f.zeile, "zitat": abw_zitat}
                else:
                    verworfen.append({"punkt_id": pid, "grund": "abweichung_ohne_beleg"})
            with self._lock:
                lf = self._leitfaden
                if lf is None or lf.punkt(pid) is None:
                    verworfen.append({"punkt_id": pid, "grund": "unbekannt"})
                    continue
                vorher = lf.punkt(pid).status
                geaendert = lf.melde_ki(pid, status, segment_id=segment_id, aussage=aussage,
                                        stand=str(eintrag.get("stand") or ""), t=t, bild=beleg_bild,
                                        abweichung=abweichung)
            if not geaendert:
                verworfen.append({"punkt_id": pid, "grund": "unveraendert"})
                continue
            neu.append({"punkt_id": pid, "status": status, "segment_id": segment_id,
                        **({"bild_id": beleg_bild["id"]} if beleg_bild else {}),
                        **({"abweichung": abw_id} if abweichung else {})})
            if abweichung:
                self._log(tr("Souffleur: Leitfaden {punkt} weicht vom Wiki ab ({fundstelle})", punkt=pid,
                             fundstelle=f"{abweichung['datei']} › {abweichung['ueberschrift']}"))
            if status != vorher:
                wort = tr("geklärt") if status == lf_modul.GEKLAERT else tr("angesprochen")
                if beleg_bild:
                    self._log(tr("Souffleur: Leitfaden {punkt} {status} vom Bildschirm ({bild}, {t} s)",
                                 punkt=pid, status=wort, bild=beleg_bild["id"], t=f"{t:.0f}"))
                else:
                    self._log(tr("Souffleur: Leitfaden {punkt} {status} bei {t} s", punkt=pid, status=wort, t=f"{t:.0f}"))
        return neu, verworfen

    def _pruefe_anstoesse(self) -> None:
        """Angesprochen, aber nicht geklärt - und das Gespräch ist weitergezogen: einmal anstoßen."""
        jetzt = self.uhr.jetzt()
        with self._lock:
            lf = self._leitfaden
            if lf is None or jetzt is None or not self._aktiv:
                return
            faellig = lf.faellige_anstoesse(jetzt, self.konfig.leitfaden_anstoss_s)
            if not faellig:
                return
            je_id = {int(s["id"]): s for s in self._segmente}
        neue = []
        for p in faellig:
            seg = je_id.get(p.segment_id) if p.segment_id is not None else None
            t = float(seg["start"]) if seg else float(p.t_zuletzt or jetzt)
            m = mk.Markierung(
                id=0, art=mk.ART_ANKNUEPFEN, segment_id=int(p.segment_id or 0), t_start=t,
                t_end=float(seg["end"]) if seg else t, sprecher=seg.get("speaker") if seg else None,
                aussage=p.aussage, ki_text=p.stand, punkt_id=p.id, punkt_text=p.text,
                t_hinweis=round(jetzt, 2), bild=dict(p.bild) if p.bild else None,
            )
            with self._lock:
                m.id = len(self._markierungen) + 1
                self._markierungen.append(m)
            neue.append(m)
        for m in neue:
            self._log(tr("Souffleur: anknüpfen an {punkt} – angesprochen bei {t} s, nicht geklärt", punkt=m.punkt_id, t=f"{m.t_start:.0f}"))
            try:
                self.on_hinweis(m.als_dict())
            except Exception as exc:  # noqa: BLE001
                self._log(tr("Souffleur: Hinweis nicht zugestellt: {fehler}", fehler=exc))
        self._schreibe_stand()

    def _verknuepfe_leitfaden(self, index: wiki_modul.WikiIndex | None) -> None:
        """Was das Wiki zu den Punkten festhält - nach jedem Laden, Wechseln oder Lösen des Wikis."""
        with self._lock:
            lf = self._leitfaden
            if lf is None:
                return
            n = lf_modul.verknuepfe_wiki(lf, index)
        if index is not None:
            self._log(tr("Souffleur: Leitfaden – {n} von {gesamt} Punkten mit Wiki-Bezug", n=n, gesamt=len(lf.punkte)))
        self._schreibe_leitfaden()

    def ergaenze_punkt(self, hinweis_id: int) -> dict:
        """Einen Hinweis (offener Punkt, Frage ohne Antwort) als Leitfaden-Punkt übernehmen - ohne
        Vorbereitung entsteht dabei ein Leitfaden. ``KeyError``, wenn es den Hinweis nicht gibt."""
        with self._lock:
            m = next((m for m in self._markierungen if m.id == hinweis_id), None)
            if m is None:
                raise KeyError(hinweis_id)
            if self._leitfaden is None:
                self._leitfaden = lf_modul.Leitfaden(punkte=[], titel=lf_modul.ERGAENZT)
            notiz = tr("Aufgekommen um {zeit} ({art})", zeit=format_timecode(m.t_start), art=mk.art_label(m.art))
            p = self._leitfaden.ergaenze(m.aussage, herkunft=f"hinweis:{m.id}", segment_id=m.segment_id or None,
                                         aussage=m.aussage, t=m.t_start, notiz=notiz)
            if self._wiki is not None and not p.wiki:
                p.wiki = lf_modul.wiki_zu_punkt(p, self._wiki)
            daten = self._leitfaden.als_dict()
        self._log(tr("Souffleur: Hinweis als Leitfaden-Punkt {punkt} übernommen", punkt=p.id))
        self._schreibe_leitfaden()
        return daten

    def leitfaden(self) -> dict | None:
        with self._lock:
            return self._leitfaden.als_dict() if self._leitfaden is not None else None

    def setze_punkt(self, punkt_id: str, status: str) -> dict:
        """Der Moderator setzt einen Punkt von Hand (offen | angesprochen | geklaert | vertagt)."""
        with self._lock:
            if self._leitfaden is None:
                raise KeyError(punkt_id)
            self._leitfaden.setze(punkt_id, status)
            daten = self._leitfaden.als_dict()
        self._schreibe_leitfaden()
        return daten

    def _schreibe_leitfaden(self) -> None:
        with self._lock:
            ziel, lf = self.session_dir, self._leitfaden
            if ziel is None or lf is None:
                return
            try:
                lf_modul.schreibe(ziel, lf)
            except OSError as exc:
                self._log(tr("Souffleur: Begleitdatei nicht schreibbar: {fehler}", fehler=exc))

    def _pruefe_befund(self, befund: dict, je_id: dict[int, dict], fund_je_id: dict,
                       bild_je_id: dict[str, bt.Bild] | None = None) -> mk.Markierung | None:
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
        # Antwort vom Bildschirm: nur mit wörtlichem Zitat aus genau diesem Bildtext.
        beleg_bild: dict | None = None
        bild = (bild_je_id or {}).get(str(befund.get("bild_id") or ""))
        bild_zitat = str(befund.get("bild_zitat") or "").strip()
        if art == mk.ART_FRAGE and bild is not None and bild_zitat and _norm(bild_zitat) in _norm(bild.text):
            beleg_bild = {"id": bild.id, "t": bild.t, "datei": bild.datei, "zitat": bild_zitat}
        ohne_befund = art == mk.ART_FRAGE and not fundstellen and beleg_bild is None
        if ohne_befund:
            ki_text = ""  # weder Wiki noch Bildschirm: dann kein KI-Ersatztext (Leitplanke 7)
        return mk.Markierung(
            id=0, art=art, segment_id=segment_id, t_start=float(seg["start"]), t_end=float(seg["end"]),
            sprecher=seg.get("speaker"), aussage=aussage, fundstellen=fundstellen, wiki_zitat=zitat,
            ki_text=ki_text, ohne_befund=ohne_befund or (art == mk.ART_OFFEN and not fundstellen),
            sicherheit=sicherheit, bild=beleg_bild,
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
        self._log(tr("Souffleur: Essenz {fenster} erzeugt ({dauer} s, KI)", fenster=ergebnis.fenster, dauer=f"{ergebnis.ki_s:.1f}"))
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
            self._log(tr("Souffleur: Begleitdatei nicht schreibbar: {fehler}", fehler=exc))
        self._schreibe_leitfaden()

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
                "wiki": self._wiki_status.als_dict() if not (self._wiki_laedt or self._wiki_wechselt) else {
                    **self._wiki_status.als_dict(), "zustand": "laedt",
                    "meldung": tr("Wiki wird gewechselt …") if self._wiki_wechselt else tr("Wiki wird gelesen …")},
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
                "leitfaden": self._leitfaden.als_dict() if self._leitfaden is not None else None,
                "uhr": self.uhr.jetzt(),
            }

    def status_text(self) -> str:
        s = self.status()
        if not s["aktiv"]:
            return tr("Souffleur pausiert")
        if s["wiki"]["zustand"] != wiki_modul.ZUSTAND_OK:
            return tr("Souffleur ohne Wiki – nur Fragen und Essenz")
        return tr("Souffleur läuft")

    def __getstate__(self):  # Sicherheit gegen versehentliches Pickling der Threads
        raise TypeError("Souffleur ist nicht serialisierbar")

    @staticmethod
    def markierung_als_dict(m: mk.Markierung) -> dict:
        return {**asdict(m), "label": mk.art_label(m.art)}
