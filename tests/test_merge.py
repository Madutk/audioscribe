from audioscribe.models import Segment, Word
from audioscribe.pipeline.merge import (
    build_paragraphs,
    fill_segment_speakers,
    relabel_speakers,
    result_to_segments,
)


def test_relabel_in_first_appearance_order():
    # SPEAKER_01 tritt zuerst auf -> "Sprecher 1"
    segs = [
        Segment(0.0, 1.0, "a", "SPEAKER_01"),
        Segment(1.0, 2.0, "b", "SPEAKER_00"),
        Segment(2.0, 3.0, "c", "SPEAKER_01"),
    ]
    n = relabel_speakers(segs)
    assert n == 2
    assert [s.speaker for s in segs] == ["Sprecher 1", "Sprecher 2", "Sprecher 1"]


def test_relabel_unknown_for_missing_speaker():
    segs = [Segment(0.0, 1.0, "a", None)]
    n = relabel_speakers(segs)
    assert n == 0
    assert segs[0].speaker == "Unbekannt"


def test_build_paragraphs_merges_consecutive_same_speaker():
    segs = [
        Segment(0.0, 1.0, "Hallo", "Sprecher 1"),
        Segment(1.0, 2.0, "zusammen", "Sprecher 1"),
        Segment(2.0, 3.0, "Ja", "Sprecher 2"),
        Segment(3.0, 4.0, "genau", "Sprecher 1"),
    ]
    paras = build_paragraphs(segs)
    assert len(paras) == 3
    assert paras[0].speaker == "Sprecher 1"
    assert paras[0].text == "Hallo zusammen"
    assert paras[0].start == 0.0 and paras[0].end == 2.0
    assert paras[1].text == "Ja"
    assert paras[2].text == "genau"


def test_build_paragraphs_splits_every_n_sentences_via_word_timestamps():
    words = [
        Word(0.0, 0.5, "Eins."),
        Word(0.6, 1.0, "Zwei."),
        Word(1.1, 1.5, "Drei."),
        Word(1.6, 2.0, "Vier."),
    ]
    seg = Segment(0.0, 2.0, "Eins. Zwei. Drei. Vier.", "Sprecher 1", words=words)
    paras = build_paragraphs([seg], sentences_per_line=2)
    assert len(paras) == 2
    assert paras[0].text == "Eins. Zwei." and paras[0].start == 0.0
    # Feiner Zeitstempel: zweite Zeile beginnt beim ersten Wort der naechsten Saetze.
    assert paras[1].text == "Drei. Vier." and paras[1].start == 1.1


def test_build_paragraphs_speaker_change_forces_break():
    s1 = Segment(0.0, 1.0, "Hallo.", "Sprecher 1", words=[Word(0.0, 1.0, "Hallo.")])
    s2 = Segment(1.0, 2.0, "Ja?", "Sprecher 2", words=[Word(1.0, 2.0, "Ja?")])
    paras = build_paragraphs([s1, s2], sentences_per_line=2)
    assert [p.speaker for p in paras] == ["Sprecher 1", "Sprecher 2"]
    assert paras[1].start == 1.0


def test_build_paragraphs_zero_merges_whole_turn():
    s1 = Segment(0.0, 1.0, "Eins. Zwei.", "Sprecher 1", words=[Word(0.0, 1.0, "Eins. Zwei.")])
    s2 = Segment(1.0, 2.0, "Drei.", "Sprecher 1", words=[Word(1.0, 2.0, "Drei.")])
    paras = build_paragraphs([s1, s2], sentences_per_line=0)
    assert len(paras) == 1
    assert paras[0].speaker == "Sprecher 1"
    assert paras[0].start == 0.0


def test_fill_segment_speakers_from_word_majority():
    seg = Segment(
        0.0,
        2.0,
        "text",
        None,
        words=[Word(0.0, 0.5, "a", "SPEAKER_00"), Word(0.5, 1.0, "b", "SPEAKER_00"),
               Word(1.0, 1.5, "c", "SPEAKER_01")],
    )
    fill_segment_speakers([seg])
    assert seg.speaker == "SPEAKER_00"


def test_result_to_segments_fills_missing_timestamps():
    result = {
        "language": "de",
        "segments": [
            {"start": None, "end": None, "text": "x",
             "words": [{"start": 1.0, "end": 1.5, "word": "x"}]},
            {"start": 2.0, "end": 3.0, "text": "y", "words": []},
        ],
    }
    segs = result_to_segments(result)
    assert segs[0].start == 1.0 and segs[0].end == 1.5
    assert segs[1].start == 2.0
