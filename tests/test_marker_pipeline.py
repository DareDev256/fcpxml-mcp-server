"""Tests for marker pipeline gaps: build_marker_element, batch auto-modes,
clip index duplicate-name behavior, and write_fcpxml output format.

These cover integration seams between models → writer → parser that existed
without direct test coverage despite each component being individually tested.
"""

import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fcpxml.models import MarkerType
from fcpxml.writer import (
    FCPXMLModifier,
    build_marker_element,
    write_fcpxml,
)

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.fcpxml"


@pytest.fixture
def temp_fcpxml():
    with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
        shutil.copy(SAMPLE, f.name)
        yield f.name
    Path(f.name).unlink(missing_ok=True)


# ============================================================
# build_marker_element — the shared builder
# ============================================================


class TestBuildMarkerElement:
    """Direct tests for the centralised marker XML element factory."""

    def test_standard_creates_marker_tag(self):
        parent = ET.Element("clip")
        elem = build_marker_element(parent, MarkerType.STANDARD, "12/24s", "1/24s", "Note")
        assert elem.tag == "marker"
        assert elem.get("completed") is None

    def test_todo_sets_completed_zero(self):
        parent = ET.Element("clip")
        elem = build_marker_element(parent, MarkerType.TODO, "0s", "1/24s", "Fix")
        assert elem.tag == "marker"
        assert elem.get("completed") == "0"

    def test_completed_sets_completed_one(self):
        parent = ET.Element("clip")
        elem = build_marker_element(parent, MarkerType.COMPLETED, "0s", "1/24s", "Done")
        assert elem.get("completed") == "1"

    def test_chapter_creates_chapter_marker_tag(self):
        parent = ET.Element("clip")
        elem = build_marker_element(parent, MarkerType.CHAPTER, "0s", "1/24s", "Ch1")
        assert elem.tag == "chapter-marker"
        assert elem.get("posterOffset") == "0s"

    def test_chapter_ignores_note(self):
        """Chapter markers must NOT carry note attrs — FCP spec forbids it."""
        parent = ET.Element("clip")
        elem = build_marker_element(
            parent, MarkerType.CHAPTER, "0s", "1/24s", "Ch", note="ignored"
        )
        assert elem.get("note") is None

    def test_standard_with_note(self):
        parent = ET.Element("clip")
        elem = build_marker_element(
            parent, MarkerType.STANDARD, "0s", "1/24s", "Review", note="Check audio"
        )
        assert elem.get("note") == "Check audio"

    def test_sanitizes_marker_name(self):
        """Null bytes in marker names must be stripped before writing."""
        parent = ET.Element("clip")
        elem = build_marker_element(parent, MarkerType.STANDARD, "0s", "1/24s", "bad\x00name")
        assert "\x00" not in elem.get("value")
        assert elem.get("value") == "badname"

    def test_element_appended_to_parent(self):
        parent = ET.Element("clip")
        build_marker_element(parent, MarkerType.STANDARD, "0s", "1/24s", "M")
        assert len(list(parent)) == 1


# ============================================================
# batch_add_markers — auto_at_cuts
# ============================================================


class TestBatchAutoAtCuts:
    """batch_add_markers(auto_at_cuts=True) iterates spine clips and marks cuts.

    BUG: auto_at_cuts reads offsets from ALL spine clips, but add_marker_at_timeline
    searches the name-indexed clip dict (last-one-wins for duplicates). Clips whose
    names were overwritten by later duplicates are unreachable → ValueError at offset 0s.
    """

    def test_auto_at_cuts_fails_on_duplicate_names(self, temp_fcpxml):
        """First cut at 0s hits Interview_A — but the indexed copy is at 1122/24s.
        This documents the duplicate-name clip index limitation."""
        modifier = FCPXMLModifier(temp_fcpxml)
        with pytest.raises(ValueError, match="No clip found"):
            modifier.batch_add_markers(markers=[], auto_at_cuts=True)

    def test_auto_at_cuts_on_unique_timeline(self, tmp_path):
        """Works correctly when all clip names are unique."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11"><resources>
<format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
<asset id="r2" name="A" src="a.mov" start="0s" duration="100s"/>
<asset id="r3" name="B" src="b.mov" start="0s" duration="100s"/>
</resources><library><event name="E"><project name="P">
<sequence format="r1" duration="240/24s"><spine>
<asset-clip ref="r2" offset="0s" name="ClipA" start="0s" duration="120/24s" format="r1"/>
<asset-clip ref="r3" offset="120/24s" name="ClipB" start="0s" duration="120/24s" format="r1"/>
</spine></sequence></project></event></library></fcpxml>"""
        p = tmp_path / "unique.fcpxml"
        p.write_text(xml)
        modifier = FCPXMLModifier(str(p))
        created = modifier.batch_add_markers(markers=[], auto_at_cuts=True)
        assert len(created) == 2
        assert all(m.get("completed") is None for m in created)


