from pathlib import Path

from audioscribe.pipeline.media import (
    AUDIO_SUFFIXES,
    VIDEO_SUFFIXES,
    is_video,
    parse_ffmpeg_duration,
)


def test_is_video_for_common_video_containers():
    for ext in (".mp4", ".mkv", ".mov", ".webm", ".AVI", ".M4V"):
        assert is_video(Path(f"meeting{ext}")), ext


def test_is_video_false_for_audio_and_unknown():
    for ext in (".mp3", ".m4a", ".wav", ".flac", ".txt", ""):
        assert not is_video(Path(f"meeting{ext}")), ext


def test_video_and_audio_suffix_sets_are_disjoint():
    assert VIDEO_SUFFIXES.isdisjoint(AUDIO_SUFFIXES)


# --- Laufzeit aus der ffmpeg-Ausgabe (fuer Fortschritt/Restzeit der Oberflaeche) ---


def test_parse_ffmpeg_duration_liest_stunden_minuten_sekunden():
    assert parse_ffmpeg_duration(
        "  Duration: 00:06:58.97, start: 0.000000, bitrate: 4713 kb/s"
    ) == 418.97
    assert parse_ffmpeg_duration("  Duration: 02:00:00.00, start: 0.0") == 7200.0


def test_parse_ffmpeg_duration_ohne_angabe():
    # MPEG-TS und manche FLV/MKV melden keine Dauer - das ist ein normaler Fall.
    assert parse_ffmpeg_duration("  Duration: N/A, bitrate: N/A") is None
    assert parse_ffmpeg_duration("Error opening input file /etc/hostname.") is None
    assert parse_ffmpeg_duration("") is None
