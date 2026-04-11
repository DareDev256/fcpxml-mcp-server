"""Tests for recently refactored helper functions.

Covers: _index_elements (writer), _iter_spine_clips (writer),
_find_spine_clip_at_seconds (writer), _resolve_clip_duration (writer),
_make_asset_clip (writer), _format_batch_result (server),
and serialize_xml edge cases (safe_xml).

These helpers were extracted in v0.6.30–0.6.52 to eliminate duplication.
Only tested indirectly through callers — these tests validate edge cases
the callers never exercise.
"""

import os
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest

from fcpxml.safe_xml import serialize_xml
from fcpxml.writer import FCPXMLModifier

# ---------------------------------------------------------------------------
# Shim the `mcp` package tree before importing server.py (same as test_server)
# ---------------------------------------------------------------------------
_NEEDS_SHIM = "mcp" not in sys.modules or "mcp.server" not in sys.modules


def _install_mcp_shim():
    mcp = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    mcp_server_stdio = types.ModuleType("mcp.server.stdio")
    mcp_types = types.ModuleType("mcp.types")

    class _FakeServer:
        def __init__(self, *a, **kw): pass
        def call_tool(self): return lambda fn: fn
        def list_tools(self): return lambda fn: fn
        def list_resources(self): return lambda fn: fn
        def read_resource(self): return lambda fn: fn
        def list_prompts(self): return lambda fn: fn
        def get_prompt(self): return lambda fn: fn

    mcp_server.Server = _FakeServer

    class _FakeCtx:
        def __init__(self, *a): pass
        async def __aenter__(self): return (MagicMock(), MagicMock())
        async def __aexit__(self, *a): pass

    mcp_server_stdio.stdio_server = _FakeCtx

    class TextContent:
        def __init__(self, *, type: str, text: str):
            self.type = type
            self.text = text

    for name in ("GetPromptResult", "Prompt", "PromptArgument",
                 "PromptMessage", "Resource", "Tool"):
        setattr(mcp_types, name, MagicMock)
    mcp_types.TextContent = TextContent

    sys.modules.setdefault("mcp", mcp)
    sys.modules.setdefault("mcp.server", mcp_server)
    sys.modules.setdefault("mcp.server.stdio", mcp_server_stdio)
    sys.modules.setdefault("mcp.types", mcp_types)


if _NEEDS_SHIM:
    _install_mcp_shim()

from server import _format_batch_result, _markdown_table  # noqa: E402, I001


# ---------------------------------------------------------------------------
# Minimal FCPXML fixtures
# ---------------------------------------------------------------------------

SPINE_3_CLIPS = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine>
            <clip name="A" offset="0/2400s" duration="2400/2400s" start="0s" />
            <gap offset="2400/2400s" duration="1200/2400s" />
            <clip name="B" offset="3600/2400s" duration="2400/2400s" start="0s" />
            <asset-clip name="C" offset="6000/2400s" duration="2400/2400s" start="0s" />
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""

EMPTY_SPINE = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine></spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""

GAPS_ONLY_SPINE = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine>
            <gap offset="0/2400s" duration="2400/2400s" />
            <gap offset="2400/2400s" duration="1200/2400s" />
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""

