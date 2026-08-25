"""Bildwechsel-Erkennung (FR-23..FR-27) - reine Logik, ohne echtes Video."""

import numpy as np
import pytest

from audioscribe.pipeline import screens
from audioscribe.review.marks import Mark, load_marks, save_marks
from audioscribe.review.merge import _image_line

# --- ffmpeg-Kommandos (rein, testbar wie review.build_extract_cmd) ---


def test_scan_cmd_streamt_graustufen_in_die_pipe():
    cmd = screens.build_scan_cmd("ffmpeg", "v.mkv", fps=2)
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == "-"  # Ausgabe in die Pipe, nicht in eine Datei
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "fps=2,scale=192:108:flags=area,format=gray"
    # flags=area mittelt beim Verkleinern - ohne das flackert ein duenner Mauszeiger.
    assert cmd[cmd.index("-pix_fmt") + 1] == "gray"


def test_scan_cmd_nimmt_gebrochene_abtastrate():
    vf = screens.build_scan_cmd("ffmpeg", "v.mkv", fps=0.5)[
        screens.build_scan_cmd("ffmpeg", "v.mkv", fps=0.5).index("-vf") + 1
    ]
    assert vf.startswith("fps=0.5,")  # kein "0.500000"


def test_shot_cmd_seekt_vor_dem_input_und_skaliert():
    cmd = screens.build_shot_cmd("ffmpeg", "v.mkv", 83.4, "out.jpg", max_breite=1600, qualitaet=3)
    # -ss VOR -i: schneller Seek zum nahen Keyframe, danach exakt bis zur Zielzeit.
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "83.400"
    assert cmd[cmd.index("-vf") + 1] == "scale='min(iw,1600)':-2:flags=lanczos"
    assert cmd[cmd.index("-q:v") + 1] == "3"
    assert cmd[-1] == "out.jpg"


def test_shot_cmd_ohne_skalierung_und_qualitaet():
    cmd = screens.build_shot_cmd("ffmpeg", "v.mkv", 5.0, "out.png")
    assert "-vf" not in cmd  # PNG in Originalaufloesung
    assert "-q:v" not in cmd


def test_shot_cmd_klemmt_negative_zeit():
    cmd = screens.build_shot_cmd("ffmpeg", "v.mkv", -3.0, "out.jpg")
    assert cmd[cmd.index("-ss") + 1] == "0.000"


# --- Blockraster: der Mauszeiger-Filter ---


def _bild(wert: int = 0) -> np.ndarray:
    return np.full((screens.SCAN_HEIGHT, screens.SCAN_WIDTH), wert, dtype=np.int16)


def test_block_means_liefert_das_raster():
    raster = screens.block_means(_bild(100))
    assert raster.shape == (screens.BLOCKS_Y, screens.BLOCKS_X)  # 9x16 = 144 Bloecke
    assert raster.mean() == 100


def test_mauszeiger_aendert_genau_einen_block():
    """Der Kern der Anforderung: eine Mausbewegung darf kein Standbild ausloesen."""
    vorher, nachher = _bild(0), _bild(0)
    nachher[0:12, 0:12] = 255  # ein Block gross, wie ein Cursor bei 192x108

    n = screens.changed_blocks(screens.block_means(vorher), screens.block_means(nachher), 8)

    assert n == 1
    schwelle, min_bloecke = screens.SENSITIVITIES["mittel"]
    assert n < min_bloecke  # -> gilt NICHT als Bildschirmwechsel


def test_fensterwechsel_schlaegt_an():
    vorher, nachher = _bild(0), _bild(200)
    schwelle, min_bloecke = screens.SENSITIVITIES["mittel"]
    n = screens.changed_blocks(screens.block_means(vorher), screens.block_means(nachher), schwelle)
    assert n == screens.BLOCKS_X * screens.BLOCKS_Y >= min_bloecke


def test_leichtes_rauschen_bleibt_unter_der_schwelle():
    vorher = _bild(120)
    nachher = _bild(124)  # +4 ueberall, z.B. Helligkeitsschwankung
    schwelle, _ = screens.SENSITIVITIES["mittel"]
    assert screens.changed_blocks(screens.block_means(vorher), screens.block_means(nachher), schwelle) == 0


@pytest.mark.parametrize(
    ("stufe", "erwartet_treffer"),
    [("grob", False), ("mittel", True), ("fein", True)],
)
def test_empfindlichkeitsstufen_an_denselben_daten(stufe, erwartet_treffer):
    """Vier geaenderte Bloecke: 'mittel' und 'fein' schlagen an, 'grob' (>=10) nicht."""
    vorher, nachher = _bild(0), _bild(0)
    nachher[0:12, 0:48] = 255  # 4 Bloecke nebeneinander

    schwelle, min_bloecke = screens.SENSITIVITIES[stufe]
    n = screens.changed_blocks(screens.block_means(vorher), screens.block_means(nachher), schwelle)
    assert (n >= min_bloecke) is erwartet_treffer


# --- Serien zusammenfassen ---


def test_serie_wird_zu_einem_zeitpunkt_am_ende():
    """Eine Animation schlaegt mehrfach an; genommen wird das fertig aufgebaute Bild."""
    assert screens.merge_runs([5.0, 5.5, 6.0], fps=2, min_gap=4.0) == [6.0]


def test_getrennte_serien_bleiben_getrennt():
    assert screens.merge_runs([5.0, 5.5, 14.0, 14.5], fps=2, min_gap=4.0) == [5.5, 14.5]


