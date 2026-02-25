"""
Security tests — input validation, sanitization, and hardening.

Covers:
- MarkerType.from_string injection/abuse resistance
- XML value sanitization (null bytes, control chars, length limits)
- Parser file size limits
- Marker completed-attribute strict validation
"""

import pytest

from fcpxml.models import MarkerType
from fcpxml.parser import _MAX_FILE_SIZE_BYTES, FCPXMLParser
from fcpxml.writer import (
    _MAX_MARKER_NAME_LENGTH,
    FCPXMLModifier,
    _sanitize_xml_value,
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