DUPLICATE_NAMES = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine>
            <clip name="Interview" offset="0/2400s" duration="2400/2400s" start="0s" />
            <clip name="Interview" offset="2400/2400s" duration="2400/2400s" start="0s" />
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def _make_modifier(xml_str: str) -> FCPXMLModifier:
    """Create an FCPXMLModifier from an XML string via temp file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.fcpxml', delete=False) as f:
        f.write(xml_str)
        path = f.name
    try:
        return FCPXMLModifier(path)
    finally:
        os.unlink(path)


# ===================================================================
# _index_elements
# ===================================================================

class TestIndexElements:
    """Tests for FCPXMLModifier._index_elements."""

    def test_indexes_clips_by_name(self):
        mod = _make_modifier(SPINE_3_CLIPS)
        assert "A" in mod.clips
        assert "B" in mod.clips

    def test_indexes_asset_clips(self):
        mod = _make_modifier(SPINE_3_CLIPS)
        assert "C" in mod.clips

    def test_duplicate_names_last_wins(self):
        """When multiple clips share a name, the last one indexed wins."""
        mod = _make_modifier(DUPLICATE_NAMES)
        # Both are named "Interview" — only one key exists
        clip = mod.clips["Interview"]
        # The last one has offset="2400/2400s"
        assert clip.get("offset") == "2400/2400s"

    def test_fallback_prefix_when_no_id_or_name(self):
        """Elements without id or name get a generated key."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine>
            <clip offset="0/2400s" duration="2400/2400s" start="0s" />
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""
        mod = _make_modifier(xml)
        # No name/id → fallback key "clip_0"
        assert "clip_0" in mod.clips

    def test_id_preferred_over_name(self):
        """When both id and name exist, id takes priority."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine>
            <clip id="r42" name="MyClip" offset="0/2400s" duration="2400/2400s" start="0s" />
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""
        mod = _make_modifier(xml)
        assert "r42" in mod.clips


# ===================================================================
# _iter_spine_clips
# ===================================================================

class TestIterSpineClips:
    """Tests for FCPXMLModifier._iter_spine_clips."""

    def test_returns_only_clip_elements(self):
        mod = _make_modifier(SPINE_3_CLIPS)
        clips = mod._iter_spine_clips()
        tags = [elem.tag for _, elem in clips]
        assert "gap" not in tags
        assert tags == ["clip", "clip", "asset-clip"]

    def test_preserves_spine_index(self):
        """Indices should be positions among ALL spine children, not just clips."""
        mod = _make_modifier(SPINE_3_CLIPS)
        clips = mod._iter_spine_clips()
        indices = [i for i, _ in clips]
        # spine has: clip(0), gap(1), clip(2), asset-clip(3)
        assert indices == [0, 2, 3]

    def test_empty_spine_returns_empty(self):
        mod = _make_modifier(EMPTY_SPINE)
        assert mod._iter_spine_clips() == []

    def test_gaps_only_spine_returns_empty(self):
        mod = _make_modifier(GAPS_ONLY_SPINE)
        assert mod._iter_spine_clips() == []


# ===================================================================
# _find_spine_clip_at_seconds
# ===================================================================

class TestFindSpineClipAtSeconds:
    """Tests for FCPXMLModifier._find_spine_clip_at_seconds."""

    def test_finds_first_clip(self):
        mod = _make_modifier(SPINE_3_CLIPS)
        clip, rel = mod._find_spine_clip_at_seconds(0.5)
        assert clip.get("name") == "A"
        assert abs(rel - 0.5) < 0.001

    def test_finds_second_clip(self):
        mod = _make_modifier(SPINE_3_CLIPS)
        # B starts at 3600/2400 = 1.5s
        clip, rel = mod._find_spine_clip_at_seconds(2.0)
        assert clip.get("name") == "B"
        assert abs(rel - 0.5) < 0.001

    def test_exact_clip_boundary(self):
        """Requesting exactly at clip start should find that clip."""
        mod = _make_modifier(SPINE_3_CLIPS)
        clip, rel = mod._find_spine_clip_at_seconds(0.0)
        assert clip.get("name") == "A"
        assert abs(rel) < 0.001

    def test_raises_past_end(self):
        mod = _make_modifier(SPINE_3_CLIPS)
        with pytest.raises(ValueError, match="No spine clip"):
            mod._find_spine_clip_at_seconds(999.0)

    def test_raises_in_gap(self):
        """Position inside a gap (not a clip) should raise."""
        mod = _make_modifier(SPINE_3_CLIPS)
        # gap is at 2400/2400s=1.0s, dur 1200/2400s=0.5s → gap covers 1.0–1.5s
        with pytest.raises(ValueError, match="No spine clip"):
            mod._find_spine_clip_at_seconds(1.25)

    def test_raises_on_empty_spine(self):
        mod = _make_modifier(EMPTY_SPINE)
        with pytest.raises(ValueError, match="No spine clip"):
            mod._find_spine_clip_at_seconds(0.0)


# ===================================================================
# _resolve_clip_duration & _make_asset_clip (v0.6.52)
# ===================================================================

ASSET_SPINE = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" frameDuration="100/2400s" width="1920" height="1080"/>
    <asset id="r2" name="Interview" duration="4800/2400s" start="0s"
           hasVideo="1" hasAudio="1" uid="AAAA"/>
  </resources>
  <library>
    <event name="Test">
      <project name="TestProject">
        <sequence format="r1">
          <spine>
            <asset-clip ref="r2" name="Interview" offset="0/2400s"
                        duration="4800/2400s" start="0s" format="r1"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""

from fcpxml.models import TimeValue  # noqa: E402


class TestResolveClipDuration:
    """Tests for FCPXMLModifier._resolve_clip_duration."""

    def test_uses_in_out_points(self):
        mod = _make_modifier(ASSET_SPINE)
        asset = mod.resources['r2']
        dur, start = mod._resolve_clip_duration(
            asset, in_point="1200/2400s", out_point="3600/2400s",
        )
        assert dur == TimeValue(2400, 2400)
        assert start == TimeValue(1200, 2400)

    def test_explicit_duration_overrides_asset(self):
        mod = _make_modifier(ASSET_SPINE)
        asset = mod.resources['r2']
        dur, start = mod._resolve_clip_duration(asset, duration="1200/2400s")
        assert dur == TimeValue(1200, 2400)
        assert start == TimeValue.zero()

    def test_falls_back_to_asset_duration(self):
        mod = _make_modifier(ASSET_SPINE)
        asset = mod.resources['r2']
        dur, start = mod._resolve_clip_duration(asset)
        assert dur == TimeValue(4800, 2400)
        assert start == TimeValue.zero()

    def test_in_out_takes_priority_over_duration(self):
        """When both in/out and duration are given, in/out wins."""
        mod = _make_modifier(ASSET_SPINE)
        asset = mod.resources['r2']
        dur, start = mod._resolve_clip_duration(
            asset, duration="600/2400s",
            in_point="0s", out_point="2400/2400s",
        )
        # in/out range = 2400/2400s, not the explicit 600/2400s
        assert dur == TimeValue(2400, 2400)


class TestMakeAssetClip:
    """Tests for FCPXMLModifier._make_asset_clip."""

    def test_creates_detached_element(self):
        mod = _make_modifier(ASSET_SPINE)
        dur = TimeValue(2400, 2400)
        elem = mod._make_asset_clip(
            'r2', 'TestClip',
            TimeValue(0, 2400), TimeValue(0, 2400), dur,
        )
        assert elem.tag == 'asset-clip'
        assert elem.get('ref') == 'r2'
        assert elem.get('name') == 'TestClip'
        assert elem.get('duration') == dur.to_fcpxml()

    def test_creates_subelement_when_parent_given(self):
        mod = _make_modifier(ASSET_SPINE)
        parent = ET.Element('clip')
        dur = TimeValue(1200, 2400)
        elem = mod._make_asset_clip(
            'r2', 'Child',
            TimeValue(0, 2400), TimeValue(0, 2400), dur,
            parent=parent,
        )
        assert elem in list(parent)
        assert elem.get('name') == 'Child'
        assert elem.get('duration') == dur.to_fcpxml()

    def test_extra_attrs_applied(self):
        mod = _make_modifier(ASSET_SPINE)
        elem = mod._make_asset_clip(
            'r2', 'Audio',
            TimeValue(0, 2400), TimeValue(0, 2400), TimeValue(2400, 2400),
            lane='-1', audioRole='music',
        )
        assert elem.get('lane') == '-1'
        assert elem.get('audioRole') == 'music'

    def test_format_attr_passthrough(self):
        mod = _make_modifier(ASSET_SPINE)
        elem = mod._make_asset_clip(
            'r2', 'Formatted',
            TimeValue(0, 2400), TimeValue(0, 2400), TimeValue(2400, 2400),
            format='r1',
        )
        assert elem.get('format') == 'r1'


# ===================================================================
# _format_batch_result (server.py)
# ===================================================================

class TestFormatBatchResult:
    """Tests for server._format_batch_result."""

    def test_basic_structure(self):
        result = _format_batch_result(
            title="Flash Frames Fixed",
            summary={"Fixed": "3", "Skipped": "1"},
            headers=["Clip", "Action"],
            rows=[["A", "Removed"], ["B", "Trimmed"]],
            output_path="/tmp/out.fcpxml",
        )
        assert "# Flash Frames Fixed" in result
        assert "## Summary" in result
        assert "- **Fixed**: 3" in result
        assert "## Details" in result
        assert "| Clip | Action |" in result
        assert "Saved to: `/tmp/out.fcpxml`" in result

    def test_empty_rows(self):
        result = _format_batch_result(
            title="Nothing Done",
            summary={"Total": "0"},
            headers=["Name"],
            rows=[],
            output_path="/tmp/empty.fcpxml",
        )
        assert "# Nothing Done" in result
        assert "| Name |" in result
        # No data rows but header and separator still present
        assert "Saved to:" in result

    def test_markdown_table_alignment(self):
        table = _markdown_table(["A", "B"], [["1", "2"], ["3", "4"]])
        lines = table.strip().split("\n")
        assert len(lines) == 4  # header + sep + 2 data rows
        assert "---" in lines[1]


# ===================================================================
# serialize_xml edge cases (safe_xml.py)
# ===================================================================

class TestSerializeXml:
    """Tests for safe_xml.serialize_xml edge cases."""

    def test_no_doctype(self):
        root = ET.Element("root")
        ET.SubElement(root, "child").text = "hello"
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
            path = f.name
        try:
            serialize_xml(root, path)
            with open(path) as f:
                content = f.read()
            assert '<?xml version="1.0" encoding="UTF-8"?>' in content
            assert "<!DOCTYPE" not in content
            assert "<child>hello</child>" in content
        finally:
            os.unlink(path)

    def test_with_doctype(self):
        root = ET.Element("fcpxml")
        with tempfile.NamedTemporaryFile(suffix='.fcpxml', delete=False) as f:
            path = f.name
        try:
            serialize_xml(root, path, doctype="<!DOCTYPE fcpxml>")
            with open(path) as f:
                content = f.read()
            assert "<!DOCTYPE fcpxml>" in content
            assert content.index("<!DOCTYPE") > content.index("<?xml")
        finally:
            os.unlink(path)

    def test_strips_blank_lines(self):
        """Output should not contain blank lines (minidom artifact)."""
        root = ET.Element("root")
        for i in range(3):
            ET.SubElement(root, f"item{i}")
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
            path = f.name
        try:
            serialize_xml(root, path)
            with open(path) as f:
                content = f.read()
            for line in content.split('\n'):
                if line:  # non-empty lines should have content
                    assert line.strip() != ""
        finally:
            os.unlink(path)
