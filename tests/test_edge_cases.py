"""Edge-case tests targeting real production failure modes.

Covers boundary conditions in TimeValue arithmetic, clip index collisions
from duplicate names, split_clip boundary behavior, diff identity rounding,
and to_fcpxml round-trip fidelity for non-standard timebases.
"""

import os
import tempfile

import pytest

from fcpxml.diff import ClipDiff, TimelineDiff, _clip_identity
from fcpxml.models import Clip, Timecode, TimeValue
from fcpxml.writer import FCPXMLModifier

# ============================================================================
# TimeValue boundary arithmetic
# ============================================================================


class TestTimeValueBoundaries:
    """Catch real bugs in rational time math at the edges."""

    def test_subtraction_produces_negative_time(self):
        """Negative results from subtraction must not silently corrupt offsets."""
        a = TimeValue(10, 30)
        b = TimeValue(20, 30)
        result = a - b
        assert result.numerator == -10
        assert result.to_seconds() < 0, "Negative time should report negative seconds"

    def test_zero_denominator_rejected_at_construction(self):
        """Zero denominator must be caught at construction, not silently propagated."""
        with pytest.raises(ValueError, match="denominator cannot be zero"):
            TimeValue(100, 0)

    def test_zero_denominator_rejected_even_with_zero_numerator(self):
        """TimeValue(0, 0) is still invalid — use TimeValue(0, 1) for zero time."""
        with pytest.raises(ValueError, match="denominator cannot be zero"):
            TimeValue(0, 0)

    def test_snap_to_frame_rejects_zero_fps(self):
        """snap_to_frame(0) would cause ZeroDivisionError without the guard."""
        tv = TimeValue(100, 2400)
        with pytest.raises(ValueError, match="fps must be positive"):
            tv.snap_to_frame(0)

    def test_snap_to_frame_rejects_negative_fps(self):
        tv = TimeValue(100, 2400)
        with pytest.raises(ValueError, match="fps must be positive"):
            tv.snap_to_frame(-24)

    def test_multiply_by_zero_yields_zero_time(self):
        tv = TimeValue(90, 30)
        result = tv * 0
        assert result.to_seconds() == 0.0

    def test_divide_by_zero_raises(self):
        """Division by zero scalar must raise ZeroDivisionError, not corrupt silently."""
        tv = TimeValue(90, 30)
        with pytest.raises(ZeroDivisionError, match="Cannot divide TimeValue by zero"):
            tv / 0

    def test_from_timecode_zero_denominator_rational(self):
        """Parsing '10/0s' must raise, not silently produce bad TimeValue."""
        with pytest.raises(ValueError, match="Zero denominator"):
            TimeValue.from_timecode("10/0s")

    def test_to_fcpxml_preserves_non_standard_denominator(self):
        """Non-standard denominators (e.g., 7) fall back to unsimplified form."""
        tv = TimeValue(14, 7)  # 2 seconds, but 7 isn't a standard timebase
        result = tv.to_fcpxml()
        assert result == "2s"  # Simplifies to 2/1, denominator=1 → "2s"

    def test_to_fcpxml_non_standard_no_simplify_to_whole(self):
        """Non-standard denominator that doesn't simplify to 1 keeps original."""
        tv = TimeValue(10, 7)  # 10/7 ≈ 1.43s, can't simplify to standard
        result = tv.to_fcpxml()
        assert result == "10/7s"  # Falls back to unsimplified

    def test_simplify_negative_numerator(self):
        """Simplify handles negative numerators correctly via abs()."""
        tv = TimeValue(-60, 30)
        simplified = tv.simplify()
        assert simplified.numerator == -2
        assert simplified.denominator == 1

    def test_equality_tolerance(self):
        """Two TimeValues within 0.0001s tolerance are equal."""
        a = TimeValue(30000, 30000)  # Exactly 1.0s
        b = TimeValue(10000, 10001)  # 0.9999... ≈ 1.0s
        assert a == b  # Within tolerance

    def test_equality_beyond_tolerance(self):
        """TimeValues differing by more than 0.0001s are NOT equal."""
        a = TimeValue(1000, 1000)  # 1.0s
        b = TimeValue(999, 1000)   # 0.999s — 0.001s apart
        assert a != b


# ============================================================================
# Timecode edge cases
# ============================================================================


class TestTimecodeEdges:
    """Edge cases in legacy Timecode wrapper."""

    def test_zero_frame_rate_seconds(self):
        """Timecode with frame_rate=0 would crash on .seconds — document behavior."""
        tc = Timecode(frames=100, frame_rate=0)
        with pytest.raises(ZeroDivisionError):
            _ = tc.seconds

    def test_negative_frames_smpte(self):
        """Negative frame count should not crash to_smpte — just produce odd output."""
        tc = Timecode(frames=-1, frame_rate=24.0)
        # Should not raise; output may be unusual but shouldn't crash
        result = tc.to_smpte()
        assert isinstance(result, str)


# ============================================================================
# Clip index collision (duplicate names)
# ============================================================================


