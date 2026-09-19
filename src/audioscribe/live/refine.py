"""Nachschärfen einer Live-Sitzung mit der Offline-Pipeline (FR-43).

Je Spur Transkription und Alignment; diarisiert wird nur die System-Spur - am Mikrofon
sitzt genau eine Person. Die Standbilder der Sitzung bleiben und werden neu eingebunden.
"""

from __future__ import annotations

from pathlib import Path

from audioscribe.config import settings
from audioscribe.live.speakers import GEGENSEITE, ICH
from audioscribe.live.store import MIC_WAV, SYSTEM_WAV, keep_live_copy, write_transcript
from audioscribe.live.track import SAMPLE_RATE, load_wav
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
    reporter = ConsoleReporter(len(spuren) * (2 if do_align else 1) + (1 if do_diar else 0) + 1)
    step = 0
    segments: list[Segment] = []
    dauer = 0.0
    sprache = settings.whisper_language

    for name, wav in spuren:
        audio = load_wav(wav)
        dauer = max(dauer, len(audio) / SAMPLE_RATE)
        step += 1
        reporter.stage(step, f"Transkription {name} (faster-whisper {settings.whisper_model})")
        result = transcribe(audio, reporter)
        sprache = result.get("language") or sprache
        if do_align:
            step += 1
            reporter.stage(step, f"Wort-Alignment {name}")
            result = align(audio, result, reporter)

        ist_system = wav.name == Path(SYSTEM_WAV).name
        diarisiert = False
        if ist_system and do_diar:
            step += 1
            reporter.stage(step, "Diarisierung System-Audio (pyannote)")
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

    step += 1
    reporter.stage(step, "Zusammenführen & Export")
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
    return session_dir / "transkript.md"
