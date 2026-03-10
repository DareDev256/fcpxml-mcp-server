"""Tests for fcpxml/diff.py — timeline comparison engine.

Covers: moved clips, transition diffs, marker removal/movement,
duplicate clip identity, simultaneous move+trim, empty timelines.
"""

import os
import tempfile

from fcpxml.diff import (
    ClipDiff,
    MarkerDiff,
    TimelineDiff,
    _clip_identity,
    compare_timelines,
)

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
            <project name="Diff Test">
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
    fd, path = tempfile.mkstemp(suffix='.fcpxml')
    with os.fdopen(fd, 'w') as f:
        f.write(xml)
    return path


class TestMovedClips:
    """Clips that change timeline position without duration change.

    Parser computes clip.start from cumulative spine position, not XML offset.
    Insert a gap to shift downstream clips' computed timeline positions.
    """

    def test_moved_clip_detected(self):
        """Gap insertion shifts Clip_B's position — detected as 'moved'."""
        # Insert a 5-second gap before Clip_B, pushing it from 10s to 15s
        xml_b = BASE_XML.replace(
            '<asset-clip ref="r3" offset="240/24s" name="Clip_B" start="0s" duration="240/24s"/>',
            '<gap offset="240/24s" duration="120/24s"/>\n'
            '                        <asset-clip ref="r3" offset="360/24s" name="Clip_B" start="0s" duration="240/24s"/>',
        ).replace('duration="480/24s"', 'duration="600/24s"')
        a, b = _tmp(BASE_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.clip_diffs if d.action == "moved"]
            assert len(moved) >= 1
            assert moved[0].clip_name == "Clip_B"
            assert moved[0].old_start is not None
            assert moved[0].new_start is not None
            assert abs(moved[0].new_start - moved[0].old_start) > 0.04
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_identical_position_is_unchanged(self):
        """Same spine structure should produce no moved clips."""
        a, b = _tmp(BASE_XML), _tmp(BASE_XML)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.clip_diffs if d.action == "moved"]
            assert len(moved) == 0
        finally:
            os.unlink(a)
            os.unlink(b)


class TestMovedAndTrimmed:
    """Clip simultaneously moved and trimmed — reports as 'moved' with trim detail."""

    def test_simultaneous_move_and_trim(self):
        """Gap insertion + duration change = moved AND trimmed."""
        # Insert gap (moves Clip_B) AND shorten it (trims Clip_B)
        xml_b = BASE_XML.replace(
            '<asset-clip ref="r3" offset="240/24s" name="Clip_B" start="0s" duration="240/24s"/>',
            '<gap offset="240/24s" duration="120/24s"/>\n'
            '                        <asset-clip ref="r3" offset="360/24s" name="Clip_B" start="0s" duration="120/24s"/>',
        ).replace('duration="480/24s"', 'duration="600/24s"')
        a, b = _tmp(BASE_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.clip_diffs if d.action == "moved"]
            assert len(moved) >= 1
            m = moved[0]
            assert "trimmed" in m.details.lower()
            assert m.old_duration != m.new_duration
        finally:
            os.unlink(a)
            os.unlink(b)


