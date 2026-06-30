"""Zusammenfuehren: WhisperX-Result -> Segmente -> 'Sprecher N' -> Absaetze.

Reine Datenlogik ohne ML-Abhaengigkeiten (gut unit-testbar).
"""

from __future__ import annotations

from collections import Counter

from audioscribe.models import Paragraph, Segment, Word

UNKNOWN = "Unbekannt"


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


def build_paragraphs(segments: list[Segment]) -> list[Paragraph]:
    """Fasst aufeinanderfolgende Segmente desselben Sprechers zu Absaetzen zusammen (FR-5)."""
    paragraphs: list[Paragraph] = []
    for seg in sorted(segments, key=lambda s: s.start):
        text = seg.text.strip()
        if not text:
            continue
        speaker = seg.speaker or UNKNOWN
        if paragraphs and paragraphs[-1].speaker == speaker:
            last = paragraphs[-1]
            last.text = f"{last.text} {text}".strip()
            last.end = seg.end
        else:
            paragraphs.append(Paragraph(seg.start, seg.end, speaker, text))
    return paragraphs
