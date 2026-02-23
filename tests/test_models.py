"""Tests for FCPXML data models — TimeValue, Timecode, Timeline, and helpers.

Covers the core time math and model properties that underpin all 34 tools.
"""

import pytest

from fcpxml.models import (
    Clip,
    FlashFrame,
    FlashFrameSeverity,
    GapInfo,
    Keyword,
    Marker,
    MarkerType,
    PacingConfig,
    Project,
    Timecode,
    Timeline,
    TimeValue,
    ValidationIssue,
    ValidationIssueType,
    ValidationResult,
)


class TestTimeValueCreation:
    """Test TimeValue construction from various input formats."""

    def test_from_rational_string(self):
        tv = TimeValue.from_timecode("90/30s")
        assert tv.numerator == 90 and tv.denominator == 30

    def test_from_seconds_string(self):
        assert TimeValue.from_timecode("5s", fps=24.0).to_seconds() == pytest.approx(5.0, abs=0.01)

    def test_from_seconds_float(self):
        assert TimeValue.from_seconds(2.5, fps=24.0).to_seconds() == pytest.approx(2.5, abs=0.05)

    def test_from_timecode_hhmmssff(self):
        assert TimeValue.from_timecode("00:01:30:15", fps=30.0).to_seconds() == pytest.approx(90.5, abs=0.05)

    def test_from_timecode_hhmmss(self):
        assert TimeValue.from_timecode("00:02:00", fps=24.0).to_seconds() == pytest.approx(120.0, abs=0.05)

    def test_from_frames_string(self):
        assert TimeValue.from_timecode("48f", fps=24.0).to_seconds() == pytest.approx(2.0, abs=0.05)

    def test_from_plain_number(self):
        assert TimeValue.from_timecode("3.5", fps=24.0).to_seconds() == pytest.approx(3.5, abs=0.05)

    def test_from_empty_string(self):
        assert TimeValue.from_timecode("") == TimeValue.zero()

    def test_zero(self):
        tv = TimeValue.zero()
        assert tv.numerator == 0 and tv.to_seconds() == 0.0

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid timecode format"):
            TimeValue.from_timecode("not_a_timecode")

    def test_drop_frame_separator(self):
        assert TimeValue.from_timecode("00:00:10;15", fps=30.0).to_seconds() == pytest.approx(10.5, abs=0.05)


class TestTimeValueConversions:

    def test_to_fcpxml(self):
        assert TimeValue(3, 1).to_fcpxml() == "3s"
        assert TimeValue(90, 30).to_fcpxml() == "3s"  # simplifies
        assert TimeValue(75, 30).to_fcpxml() == "5/2s"

    def test_to_seconds(self):
        assert TimeValue(72, 24).to_seconds() == pytest.approx(3.0)
        assert TimeValue(5, 0).to_seconds() == 0.0  # zero denominator guard

    def test_to_timecode(self):
        assert TimeValue(2700, 30).to_timecode(fps=30.0) == "00:01:30:00"
        assert TimeValue(2715, 30).to_timecode(fps=30.0) == "00:01:30:15"

    def test_to_frames(self):
        assert TimeValue(3, 1).to_frames(fps=24.0) == 72


class TestTimeValueArithmetic:

    def test_add(self):
        assert (TimeValue(72, 24) + TimeValue(48, 24)).to_seconds() == pytest.approx(5.0)

    def test_sub(self):
        assert (TimeValue(120, 24) - TimeValue(72, 24)).to_seconds() == pytest.approx(2.0)

    def test_add_different_denominators(self):
        assert (TimeValue(72, 24) + TimeValue(150, 30)).to_seconds() == pytest.approx(8.0)

    def test_mul(self):
        assert (TimeValue(72, 24) * 2).to_seconds() == pytest.approx(6.0)

    def test_div(self):
        assert (TimeValue(72, 24) / 3).to_seconds() == pytest.approx(1.0)

    def test_simplify(self):
        s = TimeValue(120, 48).simplify()
        assert s.numerator == 5 and s.denominator == 2

    def test_simplify_zero(self):
        s = TimeValue(0, 48).simplify()
        assert s.numerator == 0 and s.denominator == 1


class TestTimeValueComparisons:

    def test_ordering(self):
        small, big = TimeValue(48, 24), TimeValue(72, 24)
        assert small < big and small <= big
        assert big > small and big >= small

    def test_equality(self):
        assert TimeValue(72, 24) == TimeValue(72, 24)
        assert TimeValue(3, 1) == TimeValue(72, 24)  # cross-denominator
        assert TimeValue(72, 24) != "not a timevalue"

    def test_repr(self):
        r = repr(TimeValue(72, 24))
        assert "72" in r and "24" in r and "3.000s" in r


