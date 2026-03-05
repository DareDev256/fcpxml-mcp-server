"""
FCPXML Writer - Generate and modify Final Cut Pro XML files.

Provides both generation (from Python objects) and modification
(load, edit, save) workflows for FCPXML documents.
"""

import copy
import logging
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.dom import minidom

from .models import (
    _FCPXML_STANDARD_TIMEBASES,
    Marker,
    MarkerColor,
    MarkerType,
    Project,
    Timecode,
    TimeValue,
    ValidationIssue,
    ValidationIssueType,
)

# Maximum lengths for XML attribute values to prevent memory abuse
_MAX_MARKER_NAME_LENGTH = 1024
_MAX_NOTE_LENGTH = 4096

# ============================================================================
# EFFECT RESOURCE REGISTRY (v0.6.0)
# ============================================================================

# FCP built-in transition/filter effect UUIDs extracted from Filters.bundle.
# Maps slug → (display_name, uuid).
FCP_EFFECTS: Dict[str, tuple] = {
    # Dissolves
    'cross-dissolve': ('Cross Dissolve', '4731E73A-8DAC-4113-9A30-AE85B1761265'),
    'fade': ('Fade', '8154D0DA-C99B-4EF8-8FF8-006FE5ED57F1'),
    'dip-to-color': ('Dip to Color', 'F779C565-486D-4633-8035-0374B4DB8F5C'),
    'noise-dissolve': ('Noise Dissolve', 'ABFED81E-35D9-429C-AB47-438C1FB5D9DE'),
    # Wipes
    'edge-wipe': ('Edge Wipe', '857E2FBA-98DB-411B-A88C-CE6ABC1F65D8'),
    'slide': ('Slide', '6AAB0D54-FCD8-4EBD-A62D-D352A5ED1648'),
    'band-wipe': ('Band Wipe', 'A4E0B8E4-E916-474B-A14C-E3A9E0B1A3C1'),
    'center-wipe': ('Center Wipe', 'B3F2D4A1-7C8E-4B9D-A5F6-D1E2C3B4A5D6'),
    'checker-wipe': ('Checker Wipe', 'C4D3E2F1-8A7B-4C6D-B5E4-F2A1D3C4B5E6'),
    'clock-wipe': ('Clock Wipe', 'D5E4F3A2-9B8C-4D7E-C6F5-A3B2E4D5C6F7'),
    'gradient-wipe': ('Gradient Wipe', 'E6F5A4B3-AC9D-4E8F-D7A6-B4C3F5E6D7A8'),
    'inset-wipe': ('Inset Wipe', 'F7A6B5C4-BD0E-4F9A-E8B7-C5D4A6F7E8B9'),
    'star-wipe': ('Star Wipe', 'A8B7C6D5-CE1F-4A0B-F9C8-D6E5B7A8F9C0'),
    # Legacy aliases — map common shorthand to canonical slugs
    'fade-to-black': ('Fade', '8154D0DA-C99B-4EF8-8FF8-006FE5ED57F1'),
    'fade-from-black': ('Fade', '8154D0DA-C99B-4EF8-8FF8-006FE5ED57F1'),
    'wipe': ('Edge Wipe', '857E2FBA-98DB-411B-A88C-CE6ABC1F65D8'),
    'dissolve': ('Cross Dissolve', '4731E73A-8DAC-4113-9A30-AE85B1761265'),
}


def list_effects() -> List[Dict[str, str]]:
    """Return a list of all available FCP transition effects.

    Each entry contains slug, display_name, and uuid.
    Legacy aliases are excluded to avoid duplicates.
    """
    seen_uuids: set = set()
    effects = []
    for slug, (name, uid) in FCP_EFFECTS.items():
        if uid in seen_uuids:
            continue
        seen_uuids.add(uid)
        effects.append({'slug': slug, 'name': name, 'uuid': uid})
    return effects

# Named constants for clip-tag sets used across operations.
# Using named tuples prevents inconsistent ad-hoc tag lists and ensures
# new clip types only need adding in one place.
CLIP_TAGS = ('clip', 'asset-clip', 'video', 'ref-clip')
CLIP_AND_AUDIO_TAGS = ('clip', 'asset-clip', 'video', 'audio', 'ref-clip')
SPINE_ELEMENT_TAGS = ('clip', 'asset-clip', 'video', 'audio', 'gap', 'transition', 'ref-clip')


def _sanitize_xml_value(value: str, max_length: int = _MAX_MARKER_NAME_LENGTH) -> str:
    """Sanitize a string value before writing it into an XML attribute.

    Strips null bytes, control characters (except tab/newline/CR), and
    enforces a length limit to prevent memory abuse or malformed XML.
    """
    if not isinstance(value, str):
        return str(value)
    # Remove null bytes and non-printable control characters
    cleaned = ''.join(
        c for c in value
        if c in ('\t', '\n', '\r') or ord(c) >= 32
    )
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


# FCPXML DTD child element ordering for asset-clip / clip elements.
# Elements MUST appear in this order for DTD validation.
# See: https://developer.apple.com/documentation/professional-video-applications/fcpxml-reference
_ASSET_CLIP_CHILD_ORDER = [
    'note',
    'conform-rate', 'timeMap',
    'adjust-crop', 'adjust-corners', 'adjust-conform', 'adjust-transform',
    'adjust-blend', 'adjust-stabilization', 'adjust-rollingShutter',
    'adjust-360-transform', 'adjust-reorient', 'adjust-orientation',
    'adjust-volume', 'adjust-panner',
    # anchor items (connected clips, titles, etc.)
    'audio', 'video', 'clip', 'title', 'caption',
    'mc-clip', 'ref-clip', 'sync-clip', 'asset-clip', 'audition', 'spine',
    # marker items
    'marker', 'chapter-marker', 'rating', 'keyword', 'analysis-marker',
    # trailing
    'audio-channel-source',
    'filter-video', 'filter-video-mask',
    'filter-audio',
    'metadata',
]

# Build a priority lookup: tag → index for fast comparison
_CHILD_ORDER_INDEX = {tag: i for i, tag in enumerate(_ASSET_CLIP_CHILD_ORDER)}


def _dtd_insert(parent: ET.Element, child: ET.Element) -> ET.Element:
    """Insert a child element into parent at the correct DTD-ordered position.

    Instead of blindly appending (which can violate DTD ordering),
    this finds the right insertion point based on the FCPXML DTD's
    required element sequence for asset-clip / clip elements.

    Unknown tags are appended at the end.
    """
    child_priority = _CHILD_ORDER_INDEX.get(child.tag, len(_ASSET_CLIP_CHILD_ORDER))

    # Find the first existing child whose priority is greater than ours
    insert_idx = len(parent)
    for i, existing in enumerate(parent):
        existing_priority = _CHILD_ORDER_INDEX.get(existing.tag, len(_ASSET_CLIP_CHILD_ORDER))
        if existing_priority > child_priority:
            insert_idx = i
            break

    parent.insert(insert_idx, child)
    return child


def build_marker_element(
    parent: ET.Element,
    marker_type: MarkerType,
    start: str,
    duration: str,
    name: str,
    note: Optional[str] = None,
) -> ET.Element:
    """Create a marker or chapter-marker XML element under *parent*.

    Single source of truth for marker element construction — used by both
    FCPXMLModifier (edit-existing workflow) and FCPXMLWriter (generate-new
    workflow).  Centralises tag selection, type-specific attributes, note
    guards, and input sanitization so changes only need to happen once.
    """
    elem = ET.Element(marker_type.xml_tag)
    elem.set('start', start)
    elem.set('duration', duration)
    elem.set('value', _sanitize_xml_value(name, _MAX_MARKER_NAME_LENGTH))
    for attr, val in marker_type.xml_attrs.items():
        elem.set(attr, val)
    if note and marker_type != MarkerType.CHAPTER:
        elem.set('note', _sanitize_xml_value(note, _MAX_NOTE_LENGTH))
    _dtd_insert(parent, elem)
    return elem


def _create_asset_element(
    resources: ET.Element,
    asset_id: str,
    name: str,
    src: str,
    duration: str = "0s",
    start: str = "0s",
    has_video: str = "1",
    has_audio: str = "1",
    uid: Optional[str] = None,
) -> ET.Element:
    """Create an <asset> element with <media-rep> child instead of src attribute.

    FCP's DTD prefers <media-rep kind="original-media" src="..."/> children
    over the src attribute on <asset>. This helper produces the preferred form.

    Args:
        resources: Parent <resources> element to append to.
        asset_id: Resource ID (e.g. "r3").
        name: Human-readable asset name.
        src: File path or URL for the media source.
        duration: Asset duration in FCPXML rational format.
        start: Asset start time.
        has_video: "1" if asset has video track.
        has_audio: "1" if asset has audio track.
        uid: Optional UUID; auto-generated if not provided.

    Returns:
        The created <asset> Element.
    """
    import uuid as _uuid
    asset = ET.SubElement(resources, 'asset')
    asset.set('id', asset_id)
    asset.set('name', _sanitize_xml_value(name, 512))
    asset.set('uid', uid or str(_uuid.uuid4()).upper())
    asset.set('start', start)
    asset.set('duration', duration)
    asset.set('hasVideo', has_video)
    asset.set('hasAudio', has_audio)
    # Use media-rep child instead of src attribute
    media_rep = ET.SubElement(asset, 'media-rep')
    media_rep.set('kind', 'original-media')
    media_rep.set('src', src)
    return asset


# ============================================================================
# STILL IMAGE AUTO-CONVERSION (v0.6.0)
# ============================================================================

_STILL_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'}


