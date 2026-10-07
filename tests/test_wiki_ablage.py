"""Wiki-Ablage (PRD §21): Sitzung und Nachbereitung als neue Quelle nach raw/, Bilder in die Assets."""

import filecmp
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from audioscribe.projekt import wiki_ablage


def _seiten(projekt):
    return {p: p.read_bytes() for p in projekt.seiten_dir.rglob("*") if p.is_file()}


def test_sitzung_landet_in_raw_mit_bildern_im_assets_ordner(projekt, sitzung):
    seiten_vorher = _seiten(projekt)
    ablage = wiki_ablage.speichere_sitzung(sitzung, projekt)
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"  # Datum + Sitzungstitel
    assets = projekt.assets_dir / ziel.name
    assert ablage.ordner == str(ziel) and ablage.assets == str(assets) and ablage.bilder == 2
    # Der Wortlaut bleibt unveraendert (byte-gleich).
    assert filecmp.cmp(sitzung / "transkript.md", ziel / "transkript.md", shallow=False)
    assert sorted(p.name for p in assets.iterdir()) == ["0001_00-00-03.jpg", "0002_00-00-12.jpg"]
    assert (assets / "0001_00-00-03.jpg").read_bytes() == (sitzung / "frames" / "0001_00-00-03.jpg").read_bytes()
    # Die Seiten des Wikis werden nie angefasst.
    assert _seiten(projekt) == seiten_vorher
    assert "source_path" not in json.loads((ziel / "transcript.json").read_text(encoding="utf-8"))
    assert "source_path" in json.loads((sitzung / "transcript.json").read_text(encoding="utf-8"))  # Quelle unberuehrt
    assert (ziel / "README.md").is_file()


def test_zuordnung_zeitstempel_zu_bild_bleibt_erhalten(projekt, sitzung):
    ablage = wiki_ablage.speichere_sitzung(sitzung, projekt)
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    marks = json.loads((ziel / "marks.json").read_text(encoding="utf-8"))
    assert [(m["t"], m["id"]) for m in marks] == [(3.0, 1), (12.0, 2)]
    # Jeder Verweis fuehrt relativ von der Ablage zu einer vorhandenen Datei im Assets-Ordner.
    for m in marks:
        assert m["png"].startswith("../assets/") and (ziel / m["png"]).is_file()
    annotiert = (ziel / "transkript.annotiert.md").read_text(encoding="utf-8")
    bild1 = "![Bild #0001 – 00:00:03](../assets/2026-10-06_workshop-reisebuchung/0001_00-00-03.jpg)"
    bild2 = "![Bild #0002 – 00:00:12](../assets/2026-10-06_workshop-reisebuchung/0002_00-00-12.jpg)"
    assert bild1 in annotiert and bild2 in annotiert
    # Bild 1 (00:00:03) haengt am ersten Absatz, Bild 2 (00:00:12) am zweiten - wie im Sitzungsordner.
    assert annotiert.index("zweite Klasse") < annotiert.index(bild1) < annotiert.index("Freigabe?") < annotiert.index(bild2)
    original = (sitzung / "transkript.annotiert.md").read_text(encoding="utf-8")
    assert re.sub(r"\]\([^)]*/", "](", annotiert) == re.sub(r"\]\([^)]*/", "](", original)
    assert ablage.markierungen == 0  # ohne Wunsch gehen die Markierungen nicht mit


def test_markierungen_bleiben_ohne_wunsch_im_sitzungsordner(projekt, sitzung):
    """Markierungen sind KI-erzeugt und zitieren das Wiki - unter raw/ nur auf Wunsch."""
    ablage = wiki_ablage.speichere_sitzung(sitzung, projekt)
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    assert ablage.markierungen == 0 and (ziel / "transkript.md").is_file()
    assert not list(ziel.glob("markierungen.*")) and not list(ziel.glob("souffleur*"))
    assert "markierungen" not in (ziel / "README.md").read_text(encoding="utf-8").lower()
    assert (sitzung / "souffleur.json").is_file()  # im Sitzungsordner bleiben sie