class TestTimeline:

    @staticmethod
    def _make(durations, fps=24.0):
        clips, offset = [], 0.0
        for i, dur in enumerate(durations):
            clips.append(Clip(
                name=f"clip_{i}",
                start=Timecode(frames=int(offset * fps), frame_rate=fps),
                duration=Timecode(frames=int(dur * fps), frame_rate=fps),
            ))
            offset += dur
        return Timeline(
            name="test",
            duration=Timecode(frames=int(offset * fps), frame_rate=fps),
            frame_rate=fps, clips=clips,
        )

    def test_total_clips(self):
        assert self._make([2, 3, 1]).total_clips == 3

    def test_total_cuts(self):
        assert self._make([2, 3, 1]).total_cuts == 2
        assert self._make([]).total_cuts == 0

    def test_avg_duration(self):
        assert self._make([2, 4, 6]).average_clip_duration == pytest.approx(4.0, abs=0.1)
        assert self._make([]).average_clip_duration == 0.0

    def test_cuts_per_minute(self):
        assert self._make([2, 2, 2]).cuts_per_minute == pytest.approx(20.0, abs=0.5)

    def test_shorter_than(self):
        assert len(self._make([0.2, 5, 0.3, 2]).get_clips_shorter_than(0.5)) == 2

    def test_longer_than(self):
        assert len(self._make([1, 10, 2, 15]).get_clips_longer_than(5)) == 2

    def test_clip_at(self):
        clip = self._make([2, 3, 1]).get_clip_at(3.5)
        assert clip is not None and clip.name == "clip_1"
        assert self._make([2, 3]).get_clip_at(999) is None

    def test_by_keyword(self):
        tl = self._make([2, 3])
        tl.clips[0].keywords = [Keyword(value="interview")]
        assert len(tl.get_clips_by_keyword("interview")) == 1


class TestProject:

    def test_primary_timeline(self):
        tl = Timeline(name="main", duration=Timecode(frames=0, frame_rate=24.0))
        assert Project(name="test", timelines=[tl]).primary_timeline is tl

    def test_primary_timeline_empty(self):
        assert Project(name="empty").primary_timeline is None


class TestMarker:

    def test_youtube_timestamp_minutes(self):
        m = Marker(name="Ch", start=Timecode(frames=2160, frame_rate=24.0))
        assert m.to_youtube_timestamp() == "1:30"

    def test_youtube_timestamp_hours(self):
        m = Marker(name="Act", start=Timecode(frames=24 * 3700, frame_rate=24.0))
        assert m.to_youtube_timestamp().count(":") == 2


class TestTimecode:
    """Test Timecode — the frame-based time representation used by the parser."""

    def test_from_rational_fraction(self):
        tc = Timecode.from_rational("3600/24s", frame_rate=24.0)
        assert tc.frames == 3600
        assert tc.seconds == pytest.approx(150.0)

    def test_from_rational_whole_seconds(self):
        tc = Timecode.from_rational("5s", frame_rate=30.0)
        assert tc.frames == 150
        assert tc.seconds == pytest.approx(5.0)

    def test_from_rational_plain_number(self):
        tc = Timecode.from_rational("2.5", frame_rate=24.0)
        assert tc.frames == 60
        assert tc.seconds == pytest.approx(2.5)

    def test_from_rational_empty_string(self):
        tc = Timecode.from_rational("", frame_rate=24.0)
        assert tc.frames == 0

    def test_to_smpte_basic(self):
        tc = Timecode(frames=2700, frame_rate=30.0)
        assert tc.to_smpte() == "00:01:30:00"

    def test_to_smpte_with_frames(self):
        tc = Timecode(frames=2715, frame_rate=30.0)
        assert tc.to_smpte() == "00:01:30:15"

    def test_to_smpte_drop_frame_separator(self):
        tc = Timecode(frames=48, frame_rate=24.0, drop_frame=True)
        assert ";" in tc.to_smpte()

    def test_to_smpte_hours(self):
        tc = Timecode(frames=24 * 3661, frame_rate=24.0)
        smpte = tc.to_smpte()
        assert smpte.startswith("01:01:01")

    def test_to_rational(self):
        tc = Timecode(frames=72, frame_rate=24.0)
        assert tc.to_rational() == "72/24s"

    def test_to_time_value(self):
        tc = Timecode(frames=72, frame_rate=24.0)
        tv = tc.to_time_value()
        assert tv.numerator == 72
        assert tv.denominator == 24
        assert tv.to_seconds() == pytest.approx(3.0)

    def test_total_frames_alias(self):
        tc = Timecode(frames=100, frame_rate=30.0)
        assert tc.total_frames == 100


class TestClipProperties:
    """Test Clip computed properties."""

    def test_end_timecode(self):
        clip = Clip(
            name="test",
            start=Timecode(frames=48, frame_rate=24.0),
            duration=Timecode(frames=72, frame_rate=24.0),
        )
        assert clip.end.frames == 120
        assert clip.end.frame_rate == 24.0

    def test_duration_seconds(self):
        clip = Clip(
            name="test",
            start=Timecode(frames=0, frame_rate=24.0),
            duration=Timecode(frames=72, frame_rate=24.0),
        )
        assert clip.duration_seconds == pytest.approx(3.0)

    def test_keyword_values(self):
        clip = Clip(
            name="test",
            start=Timecode(frames=0, frame_rate=24.0),
            duration=Timecode(frames=24, frame_rate=24.0),
            keywords=[Keyword(value="interview"), Keyword(value="broll")],
        )
        assert clip.keyword_values == ["interview", "broll"]

    def test_keyword_values_empty(self):
        clip = Clip(
            name="test",
            start=Timecode(frames=0, frame_rate=24.0),
            duration=Timecode(frames=24, frame_rate=24.0),
        )
        assert clip.keyword_values == []


