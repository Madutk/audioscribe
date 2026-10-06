"""Absturzsicherung und Wiederaufnahme einer Live-Sitzung (PRD §21) - ohne Hardware, ohne Modelle.

Kindprozess-Seite: Journal, Zustandsdatei, Lebenszeichen, Startversatz in Spur/Schnitt/Replay,
Fortsetzen (``live --resume``), Abschließen (``live --finalize``) und das Verbinden der
Mitschnitt-Teile. Muster wie in ``tests/test_live.py`` (FakeAsr, WAV-Replay Ende-zu-Ende).
"""

import json
import time
import wave
from itertools import count

import numpy as np
import pytest

from audioscribe.live import events, journal
from audioscribe.live.chunker import Chunker
from audioscribe.live.speakers import SPRECHER_DATEI, SpeakerLabeler
from audioscribe.live.store import MIC_WAV, SYSTEM_WAV, teil_wav, verbinde_teile, wav_frames
from audioscribe.live.track import SAMPLE_RATE, Track, load_wav

SR = SAMPLE_RATE


# --- Helfer (wie tests/test_live.py) ---------------------------------------------------


def energy_vad(audio: np.ndarray) -> list[tuple[int, int]]:
    hop = SR // 100
    active = [np.abs(audio[i : i + hop]).max() > 0.1 for i in range(0, len(audio), hop)]
    out, start = [], None
    for i, a in enumerate([*active, False]):
        if a and start is None:
            start = i
        elif not a and start is not None:
            out.append((start * hop, min(i * hop, len(audio))))
            start = None
    return out