class TestTransitionDiffs:
    """Transition comparison — count changes, name/duration changes."""

    TRANS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="Clip_A" src="file:///a.mov" start="0s" duration="240/24s"/>
        <asset id="r3" name="Clip_B" src="file:///b.mov" start="0s" duration="240/24s"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Trans Test">
                <sequence format="r1" duration="480/24s">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="Clip_A" start="0s" duration="240/24s"/>
                        <transition name="Cross Dissolve" offset="228/24s" duration="24/24s"/>
                        <asset-clip ref="r3" offset="240/24s" name="Clip_B" start="0s" duration="240/24s"/>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""

    def test_transition_added(self):
        """Timeline with no transitions vs one transition."""
        a, b = _tmp(BASE_XML), _tmp(self.TRANS_XML)
        try:
            diff = compare_timelines(a, b)
            assert len(diff.transition_diffs) >= 1
            assert "count" in diff.transition_diffs[0].lower()
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_transition_removed(self):
        a, b = _tmp(self.TRANS_XML), _tmp(BASE_XML)
        try:
            diff = compare_timelines(a, b)
            assert len(diff.transition_diffs) >= 1
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_transition_name_change(self):
        xml_b = self.TRANS_XML.replace('Cross Dissolve', 'Fade to Black')
        a, b = _tmp(self.TRANS_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            name_changes = [d for d in diff.transition_diffs if 'Cross Dissolve' in d]
            assert len(name_changes) >= 1
        finally:
            os.unlink(a)
            os.unlink(b)


class TestMarkerDiffs:
    """Marker removal and position movement detection."""

    MARKER_XML = BASE_XML.replace(
        'name="Clip_A" start="0s" duration="240/24s"/>',
        'name="Clip_A" start="0s" duration="240/24s">'
        '<marker start="48/24s" duration="1/24s" value="Take 1"/>'
        '<marker start="120/24s" duration="1/24s" value="Take 2"/>'
        '</asset-clip>'
    ).replace(
        '<asset-clip ref="r2" offset="0s" name="Clip_A" start="0s" duration="240/24s">',
        '<asset-clip ref="r2" offset="0s" name="Clip_A" start="0s" duration="240/24s">',
    )

    def test_marker_removed(self):
        xml_b = self.MARKER_XML.replace(
            '<marker start="48/24s" duration="1/24s" value="Take 1"/>', ''
        )
        a, b = _tmp(self.MARKER_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            removed = [d for d in diff.marker_diffs if d.action == "removed"]
            assert len(removed) >= 1
            assert any(d.marker_name == "Take 1" for d in removed)
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_marker_moved(self):
        """Marker position change >1.0s should report 'moved'."""
        xml_b = self.MARKER_XML.replace(
            '<marker start="48/24s" duration="1/24s" value="Take 1"/>',
            '<marker start="120/24s" duration="1/24s" value="Take 1"/>',
        )
        a, b = _tmp(self.MARKER_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            moved = [d for d in diff.marker_diffs if d.action == "moved"]
            assert len(moved) >= 1
            m = moved[0]
            assert m.marker_name == "Take 1"
            assert m.old_position is not None
            assert m.new_position is not None
        finally:
            os.unlink(a)
            os.unlink(b)


class TestFrameRateDiff:
    """Frame rate changes between timelines."""

    def test_frame_rate_change_detected(self):
        xml_b = BASE_XML.replace('frameDuration="1/24s"', 'frameDuration="1/30s"')
        a, b = _tmp(BASE_XML), _tmp(xml_b)
        try:
            diff = compare_timelines(a, b)
            fps_changes = [c for c in diff.format_changes if "Frame rate" in c]
            assert len(fps_changes) >= 1
        finally:
            os.unlink(a)
            os.unlink(b)


class TestClipIdentity:
    """_clip_identity uses (name, source_start) for matching.

    Parser produces Timecode objects (which have .seconds), so tests
    must use Timecode — not raw TimeValue — to match real behavior.
    """

    def test_identity_with_source_start(self):
        from fcpxml.models import Clip, Timecode
        clip = Clip(
            name="Interview",
            start=Timecode(frames=0, frame_rate=24),
            duration=Timecode(frames=240, frame_rate=24),
            source_start=Timecode(frames=240, frame_rate=24),  # 10 seconds
        )
        key = _clip_identity(clip)
        assert key == ("Interview", 10.0)

    def test_identity_no_source_start(self):
        from fcpxml.models import Clip, Timecode
        clip = Clip(
            name="Test",
            start=Timecode(frames=0, frame_rate=24),
            duration=Timecode(frames=100, frame_rate=24),
            source_start=None,
        )
        key = _clip_identity(clip)
        assert key == ("Test", 0.0)


class TestTotalChangesProperty:
    """TimelineDiff.total_changes excludes 'unchanged' clips."""

    def test_unchanged_clips_not_counted(self):
        diff = TimelineDiff(
            timeline_a_name="A", timeline_b_name="B",
            clip_diffs=[
                ClipDiff(action="unchanged", clip_name="X"),
                ClipDiff(action="moved", clip_name="Y"),
            ],
        )
        assert diff.total_changes == 1

    def test_all_change_types_summed(self):
        diff = TimelineDiff(
            timeline_a_name="A", timeline_b_name="B",
            clip_diffs=[ClipDiff(action="added", clip_name="X")],
            marker_diffs=[MarkerDiff(action="removed", marker_name="M")],
            transition_diffs=["count changed"],
            format_changes=["resolution changed"],
        )
        assert diff.total_changes == 4