class TestFlashFrame:

    def test_is_critical(self):
        ff = FlashFrame(
            clip_name="bad_clip", clip_id="c1",
            start=Timecode(frames=0, frame_rate=24.0),
            duration_frames=1, duration_seconds=0.04,
            severity=FlashFrameSeverity.CRITICAL,
        )
        assert ff.is_critical is True

    def test_is_not_critical(self):
        ff = FlashFrame(
            clip_name="short_clip", clip_id="c2",
            start=Timecode(frames=0, frame_rate=24.0),
            duration_frames=4, duration_seconds=0.17,
            severity=FlashFrameSeverity.WARNING,
        )
        assert ff.is_critical is False


class TestGapInfo:

    def test_timecode_property(self):
        gap = GapInfo(
            start=Timecode(frames=2700, frame_rate=30.0),
            duration_frames=30, duration_seconds=1.0,
            previous_clip="Clip_A", next_clip="Clip_B",
        )
        assert gap.timecode == "00:01:30:00"


class TestValidationResult:

    def test_summary_format(self):
        result = ValidationResult(
            is_valid=False, health_score=72,
            issues=[
                ValidationIssue(issue_type=ValidationIssueType.FLASH_FRAME, severity="error", message="e"),
                ValidationIssue(issue_type=ValidationIssueType.GAP, severity="warning", message="w"),
            ],
            flash_frames=[
                FlashFrame("c", "c1", Timecode(0, 24.0), 1, 0.04, FlashFrameSeverity.CRITICAL),
            ],
            gaps=[
                GapInfo(Timecode(0, 24.0), 10, 0.4),
            ],
        )
        s = result.summary()
        assert "72%" in s
        assert "Errors: 1" in s
        assert "Warnings: 1" in s
        assert "Flash frames: 1" in s
        assert "Gaps: 1" in s


class TestMarkerType:

    @pytest.mark.parametrize("value,expected", [
        ("todo", MarkerType.TODO),
        ("TODO", MarkerType.TODO),
        ("completed", MarkerType.COMPLETED),
        ("COMPLETED", MarkerType.COMPLETED),
        ("standard", MarkerType.STANDARD),
        ("chapter", MarkerType.CHAPTER),
    ])
    def test_from_string_current_values(self, value, expected):
        assert MarkerType.from_string(value) == expected

    @pytest.mark.parametrize("alias,expected", [
        ("todo-marker", MarkerType.TODO),
        ("completed-marker", MarkerType.COMPLETED),
        ("chapter-marker", MarkerType.CHAPTER),
    ])
    def test_from_string_legacy_aliases(self, alias, expected):
        """Legacy spec values (e.g. 'todo-marker') resolve to current enum."""
        assert MarkerType.from_string(alias) == expected

    @pytest.mark.parametrize("value,expected", [
        ("Todo", MarkerType.TODO),
        ("tOdO", MarkerType.TODO),
        ("Completed", MarkerType.COMPLETED),
        ("cOMPLETED", MarkerType.COMPLETED),
        ("Standard", MarkerType.STANDARD),
        ("CHAPTER", MarkerType.CHAPTER),
    ])
    def test_from_string_mixed_case(self, value, expected):
        """Case should never matter — FCP specs are inconsistent about casing."""
        assert MarkerType.from_string(value) == expected

    @pytest.mark.parametrize("alias,expected", [
        ("  todo-marker  ", MarkerType.TODO),
        (" completed-marker ", MarkerType.COMPLETED),
        ("\tchapter-marker\t", MarkerType.CHAPTER),
    ])
    def test_from_string_legacy_aliases_with_whitespace(self, alias, expected):
        """Whitespace around legacy aliases must be stripped before matching."""
        assert MarkerType.from_string(alias) == expected

    def test_enum_values_are_lowercase(self):
        """Enum .value must be lowercase strings — they're used as dict keys."""
        assert MarkerType.TODO.value == "todo"
        assert MarkerType.COMPLETED.value == "completed"
        assert MarkerType.STANDARD.value == "standard"
        assert MarkerType.CHAPTER.value == "chapter"

    def test_from_string_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid marker type"):
            MarkerType.from_string("nonexistent")

    def test_xml_tag_chapter_vs_marker(self):
        assert MarkerType.CHAPTER.xml_tag == "chapter-marker"
        assert MarkerType.TODO.xml_tag == "marker"
        assert MarkerType.COMPLETED.xml_tag == "marker"
        assert MarkerType.STANDARD.xml_tag == "marker"


class TestPacingConfig:

    def test_pacing_ranges(self):
        assert PacingConfig(pacing="slow").get_duration_range() == (5.0, 10.0)
        assert PacingConfig(pacing="fast").get_duration_range() == (0.5, 2.0)
        assert PacingConfig(pacing="unknown").get_duration_range() == (2.0, 5.0)