def speech(seconds: float) -> np.ndarray:
    return np.full(int(seconds * SR), 0.5, dtype=np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


def write_wav(path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def kopf_abreissen(path) -> None:
    """Wie nach einem Absturz: ``wave`` hat die Länge nie in den Kopf geschrieben."""
    data = bytearray(path.read_bytes())
    data[4:8] = b"\x24\x00\x00\x00"
    data[40:44] = b"\x00\x00\x00\x00"
    path.write_bytes(bytes(data))


def kopf_frames(path) -> int:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes()


def pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()


class FakeAsr:
    detected = "de"

    def __init__(self, antwort="Text"):
        self.antwort = antwort

    def transcribe(self, audio, *, final, eco=False, initial_prompt=None):
        return self.antwort


@pytest.fixture
def ereignisse(monkeypatch):
    emitted, logged = [], []
    monkeypatch.setattr(events, "emit", lambda typ, **d: emitted.append((typ, d)))
    monkeypatch.setattr(events, "log", logged.append)
    return emitted, logged


def live_session(tmp_path, monkeypatch, *, antwort="Text", **kw):
    from audioscribe.live.session import LiveOptions, LiveSession

    opts = LiveOptions(output_dir=tmp_path / "out", model="m", device="cpu", compute_type="int8", speed=10.0,
                       monitor=0, mic="none", partials=False, speakers=False, **kw)
    session = LiveSession(opts)
    monkeypatch.setattr(session, "_load_asr", lambda: FakeAsr(antwort))
    monkeypatch.setattr(session, "_load_vad", lambda: energy_vad)
    monkeypatch.setattr(session, "_watch_stdin", lambda: None)
    return session


def sitzung_von_hand(ordner, *, segmente=(), status=journal.LAEUFT, **extra):
    """Sitzungsordner, wie ihn ein abgestürzter Kindprozess hinterlässt."""
    ordner.mkdir(parents=True, exist_ok=True)
    journal.schreibe_status(ordner, status=status, sprache="de", modell="small", **extra)
    j = journal.Journal(ordner)
    for seg in segmente:
        j.segment(**seg)
    j.close()
    return ordner


def seg(nr, start, end, text, track="system", speaker="Gegenseite"):
    return dict(id=nr, track=track, speaker=speaker, start=start, end=end, text=text, delay=1.0)


# --- Zustandsdatei, Journal, Lebenszeichen ----------------------------------------------


def test_status_wird_gemischt_und_ist_tolerant(tmp_path):
    assert journal.lies_status(tmp_path) is None
    stand = journal.schreibe_status(tmp_path, titel="Workshop", sprache="de", modell="small")
    for feld in ("version", "sitzung_id", "status", "titel", "gestartet", "sprache", "modell", "replay", "teile"):
        assert feld in stand, feld
    assert stand["status"] == journal.LAEUFT and stand["replay"] is False and len(stand["sitzung_id"]) == 32
    zweiter = journal.schreibe_status(tmp_path, status=journal.UNTERBROCHEN)
    assert zweiter["sitzung_id"] == stand["sitzung_id"] and zweiter["titel"] == "Workshop"
    assert journal.lies_status(tmp_path)["status"] == journal.UNTERBROCHEN
    assert not list(tmp_path.glob("*.tmp"))  # atomar: keine Reste
    (tmp_path / journal.STATUS_DATEI).write_text("{kaputt", encoding="utf-8")
    assert journal.lies_status(tmp_path) is None
    (tmp_path / journal.STATUS_DATEI).write_text("[1, 2]", encoding="utf-8")
    assert journal.lies_status(tmp_path) is None


def test_journal_uebersteht_eine_abgerissene_letzte_zeile(tmp_path):
    j = journal.Journal(tmp_path)
    j.segment(**seg(1, 0.5, 2.0, "Grüße"))
    j.shot(id=1, t=3.0, png="frames/0001_00-00-03.jpg", created="2026-10-06 10:00", kind="auto")
    j.takt(7.5)
    j.close()
    pfad = tmp_path / journal.JOURNAL_DATEI
    with pfad.open("a", encoding="utf-8") as datei:  # Absturz mitten im Schreiben
        datei.write('{"art": "segment", "id": 2, "start": 8.0, "en')
    neu = journal.Journal(tmp_path)  # Wiederaufnahme hängt an
    neu.segment(**seg(3, 9.0, 11.0, "weiter"))
    neu.close()

    bestand = journal.lies_journal(tmp_path)
    assert [(s["id"], s["text"]) for s in bestand.segmente] == [(1, "Grüße"), (3, "weiter")]
    assert bestand.letzte_id == 3 and bestand.takt_s == 7.5 and bestand.ende_s == 11.0
    assert [s["png"] for s in bestand.shots] == ["frames/0001_00-00-03.jpg"]
    assert journal.lies_journal(tmp_path / "fehlt").segmente == []


def test_journal_legt_den_sitzungsordner_nicht_an(tmp_path):
    j = journal.Journal(tmp_path / "noch-nicht-da")
    j.segment(**seg(1, 0.0, 1.0, "x"))
    j.close()
    assert not (tmp_path / "noch-nicht-da").exists()


def test_sperre_ist_das_lebenszeichen(tmp_path):
    assert journal.lebt(tmp_path) is False  # ohne Lock-Datei
    sperre = journal.sperre(tmp_path)
    assert journal.lebt(tmp_path) is True
    with pytest.raises(RuntimeError, match="läuft bereits"):
        journal.sperre(tmp_path)
    sperre.gib_frei()
    sperre.gib_frei()  # doppelt freigeben schadet nicht
    assert journal.lebt(tmp_path) is False
    journal.sperre(tmp_path).gib_frei()  # danach wieder frei


def test_offene_sitzungen_listet_nur_unterbrochene(tmp_path):
    assert journal.offene_sitzungen(tmp_path / "fehlt") == []
    alt = sitzung_von_hand(tmp_path / "live-a", segmente=[seg(1, 0.0, 4.0, "eins"), seg(2, 5.0, 9.5, "zwei")],
                           gestartet="2026-10-06T09:00:00", titel="Früh")
    sitzung_von_hand(tmp_path / "live-b", status=journal.UNTERBROCHEN, gestartet="2026-10-06T11:00:00")
    laeuft = sitzung_von_hand(tmp_path / "live-c", gestartet="2026-10-06T12:00:00")
    sitzung_von_hand(tmp_path / "live-d", status=journal.BEENDET)
    sitzung_von_hand(tmp_path / "live-e", status=journal.VERWORFEN)
    sitzung_von_hand(tmp_path / "live-f", replay=True)  # Demo/Test: nie fortsetzen
    (tmp_path / "ohne-status").mkdir()
    sperre = journal.sperre(laeuft)  # dieser Prozess lebt noch
    try:
        offen = journal.offene_sitzungen(tmp_path)
    finally:
        sperre.gib_frei()

    assert [e["name"] for e in offen] == ["live-b", "live-a"]  # jüngste zuerst
    eintrag = offen[1]
    assert set(eintrag) == {"dir", "name", "sitzung_id", "status", "titel", "gestartet", "dauer_s", "segmente"}
    assert (eintrag["dir"], eintrag["titel"], eintrag["segmente"], eintrag["dauer_s"]) == (str(alt), "Früh", 2, 9.5)
    assert eintrag["status"] == journal.UNTERBROCHEN and len(eintrag["sitzung_id"]) == 32
    # Ohne Sperre gilt auch die "laufende" als unterbrochen.
    assert [e["name"] for e in journal.offene_sitzungen(tmp_path)] == ["live-c", "live-b", "live-a"]


def test_save_marks_schreibt_atomar(tmp_path):
    from audioscribe.review.marks import Mark, load_marks, save_marks

    save_marks(tmp_path, [Mark(t=3.0, png="frames/0001_00-00-03.jpg", id=1, kind="auto")])
    save_marks(tmp_path, [Mark(t=3.0, png="frames/0001_00-00-03.jpg", id=1, kind="auto"),
                          Mark(t=9.0, png="frames/0002_00-00-09.jpg", id=2, kind="auto")])
    assert [m.id for m in load_marks(tmp_path)] == [1, 2]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["marks.json"]


def test_events_log_vertraegt_eine_tote_pipe(monkeypatch):
    import threading

    monkeypatch.setattr(events, "_stdout_tot", threading.Event())
    monkeypatch.setattr(events, "_bei_tot", [])
    gerufen = []
    events.bei_stdout_tot(lambda: gerufen.append(1))

    def tot(*args, **kw):
        raise OSError("Broken pipe")

    monkeypatch.setattr("builtins.print", tot)
    assert events.stdout_tot() is False
    events.log("geht verloren")  # wirft nicht
    events.emit(events.STATS, elapsed=1.0)
    assert events.stdout_tot() is True and gerufen == [1]  # Rückruf genau einmal


KIND_TOTE_PIPE = """
import sys, time
from audioscribe.live import events
events.bei_stdout_tot(lambda: open(sys.argv[1], 'w').write('geordnet'))
events.log('bereit')
ende = time.monotonic() + 20
while not events.stdout_tot() and time.monotonic() < ende:
    events.emit(events.STATS, elapsed=1.0)
    time.sleep(0.01)
sys.exit(0 if events.stdout_tot() else 3)
"""


def test_kindprozess_ueberlebt_den_tod_des_lesers(tmp_path):
    """Echte Pipe: der Leser (Server) schließt sie - das Kind merkt es und räumt selbst auf."""
    import subprocess
    import sys

    marke = tmp_path / "notabschluss.txt"
    kind = KIND_TOTE_PIPE
    proc = subprocess.Popen([sys.executable, "-c", kind, str(marke)], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)
    assert proc.stdout.readline().strip() == "bereit"
    proc.stdout.close()  # der Server ist weg
    proc.wait(timeout=30)
    assert marke.read_text() == "geordnet"


# --- Startversatz: Spur, Schnitt, Replay, Standbilder, Sprecher ---------------------------


def test_track_mit_startversatz_schreibt_keine_stille(tmp_path):
    start = 600 * SR  # zehn Minuten Vorlauf aus dem ersten Teil
    track = Track("system", SR, 1, tmp_path / "audio" / "system.teil2.wav", start_sample=start)
    track.feed(pcm(speech(1.0)), t_arrival=601.0)
    pos, samples = track.take(601.0)
    assert pos == start and abs(len(samples) - SR) < 0.05 * SR and np.abs(samples).min() > 0.3
    pos2, rest = track.take(603.0)  # danach füllt die Zeitleiste wie gewohnt mit Stille auf
    assert pos2 == start + len(samples) and not rest.any()
    track.close()
    # Dateiposition 0 der Teil-WAV = start_sample: nur was ab dort kam, kein Vorlauf.
    assert wav_frames(tmp_path / "audio" / "system.teil2.wav") == track.written - start < 3 * SR


def test_track_oeffnet_bei_wiederaufnahme_nie_einen_vorhandenen_mitschnitt(tmp_path):
    write_wav(tmp_path / "audio" / "system.wav", speech(1.0))
    with pytest.raises(RuntimeError, match="nicht überschrieben"):
        Track("system", SR, 1, tmp_path / "audio" / "system.wav", start_sample=SR)
    assert wav_frames(tmp_path / "audio" / "system.wav") == SR  # unberührt


def test_chunker_mit_start_liefert_absolute_zeiten():
    start = 100 * SR
    chunker = Chunker(energy_vad, start=start)
    pos = start
    for teil in (silence(1.0), speech(2.0), silence(1.0)):
        chunker.feed(pos, teil)
        pos += len(teil)
    (utt,) = chunker.poll()
    assert abs(utt.start_s - 101.0) < 0.05 and abs(utt.end_s - 103.0) < 0.05
    assert len(chunker._buf) < 2 * SR  # kein Puffer über den Vorlauf


def test_replay_capture_spielt_ab_dem_versatz(tmp_path):
    from audioscribe.live.replay import ReplayCapture

    write_wav(tmp_path / "in.wav", speech(1.0))
    start = 50 * SR
    t0 = time.monotonic()
    clock = lambda: 50.0 + (time.monotonic() - t0) * 20.0  # noqa: E731
    ended = []
    cap = ReplayCapture(clock, system=tmp_path / "in.wav", mic=None, speed=20.0, on_end=lambda: ended.append(1),
                        nachlauf_s=0.3, start_sample=start)
    track = cap.open("system", cap.loopbacks[0], tmp_path / "audio" / "system.teil2.wav")
    ende = time.monotonic() + 10
    while not ended and time.monotonic() < ende:
        time.sleep(0.02)
    assert ended == [1]
    pos, samples = track.take(51.0)
    assert pos == start and abs(len(samples) - SR) < 0.05 * SR and np.abs(samples[: SR // 2]).max() > 0.3
    cap.close()
    assert abs(wav_frames(tmp_path / "audio" / "system.teil2.wav") - SR) < 0.05 * SR


def test_screen_watcher_zaehlt_ab_start_id_weiter(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    from audioscribe.live.fenster import WindowGone
    from audioscribe.live.screen import ScreenWatcher

    class Quelle:
        label = "Attrappe"

        def __init__(self):
            self._folge = [Image.new("RGB", (64, 36), (255, 255, 255))] * 2

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def grab(self):
            if not self._folge:
                raise WindowGone("zu Ende")
            return self._folge.pop(0)

    takt = count()
    marks = []
    watcher = ScreenWatcher(1, tmp_path, lambda: 900.0 + next(takt) * 5.0, marks.append, fps=500.0,
                            log=lambda m: None, source_factory=Quelle, start_id=7)
    watcher.start()
    watcher.join(timeout=5)
    assert [m.id for m in marks] == [8]  # Startbild des neuen Teils, nicht wieder #0001
    assert marks[0].png.startswith("frames/0008_00-15-")


def test_sprecher_bleiben_nach_wiederaufnahme_dieselben(tmp_path):
    stimmen = {1.0: np.array([1.0, 0.0, 0.0], dtype=np.float32), 2.0: np.array([0.0, 1.0, 0.0], dtype=np.float32)}

    def embedder(audio):
        return stimmen[float(audio[0])]

    def stimme(wert):
        return np.full(2 * SR, wert, dtype=np.float32)

    pfad = tmp_path / SPRECHER_DATEI
    erster = SpeakerLabeler(embedder, pfad=pfad)
    assert erster.label("system", stimme(1.0)) == "Sprecher 1"
    assert erster.label("system", stimme(2.0)) == "Sprecher 2"
    assert json.loads(pfad.read_text(encoding="utf-8"))["last"] == "Sprecher 2"

    # Neuer Prozess: ohne die Begleitdatei hieße die zweite Stimme jetzt "Sprecher 1".
    zweiter = SpeakerLabeler(embedder, pfad=pfad)
    assert zweiter.label("system", np.zeros(SR // 2, dtype=np.float32)) == "Sprecher 2"  # zu kurz: erbt
    assert zweiter.label("system", stimme(2.0)) == "Sprecher 2"
    assert zweiter.label("system", stimme(1.0)) == "Sprecher 1"
    assert SpeakerLabeler(embedder).label("system", stimme(2.0)) == "Sprecher 1"  # Gegenprobe ohne Datei
    assert not list(tmp_path.glob("*.tmp"))


# --- Teile verbinden ---------------------------------------------------------------------


def test_verbinde_teile_fuellt_auf_und_repariert_den_kopf(tmp_path):
    session = tmp_path / "live-x"
    write_wav(session / teil_wav("system", 1), np.full(SR, 0.25, dtype=np.float32))
    kopf_abreissen(session / teil_wav("system", 1))  # Teil 1 endete mit dem Absturz
    write_wav(session / teil_wav("system", 2), np.full(SR // 2, 0.5, dtype=np.float32))
    write_wav(session / teil_wav("mic", 2), np.full(SR // 2, 0.75, dtype=np.float32))  # Spur erst im 2. Teil
    journal.schreibe_status(session, teile=[
        {"nr": 1, "start_sample": 0, "spuren": {"system": teil_wav("system", 1)}},
        {"nr": 2, "start_sample": 2 * SR, "spuren": {"system": teil_wav("system", 2), "mic": teil_wav("mic", 2)}},
    ])

    geschrieben = verbinde_teile(session)
    assert sorted(p.name for p in geschrieben) == ["mikrofon.wav", "system.wav"]
    system = load_wav(session / SYSTEM_WAV)
    assert kopf_frames(session / SYSTEM_WAV) == len(system) == int(2.5 * SR)  # korrekter Kopf
    assert abs(system[SR // 2] - 0.25) < 0.01 and not system[SR : 2 * SR].any() and abs(system[-10] - 0.5) < 0.01
    mic = load_wav(session / MIC_WAV)
    assert len(mic) == int(2.5 * SR) and not mic[: 2 * SR].any() and abs(mic[-10] - 0.75) < 0.01
    # Sample-Position = Sitzungszeit; danach ein Teil, keine Teil-Dateien, keine Reste.
    assert journal.lies_status(session)["teile"] == [
        {"nr": 1, "start_sample": 0, "spuren": {"mic": MIC_WAV, "system": SYSTEM_WAV}}
    ]
    assert sorted(p.name for p in (session / "audio").iterdir()) == ["mikrofon.wav", "system.wav"]

    vorher = (session / SYSTEM_WAV).read_bytes()
    assert verbinde_teile(session) == []  # idempotent
    assert (session / SYSTEM_WAV).read_bytes() == vorher


def test_verbinde_teile_nach_abbruch_zwischen_tausch_und_zustand(tmp_path):
    """Das Ziel steht schon, der Zustand nennt aber noch beide Teile: neu bauen, nichts doppelt."""
    session = tmp_path / "live-y"
    write_wav(session / teil_wav("system", 1), np.full(SR, 0.25, dtype=np.float32))
    write_wav(session / teil_wav("system", 2), np.full(SR, 0.5, dtype=np.float32))
    write_wav(session / SYSTEM_WAV, np.full(5 * SR, 0.9, dtype=np.float32))  # Rest eines abgebrochenen Versuchs
    journal.schreibe_status(session, teile=[
        {"nr": 1, "start_sample": 0, "spuren": {"system": teil_wav("system", 1)}},
        {"nr": 2, "start_sample": SR, "spuren": {"system": teil_wav("system", 2)}},
    ])
    verbinde_teile(session)
    system = load_wav(session / SYSTEM_WAV)
    assert len(system) == 2 * SR and abs(system[10] - 0.25) < 0.01 and abs(system[-10] - 0.5) < 0.01


def test_verbinde_teile_ohne_zustand_repariert_nur_den_kopf(tmp_path):
    write_wav(tmp_path / SYSTEM_WAV, speech(1.0))
    kopf_abreissen(tmp_path / SYSTEM_WAV)
    assert kopf_frames(tmp_path / SYSTEM_WAV) == 0
    verbinde_teile(tmp_path)
    assert kopf_frames(tmp_path / SYSTEM_WAV) == SR
    assert journal.lies_status(tmp_path) is None  # legt keine Zustandsdatei an


# --- Fortsetzen ----------------------------------------------------------------------------


def test_resume_setzt_ids_und_uhr_fort_ohne_bestand_zu_ueberschreiben(tmp_path, ereignisse):
    from audioscribe.live.board import Job
    from audioscribe.live.chunker import Utterance
    from audioscribe.live.session import LiveOptions, LiveSession
    from audioscribe.review.marks import Mark, save_marks

    emitted, _ = ereignisse
    ordner = sitzung_von_hand(
        tmp_path / "live-2026-10-06_10-00-00",
        segmente=[seg(1, 1.0, 3.0, "Hallo", track="mic", speaker="Ich"), seg(2, 4.0, 6.0, "Guten Tag"),
                  seg(4, 20.0, 22.5, "Dritter Satz")],  # ID 3 fehlt (Zeile ging verloren)
        titel="Workshop", status=journal.UNTERBROCHEN,
        teile=[{"nr": 1, "start_sample": 0, "spuren": {"system": SYSTEM_WAV}}],
    )
    write_wav(ordner / SYSTEM_WAV, silence(30.0))  # der Mitschnitt lief weiter als das letzte Segment
    save_marks(ordner, [Mark(t=2.0, png="frames/0001_00-00-02.jpg", id=1, kind="auto")])
    (ordner / "diagnose.jsonl").write_text(
        json.dumps({"art": "abschnitt", "chunk_index": 9, "track": "mic", "audio_start_s": 1.0, "audio_end_s": 3.0,
                    "audio_dauer_s": 2.0, "t_abgeschlossen": 3.1, "t_start": 3.2, "t_ende": 3.9, "wartezeit_s": 0.1,
                    "rechenzeit_s": 0.7, "sprecher_s": 0.0, "latenz_s": 0.9, "latenz_max_s": 0.9, "modell": "m",
                    "eco": False, "parts": 1, "anzahl_woerter": 1, "schluss": "pause"}) + "\n"
        + json.dumps({"art": "nachschaerfen", "teil": "nachschaerfen"}) + '\n{"art": "abschn', encoding="utf-8")
    sitzung_id = journal.lies_status(ordner)["sitzung_id"]

    session = LiveSession(LiveOptions(output_dir=tmp_path / "egal", model="m", device="cpu", compute_type="int8",
                                      resume_dir=ordner))
    session._asr = FakeAsr("Neu")
    session._labeler = SpeakerLabeler(None)
    assert session.dir == ordner and session._seg_id == 4 and session._teil_nr == 2
    assert session._start_sample == 30 * SR  # Mitschnitt-Ende, nicht das ältere letzte Segment
    assert session._chunk_index == 9 and len(session._diagnose.abschnitte) == 1
    session._t0 = time.monotonic()
    assert 30.0 <= session.clock() < 31.0

    session._melde_bestand()
    wieder = [(typ, d) for typ, d in emitted if d.get("restored")]
    assert [(typ, d["id"]) for typ, d in wieder] == [("segment", 1), ("segment", 2), ("segment", 4), ("shot", 1)]
    assert wieder[0][1]["track"] == "mic" and wieder[0][1]["text"] == "Hallo" and wieder[3][1]["file"] == "0001_00-00-02.jpg"

    emitted.clear()
    utt = Utterance(31 * SR, 33 * SR, np.zeros(2 * SR, dtype=np.float32))
    session._do_final(Job("system", utt, final=True, t_abgeschlossen=33.1))
    (neu,) = [d for typ, d in emitted if typ == events.SEGMENT]
    assert neu["id"] == 5 and neu["start"] == 31.0 and "restored" not in neu
    assert journal.lies_journal(ordner).letzte_id == 5  # steht sofort im Journal

    session._persist()  # erst geladen, dann geschrieben: der Bestand bleibt
    md = (ordner / "transkript.md").read_text(encoding="utf-8")
    assert md.index("Hallo") < md.index("Guten Tag") < md.index("Dritter Satz") < md.index("Neu")
    assert "#0001" in (ordner / "transkript.annotiert.md").read_text(encoding="utf-8")

    session._state("laeuft")
    zustand = emitted[-1][1]
    assert zustand["fortgesetzt"] is True and zustand["sitzung_id"] == sitzung_id and zustand["titel"] == "Workshop"
    assert zustand["dir"] == str(ordner)

    session._sichere_alte_teile()  # der alte Mitschnitt macht den Endnamen frei
    assert (ordner / teil_wav("system", 1)).is_file() and not (ordner / SYSTEM_WAV).exists()
    assert journal.lies_status(ordner)["teile"][0]["spuren"] == {"system": teil_wav("system", 1)}
    assert session._wav_name("system") == teil_wav("system", 2)


def test_resume_stolpert_nicht_ueber_reste_eines_gescheiterten_versuchs(tmp_path):
    from audioscribe.live.session import LiveOptions, LiveSession

    ordner = sitzung_von_hand(tmp_path / "live-x", segmente=[seg(1, 0.0, 2.0, "eins")], status=journal.UNTERBROCHEN,
                              teile=[{"nr": 1, "start_sample": 0, "spuren": {"system": teil_wav("system", 1)}}])
    write_wav(ordner / teil_wav("system", 1), speech(3.0))
    # Zweiter Anlauf: Mikrofon ging auf, dann scheiterte das System-Audio - nie eingetragen.
    write_wav(ordner / teil_wav("mic", 2), silence(0.1))
    session = LiveSession(LiveOptions(output_dir=tmp_path, model="m", device="cpu", compute_type="int8",
                                      resume_dir=ordner))
    assert session._teil_nr == 3 and session._start_sample == 3 * SR
    assert not (ordner / session._wav_name("mic")).exists()
    session._beginne_teil({"system": session._wav_name("system")})
    write_wav(ordner / teil_wav("system", 3), speech(1.0))
    verbinde_teile(ordner)
    assert sorted(p.name for p in (ordner / "audio").iterdir()) == ["system.wav"]  # der Rest ist geräumt
    assert wav_frames(ordner / SYSTEM_WAV) == 4 * SR


@pytest.mark.parametrize("status", [journal.BEENDET, journal.VERWORFEN])
def test_resume_lehnt_fertige_und_replay_sitzungen_ab(tmp_path, status):
    from audioscribe.live.session import LiveOptions, LiveSession

    def versuche(ordner):
        return LiveSession(LiveOptions(output_dir=tmp_path, model="m", device="cpu", compute_type="int8",
                                       resume_dir=ordner))

    with pytest.raises(RuntimeError, match="sitzung.json fehlt"):
        versuche(tmp_path)
    with pytest.raises(RuntimeError, match="nicht fortgesetzt"):
        versuche(sitzung_von_hand(tmp_path / "fertig", status=status))
    with pytest.raises(RuntimeError, match="Replay"):
        versuche(sitzung_von_hand(tmp_path / "replay", replay=True))


def test_live_sitzung_wird_nach_absturz_ende_zu_ende_fortgesetzt(tmp_path, monkeypatch, ereignisse):
    from audioscribe.live.bilanz import load_bilanz
    from audioscribe.live.diagnose import lies_diagnose

    emitted, logged = ereignisse
    write_wav(tmp_path / "eins.wav", np.concatenate([silence(1.0), speech(1.5), silence(0.5)]))
    write_wav(tmp_path / "zwei.wav", np.concatenate([silence(0.5), speech(1.0), silence(0.5)]))

    erste = live_session(tmp_path, monkeypatch, antwort="Erster Teil.", replay_system=tmp_path / "eins.wav",
                         titel="Workshop")
    assert erste.run() == 0
    ordner = erste.dir
    status = journal.lies_status(ordner)
    assert status["status"] == journal.BEENDET and status["titel"] == "Workshop" and status["replay"] is False
    assert status["teile"] == [{"nr": 1, "start_sample": 0, "spuren": {"system": SYSTEM_WAV}}]
    assert journal.lebt(ordner) is False  # Sperre mit dem Ende freigegeben
    erster_zustand = next(d for typ, d in emitted if typ == events.STATE)
    assert erster_zustand["sitzung_id"] == status["sitzung_id"] and "fortgesetzt" not in erster_zustand

    # "Absturz": Zustand blieb auf laeuft stehen, der Kopf der WAV wurde nie geschrieben.
    journal.schreibe_status(ordner, status=journal.LAEUFT)
    kopf_abreissen(ordner / SYSTEM_WAV)
    laenge_1 = wav_frames(ordner / SYSTEM_WAV)
    assert [e["name"] for e in journal.offene_sitzungen(ordner.parent)] == [ordner.name]

    emitted.clear()
    zweite = live_session(tmp_path, monkeypatch, antwort="Zweiter Teil.", replay_system=tmp_path / "zwei.wav",
                          resume_dir=ordner)
    assert zweite._start_sample == laenge_1
    assert zweite.run() == 0

    # Zuerst das Bisherige als "restored", dann erst die neue Aufnahme.
    typen = [(typ, d.get("phase"), bool(d.get("restored"))) for typ, d in emitted if typ in ("state", "segment")]
    assert typen[0] == ("state", "laden", False) and typen[1] == ("segment", None, True)
    assert typen.index(("segment", None, True)) < typen.index(("state", "laeuft", False))
    assert all(d.get("fortgesetzt") is True for typ, d in emitted if typ == events.STATE)
    alt, neu = [d for typ, d in emitted if typ == events.SEGMENT]
    assert (alt["id"], alt["text"], alt.get("restored")) == (1, "Erster Teil.", True)
    assert neu["id"] == 2 and neu["text"] == "Zweiter Teil." and "restored" not in neu
    versatz = laenge_1 / SR
    assert abs(neu["start"] - (versatz + 0.5)) < 0.15 and abs(neu["end"] - (versatz + 1.5)) < 0.15

    # Ein Mitschnitt mit korrektem Kopf; Sample-Position = Sitzungszeit.
    audio = load_wav(ordner / SYSTEM_WAV)
    assert kopf_frames(ordner / SYSTEM_WAV) == len(audio) > laenge_1 + 2 * SR
    assert np.abs(audio[int(1.2 * SR) : int(2.3 * SR)]).max() > 0.4  # Teil 1 unverändert vorn
    a, b = laenge_1 + int(0.7 * SR), laenge_1 + int(1.3 * SR)
    assert np.abs(audio[a:b]).max() > 0.4  # Teil 2 genau am Versatz
    assert sorted(p.name for p in (ordner / "audio").iterdir()) == ["system.wav"]

    status = journal.lies_status(ordner)
    assert status["status"] == journal.BEENDET and len(status["teile"]) == 1
    assert status["sitzung_id"] == erster_zustand["sitzung_id"] and status["titel"] == "Workshop"
    data = json.loads((ordner / "transcript.json").read_text(encoding="utf-8"))
    text = " ".join(p["text"] for p in data["paragraphs"])
    assert text.index("Erster Teil.") < text.index("Zweiter Teil.")
    assert [z["chunk_index"] for z in lies_diagnose(ordner) if z["art"] == "abschnitt"] == [1, 2]
    assert load_bilanz(ordner)["live"]["abschnitte"] == 2  # Fazit über beide Teile
    assert [s["id"] for s in journal.lies_journal(ordner).segmente] == [1, 2]
    assert journal.offene_sitzungen(ordner.parent) == [] and journal.lebt(ordner) is False


def test_notabschluss_wenn_der_server_stirbt(tmp_path, monkeypatch):
    emitted = []
    session = None

    def emit(typ, **d):
        emitted.append((typ, d))
        if typ == events.SEGMENT:
            session._server_weg()  # ab hier ist stdout tot

    monkeypatch.setattr(events, "emit", emit)
    monkeypatch.setattr(events, "log", lambda m: None)
    write_wav(tmp_path / "ref.wav", np.concatenate([silence(0.5), speech(1.0), silence(30.0)]))
    session = live_session(tmp_path, monkeypatch, replay_system=tmp_path / "ref.wav")

    assert session.run() == 1  # kein sauberes Ende - aber auch kein Abriss
    assert [d["phase"] for typ, d in emitted if typ == events.STATE][-1] == "stoppt"  # kein "fertig"
    status = journal.lies_status(session.dir)
    assert status["status"] == journal.UNTERBROCHEN
    assert kopf_frames(session.dir / SYSTEM_WAV) == wav_frames(session.dir / SYSTEM_WAV) > SR  # sauber geschlossen
    assert "Text" in (session.dir / "transkript.md").read_text(encoding="utf-8")  # gesichert
    assert journal.lebt(session.dir) is False
    assert [e["segmente"] for e in journal.offene_sitzungen(session.dir.parent)] == [1]


# --- Abschließen ohne Modelle ----------------------------------------------------------------


def unterbrochene_sitzung(tmp_path):
    ordner = sitzung_von_hand(
        tmp_path / "live-2026-10-06_10-00-00",
        segmente=[seg(2, 5.0, 8.0, "Guten Morgen."), seg(1, 0.5, 4.0, "Hallo zusammen.", track="mic", speaker="Ich")],
        teile=[{"nr": 1, "start_sample": 0, "spuren": {"mic": MIC_WAV}}], titel="Abnahme",
    )
    j = journal.Journal(ordner)
    j.shot(id=1, t=3.0, png="frames/0001_00-00-03.jpg", created="2026-10-06 10:00", kind="auto")
    j.takt(12.0)
    j.close()
    write_wav(ordner / MIC_WAV, speech(10.0))
    kopf_abreissen(ordner / MIC_WAV)
    (ordner / "marks.json").write_text('[{"t": 3.0, "png": "frames/0001', encoding="utf-8")  # halb geschrieben
    return ordner


def test_finalize_schreibt_transkript_und_zustand(tmp_path, ereignisse):
    from audioscribe.live.bilanz import load_bilanz
    from audioscribe.live.session import finalisiere_sitzung
    from audioscribe.review.marks import load_marks

    emitted, logged = ereignisse
    ordner = unterbrochene_sitzung(tmp_path)

    assert finalisiere_sitzung(ordner) == 0
    md = (ordner / "transkript.md").read_text(encoding="utf-8")
    assert md.index("Ich:** Hallo zusammen.") < md.index("Guten Morgen.")  # nach Zeit, aus dem Journal
    data = json.loads((ordner / "transcript.json").read_text(encoding="utf-8"))
    assert data["mode"] == "live" and data["model"] == "small" and data["duration_s"] == 12.0
    assert (ordner / "transkript.live.md").read_text(encoding="utf-8") == md
    assert [m.id for m in load_marks(ordner)] == [1]  # marks.json aus dem Journal repariert
    assert "#0001" in (ordner / "transkript.annotiert.md").read_text(encoding="utf-8")
    assert kopf_frames(ordner / MIC_WAV) == 10 * SR  # Kopf repariert
    assert journal.lies_status(ordner)["status"] == journal.BEENDET and journal.lebt(ordner) is False
    assert load_bilanz(ordner)["live"]["aufnahme_s"] == 12.0

    # Der Runner stößt das Nachschärfen nur nach "fertig" mit Ordner an.
    typen = [(typ, d.get("phase") or d.get("teil")) for typ, d in emitted if typ in ("state", "fazit")]
    assert typen == [("state", "laden"), ("fazit", "live"), ("state", "fertig")]
    # Das Gesicherte geht auch an die Oberflaeche - als "restored", damit der Souffleur nichts neu beurteilt.
    gezeigt = [d for typ, d in emitted if typ in ("segment", "shot")]
    assert gezeigt and all(d["restored"] is True for d in gezeigt)
    assert [d["id"] for typ, d in emitted if typ == "shot"] == [1]
    fertig = emitted[-1][1]
    assert fertig["dir"] == str(ordner) and fertig["session"] == ordner.name and fertig["titel"] == "Abnahme"

    assert finalisiere_sitzung(ordner) == 1 and "bereits beendet" in logged[-1]
    assert finalisiere_sitzung(tmp_path / "fehlt") == 1


def test_finalize_wartet_nicht_auf_eine_lebende_sitzung(tmp_path, ereignisse):
    from audioscribe.live.session import finalisiere_sitzung

    _, logged = ereignisse
    ordner = unterbrochene_sitzung(tmp_path)
    sperre = journal.sperre(ordner)
    try:
        assert finalisiere_sitzung(ordner) == 1 and "läuft bereits" in logged[-1]
    finally:
        sperre.gib_frei()
    assert journal.lies_status(ordner)["status"] == journal.LAEUFT


# --- CLI und argv ----------------------------------------------------------------------------


def test_cli_finalize_zweigt_vor_dem_backend_ab(tmp_path, monkeypatch, ereignisse):
    from audioscribe import cli

    def kein_backend():
        raise AssertionError("--finalize darf kein Backend laden")

    monkeypatch.setattr(cli, "_prepare_backend", kein_backend)
    ordner = unterbrochene_sitzung(tmp_path)
    assert cli.main(["live", "--finalize", str(ordner)]) == 0
    assert journal.lies_status(ordner)["status"] == journal.BEENDET
    assert cli.main(["live", "--finalize", str(tmp_path / "fehlt")]) == 1


def test_cli_resume_baut_die_optionen(tmp_path, monkeypatch, capsys):
    from audioscribe import cli

    monkeypatch.setattr(cli, "_prepare_backend", lambda: ("cpu", "int8"))
    gestartet = []

    class FakeSession:
        def __init__(self, opts):
            gestartet.append(opts)

        def run(self):
            return 0

    monkeypatch.setattr("audioscribe.live.session.LiveSession", FakeSession)
    ordner = sitzung_von_hand(tmp_path / "out" / "live-x", status=journal.UNTERBROCHEN)
    assert cli.main(["live", "--resume", str(ordner), "--titel", "Workshop", "--mic", "none"]) == 0
    (opts,) = gestartet
    assert opts.resume_dir == ordner and opts.output_dir == ordner.parent and opts.titel == "Workshop"

    assert cli.main(["live", "--resume", str(tmp_path / "fehlt")]) == 1
    assert cli.main(["live", "--resume", str(ordner), "--transcript", str(ordner)]) == 1
    assert "schliessen sich aus" in capsys.readouterr().out
    sperre = journal.sperre(ordner)
    try:
        assert cli.main(["live", "--resume", str(ordner)]) == 1  # läuft schon woanders
    finally:
        sperre.gib_frei()
    assert len(gestartet) == 1


def test_argv_fuer_resume_titel_und_finalize(tmp_path):
    from audioscribe.ui.jobs import LiveJobOptions, build_finalize_argv, build_live_argv

    ordner = tmp_path / "live-x"
    assert LiveJobOptions(output_dir=tmp_path).resume_dir is None and LiveJobOptions(output_dir=tmp_path).titel == ""
    ohne = build_live_argv(LiveJobOptions(output_dir=tmp_path), prefix=["x"])
    assert not any(a.startswith(("--resume", "--titel")) for a in ohne)  # unverändert ohne Wiederaufnahme
    argv = build_live_argv(LiveJobOptions(output_dir=tmp_path, resume_dir=ordner, titel=" Workshop Reise "),
                           prefix=["x"])
    assert argv[:2] == ["x", "live"] and f"--resume={ordner}" in argv and "--titel=Workshop Reise" in argv
    replay = build_live_argv(LiveJobOptions(output_dir=tmp_path, replay_transcript=tmp_path, titel="Demo"),
                             prefix=["x"])
    assert "--titel=Demo" in replay and not any(a.startswith("--resume") for a in replay)
    assert build_finalize_argv(ordner, prefix=["x"]) == ["x", "live", f"--finalize={ordner}"]


# --- Transkript-Replay: Zustand ja, Fortsetzen nie ---------------------------------------------


def test_transkript_replay_schreibt_zustand_als_replay(tmp_path, ereignisse):
    from pathlib import Path

    from audioscribe.live.replay_transkript import MODELL_REPLAY, ReplayOptions, TranskriptReplaySession

    emitted, _ = ereignisse
    meeting = Path(__file__).parent / "data" / "souffleur" / "meeting"
    session = TranskriptReplaySession(ReplayOptions(output_dir=tmp_path, quelle=meeting, speed=60.0, titel="Demo"))
    session._watch_stdin = lambda: None
    assert session.run() == 0
    status = journal.lies_status(session.dir)
    assert (status["status"], status["replay"], status["titel"], status["modell"]) == (
        journal.BEENDET, True, "Demo", MODELL_REPLAY)
    zustaende = [d for typ, d in emitted if typ == events.STATE]
    assert all(d["sitzung_id"] == status["sitzung_id"] and d["titel"] == "Demo" for d in zustaende)
    # Auch ein abgebrochenes Replay taucht nie unter den unterbrochenen Sitzungen auf.
    journal.schreibe_status(session.dir, status=journal.LAEUFT)
    assert journal.offene_sitzungen(tmp_path) == []
