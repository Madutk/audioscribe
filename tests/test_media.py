from pathlib import Path

from audioscribe.pipeline.media import AUDIO_SUFFIXES, VIDEO_SUFFIXES, is_video


def test_is_video_for_common_video_containers():
    for ext in (".mp4", ".mkv", ".mov", ".webm", ".AVI", ".M4V"):
        assert is_video(Path(f"meeting{ext}")), ext


def test_is_video_false_for_audio_and_unknown():
    for ext in (".mp3", ".m4a", ".wav", ".flac", ".txt", ""):
        assert not is_video(Path(f"meeting{ext}")), ext


def test_video_and_audio_suffix_sets_are_disjoint():
    assert VIDEO_SUFFIXES.isdisjoint(AUDIO_SUFFIXES)
