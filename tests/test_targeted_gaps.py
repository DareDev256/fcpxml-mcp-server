"""Targeted tests for untested branches in diff, export, and models.

Covers: clip-only-trim detection, marker addition/threshold, duplicate
identity imbalance, has_changes property, XMEML frame math precision,
video-only clip audio exclusion, TimeValue division edge cases,
ValidationResult.summary format, and MontageConfig boundary clamping.
"""

import os
import tempfile
import xml.etree.ElementTree as ET

import pytest

from fcpxml.diff import (
    TimelineDiff,
    _compare_clips,
    _compare_markers,
    compare_timelines,
)
from fcpxml.export import DaVinciExporter
from fcpxml.models import (
    Clip,
    FlashFrame,
    FlashFrameSeverity,
    GapInfo,
    MontageConfig,
    PacingCurve,
    Timecode,
    Timeline,
    TimeValue,
    ValidationIssue,
    ValidationIssueType,
    ValidationResult,
)

# ── Fixtures ──────────────────────────────────────────────────────────

BASE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="Clip_A" src="file:///a.mov" start="0s" duration="240/24s"/>
        <asset id="r3" name="Clip_B" src="file:///b.mov" start="0s" duration="240/24s"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Gap Test">
                <sequence format="r1" duration="480/24s">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="Clip_A" start="0s" duration="240/24s"/>
                        <asset-clip ref="r3" offset="240/24s" name="Clip_B" start="0s" duration="240/24s"/>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""


def _tmp(xml: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".fcpxml")
    with os.fdopen(fd, "w") as f:
        f.write(xml)
    return path


def _out(suffix=".fcpxml") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


# ── Diff: trimmed-only (no move) ─────────────────────────────────────

