"""Tests for fcpxml/export.py — DaVinci Resolve and XMEML export.

Covers: attribute stripping, compound clip flattening, audio track
generation, lane mapping, file path handling, no-timeline error,
doctype injection, NTSC detection.
"""

import os
import tempfile
import xml.etree.ElementTree as ET

import pytest

from fcpxml.export import DaVinciExporter
from fcpxml.safe_xml import serialize_xml

BASE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="Clip_A" src="file:///Media/a.mov" start="0s" duration="240/24s" hasVideo="1" hasAudio="1" format="r1"/>
        <asset id="r3" name="Clip_B" src="file:///Media/b.mov" start="0s" duration="240/24s" hasVideo="1" hasAudio="1" format="r1"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Export Test" modDate="2025-01-15 10:30:00 -0500">
                <sequence format="r1" duration="480/24s" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="Clip_A" start="0s" duration="240/24s" format="r1"/>
                        <asset-clip ref="r3" offset="240/24s" name="Clip_B" start="0s" duration="240/24s" format="r1"/>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""

CONNECTED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="Main" src="file:///Media/main.mov" start="0s" duration="240/24s" hasVideo="1" hasAudio="1" format="r1"/>
        <asset id="r3" name="Broll" src="file:///Media/broll.mov" start="0s" duration="120/24s" hasVideo="1" hasAudio="1" format="r1"/>
        <asset id="r4" name="VO" src="file:///Media/vo.mov" start="0s" duration="120/24s" hasVideo="0" hasAudio="1" format="r1"/>
    </resources>
    <library>
        <event name="Test">
            <project name="Connected Test">
                <sequence format="r1" duration="240/24s">
                    <spine>
                        <asset-clip ref="r2" offset="0s" name="Main" start="0s" duration="240/24s" format="r1" lane="0">
                            <asset-clip ref="r3" lane="1" offset="48/24s" name="Broll" start="0s" duration="120/24s"/>
                            <asset-clip ref="r4" lane="-1" offset="0s" name="VO" start="0s" duration="120/24s"/>
                        </asset-clip>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>"""

COMPOUND_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
        <asset id="r2" name="Clip_A" src="file:///a.mov" start="0s" duration="240/24s" hasVideo="1" hasAudio="1" format="r1"/>
        <media id="r5" name="Compound">
            <sequence format="r1" duration="240/24s">
                <spine>
                    <asset-clip ref="r2" offset="0s" name="Clip_A" start="0s" duration="240/24s"/>
                </spine>
            </sequence>
        </media>
    </resources>
    <library>
        <event name="Test">
            <project name="Compound Test">
                <sequence format="r1" duration="240/24s">
                    <spine>
                        <ref-clip ref="r5" offset="0s" name="Compound" duration="240/24s" srcEnable="all"/>
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


def _out(suffix='.fcpxml') -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


class TestAttributeStripping:
    """Simplified FCPXML should strip Resolve-incompatible attributes."""

    def test_moddate_removed(self):
        src = _tmp(BASE_XML)
        out = _out()
        try:
            exp = DaVinciExporter(src)
            exp.export_simplified_fcpxml(out)
            tree = ET.parse(out)
            for elem in tree.iter():
                assert 'modDate' not in elem.attrib
        finally:
            os.unlink(src)
            os.unlink(out)

    def test_version_downgraded_to_1_9(self):
        src = _tmp(BASE_XML)
        out = _out()
        try:
            exp = DaVinciExporter(src)
            exp.export_simplified_fcpxml(out)
            tree = ET.parse(out)
            assert tree.getroot().get('version') == '1.9'
        finally:
            os.unlink(src)
            os.unlink(out)

    def test_colorprocessing_stripped(self):
        xml = BASE_XML.replace('<fcpxml version="1.11">', '<fcpxml version="1.11" colorProcessing="wide">')
        src = _tmp(xml)
        out = _out()
        try:
            exp = DaVinciExporter(src)
            exp.export_simplified_fcpxml(out)
            tree = ET.parse(out)
            assert 'colorProcessing' not in tree.getroot().attrib
        finally:
            os.unlink(src)
            os.unlink(out)


class TestCompoundClipFlattening:
    """ref-clip → asset-clip conversion when flatten_compounds=True."""

    def test_ref_clip_becomes_asset_clip(self):
        src = _tmp(COMPOUND_XML)
        out = _out()
        try:
            exp = DaVinciExporter(src)
            exp.export_simplified_fcpxml(out, flatten_compounds=True)
            tree = ET.parse(out)
            ref_clips = tree.findall('.//ref-clip')
            asset_clips = tree.findall('.//asset-clip')
            assert len(ref_clips) == 0, "ref-clip should be converted"
            assert len(asset_clips) >= 1
        finally:
            os.unlink(src)
            os.unlink(out)

    def test_flatten_strips_compound_attrs(self):
        """srcEnable and other compound-specific attrs should be removed."""
        src = _tmp(COMPOUND_XML)
        out = _out()
        try:
            exp = DaVinciExporter(src)
            exp.export_simplified_fcpxml(out, flatten_compounds=True)
            tree = ET.parse(out)
            for clip in tree.findall('.//asset-clip'):
                assert 'srcEnable' not in clip.attrib
        finally:
            os.unlink(src)
            os.unlink(out)

    def test_no_flatten_preserves_ref_clip(self):
        src = _tmp(COMPOUND_XML)
        out = _out()
        try:
            exp = DaVinciExporter(src)
            exp.export_simplified_fcpxml(out, flatten_compounds=False)
            tree = ET.parse(out)
            ref_clips = tree.findall('.//ref-clip')
            assert len(ref_clips) >= 1, "ref-clip should be preserved"
        finally:
            os.unlink(src)
            os.unlink(out)


class TestXmemlAudioTracks:
    """Audio tracks from connected clips with negative lanes."""

    def test_audio_track_generated_from_negative_lane(self):
        src = _tmp(CONNECTED_XML)
        out = _out('.xml')
        try:
            exp = DaVinciExporter(src)
            exp.export_xmeml(out)
            tree = ET.parse(out)
            audio = tree.find('.//audio')
            assert audio is not None
            audio_tracks = audio.findall('track')
            assert len(audio_tracks) >= 1
        finally:
            os.unlink(src)
            os.unlink(out)

    def test_primary_storyline_audio_fallback(self):
        """When no connected audio clips, primary storyline creates audio track."""
        src = _tmp(BASE_XML)
        out = _out('.xml')
        try:
            exp = DaVinciExporter(src)
            exp.export_xmeml(out)
            tree = ET.parse(out)
            audio = tree.find('.//audio')
            tracks = audio.findall('track')
            assert len(tracks) >= 1
            clipitems = tracks[0].findall('clipitem')
            assert len(clipitems) == 2  # Both primary clips have audio
        finally:
            os.unlink(src)
            os.unlink(out)


class TestXmemlFilePathHandling:
    """Clipitem file/pathurl elements from media_path."""

    def test_clipitem_has_file_pathurl(self):
        src = _tmp(BASE_XML)
        out = _out('.xml')
        try:
            exp = DaVinciExporter(src)
            exp.export_xmeml(out)
            tree = ET.parse(out)
            clipitems = tree.findall('.//clipitem')
            found_path = False
            for ci in clipitems:
                file_elem = ci.find('file')
                if file_elem is not None:
                    pathurl = file_elem.find('pathurl')
                    if pathurl is not None and pathurl.text:
                        found_path = True
                        break
            assert found_path, "At least one clipitem should have file/pathurl"
        finally:
            os.unlink(src)
            os.unlink(out)


class TestNoTimelineError:
    """Export should fail cleanly when FCPXML has no timeline."""

    NO_TL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <format id="r1" name="FFVideoFormat1080p24" frameDuration="1/24s" width="1920" height="1080"/>
    </resources>
    <library>
        <event name="Empty"/>
    </library>
</fcpxml>"""

    def test_xmeml_raises_on_no_timeline(self):
        src = _tmp(self.NO_TL_XML)
        out = _out('.xml')
        try:
            exp = DaVinciExporter(src)
            with pytest.raises(ValueError, match="No timeline"):
                exp.export_xmeml(out)
        finally:
            os.unlink(src)
            if os.path.exists(out):
                os.unlink(out)


class TestDoctypeInjection:
    """serialize_xml should inject DOCTYPE correctly."""

    def test_doctype_inserted(self):
        root = ET.Element('fcpxml')
        root.set('version', '1.9')
        out = _out()
        try:
            serialize_xml(root, out, '<!DOCTYPE fcpxml>')
            with open(out) as f:
                content = f.read()
            assert '<!DOCTYPE fcpxml>' in content
            assert '<?xml version="1.0" encoding="UTF-8"?>' in content
        finally:
            os.unlink(out)

    def test_no_doctype(self):
        root = ET.Element('test')
        out = _out()
        try:
            serialize_xml(root, out, '')
            with open(out) as f:
                content = f.read()
            assert '<!DOCTYPE' not in content
        finally:
            os.unlink(out)


class TestNtscDetection:
    """NTSC flag set correctly for various frame rates."""

    def test_24fps_not_ntsc(self):
        src = _tmp(BASE_XML)
        out = _out('.xml')
        try:
            exp = DaVinciExporter(src)
            exp.export_xmeml(out)
            tree = ET.parse(out)
            ntsc = tree.find('.//rate/ntsc')
            assert ntsc.text == 'FALSE'
        finally:
            os.unlink(src)
            os.unlink(out)
