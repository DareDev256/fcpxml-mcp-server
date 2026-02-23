"""
FCPXML Parser - Reads Final Cut Pro XML files into Python objects.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

from .models import (
    Clip,
    ConnectedClip,
    Keyword,
    Marker,
    MarkerType,
    Project,
    Timecode,
    Timeline,
    Transition,
)

# Maximum FCPXML file size (50 MB) — prevents memory exhaustion from crafted files
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


class FCPXMLParser:
    """Parser for Final Cut Pro FCPXML files. Supports versions 1.8 - 1.11."""

    def __init__(self):
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.formats: Dict[str, Dict[str, Any]] = {}
        self.frame_rate: float = 24.0

    def parse_file(self, filepath: str) -> Project:
        """Parse an FCPXML file and return a Project object.

        Enforces a file size limit to prevent memory exhaustion from
        maliciously large XML files.
        """
        path = Path(filepath)
        if path.suffix == '.fcpxmld':
            fcpxml_path = path / 'Info.fcpxml'
            if not fcpxml_path.exists():
                raise FileNotFoundError(f"Info.fcpxml not found in bundle: {filepath}")
            filepath = str(fcpxml_path)
            path = Path(filepath)
        file_size = path.stat().st_size
        if file_size > _MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"FCPXML file exceeds maximum size "
                f"({file_size / 1024 / 1024:.1f} MB > "
                f"{_MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f} MB limit)"
            )
        tree = ET.parse(filepath)
        return self._parse_fcpxml(tree.getroot())

    def parse_string(self, xml_string: str) -> Project:
        """Parse FCPXML from a string."""
        return self._parse_fcpxml(ET.fromstring(xml_string))

    def _parse_fcpxml(self, root: ET.Element) -> Project:
        """Parse the root fcpxml element."""
        version = root.get('version', '1.11')
        resources_elem = root.find('resources')
        if resources_elem is not None:
            self._parse_resources(resources_elem)

        timelines = []
        for library in root.findall('.//library'):
            for event in library.findall('event'):
                for project in event.findall('project'):
                    timeline = self._parse_project(project)
                    if timeline:
                        timelines.append(timeline)

        if not timelines:
            for project in root.findall('.//project'):
                timeline = self._parse_project(project)
                if timeline:
                    timelines.append(timeline)

        project_name = timelines[0].name if timelines else "Untitled"
        return Project(name=project_name, timelines=timelines, fcpxml_version=version)

    def _parse_resources(self, resources: ET.Element):
        """Parse the resources section."""
        for fmt in resources.findall('format'):
            fmt_id = fmt.get('id', '')
            self.formats[fmt_id] = {
                'id': fmt_id, 'name': fmt.get('name', ''),
                'width': int(fmt.get('width', 1920)),
                'height': int(fmt.get('height', 1080)),
                'frameDuration': fmt.get('frameDuration', '1/24s')
            }
            frame_dur = fmt.get('frameDuration', '1/24s')
            if '/' in frame_dur:
                num, denom = frame_dur.rstrip('s').split('/')
                self.frame_rate = int(denom) / int(num)

        for asset in resources.findall('asset'):
            asset_id = asset.get('id', '')
            self.resources[asset_id] = {
                'id': asset_id, 'name': asset.get('name', ''),
                'src': asset.get('src', ''), 'start': asset.get('start', '0s'),
                'duration': asset.get('duration', '0s'),
                'hasVideo': asset.get('hasVideo', '1') == '1',
                'hasAudio': asset.get('hasAudio', '1') == '1',
            }

    def _parse_project(self, project: ET.Element) -> Optional[Timeline]:
        """Parse a project element into a Timeline."""
        name = project.get('name', 'Untitled')
        sequence = project.find('sequence')
        if sequence is None:
            return None

        duration_str = sequence.get('duration', '0s')
        format_ref = sequence.get('format', '')
        fmt = self.formats.get(format_ref, {})

        timeline = Timeline(
            name=name,
            duration=Timecode.from_rational(duration_str, self.frame_rate),
            frame_rate=self.frame_rate,
            width=fmt.get('width', 1920),
            height=fmt.get('height', 1080)
        )

        spine = sequence.find('spine')
        if spine is not None:
            self._parse_spine(spine, timeline)

        for marker_elem in sequence.findall('.//marker'):
            marker = self._parse_marker(marker_elem)
            if marker:
                timeline.markers.append(marker)

        for chapter_elem in sequence.findall('.//chapter-marker'):
            marker = self._parse_chapter_marker(chapter_elem)
            if marker:
                timeline.markers.append(marker)

        return timeline

    def _parse_spine(self, spine: ET.Element, timeline: Timeline):
        """Parse the spine (primary storyline) including connected clips."""
        current_offset = 0
        for elem in spine:
            tag = elem.tag
            if tag in ('asset-clip', 'clip', 'video', 'mc-clip', 'sync-clip', 'ref-clip'):
                clip = self._parse_clip(elem, current_offset)
                if clip:
                    timeline.clips.append(clip)
                    self._parse_connected_clips(elem, clip, timeline)
                    current_offset += clip.duration.frames
            elif tag == 'gap':
                duration_str = elem.get('duration', '0s')
                gap_frames = Timecode.from_rational(duration_str, self.frame_rate).frames
                self._parse_gap_connected_clips(elem, current_offset, timeline)
                current_offset += gap_frames
            elif tag == 'transition':
                transition = self._parse_transition(elem, current_offset)
                if transition:
                    timeline.transitions.append(transition)

    def _parse_clip(self, elem: ET.Element, offset: int) -> Optional[Clip]:
        """Parse a clip element."""
        name = elem.get('name', 'Untitled Clip')
        duration = Timecode.from_rational(elem.get('duration', '0s'), self.frame_rate)
        source_start = Timecode.from_rational(elem.get('start', '0s'), self.frame_rate)
        ref = elem.get('ref', '')
        media_path = self.resources.get(ref, {}).get('src', '')

        clip = Clip(
            name=name,
            start=Timecode(frames=offset, frame_rate=self.frame_rate),
            duration=duration,
            source_start=source_start,
            media_path=media_path,
            audio_role=elem.get('audioRole', ''),
            video_role=elem.get('videoRole', ''),
        )

        for marker_elem in elem.findall('marker'):
            marker = self._parse_marker(marker_elem)
            if marker:
                clip.markers.append(marker)

        for marker_elem in elem.findall('chapter-marker'):
            marker = self._parse_chapter_marker(marker_elem)
            if marker:
                clip.markers.append(marker)

        for keyword_elem in elem.findall('keyword'):
            keyword = self._parse_keyword(keyword_elem)
            if keyword:
                clip.keywords.append(keyword)

        return clip

    def _parse_marker(self, elem: ET.Element) -> Optional[Marker]:
        """Parse a marker element.

        Strictly validates the 'completed' attribute: only '0' and '1' are
        accepted. Any other value (e.g. injected strings, SQL fragments) is
        treated as a standard marker, preventing type confusion attacks.
        """
        completed_attr = elem.get('completed')
        if completed_attr == '1':
            marker_type = MarkerType.COMPLETED
        elif completed_attr == '0':
            marker_type = MarkerType.TODO
        else:
            # Any non-standard value (None, "", "true", injected strings)
            # falls through to STANDARD — never trust malformed attributes
            marker_type = MarkerType.STANDARD

        return Marker(
            name=elem.get('value', ''),
            start=Timecode.from_rational(elem.get('start', '0s'), self.frame_rate),
            duration=Timecode.from_rational(elem.get('duration', '1/24s'), self.frame_rate),
            marker_type=marker_type,
            note=elem.get('note', '')
        )

    def _parse_chapter_marker(self, elem: ET.Element) -> Optional[Marker]:
        """Parse a chapter marker element."""
        return Marker(
            name=elem.get('value', ''),
            start=Timecode.from_rational(elem.get('start', '0s'), self.frame_rate),
            duration=Timecode.from_rational(elem.get('duration', '1/24s'), self.frame_rate),
            marker_type=MarkerType.CHAPTER
        )

    def _parse_keyword(self, elem: ET.Element) -> Optional[Keyword]:
        """Parse a keyword element."""
        start_str, duration_str = elem.get('start'), elem.get('duration')
        return Keyword(
            value=elem.get('value', ''),
            start=Timecode.from_rational(start_str, self.frame_rate) if start_str else None,
            duration=Timecode.from_rational(duration_str, self.frame_rate) if duration_str else None
        )

    def _parse_transition(self, elem: ET.Element, offset: int) -> Optional[Transition]:
        """Parse a transition element."""
        return Transition(
            name=elem.get('name', 'Cross Dissolve'),
            duration=Timecode.from_rational(elem.get('duration', '1s'), self.frame_rate),
            start=Timecode(frames=offset, frame_rate=self.frame_rate)
        )

    def get_library_clips(self, keywords: Optional[list] = None) -> list:
        """
        Get all available clips from the library (assets in resources section).

        Args:
            keywords: Optional list of keywords to filter by

        Returns:
            List of dicts with asset metadata: name, asset_id, duration_seconds, src
        """
        result = []
        for asset_id, asset_data in self.resources.items():
            # Parse duration to seconds
            duration_str = asset_data.get('duration', '0s')
            duration_seconds = self._parse_duration_to_seconds(duration_str)

            clip_info = {
                'asset_id': asset_id,
                'name': asset_data.get('name', ''),
                'duration_seconds': duration_seconds,
                'src': asset_data.get('src', ''),
                'has_video': asset_data.get('hasVideo', True),
                'has_audio': asset_data.get('hasAudio', True),
            }
            result.append(clip_info)

        # Filter by keywords if provided
        if keywords:
            # For now, assets don't have keywords directly - return empty if filtering
            # In real FCPXML, keywords are typically on clips in events, not assets
            return []

        return result

    def _parse_connected_clips(self, parent_elem: ET.Element,
                                parent_clip: Clip, timeline: Timeline):
        """Parse connected clips attached to a primary storyline clip."""
        clip_tags = ('asset-clip', 'clip', 'video', 'audio', 'title', 'ref-clip')
        for child in parent_elem:
            lane = child.get('lane')
            if lane is not None and child.tag in clip_tags:
                connected = self._parse_one_connected_clip(
                    child, int(lane), parent_clip.name)
                if connected:
                    parent_clip.connected_clips.append(connected)
                    timeline.connected_clips.append(connected)
            elif child.tag == 'storyline':
                lane_val = int(child.get('lane', '1'))
                for sub_elem in child:
                    if sub_elem.tag in clip_tags:
                        connected = self._parse_one_connected_clip(
                            sub_elem, lane_val, parent_clip.name)
                        if connected:
                            parent_clip.connected_clips.append(connected)
                            timeline.connected_clips.append(connected)

    def _parse_gap_connected_clips(self, gap_elem: ET.Element,
                                    gap_offset: int, timeline: Timeline):
        """Parse connected clips attached to gap elements."""
        clip_tags = ('asset-clip', 'clip', 'video', 'audio', 'title', 'ref-clip')
        for child in gap_elem:
            lane = child.get('lane')
            if lane is not None and child.tag in clip_tags:
                connected = self._parse_one_connected_clip(
                    child, int(lane), f"gap@{gap_offset}")
                if connected:
                    timeline.connected_clips.append(connected)
            elif child.tag == 'storyline':
                lane_val = int(child.get('lane', '1'))
                for sub_elem in child:
                    if sub_elem.tag in clip_tags:
                        connected = self._parse_one_connected_clip(
                            sub_elem, lane_val, f"gap@{gap_offset}")
                        if connected:
                            timeline.connected_clips.append(connected)

    def _parse_one_connected_clip(self, elem: ET.Element, lane: int,
                                   parent_name: str) -> Optional[ConnectedClip]:
        """Parse a single connected clip element."""
        name = elem.get('name', 'Untitled')
        duration = Timecode.from_rational(
            elem.get('duration', '0s'), self.frame_rate)
        start = Timecode.from_rational(
            elem.get('start', '0s'), self.frame_rate)
        offset = Timecode.from_rational(
            elem.get('offset', '0s'), self.frame_rate)
        ref = elem.get('ref', '')
        media_path = self.resources.get(ref, {}).get('src', '')
        role = elem.get('audioRole', '') or elem.get('videoRole', '')

        connected = ConnectedClip(
            name=name, start=start, duration=duration,
            lane=lane, offset=offset, source_start=start,
            media_path=media_path, clip_type=elem.tag, role=role,
            ref_id=ref, parent_clip_name=parent_name,
        )

        for marker_elem in elem.findall('marker'):
            marker = self._parse_marker(marker_elem)
            if marker:
                connected.markers.append(marker)

        for keyword_elem in elem.findall('keyword'):
            keyword = self._parse_keyword(keyword_elem)
            if keyword:
                connected.keywords.append(keyword)

        return connected

    def _parse_duration_to_seconds(self, duration_str: str) -> float:
        """Convert FCPXML duration string to seconds."""
        if duration_str.endswith('s'):
            duration_str = duration_str[:-1]
        if '/' in duration_str:
            num, denom = duration_str.split('/')
            return float(num) / float(denom)
        return float(duration_str)


def parse_fcpxml(filepath: str) -> Project:
    """Convenience function to parse an FCPXML file."""
    return FCPXMLParser().parse_file(filepath)
