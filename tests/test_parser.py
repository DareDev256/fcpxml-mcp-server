"""Tests for FCPXML parser."""

import tempfile
from pathlib import Path

import pytest

from fcpxml.models import MarkerType
from fcpxml.parser import FCPXMLParser, parse_fcpxml

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.fcpxml"


def _fcpxml(spine_content="", resources_extra="", project_name="Test",
            frame_dur="1/24s", seq_dur="240/24s"):
    """Build a minimal FCPXML string for testing."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<fcpxml version="1.11"><resources>'
        f'<format id="r1" frameDuration="{frame_dur}" width="1920" height="1080"/>'
        f'{resources_extra}</resources>'
        f'<library location="file:///lib.fcpbundle/"><event name="Evt">'
        f'<project name="{project_name}">'
        f'<sequence format="r1" duration="{seq_dur}"><spine>'
        f'{spine_content}</spine></sequence></project>'
        f'</event></library></fcpxml>'
    )


ASSET_R2 = '<asset id="r2" name="A" src="file:///a.mov" start="0s" duration="100s"/>'
CLIP_A = '<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="120/24s" format="r1"/>'


# ============================================================
# File-based Parsing (existing)
# ============================================================

def test_parse_sample():
    project = FCPXMLParser().parse_file(str(SAMPLE))
    assert project.name == "Music Video Edit"
    assert len(project.timelines) == 1


def test_timeline_props():
    tl = FCPXMLParser().parse_file(str(SAMPLE)).primary_timeline
    assert tl.frame_rate == 24.0
    assert tl.width == 1920


def test_clips_parsed():
    tl = FCPXMLParser().parse_file(str(SAMPLE)).primary_timeline
    assert len(tl.clips) > 0
    assert tl.clips[0].name == "Interview_A"


def test_markers_parsed():
    tl = FCPXMLParser().parse_file(str(SAMPLE)).primary_timeline
    assert len([m for m in tl.markers if m.marker_type == MarkerType.CHAPTER]) == 4


def test_short_clip_detection():
    assert len(FCPXMLParser().parse_file(str(SAMPLE)).primary_timeline
               .get_clips_shorter_than(0.5)) >= 1


# ============================================================
# Library Clips
# ============================================================

def test_get_library_clips_returns_assets():
    parser = FCPXMLParser()
    parser.parse_file(str(SAMPLE))
    assert len(parser.get_library_clips()) == 3


def test_get_library_clips_includes_metadata():
    parser = FCPXMLParser()
    parser.parse_file(str(SAMPLE))
    interview = next(c for c in parser.get_library_clips() if c['name'] == 'Interview_A')
    assert interview['asset_id'] == 'r2'
    assert interview['duration_seconds'] == 300.0
    assert interview['src'] is not None


def test_get_library_clips_filter_by_keyword():
    parser = FCPXMLParser()
    parser.parse_file(str(SAMPLE))
    assert len(parser.get_library_clips(keywords=['NonExistent'])) == 0


# ============================================================
# parse_string
# ============================================================

def test_parse_string_basic():
    xml = _fcpxml(CLIP_A, ASSET_R2, project_name="MyProject")
    project = FCPXMLParser().parse_string(xml)
    assert project.name == "MyProject"
    assert len(project.timelines) == 1


def test_parse_string_clip_properties():
    xml = _fcpxml(CLIP_A, ASSET_R2)
    clip = FCPXMLParser().parse_string(xml).primary_timeline.clips[0]
    assert clip.name == "A"
    assert clip.duration.seconds == pytest.approx(5.0, abs=0.01)
    assert clip.media_path == "file:///a.mov"


def test_parse_string_matches_file():
    from_file = FCPXMLParser().parse_file(str(SAMPLE))
    from_string = FCPXMLParser().parse_string(SAMPLE.read_text())
    assert from_file.name == from_string.name
    assert len(from_file.timelines[0].clips) == len(from_string.timelines[0].clips)


def test_parse_string_30fps():
    xml = _fcpxml(
        '<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="300/30s" format="r1"/>',
        '<asset id="r2" name="A" src="a.mov" start="0s" duration="60s"/>',
        frame_dur="1/30s", seq_dur="300/30s",
    )
    assert FCPXMLParser().parse_string(xml).primary_timeline.frame_rate == 30.0


def test_parse_string_2997fps():
    xml = _fcpxml(
        '<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="30000/1001s" format="r1"/>',
        '<asset id="r2" name="A" src="a.mov" start="0s" duration="60s"/>',
        frame_dur="1001/30000s", seq_dur="30000/1001s",
    )
    assert FCPXMLParser().parse_string(xml).primary_timeline.frame_rate == pytest.approx(29.97, abs=0.01)


# ============================================================
# Markers
# ============================================================

def test_standard_marker():
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="24/24s" duration="1/24s" value="Mark1"/></asset-clip>')
    clip = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0]
    assert clip.markers[0].marker_type == MarkerType.STANDARD
    assert clip.markers[0].name == "Mark1"


def test_todo_marker():
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="24/24s" duration="1/24s" value="Fix" completed="0"/></asset-clip>')
    m = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0].markers[0]
    assert m.marker_type == MarkerType.TODO


def test_completed_marker():
    """Marker with completed='1' should be COMPLETED, not TODO."""
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="24/24s" duration="1/24s" value="Done" completed="1"/></asset-clip>')
    m = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0].markers[0]
    assert m.marker_type == MarkerType.COMPLETED


def test_multiple_marker_types_on_one_clip():
    """All four marker types coexist on a single clip without cross-contamination."""
    clip_xml = (
        '<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
        '<marker start="6/24s" duration="1/24s" value="Note"/>'
        '<marker start="12/24s" duration="1/24s" value="Task" completed="0"/>'
        '<marker start="18/24s" duration="1/24s" value="Done" completed="1"/>'
        '<chapter-marker start="24/24s" duration="1/24s" value="Ch1"/>'
        '</asset-clip>'
    )
    clip = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0]
    by_name = {m.name: m.marker_type for m in clip.markers}
    assert by_name["Note"] == MarkerType.STANDARD
    assert by_name["Task"] == MarkerType.TODO
    assert by_name["Done"] == MarkerType.COMPLETED
    assert by_name["Ch1"] == MarkerType.CHAPTER


def test_marker_without_completed_is_standard():
    """A plain <marker> with no completed attribute must parse as STANDARD, not TODO."""
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="6/24s" duration="1/24s" value="Plain"/></asset-clip>')
    m = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0].markers[0]
    assert m.marker_type == MarkerType.STANDARD
    assert m.name == "Plain"


def test_whitespace_padded_completed_zero_is_standard():
    """completed=' 0 ' must NOT be treated as TODO — strict exact-match only."""
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="24/24s" duration="1/24s" value="Padded" completed=" 0 "/></asset-clip>')
    m = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0].markers[0]
    assert m.marker_type == MarkerType.STANDARD


def test_whitespace_padded_completed_one_is_standard():
    """completed=' 1 ' must NOT be treated as COMPLETED — strict exact-match only."""
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="24/24s" duration="1/24s" value="Padded" completed=" 1 "/></asset-clip>')
    m = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0].markers[0]
    assert m.marker_type == MarkerType.STANDARD


def test_empty_completed_attribute_is_standard():
    """completed='' (present but empty) must parse as STANDARD, not TODO."""
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="240/24s" format="r1">'
                '<marker start="24/24s" duration="1/24s" value="Empty" completed=""/></asset-clip>')
    m = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2)).primary_timeline.clips[0].markers[0]
    assert m.marker_type == MarkerType.STANDARD


def test_chapter_markers_on_sequence():
    # Chapter markers are children of sequence (parsed via findall .//chapter-marker)
    tl = FCPXMLParser().parse_file(str(SAMPLE)).primary_timeline
    chapters = [m for m in tl.markers if m.marker_type == MarkerType.CHAPTER]
    assert len(chapters) == 4
    assert chapters[0].name == "Intro"


# ============================================================
# Keywords
# ============================================================

def test_keyword_with_range():
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="120/24s" format="r1">'
                '<keyword start="0s" duration="48/24s" value="Interview"/></asset-clip>')
    kw = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2, seq_dur="120/24s")).primary_timeline.clips[0].keywords[0]
    assert kw.start is not None
    assert kw.duration.seconds == pytest.approx(2.0, abs=0.01)


def test_keyword_without_range():
    clip_xml = ('<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="120/24s" format="r1">'
                '<keyword value="B-Roll"/></asset-clip>')
    kw = FCPXMLParser().parse_string(_fcpxml(clip_xml, ASSET_R2, seq_dur="120/24s")).primary_timeline.clips[0].keywords[0]
    assert kw.start is None
    assert kw.duration is None


# ============================================================
# Transitions & Gaps
# ============================================================

def test_transition_parsed():
    spine = (CLIP_A
             + '<transition name="Cross Dissolve" offset="120/24s" duration="24/24s"/>'
             + '<asset-clip ref="r2" offset="120/24s" name="B" start="10s" duration="120/24s" format="r1"/>')
    tl = FCPXMLParser().parse_string(_fcpxml(spine, ASSET_R2)).primary_timeline
    assert len(tl.transitions) == 1
    assert tl.transitions[0].name == "Cross Dissolve"
    assert len(tl.clips) == 2


def test_gap_advances_offset():
    spine = (CLIP_A
             + '<gap offset="120/24s" duration="48/24s"/>'
             + '<asset-clip ref="r2" offset="168/24s" name="B" start="10s" duration="72/24s" format="r1"/>')
    tl = FCPXMLParser().parse_string(_fcpxml(spine, ASSET_R2, seq_dur="240/24s")).primary_timeline
    assert len(tl.clips) == 2
    assert tl.clips[1].start.frames == 168  # 120 clip + 48 gap


# ============================================================
# Error Handling
# ============================================================

def test_parse_file_not_found():
    with pytest.raises(FileNotFoundError):
        FCPXMLParser().parse_file("/nonexistent/path.fcpxml")


def test_parse_string_invalid_xml():
    with pytest.raises(Exception):
        FCPXMLParser().parse_string("<not valid xml")


def test_parse_empty_sequence():
    xml = ('<?xml version="1.0" encoding="UTF-8"?><fcpxml version="1.11"><resources>'
           '<format id="r1" frameDuration="1/24s" width="1920" height="1080"/></resources>'
           '<library location="file:///x/"><event name="E"><project name="Empty">'
           '<sequence format="r1" duration="0s"/></project></event></library></fcpxml>')
    project = FCPXMLParser().parse_string(xml)
    assert project.name == "Empty"
    assert len(project.primary_timeline.clips) == 0


def test_parse_no_project():
    xml = '<?xml version="1.0" encoding="UTF-8"?><fcpxml version="1.11"><resources/></fcpxml>'
    project = FCPXMLParser().parse_string(xml)
    assert project.name == "Untitled"
    assert len(project.timelines) == 0


def test_fcpxmld_missing_info():
    with tempfile.TemporaryDirectory(suffix=".fcpxmld") as tmpdir:
        with pytest.raises(FileNotFoundError, match="Info.fcpxml not found"):
            FCPXMLParser().parse_file(tmpdir)


# ============================================================
# Helpers & Convenience
# ============================================================

def test_duration_to_seconds_rational():
    assert FCPXMLParser()._parse_duration_to_seconds("150/30s") == pytest.approx(5.0)


def test_duration_to_seconds_plain():
    assert FCPXMLParser()._parse_duration_to_seconds("10s") == pytest.approx(10.0)


def test_duration_to_seconds_bare_number():
    assert FCPXMLParser()._parse_duration_to_seconds("5") == pytest.approx(5.0)


def test_parse_fcpxml_convenience():
    project = parse_fcpxml(str(SAMPLE))
    assert project.name == "Music Video Edit"
    assert len(project.timelines[0].clips) == 9


def test_version_preserved():
    xml = _fcpxml(CLIP_A, ASSET_R2).replace('version="1.11"', 'version="1.10"')
    assert FCPXMLParser().parse_string(xml).fcpxml_version == "1.10"


def test_default_version():
    assert FCPXMLParser().parse_string('<fcpxml><resources/></fcpxml>').fcpxml_version == "1.11"