def test_markierungen_des_souffleurs_gehen_auf_wunsch_mit(projekt, sitzung):
    ablage = wiki_ablage.speichere_sitzung(sitzung, projekt, markierungen=True)
    assert ablage.markierungen == 1
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    assert "markierungen.json" in (ziel / "README.md").read_text(encoding="utf-8")
    daten = json.loads((ziel / "markierungen.json").read_text(encoding="utf-8"))
    assert daten["format_version"] == 1 and daten["sitzung"] == sitzung.name
    assert daten["markierungen"][0]["wiki"]["zitat"].startswith("Buchungen ab 250")
    assert "Frage" in (ziel / "markierungen.md").read_text(encoding="utf-8")
    assert not (ziel / "souffleur-essenz.jsonl").exists()  # Essenzen sind keine Quelle


def test_ohne_bilder_entsteht_kein_assets_ordner(projekt, sitzung):
    ablage = wiki_ablage.speichere_sitzung(sitzung, projekt, bilder=False)
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    assert ablage.assets is None and ablage.bilder == 0
    assert not projekt.assets_dir.exists() and not (ziel / "marks.json").exists()
    assert not (ziel / "transkript.annotiert.md").exists() and (ziel / "transkript.md").is_file()


def test_rein_anhaengend_und_vermerk_im_sitzungsordner(projekt, sitzung):
    a1 = wiki_ablage.speichere_sitzung(sitzung, projekt)
    inhalt = {p: p.read_bytes() for p in projekt.raw_dir.rglob("*") if p.is_file()}
    a2 = wiki_ablage.speichere_sitzung(sitzung, projekt, titel="Workshop Reisebuchung")
    assert a2.ordner == a1.ordner + "-2" and a2.assets == a1.assets + "-2"
    assert {p: p.read_bytes() for p in inhalt} == inhalt  # nichts Bestehendes veraendert
    assert [a["ordner"] for a in wiki_ablage.ablagen(sitzung)] == [a1.ordner, a2.ordner]
    assert wiki_ablage.letzte_ablage(sitzung)["ordner"] == a2.ordner


def test_gescheiterte_ablage_hinterlaesst_keine_halbe_quelle(projekt, sitzung, monkeypatch):
    import shutil

    echt = shutil.copyfile
    kopiert = []

    def kopiere(src, dst, **kw):
        kopiert.append(dst)
        if len(kopiert) == 3:  # Transkript, erstes Bild - beim zweiten Bild ist die Platte voll
            raise OSError("Platte voll")
        return echt(src, dst, **kw)

    monkeypatch.setattr(wiki_ablage.shutil, "copyfile", kopiere)
    with pytest.raises(OSError):
        wiki_ablage.speichere_sitzung(sitzung, projekt)
    monkeypatch.undo()
    # Weder die halbe Quelle noch ihr Bilder-Ordner bleiben liegen (der leere Assets-Ordner darf).
    assert [p.name for p in projekt.raw_dir.iterdir()] == ["assets"] and not any(projekt.assets_dir.iterdir())
    assert wiki_ablage.ablagen(sitzung) == []
    # Der naechste Versuch bekommt wieder den einfachen Namen, kein "-2".
    assert wiki_ablage.speichere_sitzung(sitzung, projekt).ordner.endswith("2026-10-06_workshop-reisebuchung")


def test_bilder_ordner_gleich_raw_wird_abgewiesen(projekt, sitzung):
    with pytest.raises(RuntimeError, match="raw/"):
        wiki_ablage.speichere_sitzung(sitzung, replace(projekt, assets_dir=projekt.raw_dir))
    assert not any(projekt.raw_dir.iterdir())


def test_ordnername_aus_datum_und_titel(tmp_path):
    live = tmp_path / "live-2026-10-06_11-21-57"
    assert wiki_ablage.ordnername(live) == "2026-10-06_live-11-21-57"
    assert wiki_ablage.ordnername(live, "Übergabe Büro & Co.") == "2026-10-06_uebergabe-buero-co"
    datei = tmp_path / "Meeting Reisestelle"
    datei.mkdir()
    (datei / "transcript.json").write_text(json.dumps({"created": "2026-09-01 10:00"}), encoding="utf-8")
    assert wiki_ablage.ordnername(datei) == "2026-09-01_meeting-reisestelle"


