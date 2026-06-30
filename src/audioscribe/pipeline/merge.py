"""Zusammenfuehren: WhisperX-Result -> Segmente -> 'Sprecher N' -> Absaetze.

Reine Datenlogik ohne ML-Abhaengigkeiten (gut unit-testbar).
"""

from __future__ import annotations

import re
from collections import Counter

from audioscribe.models import Paragraph, Segment, Word

UNKNOWN = "Unbekannt"

# Satzende-Erkennung (grobe Heuristik; gelegentliche Fehlzaehler bei Abkuerzungen
# verschieben nur einen Zeitstempel und sind unkritisch).
_SENTENCE_TERMINATORS = re.compile(r"[.!?…]+")


def _count_sentences(text: str) -> int:
    """Zaehlt Satzenden (Gruppen aus . ! ? …) in einem Text-Stueck."""
    return len(_SENTENCE_TERMINATORS.findall(text))


def _clean_join(parts: list[str]) -> str:
    """Fuegt Wort-Tokens mit Leerzeichen zusammen und korrigiert Satzzeichen-Abstaende."""
    text = " ".join(parts)
    text = re.sub(r"\s+([,.!?;:…»)\]])", r"\1", text)  # kein Space vor Satzzeichen
    text = re.sub(r"([(«\[])\s+", r"\1", text)  # kein Space nach oeffnender Klammer
    return text.strip()


def result_to_segments(result: dict) -> list[Segment]:
    """Konvertiert das WhisperX-Result-Dict in unsere ``Segment``-Liste.

    Robust gegen fehlende Zeitstempel (Alignment kann einzelne Werte auf ``None``
    lassen): ``start``/``end`` werden aus Nachbarwerten bzw. der Wortebene gefuellt.
    """
    raw = result.get("segments", [])
    segments: list[Segment] = []
    prev_end = 0.0
    for s in raw:
        words = [
            Word(w.get("start"), w.get("end"), str(w.get("word", "")).strip(), w.get("speaker"))
            for w in s.get("words", [])
        ]
        start = s.get("start")
        end = s.get("end")
        if start is None:
            word_starts = [w.start for w in words if w.start is not None]
            start = word_starts[0] if word_starts else prev_end
        if end is None:
            word_ends = [w.end for w in words if w.end is not None]
            end = word_ends[-1] if word_ends else start
        text = str(s.get("text", "")).strip()
        segments.append(Segment(float(start), float(end), text, s.get("speaker"), words))
        prev_end = float(end)
    return segments


def fill_segment_speakers(segments: list[Segment]) -> None:
    """Fuellt fehlende Segment-Sprecher aus der Mehrheit der Wort-Sprecher (best effort)."""
    last: str | None = None
    for seg in segments:
        if not seg.speaker:
            votes = Counter(w.speaker for w in seg.words if w.speaker)
            seg.speaker = votes.most_common(1)[0][0] if votes else last
        if seg.speaker:
            last = seg.speaker


def relabel_speakers(segments: list[Segment]) -> int:
    """Mappt rohe Labels (``SPEAKER_00`` ...) auf 'Sprecher 1/2/3' in Erstauftritts-Reihenfolge.

    Mutiert ``segment.speaker`` in-place. Liefert die Anzahl erkannter Sprecher.
    Segmente ohne Sprecher erhalten 'Unbekannt' (zaehlt nicht als Sprecher).
    """
    order: list[str] = []
    for seg in segments:
        if seg.speaker and seg.speaker not in order:
            order.append(seg.speaker)
    mapping = {raw: f"Sprecher {i + 1}" for i, raw in enumerate(order)}
    for seg in segments:
        seg.speaker = mapping.get(seg.speaker, UNKNOWN) if seg.speaker else UNKNOWN
    return len(order)


def _merge_whole_turns(segs: list[Segment]) -> list[Paragraph]:
    """Fasst aufeinanderfolgende Segmente desselben Sprechers zu EINEM Absatz zusammen."""
    paragraphs: list[Paragraph] = []
    for seg in segs:
        text = seg.text.strip()
        speaker = seg.speaker or UNKNOWN
        if paragraphs and paragraphs[-1].speaker == speaker:
            last = paragraphs[-1]
            last.text = f"{last.text} {text}".strip()
            last.end = seg.end
        else:
            paragraphs.append(Paragraph(seg.start, seg.end, speaker, text))
    return paragraphs


def _split_by_sentences(segs: list[Segment], sentences_per_line: int) -> list[Paragraph]:
    """Bricht innerhalb eines Sprecher-Beitrags alle N Saetze um (feiner Zeitstempel).

    Granularitaet kommt aus den Wort-Zeitstempeln (Alignment); fehlen die Woerter
    fuer ein Segment, dient die Segment-Zeit als Fallback. Sprecherwechsel erzwingt
    immer einen Umbruch.
    """
    paragraphs: list[Paragraph] = []
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if cur and cur["parts"]:
            paragraphs.append(
                Paragraph(cur["start"], cur["end"], cur["speaker"], _clean_join(cur["parts"]))
            )
        cur = None

    for seg in segs:
        speaker = seg.speaker or UNKNOWN
        # Tokens = ausgerichtete Woerter, sonst das Segment als ein Token.
        if seg.words:
            tokens = [(w.text, w.start, w.end) for w in seg.words]
        else:
            tokens = [(seg.text, seg.start, seg.end)]
        for text, t_start, t_end in tokens:
            token = (text or "").strip()
            if not token:
                continue
            if cur is None or cur["speaker"] != speaker:
                flush()
                cur = {
                    "start": t_start if t_start is not None else seg.start,
                    "end": t_end if t_end is not None else seg.end,
                    "speaker": speaker,
                    "parts": [],
                    "sentences": 0,
                }
            cur["parts"].append(token)
            if t_end is not None:
                cur["end"] = t_end
            cur["sentences"] += _count_sentences(token)
            if cur["sentences"] >= sentences_per_line:
                flush()

    flush()
    return paragraphs


def build_paragraphs(segments: list[Segment], sentences_per_line: int = 2) -> list[Paragraph]:
    """Erzeugt die zeitgestempelten Ausgabe-Absaetze (FR-5/FR-11).

    ``sentences_per_line`` steuert die Zeitstempel-Granularitaet: alle N Saetze ein
    neuer Zeitstempel. ``0`` (oder negativ) fasst den ganzen Sprecher-Beitrag zu
    einem Block zusammen (altes Verhalten).
    """
    segs = [s for s in sorted(segments, key=lambda s: s.start) if (s.text or "").strip()]
    if not sentences_per_line or sentences_per_line < 1:
        return _merge_whole_turns(segs)
    return _split_by_sentences(segs, sentences_per_line)