DUPLICATE_NAMES_FCPXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
<resources>
    <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
    <asset id="r2" name="Interview" src="file:///a.mov" start="0s" duration="100s" format="r1"/>
</resources>
<library><event name="E"><project name="P">
<sequence format="r1" duration="360/24s" tcStart="0s" tcFormat="NDF">
<spine>
    <asset-clip ref="r2" offset="0s" name="Interview" start="0s" duration="120/24s" format="r1"/>
    <asset-clip ref="r2" offset="120/24s" name="Interview" start="30s" duration="120/24s" format="r1"/>
    <asset-clip ref="r2" offset="240/24s" name="Interview" start="60s" duration="120/24s" format="r1"/>
</spine>
</sequence></project></event></library></fcpxml>
"""


class TestClipIndexCollision:
    """When multiple clips share a name, only the LAST one is indexed.

    This is a known limitation documented in MEMORY.md — these tests pin
    the behavior so regressions are caught if the indexing strategy changes.
    """

    def test_duplicate_name_last_wins(self):
        """_build_clip_index stores last occurrence for duplicate names."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(DUPLICATE_NAMES_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                clip = mod.clips.get("Interview")
                assert clip is not None
                # Last clip starts at source offset 60s
                assert clip.get("start") == "60s"
            finally:
                os.unlink(f.name)

    def test_add_marker_hits_last_duplicate(self):
        """add_marker on duplicate name affects last indexed clip, not first."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(DUPLICATE_NAMES_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                result = mod.add_marker("Interview", "1/24s", "Test Marker")
                assert result is not None
                # Marker should be on the LAST Interview clip (start=60s)
                clip = mod.clips["Interview"]
                markers = [c for c in clip if c.tag == "marker"]
                assert len(markers) == 1
                assert markers[0].get("value") == "Test Marker"
            finally:
                os.unlink(f.name)


# ============================================================================
# split_clip boundary behavior
# ============================================================================


SPLIT_FCPXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
<resources>
    <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
    <asset id="r2" name="A" src="file:///a.mov" start="0s" duration="100s" format="r1"/>
</resources>
<library><event name="E"><project name="P">
<sequence format="r1" duration="120/24s" tcStart="0s" tcFormat="NDF">
<spine>
    <asset-clip ref="r2" offset="0s" name="A" start="0s" duration="120/24s" format="r1"/>
</spine>
</sequence></project></event></library></fcpxml>
"""


class TestSplitClipBoundaries:
    """split_clip at edge positions — verify zero-duration segments are skipped."""

    def test_split_at_start_skips_zero_duration_segment(self):
        """Splitting at offset=0 should skip the zero-duration first segment."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(SPLIT_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                # Split at the very beginning (0 frames into clip)
                result = mod.split_clip("A", ["0/24s"])
                # Zero-duration segment should be skipped → only 1 clip remains
                assert len(result) == 1
                # Duration preserved (may be simplified by to_fcpxml)
                dur_seconds = TimeValue.from_timecode(result[0].get("duration")).to_seconds()
                assert dur_seconds == pytest.approx(5.0, abs=0.05)
            finally:
                os.unlink(f.name)

    def test_split_at_end_skips_zero_duration_tail(self):
        """Splitting at the clip's full duration produces no zero-duration tail."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(SPLIT_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                result = mod.split_clip("A", ["120/24s"])
                # Full duration split → first segment = full clip, tail = 0 → skipped
                assert len(result) == 1
            finally:
                os.unlink(f.name)

    def test_split_midpoint_produces_two_clips(self):
        """Normal midpoint split produces exactly two clips with correct offsets."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(SPLIT_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                result = mod.split_clip("A", ["60/24s"])
                assert len(result) == 2
                assert result[0].get("duration") == "60/24s"
                assert result[1].get("duration") == "60/24s"
                # Offsets must be contiguous
                assert result[0].get("offset") == "0s"
                assert result[1].get("offset") == "60/24s"
            finally:
                os.unlink(f.name)


# ============================================================================
# Split clip child-element filtering (markers, keywords)
# ============================================================================

SPLIT_MARKER_FCPXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
<resources>
    <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
    <asset id="r2" name="A" src="file:///a.mov" start="0s" duration="100s" format="r1"/>
</resources>
<library><event name="E"><project name="P">
<sequence format="r1" duration="120/24s" tcStart="0s" tcFormat="NDF">
<spine>
    <asset-clip ref="r2" offset="0s" name="A" start="10s" duration="120/24s" format="r1">
        <marker start="11s" duration="1/24s" value="Early mark"/>
        <marker start="13s" duration="1/24s" value="Late mark"/>
        <keyword start="10s" duration="120/24s" value="Interview"/>
    </asset-clip>
</spine>
</sequence></project></event></library></fcpxml>
"""