def test_nie_unter_den_wiki_seiten(projekt, sitzung):
    boese = replace(projekt, assets_dir=projekt.seiten_dir / "bilder")
    with pytest.raises(RuntimeError, match="Wiki-Seiten"):
        wiki_ablage.speichere_sitzung(sitzung, boese)
    assert not (projekt.seiten_dir / "bilder").exists() and not any(projekt.raw_dir.iterdir())
    with pytest.raises(FileNotFoundError):
        wiki_ablage.speichere_sitzung(projekt.sitzungen_dir / "gibt-es-nicht", projekt)


def test_bildnamen_mit_leerzeichen_werden_im_link_maskiert(projekt, sitzung):
    from audioscribe.review.marks import Mark, save_marks

    (sitzung / "frames" / "mein bild (1).png").write_bytes(b"png")
    save_marks(sitzung, [Mark(t=3.0, png="frames/mein bild (1).png")])
    wiki_ablage.speichere_sitzung(sitzung, projekt)
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    assert "mein%20bild%20%281%29.png)" in (ziel / "transkript.annotiert.md").read_text(encoding="utf-8")
    png = json.loads((ziel / "marks.json").read_text(encoding="utf-8"))[0]["png"]
    assert png.endswith("mein bild (1).png") and (ziel / png).is_file()  # maschinenlesbar bleibt der echte Pfad


def _analyse(projekt, sitzung):
    ws = projekt.analysen_dir / "reisebuchung"
    (ws / "material" / "frames").mkdir(parents=True)
    (ws / ".claude" / "skills").mkdir(parents=True)
    (ws / "material" / "frames" / "0001_00-00-03.jpg").write_bytes(b"\xff\xd8bild-0001_00-00-03.jpg")
    (ws / "material" / "transkript.md").write_text("kopie", encoding="utf-8")
    (ws / "agent-log.txt").write_text("log", encoding="utf-8")
    (ws / "analyse.json").write_text(json.dumps({"name": "Reisebuchung", "quelle": str(sitzung)}), encoding="utf-8")
    (ws / "prozessbild.svg").write_text("<svg/>", encoding="utf-8")
    (ws / "INDEX.md").write_text(
        "# Reisebuchung\n\nSchritt 1: ![Bild #0001 – Maske](material/frames/0001_00-00-03.jpg)\n", encoding="utf-8"
    )
    return ws


def test_nachbereitung_liegt_getrennt_und_verweist_auf_die_assets(projekt, sitzung):
    ws = _analyse(projekt, sitzung)
    ablage = wiki_ablage.speichere_nachbereitung(ws, projekt, sitzung)
    # Die Sitzung lag noch nicht im Wiki - sie wird zuerst gespeichert, die Nachbereitung darunter.
    basis = projekt.raw_dir / "2026-10-06_workshop-reisebuchung"
    ziel = basis / "nachbereitung-ki" / "reisebuchung"
    assert ablage.ordner == str(ziel) and ablage.art == "nachbereitung" and ablage.bilder == 1
    index = (ziel / "INDEX.md").read_text(encoding="utf-8")
    link = re.search(r"\]\(([^)]+)\)", index).group(1)
    assert link == "../../../assets/2026-10-06_workshop-reisebuchung/0001_00-00-03.jpg" and (ziel / link).is_file()
    # Keine zweite Bildkopie, kein Arbeitsmaterial, kein Protokoll.
    assert sorted(p.name for p in ziel.iterdir()) == ["INDEX.md", "README.md", "prozessbild.svg"]
    assert "KI-erzeugt" in (ziel / "README.md").read_text(encoding="utf-8")
    assert wiki_ablage.ablagen(ws)[0]["ordner"] == str(ziel)


