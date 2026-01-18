"""Tests for FCPXML parser."""

import pytest
from pathlib import Path
from fcpxml.parser import FCPXMLParser
from fcpxml.models import MarkerType

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