def test_mindestabstand_verwirft_zu_dichte_ereignisse():
    # 7.0 liegt nur 1.5 s nach 5.5 -> faellt raus (z.B. ein abgespieltes Video)
    assert screens.merge_runs([5.0, 5.5, 7.0], fps=2, min_gap=4.0) == [5.5]


def test_einzeltreffer_bleibt_und_leere_eingabe_bleibt_leer():
    assert screens.merge_runs([12.0], fps=2, min_gap=4.0) == [12.0]
    assert screens.merge_runs([], fps=2, min_gap=4.0) == []


# --- Dateinamen: ID UND Zeitstempel ---


def test_dateiname_traegt_id_und_zeitstempel():
    assert screens.shot_filename(1, 83.4, ".jpg") == "0001_00-01-23.jpg"
    assert screens.shot_filename(42, 3661.0, ".png") == "0042_01-01-01.png"


def test_zwei_wechsel_in_derselben_sekunde_kollidieren_nicht():
    """Der reine Zeitstempel-Name (review.frame_filename) waere hier zweimal gleich."""
    assert screens.shot_filename(7, 12.2, ".jpg") != screens.shot_filename(8, 12.4, ".jpg")


# --- Zusammenfuehrung mit von Hand gesetzten Markierungen ---


def test_manuelle_marks_ueberleben_einen_erneuten_lauf(tmp_path):
    manuell = Mark(t=10.0, png="frames/00-00-10.png", note="wichtig")
    alt_auto = Mark(t=20.0, png="frames/0001_00-00-20.jpg", id=1, kind=screens.KIND_AUTO)
    save_marks(tmp_path, [manuell, alt_auto])

    neu = [Mark(t=30.0, png="frames/0002_00-00-30.jpg", id=2, kind=screens.KIND_AUTO)]
    save_marks(tmp_path, screens.merge_marks(load_marks(tmp_path), neu))

    gespeichert = load_marks(tmp_path)
    assert [m.png for m in gespeichert] == ["frames/00-00-10.png", "frames/0002_00-00-30.jpg"]
    assert gespeichert[0].note == "wichtig"  # unveraendert
    assert gespeichert[0].kind is None


def test_marks_json_ohne_id_bleibt_lesbar(tmp_path):
    """Aeltere Sidecars kennen id/kind nicht - sie duerfen nicht brechen."""
    (tmp_path / "marks.json").write_text(
        '[{"t": 5.0, "png": "frames/00-00-05.png", "note": null, "created": "2026-01-01 10:00"}]',
        encoding="utf-8",
    )
    mark = load_marks(tmp_path)[0]
    assert mark.id is None and mark.kind is None


# --- Einbettung ins annotierte Transkript ---


def test_bildzeile_nennt_die_id():
    zeile = _image_line(Mark(t=83.4, png="frames/0001_00-01-23.jpg", id=1, kind="auto"))
    assert zeile == "![Bild #0001 – 00:01:23](frames/0001_00-01-23.jpg)"


def test_bildzeile_manueller_marks_unveraendert():
    zeile = _image_line(Mark(t=83.4, png="frames/00-01-23.png"))
    assert zeile == "![Markierter Bildschirm 00:01:23](frames/00-01-23.png)"


def test_dauerbewegung_liefert_trotzdem_bilder():
    """Kamerakachel in einer Besprechungsaufnahme: die Bewegung endet nie.

    Ohne den Notausgang waere die ganze Aufnahme EINE Serie und lieferte ein einziges
    Bild vom Schluss - fuer ein 80-Minuten-Video praktisch wertlos.
    """
    dauertreffer = [i * 0.5 for i in range(120)]  # 60 s ununterbrochene Bewegung

    ohne = screens.merge_runs(dauertreffer, fps=2, min_gap=4.0, dauerbewegung_s=0)
    mit = screens.merge_runs(dauertreffer, fps=2, min_gap=4.0, dauerbewegung_s=20.0)

    assert len(ohne) == 1  # so waere es ohne den Notausgang
    assert len(mit) >= 3  # etwa alle 20 s ein Zwischenstand


def test_scan_cmd_ueberspringt_ton_und_untertitel():
    cmd = screens.build_scan_cmd("ffmpeg", "v.mkv", fps=2)
    for flag in ("-an", "-sn", "-dn"):
        assert flag in cmd
    assert cmd.index("-an") > cmd.index("-i")  # gilt dem Ausgang, nicht dem Eingang


def test_ids_bleiben_ueber_mehrere_laeufe_stabil(tmp_path):
    """Ein zweiter Lauf nummeriert wieder ab 1 - die alten Auto-Marks fallen ja weg."""
    alt = [
        Mark(t=7.0, png="frames/0001_00-00-07.jpg", id=1, kind=screens.KIND_AUTO),
        Mark(t=14.0, png="frames/0002_00-00-14.jpg", id=2, kind=screens.KIND_AUTO),
    ]
    save_marks(tmp_path, [*alt, Mark(t=5.0, png="frames/00-00-05.png", note="von Hand")])

    vorhandene = load_marks(tmp_path)
    behalten = [m for m in vorhandene if m.kind != screens.KIND_AUTO]
    start_id = max((m.id or 0) for m in behalten) + 1 if behalten else 1

    assert start_id == 1  # nicht 3 - sonst wandern die Nummern bei jedem Lauf hoch