class TestSplitClipChildFiltering:
    """split_clip must filter markers/keywords so they only appear on the
    segment whose source range actually contains them."""

    def test_markers_land_on_correct_segment(self):
        """Markers must appear only on the segment whose source range covers them."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(SPLIT_MARKER_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                # Clip starts at source 10s, duration 120/24s = 5s → source range [10s, 15s)
                # Split at 60/24s = 2.5s into clip → source split at 12.5s
                # Segment 0: source [10s, 12.5s) — "Early mark" at 11s ✓, "Late mark" at 13s ✗
                # Segment 1: source [12.5s, 15s) — "Early mark" at 11s ✗, "Late mark" at 13s ✓
                result = mod.split_clip("A", ["60/24s"])
                assert len(result) == 2

                seg0_markers = [c for c in result[0] if c.tag == 'marker']
                seg1_markers = [c for c in result[1] if c.tag == 'marker']

                assert len(seg0_markers) == 1
                assert seg0_markers[0].get('value') == 'Early mark'

                assert len(seg1_markers) == 1
                assert seg1_markers[0].get('value') == 'Late mark'
            finally:
                os.unlink(f.name)

    def test_keyword_clamped_to_segment_boundaries(self):
        """Keywords spanning the full clip get clamped to each segment's range."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            f.write(SPLIT_MARKER_FCPXML)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                result = mod.split_clip("A", ["60/24s"])
                assert len(result) == 2

                seg0_kw = [c for c in result[0] if c.tag == 'keyword']
                seg1_kw = [c for c in result[1] if c.tag == 'keyword']

                # Both segments should have the keyword (it spans the whole clip)
                assert len(seg0_kw) == 1
                assert len(seg1_kw) == 1

                # Segment 0: keyword clamped to [10s, 12.5s) → duration = 60/24s
                seg0_dur = TimeValue.from_timecode(seg0_kw[0].get('duration'))
                assert seg0_dur.to_seconds() == pytest.approx(2.5, abs=0.05)

                # Segment 1: keyword clamped to [12.5s, 15s) → duration = 60/24s
                seg1_dur = TimeValue.from_timecode(seg1_kw[0].get('duration'))
                assert seg1_dur.to_seconds() == pytest.approx(2.5, abs=0.05)
            finally:
                os.unlink(f.name)

    def test_marker_outside_all_segments_removed(self):
        """A marker exactly at the segment boundary end is excluded."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", mode="w", delete=False) as f:
            # Marker at source 15s, clip source range [10s, 15s) — at boundary = excluded
            xml = SPLIT_MARKER_FCPXML.replace(
                '<marker start="13s"', '<marker start="15s"'
            )
            f.write(xml)
            f.flush()
            try:
                mod = FCPXMLModifier(f.name)
                result = mod.split_clip("A", ["60/24s"])
                # Marker at 15s is at clip end, should not appear on any segment
                all_markers = []
                for seg in result:
                    all_markers.extend(c for c in seg if c.tag == 'marker')
                # Only "Early mark" at 11s should survive
                assert len(all_markers) == 1
                assert all_markers[0].get('value') == 'Early mark'
            finally:
                os.unlink(f.name)


# ============================================================================
# Diff identity rounding
# ============================================================================


class TestDiffIdentityRounding:
    """_clip_identity rounds source_start to 0.01s — collisions are possible."""

    def _make_clip(self, name: str, source_start_seconds: float) -> Clip:
        return Clip(
            name=name,
            start=Timecode(frames=0, frame_rate=24),
            duration=Timecode(frames=120, frame_rate=24),
            source_start=Timecode(
                frames=int(round(source_start_seconds * 24)),
                frame_rate=24,
            ),
        )

    def test_same_name_different_source_start_distinct(self):
        """Clips one full frame apart (0.042s at 24fps) are distinct identities."""
        a = self._make_clip("Shot", 1.00)
        b = self._make_clip("Shot", 1.05)  # 1.05*24=25.2→25 frames→1.04s
        assert _clip_identity(a) != _clip_identity(b)

    def test_rounding_collision_within_half_cent(self):
        """Clips 0.004s apart may collide after rounding to 0.01s."""
        a = self._make_clip("Shot", 1.004)
        b = self._make_clip("Shot", 1.006)
        # Both round to 1.00 or 1.01 depending on frame quantization at 24fps
        id_a = _clip_identity(a)
        id_b = _clip_identity(b)
        # At 24fps: 1.004*24=24.096→24 frames→1.0s, 1.006*24=24.144→24 frames→1.0s
        # Both map to source_start=1.0 → collision
        assert id_a == id_b, "Rounding collision is expected at sub-frame precision"

    def test_timeline_diff_total_changes_excludes_unchanged(self):
        """total_changes property skips 'unchanged' diffs."""
        diff = TimelineDiff(
            timeline_a_name="A",
            timeline_b_name="B",
            clip_diffs=[
                ClipDiff(action="unchanged", clip_name="C1"),
                ClipDiff(action="moved", clip_name="C2"),
                ClipDiff(action="added", clip_name="C3"),
            ],
        )
        assert diff.total_changes == 2
        assert diff.has_changes is True
