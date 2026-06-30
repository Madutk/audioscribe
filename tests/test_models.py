from audioscribe.models import format_timecode


def test_format_timecode_basic():
    assert format_timecode(0) == "00:00:00"
    assert format_timecode(5) == "00:00:05"
    assert format_timecode(83) == "00:01:23"
    assert format_timecode(3661) == "01:01:01"


def test_format_timecode_rounds_and_clamps():
    assert format_timecode(59.6) == "00:01:00"
    assert format_timecode(-3) == "00:00:00"
