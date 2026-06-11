"""Validate generated FCPXML against Apple's official DTDs (v0.8.0).

These tests use the DTDs shipped inside the local Final Cut Pro app
bundle — the only authoritative FCPXML spec (Apple's online docs stopped
at 1.10).  On machines without FCP (CI runners), the whole module skips.
"""

import shutil
from pathlib import Path

import pytest

from fcpxml.dtd import (
    available_dtd_versions,
    find_apple_dtd,
    validate_against_dtd,
)
from fcpxml.templates import ClipSpec, apply_template
from fcpxml.writer import FCPXMLModifier

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.fcpxml"

HAVE_DTDS = bool(available_dtd_versions()) and shutil.which("xmllint")

pytestmark = pytest.mark.skipif(
    not HAVE_DTDS,
    reason="Apple FCPXML DTDs not available (Final Cut Pro not installed) "
    "or xmllint missing",
)


def test_dtds_present_through_1_13():
    versions = available_dtd_versions()
    assert "1.11" in versions
    assert "1.13" in versions


def test_find_apple_dtd_rejects_garbage():
    assert find_apple_dtd("../../etc/passwd") is None
    assert find_apple_dtd("99.99") is None


def test_template_output_is_dtd_valid(tmp_path):
    clips = {
        "main_content": ClipSpec(src="/test/main.mov", name="Main", duration=10.0),
    }
    out = str(tmp_path / "template.fcpxml")
    apply_template("lower_thirds", clips, out)
    ok, detail = validate_against_dtd(out)
    assert ok is True, detail


# DTD-valid 1.13 fixture (asset uses the required media-rep form;
# markers live inside clips, never at sequence level).
VALID_113 = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<fcpxml version="1.13"><resources>'
    '<format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" '
    'width="1920" height="1080"/>'
    '<asset id="r2" name="A" start="0s" duration="100s" hasVideo="1" format="r1">'
    '<media-rep kind="original-media" src="file:///a.mov"/>'
    '</asset>'
    '</resources>'
    '<library><event name="Evt"><project name="DTD Test">'
    '<sequence format="r1" duration="240/24s" tcStart="0s"><spine>'
    '<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="120/24s"/>'
    '<asset-clip ref="r2" offset="120/24s" name="B" start="0s" duration="120/24s"/>'
    '</spine></sequence></project></event></library></fcpxml>'
)


def test_modifier_roundtrip_stays_dtd_valid(tmp_path):
    src = tmp_path / "valid.fcpxml"
    src.write_text(VALID_113)
    ok, detail = validate_against_dtd(str(src))
    assert ok is True, f"fixture itself invalid: {detail}"

    out = str(tmp_path / "valid_modified.fcpxml")
    modifier = FCPXMLModifier(str(src))
    modifier.add_marker("A", "00:00:01:00", "dtd-check")
    modifier.trim_clip("B", trim_end="-24/24s")
    modifier.save(out)
    ok, detail = validate_against_dtd(out)
    assert ok is True, detail


def test_repo_sample_fixture_known_nonconformant():
    """examples/sample.fcpxml predates media-rep and uses sequence-level
    chapter markers — Apple's 1.11 DTD rejects both.  Documented here so
    the day it gets fixed, this test flips and forces a fixture review.
    """
    ok, detail = validate_against_dtd(str(SAMPLE))
    assert ok is False
    assert "media-rep" in detail or "asset" in detail


def test_invalid_xml_fails_dtd(tmp_path):
    bad = tmp_path / "bad.fcpxml"
    bad.write_text(
        '<?xml version="1.0"?>\n'
        '<fcpxml version="1.13"><made-up-element/></fcpxml>'
    )
    ok, detail = validate_against_dtd(str(bad))
    assert ok is False
    assert detail


def test_validate_missing_file_unavailable():
    ok, detail = validate_against_dtd("/nonexistent/file.fcpxml")
    assert ok is None
    assert "not found" in detail.lower()
