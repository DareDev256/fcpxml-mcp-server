"""
FCPXML Writer - Generate and modify Final Cut Pro XML files.
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
import uuid

from .models import Project, Timeline, Clip, Marker, MarkerType, Keyword, Timecode


class FCPXMLWriter:
    """Writer for generating Final Cut Pro FCPXML files."""
    
    def __init__(self, version: str = "1.11"):
        self.version = version
        self.resource_counter = 1
    
    def _next_resource_id(self) -> str:
        rid = f"r{self.resource_counter}"
        self.resource_counter += 1
        return rid
    
    def _generate_uid(self) -> str:
        return str(uuid.uuid4()).upper()
    
    def _tc_to_rational(self, tc: Timecode) -> str:
        return f"{tc.frames}/{int(tc.frame_rate)}s"
    
    def write_project(self, project: Project, filepath: str):
        """Write a project to an FCPXML file."""
        root = self._build_fcpxml(project)
        xml_str = ET.tostring(root, encoding='unicode')
        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent="    ")
        lines = [line for line in pretty_xml.split('\n') if line.strip()]
        final_xml = '\n'.join(lines)
        final_xml = final_xml.replace(
            '<?xml version="1.0" ?>',
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>'
        )
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_xml)
    
    def _build_fcpxml(self, project: Project) -> ET.Element:
        root = ET.Element('fcpxml', version=self.version)
        resources = ET.SubElement(root, 'resources')
        resource_map = {}
        
        if project.timelines:
            timeline = project.timelines[0]
            format_id = self._next_resource_id()
            ET.SubElement(resources, 'format',
                id=format_id,
                name=f"FFVideoFormat{timeline.height}p{int(timeline.frame_rate)}",
                frameDuration=f"1/{int(timeline.frame_rate)}s",
                width=str(timeline.width), height=str(timeline.height))
            resource_map['_format'] = format_id
        
        library = ET.SubElement(root, 'library',
            location=f"file:///Users/editor/Movies/{project.name}.fcpbundle/")
        event = ET.SubElement(library, 'event', name=project.name, uid=self._generate_uid())
        
        for timeline in project.timelines:
            self._add_timeline(event, timeline, resources, resource_map)
        return root
    
    def _add_timeline(self, event, timeline, resources, resource_map):
        project_elem = ET.SubElement(event, 'project',
            name=timeline.name, uid=self._generate_uid(),
            modDate=datetime.now().strftime("%Y-%m-%d %H:%M:%S -0500"))
        
        format_id = resource_map.get('_format', 'r1')
        sequence = ET.SubElement(project_elem, 'sequence',
            format=format_id, duration=self._tc_to_rational(timeline.duration),
            tcStart="0s", tcFormat="NDF", audioLayout="stereo", audioRate="48k")
        
        spine = ET.SubElement(sequence, 'spine')
        for clip in timeline.clips:
            self._add_clip(spine, clip, resources, resource_map)
        for marker in timeline.markers:
            self._add_marker(sequence, marker)
    
    def _add_clip(self, spine, clip, resources, resource_map):
        if clip.media_path and clip.media_path not in resource_map:
            asset_id = self._next_resource_id()
            ET.SubElement(resources, 'asset', id=asset_id, name=clip.name,
                uid=self._generate_uid(), src=clip.media_path, start="0s",
                duration=self._tc_to_rational(clip.duration), hasVideo="1", hasAudio="1")
            resource_map[clip.media_path] = asset_id
        
        asset_id = resource_map.get(clip.media_path, 'r1')
        format_id = resource_map.get('_format', 'r1')
        clip_elem = ET.SubElement(spine, 'asset-clip',
            ref=asset_id, offset=self._tc_to_rational(clip.start), name=clip.name,
            start=self._tc_to_rational(clip.source_start) if clip.source_start else "0s",
            duration=self._tc_to_rational(clip.duration), format=format_id, tcFormat="NDF")
        
        for marker in clip.markers:
            self._add_marker(clip_elem, marker)
        for keyword in clip.keywords:
            self._add_keyword(clip_elem, keyword)
    
    def _add_marker(self, parent, marker):
        tag = 'chapter-marker' if marker.marker_type == MarkerType.CHAPTER else 'marker'
        elem = ET.SubElement(parent, tag,
            start=self._tc_to_rational(marker.start),
            duration=self._tc_to_rational(marker.duration) if marker.duration else "1/24s",
            value=marker.name)
        if marker.note and tag == 'marker':
            elem.set('note', marker.note)
    
    def _add_keyword(self, parent, keyword):
        attrs = {'value': keyword.value}
        if keyword.start:
            attrs['start'] = self._tc_to_rational(keyword.start)
        if keyword.duration:
            attrs['duration'] = self._tc_to_rational(keyword.duration)
        ET.SubElement(parent, 'keyword', **attrs)