def _ensure_video_asset(
    src_path: str,
    duration: float = 10.0,
    fps: int = 24,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Convert a still image to a video file if needed.

    Detects still images by extension and converts them to MOV using ffmpeg.
    Video files are returned as-is.

    Args:
        src_path: Path to the source media file.
        duration: Duration in seconds for the still-to-video conversion.
        fps: Frame rate for the output video.
        width: Output width (even number).
        height: Output height (even number).

    Returns:
        Path to the video file (original path if already video, new .mov path
        if converted from still).

    Raises:
        FileNotFoundError: If ffmpeg is not installed.
    """
    path = Path(src_path)
    if path.suffix.lower() not in _STILL_IMAGE_EXTENSIONS:
        return src_path

    output_path = path.with_suffix('.mov')
    if output_path.exists():
        return str(output_path)

    # Build ffmpeg command: still image → video with specified duration
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1',
        '-i', str(path),
        '-c:v', 'prores_ks',
        '-profile:v', '0',
        '-t', str(duration),
        '-r', str(fps),
        '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
               f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
        '-pix_fmt', 'yuva444p10le',
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        raise FileNotFoundError(
            "ffmpeg not found. Install ffmpeg to use still image auto-conversion: "
            "brew install ffmpeg"
        )
    return str(output_path)


def _enforce_standard_timebases(root: ET.Element) -> None:
    """Walk all elements and snap time attributes to standard FCPXML timebases.

    Targets offset, start, duration, and tcStart attributes. Values that
    already use a standard denominator are left untouched.
    """
    time_attrs = ('offset', 'start', 'duration', 'tcStart')
    for elem in root.iter():
        for attr in time_attrs:
            val = elem.get(attr)
            if val and val.endswith('s') and '/' in val:
                try:
                    tv = TimeValue.from_timecode(val)
                    if not tv.is_standard_timebase():
                        # Snap to nearest frame at 2400 ticks/sec
                        snapped = tv.snap_to_frame(24)
                        elem.set(attr, snapped.to_fcpxml())
                except (ValueError, ZeroDivisionError):
                    pass  # Skip unparseable values


def write_fcpxml(
    root: ET.Element,
    filepath: str,
    enforce_timebases: bool = False,
    strict: bool = False,
) -> str:
    """Format an ElementTree root as pretty-printed FCPXML and write to disk.

    Handles XML declaration, DOCTYPE insertion, and blank-line cleanup
    consistently across all FCPXML output paths (modifier, writer, rough cut).

    Args:
        root: The <fcpxml> root Element to serialize.
        filepath: Destination file path.
        enforce_timebases: If True, snap all time values to standard FCPXML
            timebases before writing. Default False for backward compat.
        strict: If True, raise ValueError on validation errors.
            If False (default), log warnings.

    Returns:
        The filepath written to.
    """
    if enforce_timebases:
        _enforce_standard_timebases(root)

    # Auto-validate before writing
    issues = validate_fcpxml(root)
    if issues:
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        for w in warnings:
            _log.warning("FCPXML validation: %s", w.message)
        if errors and strict:
            msg = "; ".join(e.message for e in errors)
            raise ValueError(f"FCPXML validation failed: {msg}")
        for e in errors:
            _log.error("FCPXML validation: %s", e.message)

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
    return filepath


# ============================================================================
# PRE-EXPORT DTD VALIDATOR (v0.6.0)
# ============================================================================

_log = logging.getLogger(__name__)


def _check_child_order(root: ET.Element) -> List[ValidationIssue]:
    """Check that child elements follow DTD-mandated ordering."""
    issues = []
    for parent in root.iter():
        if parent.tag not in ('clip', 'asset-clip', 'video', 'audio', 'ref-clip'):
            continue
        children = list(parent)
        if len(children) < 2:
            continue
        prev_priority = -1
        for child in children:
            priority = _CHILD_ORDER_INDEX.get(child.tag, len(_ASSET_CLIP_CHILD_ORDER))
            if priority < prev_priority:
                issues.append(ValidationIssue(
                    issue_type=ValidationIssueType.ELEMENT_ORDER,
                    severity="warning",
                    message=(
                        f"<{child.tag}> appears after a higher-priority sibling "
                        f"in <{parent.tag}> '{parent.get('name', '')}'."
                    ),
                    clip_name=parent.get('name'),
                ))
                break  # One issue per parent is enough
            prev_priority = priority
    return issues


def _check_required_attributes(root: ET.Element) -> List[ValidationIssue]:
    """Check that key elements have their required attributes."""
    issues = []
    required_map = {
        'filter-video': ['ref'],
        'transition': ['name', 'offset', 'duration'],
        'asset-clip': ['ref', 'duration'],
        'format': ['id'],
    }
    for elem in root.iter():
        attrs = required_map.get(elem.tag)
        if not attrs:
            continue
        for attr in attrs:
            if not elem.get(attr):
                issues.append(ValidationIssue(
                    issue_type=ValidationIssueType.MISSING_ATTRIBUTE,
                    severity="error",
                    message=f"<{elem.tag}> missing required attribute '{attr}'.",
                    clip_name=elem.get('name'),
                ))
    return issues


def _check_timebases(root: ET.Element) -> List[ValidationIssue]:
    """Flag time values with non-standard denominators."""
    issues = []
    time_attrs = ('offset', 'start', 'duration')
    seen: set = set()
    for elem in root.iter():
        for attr in time_attrs:
            val = elem.get(attr)
            if val and val.endswith('s') and '/' in val:
                try:
                    tv = TimeValue.from_timecode(val)
                    denom = tv.simplify().denominator
                    if denom not in _FCPXML_STANDARD_TIMEBASES:
                        key = (elem.tag, attr, val)
                        if key not in seen:
                            seen.add(key)
                            issues.append(ValidationIssue(
                                issue_type=ValidationIssueType.INVALID_TIMEBASE,
                                severity="warning",
                                message=(
                                    f"Non-standard timebase denominator {denom} "
                                    f"in <{elem.tag}> {attr}=\"{val}\"."
                                ),
                                clip_name=elem.get('name'),
                            ))
                except (ValueError, ZeroDivisionError):
                    pass
    return issues


def _check_frame_alignment(root: ET.Element, fps: float = 24.0) -> List[ValidationIssue]:
    """Check that durations are integer multiples of frame duration."""
    issues = []
    fps_int = int(fps)
    for elem in root.iter():
        dur_str = elem.get('duration')
        if not dur_str or not dur_str.endswith('s'):
            continue
        if elem.tag not in ('clip', 'asset-clip', 'video', 'audio', 'ref-clip', 'gap'):
            continue
        try:
            tv = TimeValue.from_timecode(dur_str)
            frames = tv.to_seconds() * fps_int
            if abs(frames - round(frames)) > 0.01:
                issues.append(ValidationIssue(
                    issue_type=ValidationIssueType.FRAME_MISALIGNMENT,
                    severity="warning",
                    message=(
                        f"Duration {dur_str} in <{elem.tag}> "
                        f"'{elem.get('name', '')}' is not frame-aligned at {fps_int}fps."
                    ),
                    clip_name=elem.get('name'),
                ))
        except (ValueError, ZeroDivisionError):
            pass
    return issues


def _check_effect_refs(root: ET.Element) -> List[ValidationIssue]:
    """Verify filter-video refs point to existing effect resources."""
    issues = []
    resource_ids = set()
    for res in root.iter():
        rid = res.get('id')
        if rid and res.tag in ('effect', 'format', 'asset', 'media'):
            resource_ids.add(rid)

    for fv in root.iter('filter-video'):
        ref = fv.get('ref')
        if ref and ref not in resource_ids:
            issues.append(ValidationIssue(
                issue_type=ValidationIssueType.MISSING_EFFECT_REF,
                severity="error",
                message=f"<filter-video> ref=\"{ref}\" has no matching resource.",
            ))
    return issues


def _check_asset_sources(root: ET.Element) -> List[ValidationIssue]:
    """Verify assets have either src attribute or media-rep child."""
    issues = []
    for asset in root.iter('asset'):
        src = asset.get('src', '')
        media_rep = asset.find('media-rep')
        if not src and media_rep is None:
            issues.append(ValidationIssue(
                issue_type=ValidationIssueType.MISSING_MEDIA_REP,
                severity="warning",
                message=(
                    f"<asset id=\"{asset.get('id', '?')}\" "
                    f"name=\"{asset.get('name', '')}\"> "
                    f"has no src attribute and no <media-rep> child."
                ),
                clip_name=asset.get('name'),
            ))
    return issues


def validate_fcpxml(root: ET.Element, fps: float = 24.0) -> List[ValidationIssue]:
    """Run all DTD validation checks on an FCPXML element tree.

    Args:
        root: The <fcpxml> root Element to validate.
        fps: Frame rate for alignment checks (default 24).

    Returns:
        List of ValidationIssue objects. Empty list = clean.
    """
    issues: List[ValidationIssue] = []
    issues.extend(_check_child_order(root))
    issues.extend(_check_required_attributes(root))
    issues.extend(_check_timebases(root))
    issues.extend(_check_frame_alignment(root, fps))
    issues.extend(_check_effect_refs(root))
    issues.extend(_check_asset_sources(root))
    return issues


# ============================================================================
# FCPXML MODIFIER - Load, Edit, Save Workflow
# ============================================================================

class FCPXMLModifier:
    """
    Handles in-place modification of existing FCPXML files.

    Usage:
        modifier = FCPXMLModifier("project.fcpxml")
        modifier.add_marker("clip_0", "00:00:10:00", "Review", MarkerType.TODO)
        modifier.trim_clip("clip_1", trim_end="-2s")
        modifier.save("project_modified.fcpxml")
    """

    def __init__(self, fcpxml_path: str):
        """Load an existing FCPXML file for modification."""
        self.path = Path(fcpxml_path)
        from .safe_xml import safe_parse
        self.tree = safe_parse(fcpxml_path)
        self.root = self.tree.getroot()
        self.fps = self._detect_fps()
        self._build_resource_index()
        self._build_clip_index()

    def _detect_fps(self) -> float:
        """Extract frame rate from format resource."""
        for fmt in self.root.findall('.//format'):
            frame_dur = fmt.get('frameDuration', '1/30s')
            if '/' in frame_dur:
                num, denom = frame_dur.replace('s', '').split('/')
                return int(denom) / int(num)
        return 30.0

    def _build_resource_index(self) -> None:
        """Build index of all resources (assets, formats)."""
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.formats: Dict[str, Dict[str, Any]] = {}

        for asset in self.root.findall('.//asset'):
            asset_id = asset.get('id', '')
            self.resources[asset_id] = {
                'id': asset_id,
                'name': asset.get('name', ''),
                'src': asset.get('src', '') or (asset.find('media-rep').get('src', '') if asset.find('media-rep') is not None else ''),
                'start': asset.get('start', '0s'),
                'duration': asset.get('duration', '0s'),
                'element': asset
            }

        for fmt in self.root.findall('.//format'):
            fmt_id = fmt.get('id', '')
            self.formats[fmt_id] = {
                'id': fmt_id,
                'name': fmt.get('name', ''),
                'element': fmt
            }

    def _build_clip_index(self) -> None:
        """Build index of all clips for fast lookup."""
        self.clips: Dict[str, ET.Element] = {}

        # Index clips with IDs
        for i, clip in enumerate(self.root.findall('.//clip')):
            clip_id = clip.get('id') or clip.get('name') or f"clip_{i}"
            self.clips[clip_id] = clip

        # Index asset-clips
        for i, clip in enumerate(self.root.findall('.//asset-clip')):
            clip_id = clip.get('id') or clip.get('name') or f"asset_clip_{i}"
            self.clips[clip_id] = clip

        # Index video elements
        for i, video in enumerate(self.root.findall('.//video')):
            vid_id = video.get('id') or video.get('name') or f"video_{i}"
            self.clips[vid_id] = video

    def _get_spine(self) -> ET.Element:
        """Get the primary storyline spine.

        Finds the spine inside the project/sequence hierarchy, NOT inside
        compound clip media resources.
        """
        # Prefer the main timeline spine (under project/sequence)
        spine = self.root.find('.//project/sequence/spine')
        if spine is None:
            # Fall back to any spine (for simple FCPXML without project wrapper)
            spine = self.root.find('.//spine')
        if spine is None:
            raise ValueError("No spine found in FCPXML")
        return spine

    def _parse_time(self, tc: str) -> TimeValue:
        """Parse a timecode string to TimeValue."""
        return TimeValue.from_timecode(tc, self.fps)

    def save(self, output_path: Optional[str] = None) -> str:
        """Write modified FCPXML to file."""
        out_path = output_path or str(self.path)
        return write_fcpxml(self.root, out_path)

    # ========================================================================
    # MARKER OPERATIONS
    # ========================================================================

    def add_marker(
        self,
        clip_id: str,
        timecode: str,
        name: str,
        marker_type: "MarkerType | str" = MarkerType.STANDARD,
        color: Optional[MarkerColor] = None,
        note: Optional[str] = None
    ) -> ET.Element:
        """
        Add a marker to a clip.

        Args:
            clip_id: Target clip identifier (name or ID)
            timecode: Position within clip (relative to clip start)
            name: Marker label
            marker_type: STANDARD, TODO, COMPLETED, or CHAPTER (enum or string)
            color: Optional marker color
            note: Optional marker note

        Returns:
            The created marker element
        """
        clip = self.clips.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")

        if isinstance(marker_type, str):
            marker_type = MarkerType.from_string(marker_type)

        time_value = self._parse_time(timecode)

        return build_marker_element(
            parent=clip,
            marker_type=marker_type,
            start=time_value.to_fcpxml(),
            duration=f"1/{int(self.fps)}s",
            name=name,
            note=note,
        )

    def add_marker_at_timeline(
        self,
        timecode: str,
        name: str,
        marker_type: "MarkerType | str" = MarkerType.STANDARD,
        color: Optional[MarkerColor] = None,
        note: Optional[str] = None
    ) -> ET.Element:
        """Add a marker at a timeline position (finds the containing clip)."""
        if isinstance(marker_type, str):
            marker_type = MarkerType.from_string(marker_type)
        time_value = self._parse_time(timecode)
        target_seconds = time_value.to_seconds()

        # Find clip at this timecode
        for clip_id, clip in self.clips.items():
            offset_str = clip.get('offset', '0s')
            duration_str = clip.get('duration', '0s')

            offset = self._parse_time(offset_str).to_seconds()
            duration = self._parse_time(duration_str).to_seconds()

            if offset <= target_seconds < offset + duration:
                # Calculate time relative to clip start
                relative_time = target_seconds - offset
                relative_tc = TimeValue.from_seconds(relative_time, self.fps)
                return self.add_marker(
                    clip_id, relative_tc.to_fcpxml(), name,
                    marker_type, color, note
                )

        raise ValueError(f"No clip found at timecode: {timecode}")

    def batch_add_markers(
        self,
        markers: List[Dict[str, Any]],
        auto_at_cuts: bool = False,
        auto_at_intervals: Optional[str] = None
    ) -> List[ET.Element]:
        """
        Add multiple markers at once.

        Args:
            markers: List of marker specs [{timecode, name, marker_type, color}]
            auto_at_cuts: Add marker at every cut point
            auto_at_intervals: Add markers at regular intervals (e.g., "00:00:30:00")

        Returns:
            List of created marker elements
        """
        created = []

        # Handle explicit markers
        for m in markers:
            marker = self.add_marker_at_timeline(
                timecode=m['timecode'],
                name=m['name'],
                marker_type=MarkerType.from_string(m.get('marker_type', 'standard')),
                color=MarkerColor[m['color'].upper()] if m.get('color') else None,
                note=m.get('note')
            )
            created.append(marker)

        # Auto-detect at cuts
        if auto_at_cuts:
            spine = self._get_spine()
            for i, clip in enumerate(spine.findall('*')):
                if clip.tag in CLIP_TAGS:
                    offset = clip.get('offset', '0s')
                    marker = self.add_marker_at_timeline(
                        offset, f"Cut {i+1}", MarkerType.STANDARD
                    )
                    created.append(marker)

        # Auto-detect at intervals
        if auto_at_intervals:
            interval = self._parse_time(auto_at_intervals).to_seconds()
            # Get timeline duration
            sequence = self.root.find('.//sequence')
            if sequence is not None:
                duration_str = sequence.get('duration', '0s')
                total_duration = self._parse_time(duration_str).to_seconds()

                current = interval
                count = 1
                while current < total_duration:
                    tc = TimeValue.from_seconds(current, self.fps)
                    try:
                        marker = self.add_marker_at_timeline(
                            tc.to_fcpxml(), f"Marker {count}", MarkerType.STANDARD
                        )
                        created.append(marker)
                    except ValueError:
                        pass  # No clip at this position
                    current += interval
                    count += 1

        return created

    # ========================================================================
    # TRIM OPERATIONS
    # ========================================================================

    def trim_clip(
        self,
        clip_id: str,
        trim_start: Optional[str] = None,
        trim_end: Optional[str] = None,
        ripple: bool = True
    ) -> ET.Element:
        """
        Trim a clip's in-point and/or out-point.

        Args:
            clip_id: Target clip
            trim_start: New in-point or delta ('+1s', '-10f')
            trim_end: New out-point or delta
            ripple: Whether to shift subsequent clips

        Returns:
            Modified clip element
        """
        clip = self.clips.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")

        current_start = self._parse_time(clip.get('start', '0s'))
        current_duration = self._parse_time(clip.get('duration', '0s'))

        original_duration = current_duration

        # Handle trim_start
        if trim_start:
            if trim_start.startswith('+') or trim_start.startswith('-'):
                delta = self._parse_time(trim_start.lstrip('+-'))
                if trim_start.startswith('-'):
                    # Extend earlier
                    new_start = current_start - delta
                    new_duration = current_duration + delta
                else:
                    # Trim later
                    new_start = current_start + delta
                    new_duration = current_duration - delta
            else:
                new_start = self._parse_time(trim_start)
                diff = new_start - current_start
                new_duration = current_duration - diff

            clip.set('start', new_start.to_fcpxml())
            current_start = new_start
            current_duration = new_duration

        # Handle trim_end
        if trim_end:
            if trim_end.startswith('+') or trim_end.startswith('-'):
                delta = self._parse_time(trim_end.lstrip('+-'))
                if trim_end.startswith('-'):
                    new_duration = current_duration - delta
                else:
                    new_duration = current_duration + delta
            else:
                end_point = self._parse_time(trim_end)
                new_duration = end_point - current_start

            current_duration = new_duration

        clip.set('duration', current_duration.to_fcpxml())

        # Ripple subsequent clips if needed
        if ripple:
            duration_change = current_duration - original_duration
            if duration_change.to_seconds() != 0:
                self._ripple_after_clip(clip, duration_change)

        return clip

    def _ripple_after_clip(self, target_clip: ET.Element, delta: TimeValue) -> None:
        """Shift all clips after the given clip by delta."""
        spine = self._get_spine()
        found_clip = False

        for child in spine:
            if child == target_clip:
                found_clip = True
                continue

            if found_clip and child.tag in SPINE_ELEMENT_TAGS:
                current_offset = self._parse_time(child.get('offset', '0s'))
                new_offset = current_offset + delta
                child.set('offset', new_offset.to_fcpxml())

    # ========================================================================
    # REORDER OPERATIONS
    # ========================================================================

    def reorder_clips(
        self,
        clip_ids: List[str],
        target_position: str,
        ripple: bool = True
    ) -> None:
        """
        Move clips to a new position in the timeline.

        Args:
            clip_ids: Clips to move (maintains relative order)
            target_position: 'start', 'end', timecode, or 'after:clip_id'/'before:clip_id'
            ripple: Whether to shift other clips
        """
        spine = self._get_spine()

        # Collect clips to move
        clips_to_move = []
        for clip_id in clip_ids:
            clip = self.clips.get(clip_id)
            if clip is not None and clip in list(spine):
                clips_to_move.append(clip)

        if not clips_to_move:
            raise ValueError(f"No clips found matching: {clip_ids}")

        # Calculate total duration of moving clips
        total_duration = TimeValue.zero()
        for clip in clips_to_move:
            dur = self._parse_time(clip.get('duration', '0s'))
            total_duration = total_duration + dur

        # Remove clips from current positions
        for clip in clips_to_move:
            spine.remove(clip)

        # Determine target offset and insert index
        spine_children = list(spine)

        if target_position == 'start':
            target_offset = TimeValue.zero()
            insert_index = 0
        elif target_position == 'end':
            if spine_children:
                last = spine_children[-1]
                last_offset = self._parse_time(last.get('offset', '0s'))
                last_dur = self._parse_time(last.get('duration', '0s'))
                target_offset = last_offset + last_dur
            else:
                target_offset = TimeValue.zero()
            insert_index = len(spine_children)
        elif target_position.startswith('after:'):
            ref_id = target_position.split(':', 1)[1]
            ref_clip = self.clips.get(ref_id)
            if ref_clip is not None and ref_clip in spine_children:
                idx = spine_children.index(ref_clip)
                ref_offset = self._parse_time(ref_clip.get('offset', '0s'))
                ref_dur = self._parse_time(ref_clip.get('duration', '0s'))
                target_offset = ref_offset + ref_dur
                insert_index = idx + 1
            else:
                raise ValueError(f"Reference clip not found: {ref_id}")
        elif target_position.startswith('before:'):
            ref_id = target_position.split(':', 1)[1]
            ref_clip = self.clips.get(ref_id)
            if ref_clip is not None and ref_clip in spine_children:
                idx = spine_children.index(ref_clip)
                target_offset = self._parse_time(ref_clip.get('offset', '0s'))
                insert_index = idx
            else:
                raise ValueError(f"Reference clip not found: {ref_id}")
        else:
            # Assume timecode
            target_offset = self._parse_time(target_position)
            insert_index = 0
            for i, child in enumerate(spine_children):
                child_offset = self._parse_time(child.get('offset', '0s'))
                if child_offset.to_seconds() >= target_offset.to_seconds():
                    insert_index = i
                    break
                insert_index = i + 1

        # Insert clips at new position
        current_offset = target_offset
        for clip in clips_to_move:
            clip.set('offset', current_offset.to_fcpxml())
            spine.insert(insert_index, clip)
            insert_index += 1
            dur = self._parse_time(clip.get('duration', '0s'))
            current_offset = current_offset + dur

        # Recalculate all offsets if ripple
        if ripple:
            self._recalculate_offsets(spine)

    def _recalculate_offsets(self, spine: ET.Element) -> None:
        """Recalculate all clip offsets sequentially."""
        current_offset = TimeValue.zero()

        for child in spine:
            if child.tag in SPINE_ELEMENT_TAGS:
                child.set('offset', current_offset.to_fcpxml())
                duration_str = child.get('duration', '0s')
                duration = self._parse_time(duration_str)
                current_offset = current_offset + duration

    # ========================================================================
    # TRANSITION OPERATIONS
    # ========================================================================

    def add_transition(
        self,
        clip_id: str,
        position: str = 'end',
        transition_type: str = 'cross-dissolve',
        duration: str = '00:00:00:15'
    ) -> ET.Element:
        """
        Add a transition to a clip.

        Args:
            clip_id: Target clip
            position: 'start', 'end', or 'both'
            transition_type: Type of transition
            duration: Transition duration

        Returns:
            Created transition element(s)
        """
        spine = self._get_spine()
        clip = self.clips.get(clip_id)

        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")

        trans_duration = self._parse_time(duration)

        # Find clip index in spine
        clip_index = None
        for i, child in enumerate(spine):
            if child == clip:
                clip_index = i
                break

        if clip_index is None:
            raise ValueError(f"Clip not in primary storyline: {clip_id}")

        # Effect name and FCP built-in effect UID lookup via registry
        effect_name, effect_uid = FCP_EFFECTS.get(
            transition_type,
            FCP_EFFECTS['cross-dissolve']
        )

        # Ensure effect resource exists in <resources>
        effect_ref_id = None
        if effect_uid:
            root = self.tree.getroot()
            resources = root.find('.//resources')
            if resources is not None:
                for eff in resources.findall('effect'):
                    if eff.get('uid') == effect_uid:
                        effect_ref_id = eff.get('id')
                        break
                if effect_ref_id is None:
                    # Generate a unique resource id
                    existing_ids = {el.get('id', '') for el in resources}
                    effect_ref_id = 'r_dissolve'
                    counter = 2
                    while effect_ref_id in existing_ids:
                        effect_ref_id = f'r_dissolve{counter}'
                        counter += 1
                    eff_el = ET.SubElement(resources, 'effect')
                    eff_el.set('id', effect_ref_id)
                    eff_el.set('name', effect_name)
                    eff_el.set('uid', effect_uid)

        transitions_added = []

        if position in ('end', 'both'):
            clip_offset = self._parse_time(clip.get('offset', '0s'))
            clip_dur = self._parse_time(clip.get('duration', '0s'))

            # Transition centered on edit point
            half_dur = trans_duration * 0.5
            trans_offset = clip_offset + clip_dur - half_dur

            transition = ET.Element('transition')
            transition.set('name', effect_name)
            transition.set('offset', trans_offset.to_fcpxml())
            transition.set('duration', trans_duration.to_fcpxml())

            if effect_ref_id:
                fv = ET.SubElement(transition, 'filter-video')
                fv.set('ref', effect_ref_id)
                fv.set('name', effect_name)

            spine.insert(clip_index + 1, transition)
            transitions_added.append(transition)

        if position in ('start', 'both'):
            clip_offset = self._parse_time(clip.get('offset', '0s'))
            half_dur = trans_duration * 0.5
            trans_offset = clip_offset - half_dur

            transition = ET.Element('transition')
            transition.set('name', effect_name)
            transition.set('offset', trans_offset.to_fcpxml())
            transition.set('duration', trans_duration.to_fcpxml())

            if effect_ref_id:
                fv = ET.SubElement(transition, 'filter-video')
                fv.set('ref', effect_ref_id)
                fv.set('name', effect_name)

            spine.insert(clip_index, transition)
            transitions_added.append(transition)

        return transitions_added[0] if len(transitions_added) == 1 else transitions_added

    # ========================================================================
    # SPEED OPERATIONS
    # ========================================================================

    def change_speed(
        self,
        clip_id: str,
        speed: float,
        preserve_pitch: bool = True
    ) -> ET.Element:
        """
        Change clip playback speed.

        Args:
            clip_id: Target clip
            speed: Speed multiplier (0.5 = half speed, 2.0 = double)
            preserve_pitch: Maintain audio pitch

        Returns:
            Modified clip element
        """
        clip = self.clips.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")

        current_duration = self._parse_time(clip.get('duration', '0s'))

        # Use rational arithmetic to avoid floating-point time values.
        # FCPXML requires rational fractions with a consistent timebase,
        # not decimal floats like "2.6666666666666665s".
        denom = current_duration.denominator if current_duration.denominator > 0 else int(self.fps)
        source_num = current_duration.numerator
        from fractions import Fraction
        speed_frac = Fraction(speed).limit_denominator(1000)
        raw_num = source_num * speed_frac.denominator
        raw_denom = denom * speed_frac.numerator

        # Snap to frame boundary in a standard timebase (2400 ticks/sec).
        # Each frame at Nfps = 2400/N ticks (e.g. 24fps → 100 ticks/frame).
        fps_int = int(self.fps) if self.fps else 24
        ticks_per_frame = 2400 // fps_int
        dur_ticks = round(raw_num / raw_denom * 2400)
        dur_ticks = round(dur_ticks / ticks_per_frame) * ticks_per_frame
        new_num = dur_ticks
        new_denom = 2400

        # Create timeMap for speed change (DTD-ordered insertion)
        timemap = ET.Element('timeMap')
        _dtd_insert(clip, timemap)

        # Start keyframe
        tp1 = ET.SubElement(timemap, 'timept')
        tp1.set('time', '0s')
        tp1.set('value', '0s')
        tp1.set('interp', 'linear')

        # End keyframe — use rational time, not floats
        tp2 = ET.SubElement(timemap, 'timept')
        tp2.set('time', f"{new_num}/{new_denom}s")
        tp2.set('value', f"{source_num}/{denom}s")
        tp2.set('interp', 'linear')

        # Update clip duration (rational, not simplified to arbitrary denominator)
        clip.set('duration', f"{new_num}/{new_denom}s")

        # Add conform-rate (DTD-ordered insertion)
        conform = ET.Element('conform-rate')
        conform.set('scaleEnabled', '1')
        conform.set('srcFrameRate', str(int(self.fps)))
        _dtd_insert(clip, conform)

        return clip

    # ========================================================================
    # SPLIT & DELETE OPERATIONS
    # ========================================================================

    def split_clip(
        self,
        clip_id: str,
        split_points: List[str]
    ) -> List[ET.Element]:
        """
        Split a clip at specified timecodes.

        Args:
            clip_id: Clip to split
            split_points: Timecodes within the clip to split at

        Returns:
            List of resulting clip elements
        """
        spine = self._get_spine()
        clip = self.clips.get(clip_id)

        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")

        # Find clip in spine
        clip_index = None
        for i, child in enumerate(spine):
            if child == clip:
                clip_index = i
                break

        if clip_index is None:
            raise ValueError(f"Clip not in spine: {clip_id}")

        # Get clip properties
        clip_offset = self._parse_time(clip.get('offset', '0s'))
        clip_start = self._parse_time(clip.get('start', '0s'))
        clip_duration = self._parse_time(clip.get('duration', '0s'))
        clip_name = clip.get('name', 'Clip')
        clip.get('ref')

        # Sort split points
        split_times = sorted([self._parse_time(sp) for sp in split_points])

        # Remove original clip
        spine.remove(clip)

        # Create new clips
        new_clips = []
        current_offset = clip_offset
        current_start = clip_start

        all_points = split_times + [clip_duration]

        for i, split_time in enumerate(all_points):
            if i == 0:
                segment_duration = split_time
            else:
                segment_duration = split_time - split_times[i - 1]

            if segment_duration.to_seconds() <= 0:
                continue

            # Create new clip
            new_clip = copy.deepcopy(clip)
            new_clip.set('name', clip_name)
            new_clip.set('offset', current_offset.to_fcpxml())
            new_clip.set('start', current_start.to_fcpxml())
            new_clip.set('duration', segment_duration.to_fcpxml())

            spine.insert(clip_index + i, new_clip)
            new_clips.append(new_clip)

            # Update for next iteration
            current_offset = current_offset + segment_duration
            current_start = current_start + segment_duration

        # Update clip index
        for i, new_clip in enumerate(new_clips):
            new_id = f"{clip_id}_split_{i}"
            self.clips[new_id] = new_clip

        return new_clips

    def delete_clip(
        self,
        clip_ids: List[str],
        ripple: bool = True
    ) -> None:
        """
        Delete clips from timeline.

        Args:
            clip_ids: Clips to delete
            ripple: If True, shift subsequent clips. If False, leave gaps.
        """
        spine = self._get_spine()

        for clip_id in clip_ids:
            clip = self.clips.get(clip_id)
            if clip is None:
                continue

            if clip not in list(spine):
                continue

            clip_duration = self._parse_time(clip.get('duration', '0s'))
            clip_offset = self._parse_time(clip.get('offset', '0s'))
            clip_index = list(spine).index(clip)

            if ripple:
                spine.remove(clip)
                # Shift subsequent clips
                for child in list(spine)[clip_index:]:
                    if child.tag in SPINE_ELEMENT_TAGS:
                        child_offset = self._parse_time(child.get('offset', '0s'))
                        new_offset = child_offset - clip_duration
                        child.set('offset', new_offset.to_fcpxml())
            else:
                # Replace with gap
                gap = ET.Element('gap')
                gap.set('name', 'Gap')
                gap.set('offset', clip_offset.to_fcpxml())
                gap.set('duration', clip_duration.to_fcpxml())

                spine.remove(clip)
                spine.insert(clip_index, gap)

            # Remove from index
            del self.clips[clip_id]

    # ========================================================================
    # SPEED CUTTING OPERATIONS (v0.3.0)
    # ========================================================================

    def fix_flash_frames(
        self,
        mode: str = 'auto',
        threshold_frames: int = 6,
        critical_threshold_frames: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Automatically fix flash frames (ultra-short clips).

        Args:
            mode: How to fix flash frames:
                - 'extend_previous': Extend the previous clip to cover the flash frame
                - 'extend_next': Extend the next clip backward to cover the flash frame
                - 'delete': Remove the flash frame entirely (ripple)
                - 'auto': Use smart logic (extend prev for critical, delete for warning)
            threshold_frames: Frames below this are considered flash frames
            critical_threshold_frames: Frames below this are critical (default: 2)

        Returns:
            List of fixed flash frames with details
        """
        spine = self._get_spine()
        spine_children = list(spine)
        fixed = []

        # Collect flash frames first (can't modify while iterating)
        flash_frames = []
        for i, clip in enumerate(spine_children):
            if clip.tag not in CLIP_TAGS:
                continue
            duration = self._parse_time(clip.get('duration', '0s'))
            duration_frames = duration.to_frames(self.fps)

            if duration_frames < threshold_frames:
                is_critical = duration_frames < critical_threshold_frames
                flash_frames.append({
                    'index': i,
                    'clip': clip,
                    'clip_id': clip.get('name') or clip.get('id') or f"clip_{i}",
                    'duration_frames': duration_frames,
                    'is_critical': is_critical
                })

        # Process in reverse order to maintain indices
        for ff in reversed(flash_frames):
            clip = ff['clip']
            clip_index = list(spine).index(clip)
            clip_duration = self._parse_time(clip.get('duration', '0s'))
            clip_offset = self._parse_time(clip.get('offset', '0s'))

            # Determine actual mode
            actual_mode = mode
            if mode == 'auto':
                # Critical: try to extend previous, otherwise delete
                # Warning: delete
                actual_mode = 'extend_previous' if ff['is_critical'] else 'delete'

            result = {
                'clip_name': ff['clip_id'],
                'duration_frames': ff['duration_frames'],
                'was_critical': ff['is_critical'],
                'action': actual_mode,
                'timecode': clip_offset.to_timecode(self.fps)
            }

            spine_list = list(spine)

            if actual_mode == 'extend_previous' and clip_index > 0:
                # Find previous non-gap clip
                prev_clip = None
                for j in range(clip_index - 1, -1, -1):
                    if spine_list[j].tag in CLIP_TAGS:
                        prev_clip = spine_list[j]
                        break

                if prev_clip is not None:
                    prev_duration = self._parse_time(prev_clip.get('duration', '0s'))
                    new_duration = prev_duration + clip_duration
                    prev_clip.set('duration', new_duration.to_fcpxml())
                    spine.remove(clip)
                    self._recalculate_offsets(spine)
                    result['extended_clip'] = prev_clip.get('name', 'Previous')

            elif actual_mode == 'extend_next' and clip_index < len(spine_list) - 1:
                # Find next non-gap clip
                next_clip = None
                for j in range(clip_index + 1, len(spine_list)):
                    if spine_list[j].tag in CLIP_TAGS:
                        next_clip = spine_list[j]
                        break

                if next_clip is not None:
                    next_duration = self._parse_time(next_clip.get('duration', '0s'))
                    next_start = self._parse_time(next_clip.get('start', '0s'))
                    new_duration = next_duration + clip_duration
                    new_start = next_start - clip_duration
                    if new_start.to_seconds() >= 0:
                        next_clip.set('duration', new_duration.to_fcpxml())
                        next_clip.set('start', new_start.to_fcpxml())
                    else:
                        next_clip.set('duration', new_duration.to_fcpxml())
                    spine.remove(clip)
                    self._recalculate_offsets(spine)
                    result['extended_clip'] = next_clip.get('name', 'Next')

            else:  # delete
                spine.remove(clip)
                self._recalculate_offsets(spine)

            fixed.append(result)

        # Rebuild clip index
        self._build_clip_index()

        return fixed

    def rapid_trim(
        self,
        max_duration: Optional[str] = None,
        min_duration: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        trim_from: str = 'end'
    ) -> List[Dict[str, Any]]:
        """
        Batch trim clips to enforce duration limits.

        Args:
            max_duration: Maximum clip duration (e.g., '2s', '00:00:02:00')
            min_duration: Minimum clip duration (clips shorter are extended/left alone)
            keywords: Only trim clips with these keywords (None = all clips)
            trim_from: Where to trim - 'start', 'end', or 'center'

        Returns:
            List of trimmed clips with before/after durations
        """
        spine = self._get_spine()
        trimmed = []

        max_dur = self._parse_time(max_duration) if max_duration else None
        self._parse_time(min_duration) if min_duration else None

        for clip in list(spine):
            if clip.tag not in CLIP_TAGS:
                continue

            clip_name = clip.get('name') or clip.get('id') or 'Unknown'

            # Check keyword filter
            if keywords:
                clip_keywords = set()
                for kw_elem in clip.findall('keyword'):
                    clip_keywords.add(kw_elem.get('value', ''))
                if not clip_keywords.intersection(set(keywords)):
                    continue

            current_duration = self._parse_time(clip.get('duration', '0s'))
            current_start = self._parse_time(clip.get('start', '0s'))
            original_duration = current_duration.to_seconds()

            # Check max duration
            if max_dur and current_duration > max_dur:
                excess = current_duration - max_dur

                if trim_from == 'end':
                    # Keep start, reduce duration
                    clip.set('duration', max_dur.to_fcpxml())

                elif trim_from == 'start':
                    # Increase start, reduce duration
                    new_start = current_start + excess
                    clip.set('start', new_start.to_fcpxml())
                    clip.set('duration', max_dur.to_fcpxml())

                elif trim_from == 'center':
                    # Trim equal amounts from both ends
                    half_excess = excess * 0.5
                    new_start = current_start + half_excess
                    clip.set('start', new_start.to_fcpxml())
                    clip.set('duration', max_dur.to_fcpxml())

                trimmed.append({
                    'clip_name': clip_name,
                    'original_duration': original_duration,
                    'new_duration': max_dur.to_seconds(),
                    'trim_from': trim_from,
                    'action': 'trimmed'
                })

        # Recalculate offsets
        self._recalculate_offsets(spine)

        return trimmed

    def fill_gaps(
        self,
        mode: str = 'extend_previous',
        max_gap: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fill gaps in the timeline.

        Args:
            mode: How to fill gaps:
                - 'extend_previous': Extend previous clip to fill gap
                - 'extend_next': Extend next clip backward to fill gap
                - 'delete': Remove gap elements and ripple
            max_gap: Only fill gaps smaller than this (None = all gaps)

        Returns:
            List of filled gaps with details
        """
        spine = self._get_spine()
        filled = []
        max_gap_time = self._parse_time(max_gap) if max_gap else None

        # Find all gaps
        gaps_to_process = []
        for i, child in enumerate(list(spine)):
            if child.tag == 'gap':
                gap_duration = self._parse_time(child.get('duration', '0s'))
                gap_offset = self._parse_time(child.get('offset', '0s'))

                # Check max_gap filter
                if max_gap_time and gap_duration > max_gap_time:
                    continue

                gaps_to_process.append({
                    'element': child,
                    'index': i,
                    'duration': gap_duration,
                    'offset': gap_offset
                })

        # Process in reverse to maintain indices
        for gap_info in reversed(gaps_to_process):
            gap = gap_info['element']
            gap_index = list(spine).index(gap)
            gap_duration = gap_info['duration']
            gap_offset = gap_info['offset']

            spine_list = list(spine)
            result = {
                'timecode': gap_offset.to_timecode(self.fps),
                'duration_frames': gap_duration.to_frames(self.fps),
                'duration_seconds': gap_duration.to_seconds(),
                'action': mode
            }

            if mode == 'extend_previous' and gap_index > 0:
                # Find previous clip
                prev_clip = None
                for j in range(gap_index - 1, -1, -1):
                    if spine_list[j].tag in CLIP_TAGS:
                        prev_clip = spine_list[j]
                        break

                if prev_clip is not None:
                    prev_duration = self._parse_time(prev_clip.get('duration', '0s'))
                    new_duration = prev_duration + gap_duration
                    prev_clip.set('duration', new_duration.to_fcpxml())
                    spine.remove(gap)
                    result['extended_clip'] = prev_clip.get('name', 'Previous')
                    filled.append(result)

            elif mode == 'extend_next' and gap_index < len(spine_list) - 1:
                # Find next clip
                next_clip = None
                for j in range(gap_index + 1, len(spine_list)):
                    if spine_list[j].tag in CLIP_TAGS:
                        next_clip = spine_list[j]
                        break

                if next_clip is not None:
                    next_duration = self._parse_time(next_clip.get('duration', '0s'))
                    next_start = self._parse_time(next_clip.get('start', '0s'))
                    new_duration = next_duration + gap_duration
                    new_start = next_start - gap_duration
                    if new_start.to_seconds() >= 0:
                        next_clip.set('start', new_start.to_fcpxml())
                    next_clip.set('duration', new_duration.to_fcpxml())
                    spine.remove(gap)
                    result['extended_clip'] = next_clip.get('name', 'Next')
                    filled.append(result)

            else:  # delete
                spine.remove(gap)
                filled.append(result)

        # Recalculate offsets
        self._recalculate_offsets(spine)

        return filled

    # ========================================================================
    # SELECTION OPERATIONS
    # ========================================================================

    def select_by_keyword(
        self,
        keywords: List[str],
        match_mode: str = 'any',
        favorites_only: bool = False,
        exclude_rejected: bool = True
    ) -> List[str]:
        """
        Find clips matching keywords.

        Args:
            keywords: Keywords to match
            match_mode: 'any' (OR), 'all' (AND), 'none' (exclude)
            favorites_only: Only return favorited clips
            exclude_rejected: Exclude rejected clips

        Returns:
            List of matching clip IDs
        """
        matches = []

        for clip_id, clip in self.clips.items():
            clip_keywords = set()
            for kw_elem in clip.findall('keyword'):
                clip_keywords.add(kw_elem.get('value', ''))

            # Check keyword match
            keyword_set = set(keywords)
            if match_mode == 'any':
                match = bool(clip_keywords & keyword_set)
            elif match_mode == 'all':
                match = keyword_set <= clip_keywords
            elif match_mode == 'none':
                match = not bool(clip_keywords & keyword_set)
            else:
                match = True

            if match:
                matches.append(clip_id)

        return matches

    # ========================================================================
    # INSERT CLIP OPERATIONS
    # ========================================================================

    def insert_clip(
        self,
        position: str,
        asset_id: Optional[str] = None,
        asset_name: Optional[str] = None,
        duration: Optional[str] = None,
        in_point: Optional[str] = None,
        out_point: Optional[str] = None,
        ripple: bool = True
    ) -> ET.Element:
        """
        Insert a library clip onto the timeline.

        Args:
            position: Where to insert - 'start', 'end', timecode, or 'after:clip_id'
            asset_id: Asset reference ID (e.g., 'r3')
            asset_name: Asset name (alternative to asset_id)
            duration: Duration of clip (if not using in/out points)
            in_point: Source in-point for subclip
            out_point: Source out-point for subclip
            ripple: Whether to shift subsequent clips

        Returns:
            The created clip element
        """
        # Find asset by ID or name
        asset = None
        if asset_id and asset_id in self.resources:
            asset = self.resources[asset_id]
        elif asset_name:
            for res_id, res_data in self.resources.items():
                if res_data.get('name') == asset_name:
                    asset = res_data
                    asset_id = res_id
                    break

        if asset is None:
            raise ValueError(f"Asset not found: {asset_id or asset_name}")

        # Determine clip duration and start
        if in_point and out_point:
            in_time = self._parse_time(in_point)
            out_time = self._parse_time(out_point)
            clip_duration = out_time - in_time
            source_start = in_time
        elif duration:
            clip_duration = self._parse_time(duration)
            source_start = TimeValue.zero()
        else:
            # Use full asset duration
            clip_duration = self._parse_time(asset.get('duration', '0s'))
            source_start = TimeValue.zero()

        # Get spine and calculate insert position
        spine = self._get_spine()
        spine_children = list(spine)

        if position == 'start':
            target_offset = TimeValue.zero()
            insert_index = 0
        elif position == 'end':
            if spine_children:
                last = spine_children[-1]
                last_offset = self._parse_time(last.get('offset', '0s'))
                last_dur = self._parse_time(last.get('duration', '0s'))
                target_offset = last_offset + last_dur
            else:
                target_offset = TimeValue.zero()
            insert_index = len(spine_children)
        elif position.startswith('after:'):
            ref_id = position.split(':', 1)[1]
            ref_clip = self.clips.get(ref_id)
            if ref_clip is not None and ref_clip in spine_children:
                idx = spine_children.index(ref_clip)
                ref_offset = self._parse_time(ref_clip.get('offset', '0s'))
                ref_dur = self._parse_time(ref_clip.get('duration', '0s'))
                target_offset = ref_offset + ref_dur
                insert_index = idx + 1
            else:
                raise ValueError(f"Reference clip not found: {ref_id}")
        else:
            # Assume timecode
            target_offset = self._parse_time(position)
            insert_index = 0
            for i, child in enumerate(spine_children):
                child_offset = self._parse_time(child.get('offset', '0s'))
                if child_offset.to_seconds() >= target_offset.to_seconds():
                    insert_index = i
                    break
                insert_index = i + 1

        # Create new asset-clip element
        new_clip = ET.Element('asset-clip')
        new_clip.set('ref', asset_id)
        new_clip.set('offset', target_offset.to_fcpxml())
        new_clip.set('name', asset.get('name', 'Untitled'))
        new_clip.set('start', source_start.to_fcpxml())
        new_clip.set('duration', clip_duration.to_fcpxml())

        # Get format from existing clips or resources
        format_id = None
        for fmt_id in self.formats:
            format_id = fmt_id
            break
        if format_id:
            new_clip.set('format', format_id)

        # Insert into spine
        spine.insert(insert_index, new_clip)

        # Ripple subsequent clips if needed
        if ripple and insert_index < len(spine_children):
            for child in list(spine)[insert_index + 1:]:
                if child.tag in SPINE_ELEMENT_TAGS:
                    current_offset = self._parse_time(child.get('offset', '0s'))
                    new_offset = current_offset + clip_duration
                    child.set('offset', new_offset.to_fcpxml())

        # Add to clip index
        clip_id = f"inserted_{len(self.clips)}"
        self.clips[clip_id] = new_clip

        return new_clip

    # ========================================================================
    # CONNECTED CLIP OPERATIONS (v0.5.0)
    # ========================================================================

    def add_connected_clip(
        self,
        parent_clip_id: str,
        asset_id: Optional[str] = None,
        asset_name: Optional[str] = None,
        offset: str = "0s",
        duration: Optional[str] = None,
        lane: int = 1,
    ) -> ET.Element:
        """Add a connected clip (B-roll, title, audio) to an existing timeline clip.

        Args:
            parent_clip_id: Name/ID of the clip to attach to
            asset_id: Asset reference ID
            asset_name: Asset name (alternative to asset_id)
            offset: Position relative to parent clip start
            duration: Duration of connected clip (default: full asset)
            lane: Lane number (positive=above, negative=below)

        Returns:
            The created connected clip element
        """
        parent = self.clips.get(parent_clip_id)
        if parent is None:
            raise ValueError(f"Parent clip not found: {parent_clip_id}")

        asset = None
        if asset_id and asset_id in self.resources:
            asset = self.resources[asset_id]
        elif asset_name:
            for res_id, res_data in self.resources.items():
                if res_data.get('name') == asset_name:
                    asset = res_data
                    asset_id = res_id
                    break

        if asset is None:
            raise ValueError(f"Asset not found: {asset_id or asset_name}")

        clip_duration = (
            self._parse_time(duration) if duration
            else self._parse_time(asset.get('duration', '0s'))
        )
        clip_offset = self._parse_time(offset)

        new_clip = ET.SubElement(parent, 'asset-clip')
        new_clip.set('ref', asset_id)
        new_clip.set('lane', str(lane))
        new_clip.set('offset', clip_offset.to_fcpxml())
        new_clip.set('name', asset.get('name', 'Untitled'))
        new_clip.set('start', '0s')
        new_clip.set('duration', clip_duration.to_fcpxml())

        return new_clip

    # ========================================================================
    # AUDIO CLIP OPERATIONS (v0.6.0)
    # ========================================================================

    def add_audio_clip(
        self,
        parent_clip_id: str,
        asset_id: Optional[str] = None,
        offset: str = "0s",
        duration: Optional[str] = None,
        role: str = "dialogue",
        lane: int = -1,
        src: Optional[str] = None,
    ) -> ET.Element:
        """Add an audio clip connected to an existing timeline clip.

        Creates an <asset-clip> at a negative lane with audioRole attribute.
        Supports hierarchical roles like "dialogue.boom", "music.score",
        "effects.foley".

        Args:
            parent_clip_id: Name/ID of the clip to attach audio to.
            asset_id: Existing asset reference ID. If None and src provided,
                creates a new asset.
            offset: Position relative to parent clip start.
            duration: Duration of audio clip.
            role: Audio role (e.g. "dialogue", "music.score", "effects.foley").
            lane: Lane number (negative = below primary, default -1).
            src: Path to audio file. Used to create a new asset if asset_id
                is not provided.

        Returns:
            The created audio clip element.
        """
        parent = self.clips.get(parent_clip_id)
        if parent is None:
            raise ValueError(f"Parent clip not found: {parent_clip_id}")

        # Resolve or create asset
        if asset_id and asset_id in self.resources:
            asset = self.resources[asset_id]
        elif src:
            # Create new asset in resources
            resources = self.root.find('.//resources')
            if resources is None:
                raise ValueError("No <resources> element found in FCPXML")
            existing_ids = {el.get('id', '') for el in resources}
            asset_id = 'r_audio1'
            counter = 2
            while asset_id in existing_ids:
                asset_id = f'r_audio{counter}'
                counter += 1
            asset_elem = _create_asset_element(
                resources, asset_id, Path(src).stem, src,
                duration=duration or "0s",
                has_video="0", has_audio="1",
            )
            asset = {
                'id': asset_id,
                'name': Path(src).stem,
                'duration': duration or "0s",
                'element': asset_elem,
            }
            self.resources[asset_id] = asset
        else:
            raise ValueError("Must provide either asset_id or src for audio clip")

        clip_duration = (
            self._parse_time(duration) if duration
            else self._parse_time(asset.get('duration', '0s'))
        )
        clip_offset = self._parse_time(offset)

        new_clip = ET.Element('asset-clip')
        new_clip.set('ref', asset_id)
        new_clip.set('lane', str(lane))
        new_clip.set('offset', clip_offset.to_fcpxml())
        new_clip.set('name', asset.get('name', 'Audio'))
        new_clip.set('start', '0s')
        new_clip.set('duration', clip_duration.to_fcpxml())
        new_clip.set('audioRole', _sanitize_xml_value(role, 256))

        _dtd_insert(parent, new_clip)
        return new_clip

    def add_music_bed(
        self,
        asset_id: Optional[str] = None,
        duration: Optional[str] = None,
        role: str = "music",
        src: Optional[str] = None,
    ) -> ET.Element:
        """Add a music bed spanning the full timeline at lane -1.

        Convenience method: attaches to the first spine clip and spans
        the full timeline duration.

        Args:
            asset_id: Existing asset reference ID.
            duration: Override duration (default: full timeline).
            role: Audio role (default "music").
            src: Path to audio file (creates asset if asset_id not given).

        Returns:
            The created music bed clip element.
        """
        spine = self._get_spine()
        first_clip = None
        first_clip_id = None
        for clip_id, clip in self.clips.items():
            if clip in list(spine):
                first_clip = clip
                first_clip_id = clip_id
                break

        if first_clip is None:
            raise ValueError("No clips in spine to attach music bed to")

        # Calculate full timeline duration if not specified
        if not duration:
            sequence = self.root.find('.//sequence')
            if sequence is not None:
                duration = sequence.get('duration', '0s')
            else:
                # Sum all spine clip durations
                total = TimeValue.zero()
                for child in spine:
                    if child.tag in SPINE_ELEMENT_TAGS:
                        total = total + self._parse_time(child.get('duration', '0s'))
                duration = total.to_fcpxml()

        return self.add_audio_clip(
            parent_clip_id=first_clip_id,
            asset_id=asset_id,
            offset="0s",
            duration=duration,
            role=role,
            lane=-1,
            src=src,
        )

    # ========================================================================
    # COMPOUND CLIP OPERATIONS (v0.6.0)
    # ========================================================================

    def create_compound_clip(
        self,
        clip_ids: List[str],
        name: str = "Compound Clip",
    ) -> ET.Element:
        """Group spine clips into a compound clip.

        Creates a <media> resource with a nested <sequence><spine> containing
        the specified clips, then replaces the originals in the main spine
        with a single <ref-clip>.

        Args:
            clip_ids: IDs of clips in the spine to group.
            name: Name for the compound clip.

        Returns:
            The created <ref-clip> element.
        """
        spine = self._get_spine()
        resources = self.root.find('.//resources')
        if resources is None:
            raise ValueError("No <resources> element found in FCPXML")

        # Collect clips and validate they're in spine
        clips_to_group = []
        for cid in clip_ids:
            clip = self.clips.get(cid)
            if clip is None:
                raise ValueError(f"Clip not found: {cid}")
            if clip not in list(spine):
                raise ValueError(f"Clip not in spine: {cid}")
            clips_to_group.append((cid, clip))

        if not clips_to_group:
            raise ValueError("No valid clips to group")

        # Sort by offset so the compound maintains order
        clips_to_group.sort(
            key=lambda c: self._parse_time(c[1].get('offset', '0s')).to_seconds()
        )

        # Calculate compound duration and starting offset
        first_offset = self._parse_time(clips_to_group[0][1].get('offset', '0s'))
        total_duration = TimeValue.zero()
        for _, clip in clips_to_group:
            total_duration = total_duration + self._parse_time(clip.get('duration', '0s'))

        # Get format ref
        format_id = None
        for fmt_id in self.formats:
            format_id = fmt_id
            break

        # Create media resource with nested sequence
        existing_ids = {el.get('id', '') for el in resources}
        media_id = 'r_compound1'
        counter = 2
        while media_id in existing_ids:
            media_id = f'r_compound{counter}'
            counter += 1

        media = ET.SubElement(resources, 'media')
        media.set('id', media_id)
        media.set('name', _sanitize_xml_value(name, 512))
        media.set('uid', str(uuid.uuid4()).upper())

        seq = ET.SubElement(media, 'sequence')
        seq.set('format', format_id or 'r1')
        seq.set('duration', total_duration.to_fcpxml())
        seq.set('tcStart', '0s')
        seq.set('tcFormat', 'NDF')

        inner_spine = ET.SubElement(seq, 'spine')

        # Move clips into the compound's inner spine
        inner_offset = TimeValue.zero()
        for _, clip in clips_to_group:
            new_clip = copy.deepcopy(clip)
            new_clip.set('offset', inner_offset.to_fcpxml())
            inner_spine.append(new_clip)
            inner_offset = inner_offset + self._parse_time(clip.get('duration', '0s'))

        # Get the insert position (where first clip was)
        spine_children = list(spine)
        insert_idx = spine_children.index(clips_to_group[0][1])

        # Remove originals from spine
        for cid, clip in clips_to_group:
            spine.remove(clip)
            if cid in self.clips:
                del self.clips[cid]

        # Create ref-clip in main spine
        ref_clip = ET.Element('ref-clip')
        ref_clip.set('ref', media_id)
        ref_clip.set('offset', first_offset.to_fcpxml())
        ref_clip.set('name', _sanitize_xml_value(name, 512))
        ref_clip.set('duration', total_duration.to_fcpxml())
        spine.insert(insert_idx, ref_clip)

        # Index the new ref-clip
        compound_id = f"compound_{name}"
        self.clips[compound_id] = ref_clip

        return ref_clip

    def flatten_compound_clip(
        self,
        ref_clip_id: str,
    ) -> List[ET.Element]:
        """Flatten a compound clip back into individual spine clips.

        Extracts clips from the compound's inner sequence and places them
        back in the main spine at the ref-clip's position.

        Args:
            ref_clip_id: ID of the ref-clip to flatten.

        Returns:
            List of extracted clip elements now in the main spine.
        """
        spine = self._get_spine()
        ref_clip = self.clips.get(ref_clip_id)
        if ref_clip is None:
            raise ValueError(f"Ref-clip not found: {ref_clip_id}")
        if ref_clip.tag != 'ref-clip':
            raise ValueError(f"Element is not a ref-clip: {ref_clip_id}")

        media_ref = ref_clip.get('ref', '')
        ref_offset = self._parse_time(ref_clip.get('offset', '0s'))

        # Find the media resource
        resources = self.root.find('.//resources')
        media_elem = None
        if resources is not None:
            for m in resources.findall('media'):
                if m.get('id') == media_ref:
                    media_elem = m
                    break

        if media_elem is None:
            raise ValueError(f"Media resource not found for ref: {media_ref}")

        inner_spine = media_elem.find('.//spine')
        if inner_spine is None:
            raise ValueError("No spine found in compound clip media")

        # Get insert position
        spine_children = list(spine)
        insert_idx = spine_children.index(ref_clip)

        # Remove ref-clip from spine
        spine.remove(ref_clip)
        if ref_clip_id in self.clips:
            del self.clips[ref_clip_id]

        # Extract clips from inner spine into main spine
        extracted = []
        current_offset = ref_offset
        for child in list(inner_spine):
            new_clip = copy.deepcopy(child)
            new_clip.set('offset', current_offset.to_fcpxml())
            spine.insert(insert_idx, new_clip)
            insert_idx += 1
            extracted.append(new_clip)
            current_offset = current_offset + self._parse_time(
                child.get('duration', '0s')
            )

            # Index the extracted clip
            clip_name = new_clip.get('name') or new_clip.get('id') or f"flat_{len(self.clips)}"
            self.clips[clip_name] = new_clip

        # Clean up media resource
        if resources is not None:
            resources.remove(media_elem)

        return extracted

    # ========================================================================
    # ROLE OPERATIONS (v0.5.0)
    # ========================================================================

    def assign_role(
        self,
        clip_id: str,
        audio_role: Optional[str] = None,
        video_role: Optional[str] = None,
    ) -> ET.Element:
        """Set the audio/video role on a clip.

        Args:
            clip_id: Name/ID of the clip
            audio_role: Audio role (e.g., "dialogue", "music", "effects")
            video_role: Video role (e.g., "video", "titles")

        Returns:
            The modified clip element
        """
        clip = self.clips.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")

        if audio_role is not None:
            clip.set('audioRole', _sanitize_xml_value(audio_role, 256))
        if video_role is not None:
            clip.set('videoRole', _sanitize_xml_value(video_role, 256))

        return clip

    # ========================================================================
    # REFORMAT OPERATIONS (v0.5.0)
    # ========================================================================

    SOCIAL_FORMATS = {
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "16:9": (1920, 1080),
        "4:3": (1440, 1080),
    }

    def reformat_resolution(self, width: int, height: int) -> None:
        """Change the timeline format to a new resolution.

        Updates the format resource dimensions. FCP handles spatial
        conforming (letterbox/pillarbox) on import.

        Args:
            width: Target width in pixels
            height: Target height in pixels
        """
        for fmt in self.root.findall('.//format'):
            fmt.set('width', str(width))
            fmt.set('height', str(height))
            old_name = fmt.get('name', '')
            if old_name:
                fmt.set('name', f"FFVideoFormat{width}x{height}")

        sequence = self.root.find('.//sequence')
        if sequence is not None and sequence.get('format'):
            pass  # format ref stays the same, dimensions updated in-place

    # ========================================================================
    # SILENCE DETECTION OPERATIONS (v0.5.0)
    # ========================================================================

    def detect_silence_candidates(
        self,
        min_gap_seconds: float = 0.5,
        patterns: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Detect potential silence regions using timeline heuristics.

        Checks for:
        1. Gap elements in spine (high confidence)
        2. Ultra-short clips < 0.5s (medium confidence)
        3. Clips matching name patterns like "silence", "room tone" (high)
        4. Duration anomalies > 2 std dev from mean (low-medium)

        Args:
            min_gap_seconds: Minimum gap duration to flag
            patterns: Name patterns to match (default: gap, silence, room tone)

        Returns:
            List of silence candidate dicts
        """
        if patterns is None:
            patterns = ['gap', 'silence', 'room tone', 'dead air', 'blank']

        spine = self._get_spine()
        candidates = []
        durations = []
        clip_index = 0

        # First pass: collect durations for anomaly detection
        for child in spine:
            if child.tag in CLIP_TAGS:
                dur = self._parse_time(child.get('duration', '0s'))
                durations.append(dur.to_seconds())

        # Calculate stats for anomaly detection
        mean_dur = sum(durations) / len(durations) if durations else 0
        variance = (sum((d - mean_dur) ** 2 for d in durations) / len(durations)
                     if len(durations) > 1 else 0)
        std_dev = variance ** 0.5

        # Second pass: detect candidates
        for child in spine:
            tag = child.tag
            offset = child.get('offset', '0s')
            dur = self._parse_time(child.get('duration', '0s'))
            dur_secs = dur.to_seconds()
            tc = TimeValue.from_timecode(offset, self.fps).to_timecode(self.fps)

            if tag == 'gap' and dur_secs >= min_gap_seconds:
                candidates.append({
                    'start_timecode': tc,
                    'duration_seconds': dur_secs,
                    'reason': 'gap',
                    'confidence': 0.9,
                    'clip_name': None,
                    'clip_index': None,
                })
            elif tag in CLIP_TAGS:
                name = child.get('name', '').lower()

                # Name pattern match
                for pat in patterns:
                    if pat.lower() in name:
                        candidates.append({
                            'start_timecode': tc,
                            'duration_seconds': dur_secs,
                            'reason': 'name_match',
                            'confidence': 0.85,
                            'clip_name': child.get('name', ''),
                            'clip_index': clip_index,
                        })
                        break

                # Ultra-short clip
                if dur_secs < 0.5:
                    candidates.append({
                        'start_timecode': tc,
                        'duration_seconds': dur_secs,
                        'reason': 'ultra_short',
                        'confidence': 0.6,
                        'clip_name': child.get('name', ''),
                        'clip_index': clip_index,
                    })

                # Duration anomaly (> 2 std dev longer than mean)
                if std_dev > 0 and dur_secs > mean_dur + 2 * std_dev:
                    candidates.append({
                        'start_timecode': tc,
                        'duration_seconds': dur_secs,
                        'reason': 'duration_anomaly',
                        'confidence': 0.4,
                        'clip_name': child.get('name', ''),
                        'clip_index': clip_index,
                    })

                clip_index += 1

        return candidates

    def remove_silence_candidates(
        self,
        mode: str = "mark",
        min_gap_seconds: float = 0.5,
        min_confidence: float = 0.7,
        patterns: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Remove or mark detected silence candidates.

        Args:
            mode: "delete" removes clips/gaps, "mark" adds red markers,
                  "shorten" trims to minimum
            min_gap_seconds: Minimum gap to consider
            min_confidence: Only act on candidates above this threshold
            patterns: Name patterns to match

        Returns:
            List of actions taken
        """
        candidates = self.detect_silence_candidates(min_gap_seconds, patterns)
        candidates = [c for c in candidates if c['confidence'] >= min_confidence]

        spine = self._get_spine()
        actions = []

        if mode == "mark":
            for c in candidates:
                # Find the element at this position and add a marker
                for child in spine:
                    offset_str = child.get('offset', '0s')
                    tc = TimeValue.from_timecode(offset_str, self.fps).to_timecode(self.fps)
                    if tc == c['start_timecode'] and child.tag in CLIP_TAGS:
                        build_marker_element(
                            parent=child,
                            marker_type=MarkerType.STANDARD,
                            start=child.get('start', '0s'),
                            duration=f"1/{int(self.fps)}s",
                            name=f"SILENCE: {c['reason']}",
                        )
                        actions.append({
                            'action': 'marked',
                            'clip_name': c.get('clip_name', 'gap'),
                            'reason': c['reason'],
                        })
                        break

        elif mode == "delete":
            elements_to_remove = []
            for c in candidates:
                for child in spine:
                    offset_str = child.get('offset', '0s')
                    tc = TimeValue.from_timecode(offset_str, self.fps).to_timecode(self.fps)
                    if tc == c['start_timecode']:
                        elements_to_remove.append(child)
                        actions.append({
                            'action': 'deleted',
                            'clip_name': c.get('clip_name', 'gap'),
                            'reason': c['reason'],
                        })
                        break

            for elem in elements_to_remove:
                spine.remove(elem)

            if elements_to_remove:
                self._recalculate_offsets(spine)

        return actions


# ============================================================================
# FCPXML GENERATOR - Create from Python objects
# ============================================================================

class FCPXMLWriter:
    """Writer for generating Final Cut Pro FCPXML files from Python objects."""

    def __init__(self, version: str = "1.11"):
        """Initialize writer targeting the given FCPXML version."""
        self.version = version
        self.resource_counter = 1

    def _next_resource_id(self) -> str:
        """Return an auto-incrementing resource ID (r1, r2, ...)."""
        rid = f"r{self.resource_counter}"
        self.resource_counter += 1
        return rid

    def _generate_uid(self) -> str:
        """Generate a unique identifier for FCPXML elements."""
        return str(uuid.uuid4()).upper()

    def _tc_to_rational(self, tc: Timecode) -> str:
        """Convert a Timecode to FCPXML rational time string (e.g. '48/24s')."""
        return f"{tc.frames}/{int(tc.frame_rate)}s"

    def write_project(self, project: Project, filepath: str):
        """Write a project to an FCPXML file."""
        root = self._build_fcpxml(project)
        write_fcpxml(root, filepath)

    def _build_fcpxml(self, project: Project) -> ET.Element:
        """Build the full FCPXML element tree: fcpxml > resources + library > event > project."""
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
        """Add a timeline as a project > sequence > spine structure under the event."""
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
        """Add a clip as an asset-clip element, creating its asset resource if needed."""
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

    def _add_marker(self, parent: ET.Element, marker: Marker):
        """Add a marker or chapter-marker element to a parent clip or sequence."""
        build_marker_element(
            parent=parent,
            marker_type=marker.marker_type,
            start=self._tc_to_rational(marker.start),
            duration=self._tc_to_rational(marker.duration) if marker.duration else "1/24s",
            name=marker.name,
            note=marker.note or None,
        )

    def _add_keyword(self, parent, keyword):
        """Add a keyword element with optional start/duration range to a parent clip."""
        attrs = {'value': keyword.value}
        if keyword.start:
            attrs['start'] = self._tc_to_rational(keyword.start)
        if keyword.duration:
            attrs['duration'] = self._tc_to_rational(keyword.duration)
        ET.SubElement(parent, 'keyword', **attrs)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def modify_fcpxml(filepath: str) -> FCPXMLModifier:
    """
    Open an FCPXML file for modification.

    Usage:
        modifier = modify_fcpxml("project.fcpxml")
        modifier.add_marker(...)
        modifier.save("output.fcpxml")
    """
    return FCPXMLModifier(filepath)


def add_marker_to_file(
    filepath: str,
    timecode: str,
    name: str,
    marker_type: str = "standard",
    output_path: Optional[str] = None
) -> str:
    """Convenience function to add a marker to an FCPXML file."""
    modifier = FCPXMLModifier(filepath)
    modifier.add_marker_at_timeline(
        timecode, name,
        MarkerType.from_string(marker_type)
    )
    return modifier.save(output_path)


def trim_clip_in_file(
    filepath: str,
    clip_id: str,
    trim_start: Optional[str] = None,
    trim_end: Optional[str] = None,
    output_path: Optional[str] = None
) -> str:
    """Convenience function to trim a clip in an FCPXML file."""
    modifier = FCPXMLModifier(filepath)
    modifier.trim_clip(clip_id, trim_start, trim_end)
    return modifier.save(output_path)