class TestTrimmedOnly:
    """Clip duration changes without position change → 'trimmed' action."""

    def test_clip_trimmed_without_move(self):
        """Shorten Clip_A in-place — position unchanged, duration changed."""
        xml_b = BASE_XML.replace(
            'name="Clip_A" start="0s" duration="240/24s"',
            'name="Clip_A" start="0s" duration="120/24s"',
            1,  # only first occurrence (spine clip, not asset)
        )
        a, b = _tmp(BASE_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            trimmed = [d for d in diff.clip_diffs if d.action == "trimmed"]
            assert len(trimmed) >= 1
            assert trimmed[0].clip_name == "Clip_A"
            assert trimmed[0].old_duration != trimmed[0].new_duration
            # Position should be unchanged
            assert abs(trimmed[0].old_start - trimmed[0].new_start) <= 0.04
        finally:
            os.unlink(a)
            os.unlink(b)


# ── Diff: marker addition ────────────────────────────────────────────

class TestMarkerAddition:
    """Markers present in B but not A should report 'added'."""

    def test_marker_added(self):
        xml_b = BASE_XML.replace(
            'name="Clip_A" start="0s" duration="240/24s"/>',
            'name="Clip_A" start="0s" duration="240/24s">'
            '<marker start="48/24s" duration="1/24s" value="New Mark"/>'
            "</asset-clip>",
        )
        a, b = _tmp(BASE_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            added = [d for d in diff.marker_diffs if d.action == "added"]
            assert len(added) >= 1
            assert any(m.marker_name == "New Mark" for m in added)
        finally:
            os.unlink(a)
            os.unlink(b)


# ── Diff: marker threshold boundary ──────────────────────────────────

class TestMarkerThreshold:
    """Markers moved ≤1.0s are NOT reported; >1.0s are."""

    def test_marker_at_exact_threshold_not_reported(self):
        """1.0s movement is boundary — should NOT be reported as moved."""
        diff = TimelineDiff(timeline_a_name="A", timeline_b_name="B")
        # Simulate: marker at 0s in A, 1.0s in B (exactly at threshold)
        tl_a = _make_timeline_with_marker("Mk", 0.0)
        tl_b = _make_timeline_with_marker("Mk", 1.0)
        _compare_markers(tl_a, tl_b, diff)
        moved = [d for d in diff.marker_diffs if d.action == "moved"]
        assert len(moved) == 0, "Exactly 1.0s should NOT trigger 'moved'"

    def test_marker_above_threshold_reported(self):
        """~1.08s movement (26 frames at 24fps) exceeds threshold — reported."""
        diff = TimelineDiff(timeline_a_name="A", timeline_b_name="B")
        tl_a = _make_timeline_with_marker("Mk", 0.0)
        # 26 frames / 24fps = 1.083s, safely above 1.0s threshold
        tl_b = _make_timeline_with_marker("Mk", 26 / 24)
        _compare_markers(tl_a, tl_b, diff)
        moved = [d for d in diff.marker_diffs if d.action == "moved"]
        assert len(moved) == 1


# ── Diff: duplicate identity imbalance ────────────────────────────────

class TestDuplicateIdentityImbalance:
    """When clip identity maps have unequal counts, extras are added/removed."""

    def test_extra_clip_in_b_is_added(self):
        """3 clips with same identity in B vs 2 in A → 1 added."""
        diff = TimelineDiff(timeline_a_name="A", timeline_b_name="B")
        tc = Timecode(frames=0, frame_rate=24)
        dur = Timecode(frames=48, frame_rate=24)
        clips_a = [Clip(name="X", start=tc, duration=dur, source_start=tc)] * 2
        clips_b = [Clip(name="X", start=tc, duration=dur, source_start=tc)] * 3
        _compare_clips(clips_a, clips_b, diff)
        added = [d for d in diff.clip_diffs if d.action == "added"]
        assert len(added) == 1

    def test_extra_clip_in_a_is_removed(self):
        tc = Timecode(frames=0, frame_rate=24)
        dur = Timecode(frames=48, frame_rate=24)
        diff = TimelineDiff(timeline_a_name="A", timeline_b_name="B")
        clips_a = [Clip(name="X", start=tc, duration=dur, source_start=tc)] * 3
        clips_b = [Clip(name="X", start=tc, duration=dur, source_start=tc)] * 1
        _compare_clips(clips_a, clips_b, diff)
        removed = [d for d in diff.clip_diffs if d.action == "removed"]
        assert len(removed) == 2


# ── Diff: has_changes property ────────────────────────────────────────

class TestHasChanges:
    def test_no_changes(self):
        diff = TimelineDiff(timeline_a_name="A", timeline_b_name="B")
        assert diff.has_changes is False

    def test_with_format_change(self):
        diff = TimelineDiff(
            timeline_a_name="A", timeline_b_name="B",
            format_changes=["Resolution: 1920x1080 -> 3840x2160"],
        )
        assert diff.has_changes is True


# ── Export: XMEML frame math ──────────────────────────────────────────

class TestXmemlFrameMath:
    """Verify clipitem start/end/in/out frame calculations."""

    def test_clipitem_frame_values(self):
        src = _tmp(BASE_XML)
        out = _out(".xml")
        try:
            exp = DaVinciExporter(src)
            exp.export_xmeml(out)
            tree = ET.parse(out)
            ci = tree.findall(".//clipitem")
            # First clip: start=0, duration=10s at 24fps = 240 frames
            first = ci[0]
            assert first.find("start").text == "0"
            assert first.find("end").text == "240"
            assert first.find("in").text == "0"
            assert first.find("out").text == "240"
        finally:
            os.unlink(src)
            os.unlink(out)


# ── TimeValue: division edge cases ────────────────────────────────────

class TestTimeValueDivision:
    def test_divide_by_zero_raises(self):
        """Division by zero must raise ZeroDivisionError, not silently corrupt."""
        tv = TimeValue(100, 1)
        with pytest.raises(ZeroDivisionError, match="Cannot divide TimeValue by zero"):
            tv / 0.0

    def test_negative_timevalue_comparison(self):
        """Negative TimeValue should compare correctly."""
        neg = TimeValue(-10, 1)
        pos = TimeValue(10, 1)
        assert neg < pos
        assert not (pos < neg)

    def test_multiply_preserves_denominator(self):
        tv = TimeValue(100, 2400)
        result = tv * 2
        assert result.denominator == 2400
        assert result.numerator == 200


# ── ValidationResult.summary format ───────────────────────────────────

class TestValidationSummary:
    def test_summary_format(self):
        result = ValidationResult(
            is_valid=False,
            health_score=72,
            issues=[
                ValidationIssue(ValidationIssueType.FLASH_FRAME, "error", "flash"),
                ValidationIssue(ValidationIssueType.GAP, "warning", "gap"),
                ValidationIssue(ValidationIssueType.GAP, "warning", "gap2"),
            ],
            flash_frames=[
                FlashFrame("clip1", "r2", Timecode(0, 24), 1, 0.04, FlashFrameSeverity.CRITICAL),
            ],
            gaps=[
                GapInfo(Timecode(100, 24), 5, 0.21),
                GapInfo(Timecode(200, 24), 3, 0.13),
            ],
        )
        s = result.summary()
        assert "72%" in s
        assert "Errors: 1" in s
        assert "Warnings: 2" in s
        assert "Flash frames: 1" in s
        assert "Gaps: 2" in s


# ── MontageConfig: clamping at boundaries ─────────────────────────────

class TestMontageConfigClamping:
    def test_decelerating_at_end_clamps_to_max(self):
        """Decelerating at position=1.0 returns start_duration, clamped to max."""
        cfg = MontageConfig(
            target_duration=60,
            pacing_curve=PacingCurve.DECELERATING,
            start_duration=10.0,
            end_duration=0.5,
            max_duration=5.0,
        )
        # At position 1.0, decelerating = end + (start-end)*1.0 = start = 10.0
        # Clamped to max_duration = 5.0
        assert cfg.get_duration_at_position(1.0) == 5.0

    def test_accelerating_at_start_clamps_to_max(self):
        cfg = MontageConfig(
            target_duration=60,
            pacing_curve=PacingCurve.ACCELERATING,
            start_duration=8.0,
            end_duration=0.5,
            max_duration=5.0,
        )
        # At position 0.0, accelerating = start = 8.0, clamped to 5.0
        assert cfg.get_duration_at_position(0.0) == 5.0


# ── Helpers ───────────────────────────────────────────────────────────

def _make_timeline_with_marker(name: str, position_seconds: float) -> Timeline:
    """Build a minimal Timeline with one clip-level marker at a given position."""
    from fcpxml.models import Marker, MarkerType

    tc = Timecode(frames=0, frame_rate=24)
    dur = Timecode(frames=2400, frame_rate=24)
    marker_tc = Timecode(frames=int(position_seconds * 24), frame_rate=24)
    clip = Clip(
        name="Host",
        start=tc,
        duration=dur,
        markers=[Marker(name=name, start=marker_tc, marker_type=MarkerType.STANDARD)],
    )
    return Timeline(name="Test", duration=dur, clips=[clip])
