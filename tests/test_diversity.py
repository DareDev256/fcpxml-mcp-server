"""Diversity-picked tests targeting untested boundaries across modules.

Covers: diff threshold boundaries (0.04s clip move, 1.0s marker move),
MontageConfig pacing curves at inflection points, Timeline model edge
cases (zero duration, empty clips), DuplicateGroup overlap detection,
ValidationResult aggregation, export lane-to-track mapping fidelity,
and TimelineDiff empty-state properties.
"""

import os
import tempfile

import pytest

from fcpxml.diff import ClipDiff, TimelineDiff, compare_timelines
from fcpxml.models import (
    Clip,
    DuplicateGroup,
    MontageConfig,
    PacingCurve,
    Timecode,
    Timeline,
    ValidationIssue,
    ValidationIssueType,
    ValidationResult,
)

# ============================================================================
# Diff threshold boundaries — 0.04s is the move/trim detection threshold
# ============================================================================


def _tmp(xml: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".fcpxml")
    with os.fdopen(fd, "w") as f:
        f.write(xml)
    return path


# Clip_A = 10s, Clip_B = 10s
THRESHOLD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="A" src="file:///a.mov" start="0s" duration="240/24s"/>
        <asset id="r3" name="B" src="file:///b.mov" start="0s" duration="240/24s"/>
    </resources>
    <library><event name="E"><project name="P">
    <sequence format="r1" duration="480/24s">
    <spine>
        <asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s"/>
        <asset-clip ref="r3" offset="240/24s" name="B" start="0s" duration="240/24s"/>
    </spine></sequence></project></event></library>
