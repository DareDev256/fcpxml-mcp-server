"""Tests for fcpxml/transcribe.py — transcript intelligence (v0.13).

Matching/merging/inversion helpers are pure and run everywhere; the
transcribe() integration path degrades to None without faster-whisper, which
is itself under test (the graceful-degradation contract).
"""

import json
from pathlib import Path

import pytest

from fcpxml.parser import FCPXMLParser
from fcpxml.transcribe import (
    DEFAULT_FILLERS,
    find_filler_spans,
    find_phrase_spans,
    invert_ranges,
    merge_ranges,
    normalize_word,
    segments_to_srt,
    transcribe,
)


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


WORDS = [
    w("So,", 0.0, 0.3),
    w("um,", 0.4, 0.6),
    w("welcome", 0.7, 1.1),
    w("to", 1.15, 1.25),
    w("the", 1.3, 1.4),
    w("Show!", 1.45, 1.9),
    w("You", 2.0, 2.2),
    w("know,", 2.25, 2.4),
    w("the", 2.5, 2.6),
    w("show", 2.65, 3.0),
    w("is", 3.05, 3.15),
    w("um", 3.2, 3.5),
    w("great.", 3.6, 4.0),
]


class TestNormalizeWord:
    def test_lowercase_and_punctuation(self):
        assert normalize_word("Show!") == "show"
        assert normalize_word(" um, ") == "um"

    def test_keeps_apostrophes(self):
        assert normalize_word("don't") == "don't"

    def test_pure_punctuation_becomes_empty(self):
        assert normalize_word("...") == ""


class TestFindPhraseSpans:
    def test_single_word_multiple_hits(self):
        spans = find_phrase_spans(WORDS, "um")
        assert spans == [(0.4, 0.6), (3.2, 3.5)]

    def test_multi_word_phrase(self):
        spans = find_phrase_spans(WORDS, "welcome to the show")
        assert spans == [(0.7, 1.9)]

    def test_case_and_punctuation_insensitive(self):
        assert find_phrase_spans(WORDS, "THE SHOW!") == [(1.3, 1.9), (2.5, 3.0)]

    def test_no_match(self):
        assert find_phrase_spans(WORDS, "absent phrase") == []

    def test_empty_phrase(self):
        assert find_phrase_spans(WORDS, "") == []
        assert find_phrase_spans(WORDS, "...") == []

    def test_no_overlapping_rescan(self):
        words = [w("go", 0, 1), w("go", 1, 2), w("go", 2, 3)]
        assert find_phrase_spans(words, "go go") == [(0, 2)]


class TestFindFillerSpans:
    def test_default_fillers(self):
        spans = find_filler_spans(WORDS)
        assert (0.4, 0.6) in spans
        assert (3.2, 3.5) in spans

    def test_multi_word_filler(self):
        spans = find_filler_spans(WORDS, fillers=("you know",))
        assert spans == [(2.0, 2.4)]

    def test_sorted_output(self):
        spans = find_filler_spans(WORDS, fillers=("um", "so"))
        assert spans == sorted(spans)

    def test_defaults_are_conservative(self):
        # "like" and "so" are speech, not noise — must not be default-cut.
        assert "like" not in DEFAULT_FILLERS
        assert "so" not in DEFAULT_FILLERS


class TestMergeRanges:
    def test_empty(self):
        assert merge_ranges([]) == []

    def test_overlap_merges(self):
        assert merge_ranges([(0, 2), (1, 3)]) == [(0, 3)]

    def test_disjoint_stay_split(self):
        assert merge_ranges([(0, 1), (2, 3)]) == [(0, 1), (2, 3)]

    def test_min_gap_bridges(self):
        assert merge_ranges([(0, 1), (1.05, 2)], min_gap=0.1) == [(0, 2)]

    def test_unsorted_input(self):
        assert merge_ranges([(2, 3), (0, 1)]) == [(0, 1), (2, 3)]


class TestInvertRanges:
    def test_middle_keep(self):
        assert invert_ranges([(1, 2)], 0, 4) == [(0, 1), (2, 4)]

    def test_keep_at_edges(self):
        assert invert_ranges([(0, 1), (3, 4)], 0, 4) == [(1, 3)]

    def test_nothing_kept_cuts_everything(self):
        assert invert_ranges([], 0, 4) == [(0, 4)]

    def test_everything_kept_cuts_nothing(self):
        assert invert_ranges([(0, 4)], 0, 4) == []

    def test_keep_outside_window_ignored(self):
        assert invert_ranges([(10, 12)], 0, 4) == [(0, 4)]

    def test_overlapping_keeps_merged_first(self):
        assert invert_ranges([(1, 2), (1.5, 3)], 0, 4) == [(0, 1), (3, 4)]

    def test_empty_window(self):
        assert invert_ranges([(0, 1)], 5, 5) == []


