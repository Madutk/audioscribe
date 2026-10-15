"""Nachschärfen einer Live-Sitzung mit der Offline-Pipeline (FR-43).

Je Spur Transkription und Alignment; diarisiert wird nur die System-Spur - am Mikrofon
sitzt genau eine Person. Die Standbilder der Sitzung bleiben und werden neu eingebunden.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from audioscribe.config import resolve_asr_backend, resolve_device, settings
from audioscribe.live import events
from audioscribe.live.bilanz import TEIL_LIVE, TEIL_REFINE, RefineBilanz, beschreibe_refine, save_bilanz
from audioscribe.live.diagnose import ART_UEBERSPRECHEN, DIAGNOSE_NAME, Diagnose, lies_diagnose
from audioscribe.live.speakers import GEGENSEITE, ICH
from audioscribe.live.store import MIC_WAV, SYSTEM_WAV, keep_live_copy, write_transcript
from audioscribe.live.track import SAMPLE_RATE, load_wav
from audioscribe.live.uebersprechen import ausschnitt, gleiche_ab, lag_samples, pruefe, schaetze_lag
from audioscribe.models import Segment
from audioscribe.pipeline.merge import fill_segment_speakers, relabel_speakers, result_to_segments
from audioscribe.progress import ConsoleReporter


def refine_session(session_dir: str | Path) -> Path:
    from audioscribe.pipeline.diarize import diarize
    from audioscribe.pipeline.transcribe import align, transcribe

    session_dir = Path(session_dir)
    spuren = [
        (name, session_dir / wav)
        for name, wav in (("Mikrofon", MIC_WAV), ("System-Audio", SYSTEM_WAV))
        if (session_dir / wav).is_file()
    ]
    if not spuren:
        raise FileNotFoundError(f"Kein Mitschnitt in {session_dir / 'audio'} - keine Live-Sitzung?")

    do_align = settings.enable_alignment
    do_diar = settings.enable_diarization and (session_dir / SYSTEM_WAV).is_file()
    audios = {name: load_wav(wav) for name, wav in spuren}
    # Übersprechen (live/uebersprechen.py): mit beiden Spuren noch einmal über den ganzen
    # Mitschnitt prüfen, was live nur mit dem Rückblick von 40 s entschieden wurde.
    schwelle = settings.live_uebersprechen_schwelle
    mit_filter = schwelle > 0 and len(audios) == 2
    reporter = ConsoleReporter(
        len(spuren) * (2 if do_align else 1) + (1 if do_diar else 0) + (1 if mit_filter else 0) + 1
    )
    step = 0
    segments: list[Segment] = []
    dauer = 0.0
    sprache = settings.whisper_language
    t_start = time.monotonic()
    stufen = _Stufen()  # Fazit: Dauer je Stufe
    backend = resolve_asr_backend(settings.asr_backend, resolve_device(settings.device))
    # Live-Entscheidungen VOR dem ersten eigenen Schreiben lesen - sonst stünden die
    # Offline-Zeilen dieses Laufs mit im Abgleich.
    live_zeilen = [
        z for z in lies_diagnose(session_dir) if z.get("art") == ART_UEBERSPRECHEN and z.get("teil") == TEIL_LIVE
    ]
    diagnose = Diagnose(session_dir / DIAGNOSE_NAME)  # FR-47: an das Live-Log anhängen

    def stage(name: str) -> None:
        nonlocal step
        step += 1
        reporter.stage(step, name)
        stufen.start(name)

    uebersprechen: dict | None = None
    offline: list[tuple[float, float, bool]] = []  # (start_s, end_s, verworfen) je Mikrofon-Segment
    if mit_filter:
        stage("Übersprechen: Zeitversatz schätzen")
        lag_s, lag_score = schaetze_lag(audios["Mikrofon"], audios["System-Audio"])
        uebersprechen = {"geprueft": 0, "verworfen": 0, "lag_s": lag_s, "lag_score": lag_score}

    for name, wav in spuren:
        audio = audios[name]
        dauer = max(dauer, len(audio) / SAMPLE_RATE)
        stage(f"Transkription {name} ({backend} {settings.whisper_model})")
        result = transcribe(audio, reporter)
        sprache = result.get("language") or sprache
        # WhisperX liefert keine Qualitätswerte je Segment - nur Lage und Wortzahl.
        for seg in result.get("segments") or []:
            diagnose.zeile(
                "nachschaerfen",
                teil=TEIL_REFINE,
                spur=name,
                start_s=round(float(seg.get("start") or 0.0), 2),
                end_s=round(float(seg.get("end") or 0.0), 2),
                dauer_s=round(float(seg.get("end") or 0.0) - float(seg.get("start") or 0.0), 2),
                anzahl_woerter=len(str(seg.get("text") or "").split()),
                modell=settings.whisper_model,
            )
        if do_align:
            stage(f"Wort-Alignment {name}")
            result = align(audio, result, reporter)

        ist_system = wav.name == Path(SYSTEM_WAV).name
        if uebersprechen is not None and not ist_system:
            result["segments"] = _filtere_uebersprechen(
                result.get("segments") or [], audio, audios["System-Audio"], schwelle, diagnose, offline, uebersprechen
            )
            reporter.info(
                f"Übersprechen: {uebersprechen['verworfen']} von {uebersprechen['geprueft']} Mikrofon-Segmenten "
                f"verworfen (Zeitversatz {uebersprechen['lag_s']:.2f} s)".replace(".", ",")
            )
        diarisiert = False
        if ist_system and do_diar:
            stage("Diarisierung System-Audio (pyannote)")
            try:
                result = diarize(audio, result, reporter)
                diarisiert = True
            except RuntimeError as exc:
                reporter.info(f"Diarisierung übersprungen: {str(exc).splitlines()[0]}")

        teil = result_to_segments(result)
        if diarisiert:
            fill_segment_speakers(teil)
            relabel_speakers(teil)
        else:
            label = GEGENSEITE if ist_system else ICH
            for seg in teil:
                seg.speaker = label
                for word in seg.words:
                    word.speaker = label
        segments += teil

    stage("Zusammenführen & Export")
    keep_live_copy(session_dir, overwrite=False)
    write_transcript(
        session_dir,
        segments,
        duration_s=dauer,
        language=sprache,
        model=settings.whisper_model,
        mode="refined",
        sentences_per_timestamp=settings.sentences_per_timestamp,
    )
    reporter.info(f"Markdown: {session_dir / 'transkript.md'}")
    gesamt = time.monotonic() - t_start
    if uebersprechen is not None:
        uebersprechen.update(gleiche_ab(live_zeilen, offline))
    bilanz = RefineBilanz(
        gesamt_s=round(gesamt, 1),
        audio_s=round(dauer, 1),
        tempo=round(gesamt / dauer, 2) if dauer > 0 else None,
        modell=settings.whisper_model,
        stufen=stufen.close(),
        uebersprechen=uebersprechen,
    )
    for st in bilanz.stufen:
        diagnose.zeile("stufe", teil=TEIL_REFINE, name=st["name"], dauer_s=st["dauer_s"])
    diagnose.close()
    save_bilanz(session_dir, TEIL_REFINE, bilanz)
    reporter.info(beschreibe_refine(bilanz))
    events.emit(events.FAZIT, teil=TEIL_REFINE, **asdict(bilanz))
    return session_dir / "transkript.md"


def _filtere_uebersprechen(
    segmente: list[dict],
    mic: object,
    system: object,
    schwelle: float,
    diagnose: Diagnose,
    offline: list[tuple[float, float, bool]],
    zaehler: dict,
) -> list[dict]:
    """Mikrofon-Segmente, die nur das Echo der System-Spur sind, aus dem Ergebnis nehmen.

    Jede Prüfung steht als Zeile im Diagnose-Log (``teil`` nachschaerfen); ``offline`` sammelt
    die Entscheidungen für den Abgleich mit den Live-Zeilen. Segmente ohne Zeiten bleiben."""
    lag_min, lag_max = lag_samples()
    behalten: list[dict] = []
    for seg in segmente:
        start, end = seg.get("start"), seg.get("end")
        if start is None or end is None or float(end) <= float(start):
            behalten.append(seg)
            continue
        s, e = int(float(start) * SAMPLE_RATE), int(float(end) * SAMPLE_RATE)
        p = pruefe(
            ausschnitt(mic, s, e),
            ausschnitt(system, s - lag_max, e - lag_min),
            dauer_s=(e - s) / SAMPLE_RATE,
            schwelle=schwelle,
        )
        zaehler["geprueft"] += 1
        if p.verworfen:
            zaehler["verworfen"] += 1
        else:
            behalten.append(seg)
        offline.append((float(start), float(end), p.verworfen))
        diagnose.uebersprechen(
            teil=TEIL_REFINE,
            spur="Mikrofon",
            start_s=round(float(start), 2),
            end_s=round(float(end), 2),
            dauer_s=p.dauer_s,
            score=p.score,
            lag_s=p.lag_s,
            schwelle=p.schwelle,
            entscheidung=p.entscheidung,
            grund=p.grund,
        )
    return behalten


class _Stufen:
    """Stoppuhr je Stufe: ``start`` schließt die vorige, ``close`` die letzte."""

    def __init__(self) -> None:
        self.liste: list[dict] = []
        self._seit: float | None = None

    def start(self, name: str) -> None:
        self.close()
        self.liste.append({"name": name, "dauer_s": 0.0})
        self._seit = time.monotonic()

    def close(self) -> list[dict]:
        if self._seit is not None and self.liste:
            self.liste[-1]["dauer_s"] = round(time.monotonic() - self._seit, 1)
            self._seit = None
        return self.liste