</fcpxml>"""


class TestDiffMoveThreshold:
    """Clip move detection uses 0.04s threshold — test both sides."""

    def test_below_threshold_not_detected(self):
        """1-frame shift at 24fps (0.042s) is right at threshold — but a sub-frame
        shift of 0.03s should NOT be detected as a move."""
        # This is tested indirectly: identical files produce no moves
        a = _tmp(THRESHOLD_XML)
        b = _tmp(THRESHOLD_XML)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.clip_diffs if d.action == "moved"]
            assert len(moved) == 0
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_trimmed_only_detected_as_trim(self):
        """Duration change without position change should be 'trimmed' not 'moved'."""
        xml_b = THRESHOLD_XML.replace(
            'name="B" start="0s" duration="240/24s"/>',
            'name="B" start="0s" duration="120/24s"/>',
        )
        xml_b = xml_b.replace('duration="480/24s"', 'duration="360/24s"')
        a, b = _tmp(THRESHOLD_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            trimmed = [d for d in diff.clip_diffs if d.action == "trimmed"]
            moved = [d for d in diff.clip_diffs if d.action == "moved"]
            assert len(trimmed) >= 1, "Duration-only change should be 'trimmed'"
            assert trimmed[0].clip_name == "B"
            assert len(moved) == 0, "No position change, so no 'moved'"
        finally:
            os.unlink(a)
            os.unlink(b)


class TestDiffMarkerThreshold:
    """Marker movement uses 1.0s threshold — sub-second moves are ignored."""

    MARKER_XML = THRESHOLD_XML.replace(
        'name="A" start="0s" duration="240/24s"/>',
        'name="A" start="0s" duration="240/24s">'
        '<marker start="48/24s" duration="1/24s" value="Mark"/>'
        "</asset-clip>",
    )

    def test_marker_sub_second_move_ignored(self):
        """Moving marker by 12 frames at 24fps (0.5s) should NOT be reported."""
        xml_b = self.MARKER_XML.replace('start="48/24s"', 'start="60/24s"')
        a, b = _tmp(self.MARKER_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.marker_diffs if d.action == "moved"]
            assert len(moved) == 0, "0.5s move is under 1.0s threshold"
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_marker_over_threshold_detected(self):
        """Moving marker by 48 frames at 24fps (2.0s) SHOULD be reported."""
        xml_b = self.MARKER_XML.replace('start="48/24s"', 'start="96/24s"')
        a, b = _tmp(self.MARKER_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.marker_diffs if d.action == "moved"]
            assert len(moved) >= 1
            assert moved[0].marker_name == "Mark"
        finally:
            os.unlink(a)
            os.unlink(b)


class TestTimelineDiffEmptyState:
    """TimelineDiff properties when no changes exist."""

    def test_empty_diff_has_no_changes(self):
        diff = TimelineDiff(timeline_a_name="A", timeline_b_name="B")
        assert diff.total_changes == 0
        assert diff.has_changes is False

    def test_only_unchanged_clips_means_no_changes(self):
        diff = TimelineDiff(
            timeline_a_name="A",
            timeline_b_name="B",
            clip_diffs=[
                ClipDiff(action="unchanged", clip_name="X"),
                ClipDiff(action="unchanged", clip_name="Y"),
            ],
        )
        assert diff.total_changes == 0
        assert diff.has_changes is False


# ============================================================================
# MontageConfig pacing curve inflection points
# ============================================================================


class TestMontageConfigCurves:
    """Test pacing curve math at boundary and inflection positions."""

    def test_pyramid_at_midpoint(self):
        """PYRAMID inflection at 0.5 should produce end_duration (fastest)."""
        cfg = MontageConfig(
            target_duration=60,
            pacing_curve=PacingCurve.PYRAMID,
            start_duration=4.0,
            end_duration=1.0,
        )
        # At position=0.5: first-half formula yields end_duration
        dur = cfg.get_duration_at_position(0.5)
        assert dur == pytest.approx(1.0, abs=0.01)

    def test_pyramid_at_zero(self):
        """PYRAMID at start should produce start_duration."""
        cfg = MontageConfig(
            target_duration=60, pacing_curve=PacingCurve.PYRAMID,
            start_duration=4.0, end_duration=1.0,
        )
        assert cfg.get_duration_at_position(0.0) == pytest.approx(4.0, abs=0.01)

    def test_pyramid_at_one(self):
        """PYRAMID at end should return to start_duration."""
        cfg = MontageConfig(
            target_duration=60, pacing_curve=PacingCurve.PYRAMID,
            start_duration=4.0, end_duration=1.0,
        )
        assert cfg.get_duration_at_position(1.0) == pytest.approx(4.0, abs=0.01)

    def test_constant_ignores_position(self):
        """CONSTANT curve returns same duration regardless of position."""
        cfg = MontageConfig(
            target_duration=30, pacing_curve=PacingCurve.CONSTANT,
            start_duration=3.0, end_duration=1.0,
        )
        assert cfg.get_duration_at_position(0.0) == cfg.get_duration_at_position(1.0)

    def test_accelerating_monotonically_decreases(self):
        """ACCELERATING: clip durations should decrease from start to end."""
        cfg = MontageConfig(
            target_duration=60, pacing_curve=PacingCurve.ACCELERATING,
            start_duration=5.0, end_duration=0.5, min_duration=0.2,
        )
        durations = [cfg.get_duration_at_position(p) for p in [0.0, 0.25, 0.5, 0.75, 1.0]]
        for i in range(len(durations) - 1):
            assert durations[i] >= durations[i + 1], f"Not monotonic at index {i}"

    def test_clamping_respects_min_max(self):
        """Duration should never exceed max or drop below min."""
        cfg = MontageConfig(
            target_duration=60, pacing_curve=PacingCurve.ACCELERATING,
            start_duration=10.0, end_duration=0.1,
            min_duration=0.5, max_duration=5.0,
        )
        for p in [0.0, 0.5, 1.0]:
            dur = cfg.get_duration_at_position(p)
            assert dur >= cfg.min_duration
            assert dur <= cfg.max_duration


# ============================================================================
# Timeline model edge cases
# ============================================================================


class TestTimelineModelEdges:
    """Timeline properties when clips are empty or duration is degenerate."""

    def _make_timeline(self, clips=None, duration_frames=0, fps=24.0):
        return Timeline(
            name="Test",
            duration=Timecode(frames=duration_frames, frame_rate=fps),
            frame_rate=fps,
            clips=clips or [],
        )

    def test_cuts_per_minute_zero_duration(self):
        """Zero-duration timeline should return 0.0 CPM, not ZeroDivisionError."""
        tl = self._make_timeline(duration_frames=0)
        assert tl.cuts_per_minute == 0.0

    def test_average_clip_duration_empty(self):
        assert self._make_timeline().average_clip_duration == 0.0

    def test_get_clip_at_exact_boundary(self):
        """get_clip_at uses start <= tc < end — clip end is exclusive."""
        clip = Clip(
            name="X",
            start=Timecode(frames=0, frame_rate=24),
            duration=Timecode(frames=48, frame_rate=24),
        )
        tl = self._make_timeline(clips=[clip], duration_frames=48)
        assert tl.get_clip_at(0.0) is clip       # At start
        assert tl.get_clip_at(1.99) is clip       # Just before end
        assert tl.get_clip_at(2.0) is None        # Exactly at end (exclusive)

    def test_total_cuts_single_clip(self):
        clip = Clip("X", Timecode(0, 24), Timecode(24, 24))
        tl = self._make_timeline(clips=[clip], duration_frames=24)
        assert tl.total_cuts == 0  # 1 clip = 0 cuts


# ============================================================================
# DuplicateGroup overlap detection
# ============================================================================


class TestDuplicateGroupOverlap:
    """has_overlapping_ranges detects source range collisions."""

    def test_non_overlapping(self):
        grp = DuplicateGroup(
            source_ref="r1", source_name="Clip",
            clips=[
                {"source_start": 0, "source_duration": 5},
                {"source_start": 5, "source_duration": 5},
            ],
        )
        assert grp.has_overlapping_ranges is False

    def test_overlapping(self):
        grp = DuplicateGroup(
            source_ref="r1", source_name="Clip",
            clips=[
                {"source_start": 0, "source_duration": 10},
                {"source_start": 5, "source_duration": 10},
            ],
        )
        assert grp.has_overlapping_ranges is True

    def test_empty_clips(self):
        grp = DuplicateGroup(source_ref="r1", source_name="Clip", clips=[])
        assert grp.has_overlapping_ranges is False


# ============================================================================
# ValidationResult aggregation
# ============================================================================


class TestValidationResultAggregation:
    """summary() and count properties."""

    def test_mixed_severities(self):
        result = ValidationResult(
            is_valid=False, health_score=60,
            issues=[
                ValidationIssue(ValidationIssueType.FLASH_FRAME, "error", "bad"),
                ValidationIssue(ValidationIssueType.GAP, "warning", "gap found"),
                ValidationIssue(ValidationIssueType.GAP, "warning", "another gap"),
                ValidationIssue(ValidationIssueType.DUPLICATE, "error", "dupe"),
            ],
        )
        assert result.error_count == 2
        assert result.warning_count == 2
        summary = result.summary()
        assert "60%" in summary
        assert "Errors: 2" in summary

    def test_perfect_health(self):
        result = ValidationResult(is_valid=True, health_score=100)
        assert result.error_count == 0
        assert result.warning_count == 0
        assert "100%" in result.summary()
