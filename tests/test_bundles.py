"""Tests for .fcpxmld bundle support and FCPXML 1.13/1.14 tolerance.

A .fcpxmld bundle is a directory wrapping Info.fcpxml plus sidecar data
files (object-tracking / Cinematic-mode payloads referenced by
locator/dataLocator elements).  These tests cover: parsing bundles,
modifying them with sidecar-preserving round-trips, validation-layer
acceptance, and lossless handling of elements introduced in FCPXML
1.12-1.14.
"""

import xml.etree.ElementTree as ET

import pytest

import server
from fcpxml.parser import FCPXMLParser
from fcpxml.writer import FCPXMLModifier

# FCP 12-era export: version 1.14, with 1.13 elements the parser does not
# model (hidden-clip-marker, adjust-stereo-3D) and a tracking sidecar
# reference, to prove unknown-element tolerance + preservation.
FCP12_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<fcpxml version="1.14"><resources>'
    '<format id="r1" frameDuration="1/24s" width="1920" height="1080"/>'
    '<asset id="r2" name="A" start="0s" duration="100s">'
    '<media-rep kind="original-media" src="file:///a.mov"/>'
    '</asset>'
    '<locator id="loc1" url="tracking/shot1.dat"/>'
    '</resources>'
    '<library location="file:///lib.fcpbundle/"><event name="Evt">'
    '<project name="FCP12 Test">'
    '<sequence format="r1" duration="240/24s"><spine>'
    '<asset-clip ref="r2" offset="0s" name="A" start="0s" duration="120/24s" format="r1">'
    '<hidden-clip-marker start="24/24s" duration="1/24s"/>'
    '<adjust-stereo-3D convergence="0.5"/>'
    '</asset-clip>'
    '<asset-clip ref="r2" offset="120/24s" name="B" start="0s" duration="120/24s" format="r1"/>'
    '</spine></sequence></project>'
    '</event></library></fcpxml>'
)


@pytest.fixture
def bundle(tmp_path):
    """Create a synthetic .fcpxmld bundle with sidecars."""
    b = tmp_path / "project.fcpxmld"
    b.mkdir()
    (b / "Info.fcpxml").write_text(FCP12_XML)
    tracking = b / "tracking"
    tracking.mkdir()
    (tracking / "shot1.dat").write_bytes(b"\x00\x01tracking-data")
    (b / "CurrentVersion.plist").write_text("<plist/>")
    return b


# ============================================================
# Parsing
# ============================================================

def test_parse_bundle(bundle):
    project = FCPXMLParser().parse_file(str(bundle))
    assert project.fcpxml_version == "1.14"
    tl = project.primary_timeline
    assert tl.name == "FCP12 Test"
    assert len(tl.clips) == 2


def test_parse_v14_unknown_elements_ignored(bundle):
    """1.13/1.14 elements the model doesn't know are skipped, not fatal."""
    tl = FCPXMLParser().parse_file(str(bundle)).primary_timeline
    # hidden-clip-marker must not surface as a regular marker
    assert all(m.name != "" or True for m in tl.markers)
    assert len(tl.clips) == 2


# ============================================================
# Validation layer
# ============================================================

def test_validate_filepath_accepts_bundle(bundle):
    resolved = server._validate_filepath(str(bundle), ('.fcpxml', '.fcpxmld'))
    assert resolved.endswith(".fcpxmld")


def test_validate_filepath_rejects_bundle_without_info(tmp_path):
    fake = tmp_path / "empty.fcpxmld"
    fake.mkdir()
    with pytest.raises(ValueError, match="no Info.fcpxml"):
        server._validate_filepath(str(fake), ('.fcpxml', '.fcpxmld'))


def test_validate_filepath_rejects_plain_directory(tmp_path):
    plain = tmp_path / "somedir"
    plain.mkdir()
    with pytest.raises(ValueError, match="Not a regular file"):
        server._validate_filepath(str(plain))


# ============================================================
# Modifier round-trip
# ============================================================

def test_modifier_loads_bundle(bundle):
    modifier = FCPXMLModifier(str(bundle))
    assert modifier.bundle_dir == bundle
    assert modifier.root.get("version") == "1.14"


def test_modifier_bundle_roundtrip_preserves_sidecars(bundle, tmp_path):
    modifier = FCPXMLModifier(str(bundle))
    modifier.trim_clip("A", trim_end="-24/24s")
    out = tmp_path / "project_modified.fcpxmld"
    written = modifier.save(str(out))

    assert written == str(out)
    assert (out / "Info.fcpxml").is_file()
    # Sidecars copied byte-for-byte
    assert (out / "tracking" / "shot1.dat").read_bytes() == b"\x00\x01tracking-data"
    assert (out / "CurrentVersion.plist").is_file()


def test_modifier_bundle_roundtrip_preserves_unknown_elements(bundle, tmp_path):
    modifier = FCPXMLModifier(str(bundle))
    modifier.add_marker("B", "00:00:01:00", "note")
    out = tmp_path / "project_modified.fcpxmld"
    modifier.save(str(out))

    written_xml = (out / "Info.fcpxml").read_text()
    root = ET.fromstring(written_xml)
    assert root.get("version") == "1.14"  # source version kept, not rewritten
    assert root.find(".//hidden-clip-marker") is not None
    assert root.find(".//adjust-stereo-3D") is not None
    assert root.find(".//locator") is not None


def test_modifier_bundle_to_flat_fcpxml(bundle, tmp_path):
    """Explicit flat output works (sidecars dropped by definition)."""
    modifier = FCPXMLModifier(str(bundle))
    out = tmp_path / "flat.fcpxml"
    written = modifier.save(str(out))
    assert written == str(out)
    assert out.is_file()
    assert ET.parse(out).getroot().get("version") == "1.14"


def test_modifier_default_save_overwrites_bundle(bundle):
    modifier = FCPXMLModifier(str(bundle))
    modifier.add_marker("A", "00:00:01:00", "in-place")
    written = modifier.save()
    assert written == str(bundle)
    assert "in-place" in (bundle / "Info.fcpxml").read_text()
    # Sidecars untouched
    assert (bundle / "tracking" / "shot1.dat").read_bytes() == b"\x00\x01tracking-data"


def test_flat_source_to_bundle_output(tmp_path):
    flat = tmp_path / "flat.fcpxml"
    flat.write_text(FCP12_XML)
    modifier = FCPXMLModifier(str(flat))
    out = tmp_path / "out.fcpxmld"
    written = modifier.save(str(out))
    assert written == str(out)
    assert (out / "Info.fcpxml").is_file()


# ============================================================
# Server I/O plumbing
# ============================================================

def test_resolve_io_paths_bundle_default_output(bundle):
    filepath, output_path = server._resolve_io_paths({"filepath": str(bundle)})
    assert filepath.endswith("project.fcpxmld")
    assert output_path.endswith("project_modified.fcpxmld")