class TestTranscribeDegradation:
    def test_missing_file_returns_none(self):
        assert transcribe("/nonexistent/path/audio.wav") is None

    def test_invalid_model_raises(self):
        with pytest.raises(ValueError, match="model_size"):
            transcribe("whatever.wav", model_size="huge-nonsense")

    def test_missing_dependency_returns_none(self, tmp_path, monkeypatch):
        # A real file, but faster_whisper import blocked -> graceful None.
        f = tmp_path / "a.wav"
        f.write_bytes(b"RIFF0000WAVE")
        import builtins

        real_import = builtins.__import__

        def block(name, *args, **kwargs):
            if name.startswith("faster_whisper"):
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", block)
        assert transcribe(str(f)) is None


class TestSegmentsToSrt:
    def test_format(self):
        srt = segments_to_srt(
            [
                {"text": "Hello there.", "start": 0.0, "end": 1.5},
                {"text": "Second line.", "start": 61.25, "end": 3661.0},
            ]
        )
        assert "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n" in srt
        assert "2\n00:01:01,250 --> 01:01:01,000\nSecond line.\n" in srt

    def test_empty(self):
        assert segments_to_srt([]) == ""


# ===== MCP handler integration (no whisper needed — uses cached transcripts) =====

PROJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.13">
  <resources>
    <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
    <asset id="r2" name="interview" start="0s" duration="8s" hasVideo="0" hasAudio="1"
           audioSources="1" audioChannels="1" audioRate="48000">
      <media-rep kind="original-media" src="{src}"/>
    </asset>
  </resources>
  <library>
    <event name="Test">
      <project name="TranscriptTest">
        <sequence format="r1" duration="8s" tcStart="0s">
          <spine>
            <asset-clip ref="r2" offset="0s" name="interview" start="0s" duration="8s" audioRole="dialogue"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""

TRANSCRIPT = {
    "source": "interview.wav",
    "language": "en",
    "duration": 8.0,
    "text": "Um, welcome to the show. Uh, today we talk about editing.",
    "segments": [
        {"text": "Um, welcome to the show.", "start": 0.0, "end": 2.5},
        {"text": "Uh, today we talk about editing.", "start": 3.0, "end": 7.5},
    ],
    "words": [
        {"word": "Um,", "start": 0.0, "end": 0.5},
        {"word": "welcome", "start": 0.5, "end": 1.0},
        {"word": "to", "start": 1.0, "end": 1.25},
        {"word": "the", "start": 1.25, "end": 1.5},
        {"word": "show.", "start": 1.5, "end": 2.5},
        {"word": "Uh,", "start": 3.0, "end": 3.5},
        {"word": "today", "start": 3.5, "end": 4.0},
        {"word": "we", "start": 4.0, "end": 4.25},
        {"word": "talk", "start": 4.25, "end": 4.75},
        {"word": "about", "start": 4.75, "end": 5.25},
        {"word": "editing.", "start": 5.25, "end": 7.5},
    ],
}


def _write_fixture(tmp_path: Path) -> str:
    """Dummy media + cached transcript + project referencing them."""
    wav = tmp_path / "interview.wav"
    wav.write_bytes(b"RIFF0000WAVEnot-real-audio")
    (tmp_path / "interview_transcript.json").write_text(json.dumps(TRANSCRIPT))
    fcpxml_path = tmp_path / "project.fcpxml"
    fcpxml_path.write_text(PROJECT_XML.format(src=f"file://{wav}"))
    return str(fcpxml_path)


def _spine_segments(path: str, name: str = "interview"):
    project = FCPXMLParser().parse_file(path)
    return [c for c in project.primary_timeline.clips if c.name == name]


class TestRemoveFillerWordsHandler:
    async def test_cuts_default_fillers(self, tmp_path):
        from server import handle_remove_filler_words

        filepath = _write_fixture(tmp_path)
        result = await handle_remove_filler_words({"filepath": filepath, "padding": 0})
        assert "_defillered" in result[0].text

        segments = _spine_segments(str(tmp_path / "project_defillered.fcpxml"))
        # um (0-0.5) trims the clip head, uh (3-3.5) splits -> 2 segments, ~7s total
        assert len(segments) == 2
        total = sum(c.duration.seconds for c in segments)
        assert total == pytest.approx(7.0, abs=0.1)
        assert segments[0].source_start.seconds == pytest.approx(0.5, abs=0.05)
        assert segments[1].source_start.seconds == pytest.approx(3.5, abs=0.05)

    async def test_no_fillers_found_saves_nothing(self, tmp_path):
        from server import handle_remove_filler_words

        filepath = _write_fixture(tmp_path)
        result = await handle_remove_filler_words(
            {"filepath": filepath, "fillers": ["nonexistentword"]}
        )
        assert "nothing saved" in result[0].text.lower()
        assert not (tmp_path / "project_defillered.fcpxml").exists()

    async def test_rejects_bad_padding(self, tmp_path):
        from server import handle_remove_filler_words

        filepath = _write_fixture(tmp_path)
        with pytest.raises(ValueError):
            await handle_remove_filler_words({"filepath": filepath, "padding": 99})


