"""Aufnahmen ohne Projekt (PRD §21): der Eingangsordner und das Zuordnen zu einem Projekt.

"Sofort aufnehmen" legt Live-Sitzungen in einen Eingangsordner. Von dort wandern sie später
in den Sitzungsordner eines Projekts - verschoben, nicht kopiert. Der Ordnername bleibt
(``live-YYYY-MM-DD_HH-MM-SS``), nur bei einer Kollision kommt ``-2``, ``-3`` … dazu.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from audioscribe.projekt.modell import Projekt, ProjektFehler
from audioscribe.projekt.wiki_ablage import _freier_name

ORDNERNAME = Path("AudioScribe") / "Ohne Projekt"


def standard_dir() -> Path:
    """Vorgabe für den Eingangsordner: im Dokumente-Ordner, sonst im Home."""
    home = Path.home()
    for name in ("Dokumente", "Documents"):
        try:
            if (home / name).is_dir():
                return home / name / ORDNERNAME
        except OSError:
            continue
    return home / ORDNERNAME


def eingang_dir(state: Mapping[str, object]) -> Path:
    """Wohin Aufnahmen ohne Projekt gehen: die Einstellung, sonst die Vorgabe."""
    wert = state.get("eingang_dir")
    if isinstance(wert, str) and wert.strip():
        return Path(wert.strip()).expanduser()
    return standard_dir()


def liste(basis: Path) -> list[dict]:
    """Beendete Sitzungen im Eingangsordner, jüngste zuerst (unterbrochene zeigt das Banner)."""
    from audioscribe.live import journal

    out: list[dict] = []
    try:
        ordner = [p for p in Path(basis).iterdir() if p.is_dir()]
    except OSError:
        return out
    for pfad in ordner:
        status = journal.lies_status(pfad)
        if status is None or status.get("replay") or status.get("status") != journal.BEENDET:
            continue
        bestand = journal.lies_journal(pfad)
        out.append(
            {
                "dir": str(pfad),
                "name": pfad.name,
                "titel": str(status.get("titel") or ""),
                "gestartet": str(status.get("gestartet") or ""),
                "dauer_s": round(bestand.ende_s, 1),
            }
        )
    out.sort(key=lambda s: (s["gestartet"], s["name"]), reverse=True)
    return out


def pruefe_sitzung(sitzung: Path) -> None:
    """Nur eine sauber beendete Sitzung, die kein Prozess mehr hält, lässt sich verschieben."""
    from audioscribe.live import journal

    status = journal.lies_status(sitzung)
    if status is None:
        raise ProjektFehler(f"Kein Sitzungsordner: {sitzung}")
    if journal.lebt(sitzung):
        raise RuntimeError("Die Sitzung läuft noch.")
    if status.get("status") != journal.BEENDET:
        raise RuntimeError("Die Sitzung ist nicht beendet – bitte erst abschließen.")


def verschiebe(sitzung: Path, projekt: Projekt) -> Path:
    """Sitzung in den Sitzungsordner des Projekts verschieben; liefert den neuen Ordner.

    Scheitert das Verschieben über Laufwerksgrenzen hinweg mittendrin, wird die halbe Kopie
    entfernt - die Quelle bleibt dann unangetastet.
    """
    sitzung = Path(sitzung)
    pruefe_sitzung(sitzung)
    ziel_basis = projekt.sitzungen_dir
    ziel_basis.mkdir(parents=True, exist_ok=True)
    try:
        if sitzung.resolve().parent == ziel_basis.resolve():
            raise ProjektFehler("Die Sitzung liegt schon im Sitzungsordner dieses Projekts.")
    except OSError as exc:
        raise ProjektFehler(str(exc)) from exc
    ziel = ziel_basis / _freier_name(sitzung.name, ziel_basis)
    alt = sitzung.resolve()
    try:
        os.rename(sitzung, ziel)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # Anderes Laufwerk: erst vollständig kopieren, dann die Quelle löschen.
        try:
            shutil.copytree(sitzung, ziel)
        except OSError:
            shutil.rmtree(ziel, ignore_errors=True)
            raise
        shutil.rmtree(sitzung, ignore_errors=True)
    _quelle_umschreiben(ziel, alt)
    return ziel


def _quelle_umschreiben(ordner: Path, alt: Path) -> None:
    """``source_path`` in den Transkripten ist absolut - auf den neuen Ordner umbiegen."""
    neu = ordner.resolve()
    for datei in ordner.glob("transcript*.json"):
        try:
            data = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        quelle = data.get("source_path") if isinstance(data, dict) else None
        if not isinstance(quelle, str):
            continue
        try:
            rel = Path(quelle).relative_to(alt)
        except ValueError:
            continue
        data["source_path"] = str(neu / rel)
        tmp = datei.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, datei)
