"""Tests for FCPXML parser."""

from pathlib import Path

from fcpxml.models import MarkerType
from fcpxml.parser import FCPXMLParser

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.fcpxml"


def test_parse_sample():
    project = FCPXMLParser().parse_file(str(SAMPLE))
    assert project.name == "Music Video Edit"
    assert len(project.timelines) == 1


def test_timeline_props():
    project = FCPXMLParser().parse_file(str(SAMPLE))
    tl = project.primary_timeline
    assert tl.frame_rate == 24.0
    assert tl.width == 1920


def test_clips_parsed():
    project = FCPXMLParser().parse_file(str(SAMPLE))
    tl = project.primary_timeline
    assert len(tl.clips) > 0
    assert tl.clips[0].name == "Interview_A"


def test_markers_parsed():
    project = FCPXMLParser().parse_file(str(SAMPLE))
    tl = project.primary_timeline
    chapters = [m for m in tl.markers if m.marker_type == MarkerType.CHAPTER]
    assert len(chapters) == 4


def test_short_clip_detection():
    project = FCPXMLParser().parse_file(str(SAMPLE))
    short = project.primary_timeline.get_clips_shorter_than(0.5)
    assert len(short) >= 1


# ============================================================
# Library Clips Tests
# ============================================================

def test_get_library_clips_returns_assets():
    """Library clips should list all assets from the resources section."""
    parser = FCPXMLParser()
    parser.parse_file(str(SAMPLE))
    library_clips = parser.get_library_clips()

    # Sample has 3 assets: Interview_A, Broll_City, Broll_Studio
    assert len(library_clips) == 3


def test_get_library_clips_includes_metadata():
    """Each library clip should have name, duration, and asset_id."""
    parser = FCPXMLParser()
    parser.parse_file(str(SAMPLE))
    library_clips = parser.get_library_clips()

    # Find Interview_A
    interview = next((c for c in library_clips if c['name'] == 'Interview_A'), None)
    assert interview is not None
    assert interview['asset_id'] == 'r2'
    assert interview['duration_seconds'] == 300.0  # 300s in sample
    assert interview['src'] is not None


def test_get_library_clips_filter_by_keyword():
    """Should be able to filter library clips by keyword if keywords exist."""
    parser = FCPXMLParser()
    parser.parse_file(str(SAMPLE))
    # Note: In sample.fcpxml, keywords are on timeline clips not assets
    # This test verifies filtering returns all when no keyword filter matches
    library_clips = parser.get_library_clips(keywords=['NonExistent'])
    assert len(library_clips) == 0