class TestEditByTranscriptHandler:
    async def test_remove_phrase(self, tmp_path):
        from server import handle_edit_by_transcript

        filepath = _write_fixture(tmp_path)
        await handle_edit_by_transcript(
            {"filepath": filepath, "phrases": ["welcome to the show"], "padding": 0}
        )
        segments = _spine_segments(str(tmp_path / "project_transcript_edit.fcpxml"))
        # 0.5-2.5 removed -> two segments, ~6s total
        assert len(segments) == 2
        total = sum(c.duration.seconds for c in segments)
        assert total == pytest.approx(6.0, abs=0.1)

    async def test_keep_only_phrase(self, tmp_path):
        from server import handle_edit_by_transcript

        filepath = _write_fixture(tmp_path)
        await handle_edit_by_transcript(
            {"filepath": filepath, "phrases": ["today we talk about editing"],
             "mode": "keep_only", "padding": 0}
        )
        segments = _spine_segments(str(tmp_path / "project_transcript_edit.fcpxml"))
        # keep 3.5-7.5 -> one segment ~4s
        assert len(segments) == 1
        assert segments[0].duration.seconds == pytest.approx(4.0, abs=0.1)
        assert segments[0].source_start.seconds == pytest.approx(3.5, abs=0.1)

    async def test_keep_only_without_match_leaves_clip(self, tmp_path):
        from server import handle_edit_by_transcript

        filepath = _write_fixture(tmp_path)
        result = await handle_edit_by_transcript(
            {"filepath": filepath, "phrases": ["absent phrase"], "mode": "keep_only"}
        )
        assert "left untouched" in result[0].text
        assert not (tmp_path / "project_transcript_edit.fcpxml").exists()

    async def test_rejects_empty_phrases(self, tmp_path):
        from server import handle_edit_by_transcript

        filepath = _write_fixture(tmp_path)
        with pytest.raises(ValueError):
            await handle_edit_by_transcript({"filepath": filepath, "phrases": []})
        with pytest.raises(ValueError):
            await handle_edit_by_transcript({"filepath": filepath, "phrases": ["  "]})

    async def test_rejects_bad_mode(self, tmp_path):
        from server import handle_edit_by_transcript

        filepath = _write_fixture(tmp_path)
        with pytest.raises(ValueError):
            await handle_edit_by_transcript(
                {"filepath": filepath, "phrases": ["x"], "mode": "invert"}
            )


class TestTranscribeMediaHandler:
    async def test_uses_cached_transcript(self, tmp_path):
        from server import handle_transcribe_media

        filepath = _write_fixture(tmp_path)
        result = await handle_transcribe_media({"filepath": filepath})
        text = result[0].text
        assert "interview.wav" in text
        assert "11" in text  # word count
        assert "edit_by_transcript" in text

    async def test_write_srt_from_cache(self, tmp_path):
        from server import handle_transcribe_media

        filepath = _write_fixture(tmp_path)
        await handle_transcribe_media({"filepath": filepath, "write_srt": True})
        srt = (tmp_path / "interview_transcript.srt").read_text()
        assert "welcome to the show" in srt
        assert "-->" in srt

    async def test_no_whisper_no_cache_gives_install_hint(self, tmp_path, monkeypatch):
        import builtins

        from server import handle_transcribe_media

        wav = tmp_path / "raw.wav"
        wav.write_bytes(b"RIFF0000WAVE")
        fcpxml_path = tmp_path / "project.fcpxml"
        fcpxml_path.write_text(PROJECT_XML.format(src=f"file://{wav}"))

        real_import = builtins.__import__

        def block(name, *args, **kwargs):
            if name.startswith("faster_whisper"):
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", block)
        result = await handle_transcribe_media({"filepath": str(fcpxml_path)})
        assert "[transcribe]" in result[0].text

    async def test_missing_media_reported(self, tmp_path):
        from server import handle_transcribe_media

        fcpxml_path = tmp_path / "project.fcpxml"
        fcpxml_path.write_text(PROJECT_XML.format(src="file:///nonexistent/a.wav"))
        result = await handle_transcribe_media({"filepath": str(fcpxml_path)})
        assert "missing" in result[0].text.lower()