def test_nachbereitung_mit_bildern_legt_die_sitzung_nicht_doppelt_ab(projekt, sitzung):
    """Sitzung liegt ohne Bilder im Wiki, die Nachbereitung will Bilder: keine zweite Quelle unter raw/."""
    ws = _analyse(projekt, sitzung)
    (ws / "berichte" / "material").mkdir(parents=True)
    (ws / "berichte" / "material" / "anhang.md").write_text("Anhang", encoding="utf-8")
    wiki_ablage.speichere_sitzung(sitzung, projekt, bilder=False)
    ablage = wiki_ablage.speichere_nachbereitung(ws, projekt, sitzung, bilder=True)
    assert [p.name for p in projekt.raw_dir.iterdir() if p.name != "assets"] == ["2026-10-06_workshop-reisebuchung"]
    ziel = projekt.raw_dir / "2026-10-06_workshop-reisebuchung" / "nachbereitung-ki" / "reisebuchung"
    link = re.search(r"\]\(([^)]+)\)", (ziel / "INDEX.md").read_text(encoding="utf-8")).group(1)
    assert (ziel / link).is_file() and ablage.bilder == 1
    assert [p.name for p in (projekt.assets_dir / "2026-10-06_workshop-reisebuchung").iterdir()] == ["0001_00-00-03.jpg"]
    # Nur das Arbeitsmaterial der obersten Ebene bleibt draussen - ein gleichnamiger Unterordner geht mit.
    assert (ziel / "berichte" / "material" / "anhang.md").is_file() and not (ziel / "material").exists()


def test_nachbereitung_folgt_keinen_pfaden_aus_dokument_oder_vermerk(projekt, sitzung, tmp_path):
    ws = _analyse(projekt, sitzung)
    (ws / "material" / "geheim.txt").write_text("geheim", encoding="utf-8")
    (ws / "README.md").write_text("# Bericht des Agenten\n", encoding="utf-8")
    (ws / "INDEX.md").write_text(
        "![a](material/frames/0001_00-00-03.jpg) [x](material/frames/../geheim.txt)\n", encoding="utf-8"
    )
    # Ein Vermerk aus einem anderen Projekt (geteilter Sitzungsordner, kopiertes Wiki) zaehlt nicht.
    fremd = tmp_path / "fremdes-wiki" / "raw" / "alt"
    fremd.mkdir(parents=True)
    (sitzung / wiki_ablage.VERMERK).write_text(
        json.dumps([{"ordner": str(fremd), "assets": None, "art": "sitzung"}, {"art": "sitzung"}]), encoding="utf-8"
    )
    assert wiki_ablage.letzte_ablage(sitzung, projekt) is None
    ablage = wiki_ablage.speichere_nachbereitung(ws, projekt, sitzung)
    assert Path(ablage.ordner).is_relative_to(projekt.raw_dir) and not any(fremd.iterdir())
    # Nur Dateinamen aus material/frames: ".." fuehrt nirgendwohin.
    assert not list(projekt.wiki_dir.rglob("geheim.txt"))
    assert "material/frames/../geheim.txt" in (Path(ablage.ordner) / "INDEX.md").read_text(encoding="utf-8")
    # Das README des Agenten bleibt; der KI-Hinweis steht daneben.
    assert (Path(ablage.ordner) / "README.md").read_text(encoding="utf-8").startswith("# Bericht des Agenten")
    assert "KI-erzeugt" in (Path(ablage.ordner) / "KI-ERZEUGT.md").read_text(encoding="utf-8")


def test_nachbereitung_ohne_bilder_macht_textverweise(projekt, sitzung):
    ws = _analyse(projekt, sitzung)
    wiki_ablage.speichere_sitzung(sitzung, projekt, bilder=False)
    ablage = wiki_ablage.speichere_nachbereitung(ws, projekt, sitzung, bilder=False)
    index = (projekt.raw_dir / "2026-10-06_workshop-reisebuchung" / "nachbereitung-ki" / "reisebuchung" / "INDEX.md")
    text = index.read_text(encoding="utf-8")
    assert "_[Bild #0001 – Maske]_" in text and "material/frames" not in text
    assert ablage.bilder == 0 and not projekt.assets_dir.exists()


def test_ohne_wiki_wird_nicht_abgelegt(projekt_ohne_wiki, sitzung_ohne_wiki):
    """Ein Projekt ohne Wiki hat kein Ziel fuer die Ablage - und der Sitzungsordner bleibt unberuehrt."""
    vorher = sorted(p.name for p in sitzung_ohne_wiki.iterdir())
    with pytest.raises(RuntimeError, match="kein Wiki"):
        wiki_ablage.speichere_sitzung(sitzung_ohne_wiki, projekt_ohne_wiki)
    assert sorted(p.name for p in sitzung_ohne_wiki.iterdir()) == vorher
    assert wiki_ablage.letzte_ablage(sitzung_ohne_wiki, projekt_ohne_wiki) is None