# ============================================================
# batch_add_markers — auto_at_intervals
# ============================================================


class TestBatchAutoAtIntervals:

    def test_interval_creates_markers_on_unique_timeline(self, tmp_path):
        """Interval markers work when all clip names are unique (no index collisions)."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11"><resources>
<format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
<asset id="r2" name="A" src="a.mov" start="0s" duration="100s"/>
</resources><library><event name="E"><project name="P">
<sequence format="r1" duration="720/24s"><spine>
<asset-clip ref="r2" offset="0s" name="Long" start="0s" duration="720/24s" format="r1"/>
</spine></sequence></project></event></library></fcpxml>"""
        p = tmp_path / "interval.fcpxml"
        p.write_text(xml)
        modifier = FCPXMLModifier(str(p))
        # 30s timeline, 10s intervals → 2 markers (at 10s and 20s)
        created = modifier.batch_add_markers(
            markers=[], auto_at_intervals="00:00:10:00"
        )
        assert len(created) == 2
        assert all(m.get("value", "").startswith("Marker ") for m in created)

    def test_interval_past_timeline_creates_nothing(self, temp_fcpxml):
        modifier = FCPXMLModifier(temp_fcpxml)
        # 999s interval on a ~54s timeline → zero markers
        created = modifier.batch_add_markers(
            markers=[], auto_at_intervals="00:16:00:00"
        )
        assert len(created) == 0


# ============================================================
# _build_clip_index — duplicate name behavior
# ============================================================


class TestClipIndexDuplicateNames:
    """The clip index uses name as key — duplicates mean last-one-wins."""

    def test_last_duplicate_wins(self, temp_fcpxml):
        """sample.fcpxml has multiple Interview_A clips; only the last is indexed."""
        modifier = FCPXMLModifier(temp_fcpxml)
        clip = modifier.clips.get("Interview_A")
        assert clip is not None
        # The last Interview_A in the spine is at offset 1122/24s
        assert clip.get("offset") == "1122/24s"

    def test_all_unique_names_indexed(self, temp_fcpxml):
        modifier = FCPXMLModifier(temp_fcpxml)
        # sample has: Interview_A (×3), Broll_City (×3), Broll_Studio (×3)
        # But only 3 unique names survive indexing
        assert "Interview_A" in modifier.clips
        assert "Broll_City" in modifier.clips
        assert "Broll_Studio" in modifier.clips


# ============================================================
# write_fcpxml — output format validation
# ============================================================


class TestWriteFcpxmlFormat:
    """write_fcpxml must produce FCP-importable XML with correct headers."""

    def test_xml_declaration_and_doctype(self, tmp_path):
        root = ET.Element("fcpxml")
        root.set("version", "1.11")
        out = str(tmp_path / "out.fcpxml")
        write_fcpxml(root, out)
        content = Path(out).read_text()
        assert content.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert "<!DOCTYPE fcpxml>" in content

    def test_no_blank_lines(self, tmp_path):
        """Blank lines in pretty-printed XML confuse some FCP importers."""
        root = ET.Element("fcpxml")
        ET.SubElement(root, "resources")
        out = str(tmp_path / "blanks.fcpxml")
        write_fcpxml(root, out)
        content = Path(out).read_text()
        for line in content.split("\n"):
            assert line.strip() != "" or line == content.split("\n")[-1]

    def test_roundtrip_parseable(self, tmp_path):
        """Output of write_fcpxml must be parseable by ET.parse."""
        root = ET.Element("fcpxml")
        root.set("version", "1.11")
        res = ET.SubElement(root, "resources")
        ET.SubElement(res, "format", id="r1", frameDuration="1/24s",
                      width="1920", height="1080")
        out = str(tmp_path / "rt.fcpxml")
        write_fcpxml(root, out)
        tree = ET.parse(out)
        assert tree.getroot().tag == "fcpxml"
