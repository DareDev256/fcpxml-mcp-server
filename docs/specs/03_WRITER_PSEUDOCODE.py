# writer.py - FCPXML Write Operations

"""
FCPXML Writer Module

Handles all write operations for Final Cut Pro XML files.
Each function takes parsed FCPXML, performs modifications, and returns valid FCPXML.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Union
from xml.etree import ElementTree as ET
from enum import Enum
import copy

# ============================================================================
# DATA MODELS
# ============================================================================

class MarkerType(Enum):
    STANDARD = "standard"
    TODO = "todo"
    CHAPTER = "chapter"
    COMPLETED = "completed"

class MarkerColor(Enum):
    BLUE = 0
    CYAN = 1
    GREEN = 2
    YELLOW = 3
    ORANGE = 4
    RED = 5
    PINK = 6
    PURPLE = 7

@dataclass
class TimeValue:
    """Represents FCPXML time format (rational or decimal seconds)"""
    numerator: int
    denominator: int = 1
    
    @classmethod
    def from_timecode(cls, tc: str, fps: float = 30.0) -> 'TimeValue':
        """
        Convert timecode string to TimeValue
        Accepts: 'HH:MM:SS:FF', 'HH:MM:SS;FF' (drop-frame), 'XXs', 'XX.XXs', 'X/Ys'
        """
        # Handle FCPXML format (e.g., "30s", "15/30s", "100/1s")
        if tc.endswith('s'):
            tc = tc[:-1]
            if '/' in tc:
                num, denom = tc.split('/')
                return cls(int(num), int(denom))
            else:
                # Decimal seconds
                seconds = float(tc)
                frames = int(seconds * fps)
                return cls(frames, int(fps))
        
        # Handle timecode format (HH:MM:SS:FF)
        parts = tc.replace(';', ':').split(':')
        if len(parts) == 4:
            h, m, s, f = map(int, parts)
            total_frames = (h * 3600 + m * 60 + s) * int(fps) + f
            return cls(total_frames, int(fps))
        
        raise ValueError(f"Invalid timecode format: {tc}")
    
    def to_fcpxml(self) -> str:
        """Convert to FCPXML time string"""
        if self.denominator == 1:
            return f"{self.numerator}s"
        return f"{self.numerator}/{self.denominator}s"
    
    def to_seconds(self) -> float:
        """Convert to decimal seconds"""
        return self.numerator / self.denominator
    
    def __add__(self, other: 'TimeValue') -> 'TimeValue':
        # Find common denominator
        new_denom = self.denominator * other.denominator
        new_num = (self.numerator * other.denominator) + (other.numerator * self.denominator)
        return TimeValue(new_num, new_denom).simplify()
    
    def __sub__(self, other: 'TimeValue') -> 'TimeValue':
        new_denom = self.denominator * other.denominator
        new_num = (self.numerator * other.denominator) - (other.numerator * self.denominator)
        return TimeValue(new_num, new_denom).simplify()
    
    def simplify(self) -> 'TimeValue':
        """Reduce fraction to simplest form"""
        from math import gcd
        divisor = gcd(self.numerator, self.denominator)
        return TimeValue(self.numerator // divisor, self.denominator // divisor)


# ============================================================================
# CORE WRITER CLASS
# ============================================================================

class FCPXMLWriter:
    """
    Handles all write operations on FCPXML documents.
    
    Usage:
        writer = FCPXMLWriter(fcpxml_path)
        writer.add_marker(clip_id, timecode, name, marker_type)
        writer.save(output_path)
    """
    
    def __init__(self, fcpxml_path: str):
        self.tree = ET.parse(fcpxml_path)
        self.root = self.tree.getroot()
        self.fps = self._detect_fps()
        self._build_clip_index()
    
    def _detect_fps(self) -> float:
        """Extract frame rate from format resource"""
        for fmt in self.root.findall('.//format'):
            frame_dur = fmt.get('frameDuration', '1/30s')
            if '/' in frame_dur:
                num, denom = frame_dur.replace('s', '').split('/')
                return int(denom) / int(num)
        return 30.0  # Default
    
    def _build_clip_index(self) -> None:
        """Build index of all clips for fast lookup"""
        self.clips: Dict[str, ET.Element] = {}
        for i, clip in enumerate(self.root.findall('.//clip')):
            clip_id = clip.get('id') or f"clip_{i}"
            self.clips[clip_id] = clip
        for i, video in enumerate(self.root.findall('.//video')):
            vid_id = video.get('id') or f"video_{i}"
            self.clips[vid_id] = video
    
    def _get_spine(self) -> ET.Element:
        """Get the primary storyline spine"""
        spine = self.root.find('.//spine')
        if spine is None:
            raise ValueError("No spine found in FCPXML")
        return spine
    
    def _recalculate_offsets(self, spine: ET.Element) -> None:
        """Recalculate all clip offsets after modifications"""
        current_offset = TimeValue(0)
        
        for child in spine:
            if child.tag in ('clip', 'video', 'audio', 'gap', 'transition', 'ref-clip'):
                child.set('offset', current_offset.to_fcpxml())
                
                duration_str = child.get('duration', '0s')
                duration = TimeValue.from_timecode(duration_str, self.fps)
                current_offset = current_offset + duration
    
    def save(self, output_path: str) -> str:
        """Write modified FCPXML to file"""
        self.tree.write(output_path, encoding='UTF-8', xml_declaration=True)
        return output_path


    # ========================================================================
    # MARKER OPERATIONS
    # ========================================================================
    
    def add_marker(
        self,
        clip_id: str,
        timecode: str,
        name: str,
        marker_type: MarkerType = MarkerType.STANDARD,
        color: Optional[MarkerColor] = None,
        note: Optional[str] = None
    ) -> ET.Element:
        """
        Add a marker to a clip.
        
        Args:
            clip_id: Target clip identifier
            timecode: Position within clip (relative to clip start)
            name: Marker label
            marker_type: standard, chapter, or todo
            color: Optional marker color
            note: Optional marker note
        
        Returns:
            The created marker element
        """
        clip = self.clips.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")
        
        # Convert timecode to FCPXML time
        time_value = TimeValue.from_timecode(timecode, self.fps)
        
        # Create marker element
        marker = ET.SubElement(clip, marker_type.value)
        marker.set('start', time_value.to_fcpxml())
        marker.set('duration', f"1/{int(self.fps)}s")  # 1 frame duration
        marker.set('value', name)
        
        # Add poster offset for chapter markers
        if marker_type == MarkerType.CHAPTER:
            marker.set('posterOffset', '0s')
        
        # Add color if specified
        if color is not None:
            color_elem = ET.SubElement(marker, 'marker-color')
            color_elem.set('color', str(color.value))
        
        # Add note if specified
        if note:
            note_elem = ET.SubElement(marker, 'note')
            note_elem.text = note
        
        return marker
    
    def batch_add_markers(
        self,
        markers: List[Dict],
        auto_detect: Optional[Dict] = None
    ) -> List[ET.Element]:
        """
        Add multiple markers at once.
        
        Args:
            markers: List of marker specs [{clip_id, timecode, name, ...}]
            auto_detect: Auto-generate markers (at_cuts, at_keywords, at_intervals)
        
        Returns:
            List of created marker elements
        """
        created = []
        
        # Handle explicit markers
        for m in markers:
            marker = self.add_marker(
                clip_id=m['clip_id'],
                timecode=m['timecode'],
                name=m['name'],
                marker_type=MarkerType[m.get('marker_type', 'STANDARD').upper()],
                color=MarkerColor[m['color'].upper()] if m.get('color') else None,
                note=m.get('note')
            )
            created.append(marker)
        
        # Handle auto-detection
        if auto_detect:
            if auto_detect.get('at_cuts'):
                # Add marker at every cut point
                spine = self._get_spine()
                for clip in spine.findall('clip'):
                    offset = clip.get('offset', '0s')
                    marker = self.add_marker(
                        clip_id=clip.get('id', 'clip_0'),
                        timecode='0s',  # Start of clip = cut point
                        name='Cut',
                        marker_type=MarkerType.STANDARD,
                        color=MarkerColor.YELLOW
                    )
                    created.append(marker)
            
            if auto_detect.get('at_intervals'):
                # Add markers at regular intervals
                interval = TimeValue.from_timecode(auto_detect['at_intervals'], self.fps)
                # Implementation: iterate through timeline at interval steps
                pass
        
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
        
        # Get current values
        current_start = TimeValue.from_timecode(clip.get('start', '0s'), self.fps)
        current_duration = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
        
        duration_delta = TimeValue(0)
        
        # Handle trim_start
        if trim_start:
            if trim_start.startswith('+') or trim_start.startswith('-'):
                # Delta trim
                delta = TimeValue.from_timecode(trim_start.lstrip('+-'), self.fps)
                if trim_start.startswith('-'):
                    new_start = current_start - delta
                    new_duration = current_duration + delta
                else:
                    new_start = current_start + delta
                    new_duration = current_duration - delta
            else:
                # Absolute trim
                new_start = TimeValue.from_timecode(trim_start, self.fps)
                start_diff = new_start - current_start
                new_duration = current_duration - start_diff
            
            clip.set('start', new_start.to_fcpxml())
            duration_delta = new_duration - current_duration
            current_duration = new_duration
        
        # Handle trim_end
        if trim_end:
            if trim_end.startswith('+') or trim_end.startswith('-'):
                delta = TimeValue.from_timecode(trim_end.lstrip('+-'), self.fps)
                if trim_end.startswith('-'):
                    new_duration = current_duration - delta
                else:
                    new_duration = current_duration + delta
            else:
                # Absolute end point
                end_point = TimeValue.from_timecode(trim_end, self.fps)
                new_duration = end_point - current_start
            
            duration_delta = duration_delta + (new_duration - current_duration)
            current_duration = new_duration
        
        clip.set('duration', current_duration.to_fcpxml())
        
        # Ripple subsequent clips
        if ripple and duration_delta.numerator != 0:
            self._ripple_after_clip(clip, duration_delta)
        
        return clip
    
    def _ripple_after_clip(self, clip: ET.Element, delta: TimeValue) -> None:
        """Shift all clips after the given clip by delta"""
        spine = self._get_spine()
        found_clip = False
        
        for child in spine:
            if child == clip:
                found_clip = True
                continue
            
            if found_clip and child.tag in ('clip', 'video', 'audio', 'gap', 'ref-clip'):
                current_offset = TimeValue.from_timecode(child.get('offset', '0s'), self.fps)
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
            for child in spine:
                if child.get('id') == clip_id or child.get('name') == clip_id:
                    clips_to_move.append(child)
                    break
        
        if not clips_to_move:
            raise ValueError(f"No clips found matching: {clip_ids}")
        
        # Calculate total duration of moving clips
        total_duration = TimeValue(0)
        for clip in clips_to_move:
            dur = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
            total_duration = total_duration + dur
        
        # Remove clips from current positions (store for reinsertion)
        for clip in clips_to_move:
            spine.remove(clip)
        
        # Determine target offset
        if target_position == 'start':
            target_offset = TimeValue(0)
            insert_index = 0
        elif target_position == 'end':
            # Find end of timeline
            last_clip = list(spine)[-1] if len(spine) > 0 else None
            if last_clip is not None:
                last_offset = TimeValue.from_timecode(last_clip.get('offset', '0s'), self.fps)
                last_dur = TimeValue.from_timecode(last_clip.get('duration', '0s'), self.fps)
                target_offset = last_offset + last_dur
            else:
                target_offset = TimeValue(0)
            insert_index = len(spine)
        elif target_position.startswith('after:'):
            ref_id = target_position.split(':')[1]
            for i, child in enumerate(spine):
                if child.get('id') == ref_id or child.get('name') == ref_id:
                    ref_offset = TimeValue.from_timecode(child.get('offset', '0s'), self.fps)
                    ref_dur = TimeValue.from_timecode(child.get('duration', '0s'), self.fps)
                    target_offset = ref_offset + ref_dur
                    insert_index = i + 1
                    break
        elif target_position.startswith('before:'):
            ref_id = target_position.split(':')[1]
            for i, child in enumerate(spine):
                if child.get('id') == ref_id or child.get('name') == ref_id:
                    target_offset = TimeValue.from_timecode(child.get('offset', '0s'), self.fps)
                    insert_index = i
                    break
        else:
            # Assume timecode
            target_offset = TimeValue.from_timecode(target_position, self.fps)
            # Find insert position
            insert_index = 0
            for i, child in enumerate(spine):
                child_offset = TimeValue.from_timecode(child.get('offset', '0s'), self.fps)
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
            dur = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
            current_offset = current_offset + dur
        
        # Recalculate all offsets if ripple
        if ripple:
            self._recalculate_offsets(spine)


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
        """
        spine = self._get_spine()
        clip = self.clips.get(clip_id)
        
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")
        
        trans_duration = TimeValue.from_timecode(duration, self.fps)
        
        # Find clip index in spine
        clip_index = None
        for i, child in enumerate(spine):
            if child == clip:
                clip_index = i
                break
        
        if clip_index is None:
            raise ValueError(f"Clip not in primary storyline: {clip_id}")
        
        transitions_added = []
        
        # Map transition type to FCPXML effect name
        effect_map = {
            'cross-dissolve': 'Cross Dissolve',
            'fade-to-black': 'Fade to Color',
            'fade-from-black': 'Fade from Color',
            'dip-to-color': 'Dip to Color',
            'wipe': 'Wipe',
            'slide': 'Slide'
        }
        effect_name = effect_map.get(transition_type, 'Cross Dissolve')
        
        if position in ('end', 'both'):
            # Add transition after clip
            clip_offset = TimeValue.from_timecode(clip.get('offset', '0s'), self.fps)
            clip_dur = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
            
            # Transition starts at clip_end - (duration / 2)
            half_dur = TimeValue(trans_duration.numerator, trans_duration.denominator * 2)
            trans_offset = clip_offset + clip_dur - half_dur
            
            transition = ET.Element('transition')
            transition.set('name', effect_name)
            transition.set('offset', trans_offset.to_fcpxml())
            transition.set('duration', trans_duration.to_fcpxml())
            
            # Add filter reference
            filter_video = ET.SubElement(transition, 'filter-video')
            filter_video.set('name', effect_name)
            
            spine.insert(clip_index + 1, transition)
            transitions_added.append(transition)
        
        if position in ('start', 'both'):
            # Add transition before clip
            clip_offset = TimeValue.from_timecode(clip.get('offset', '0s'), self.fps)
            half_dur = TimeValue(trans_duration.numerator, trans_duration.denominator * 2)
            trans_offset = clip_offset - half_dur
            
            transition = ET.Element('transition')
            transition.set('name', effect_name)
            transition.set('offset', trans_offset.to_fcpxml())
            transition.set('duration', trans_duration.to_fcpxml())
            
            filter_video = ET.SubElement(transition, 'filter-video')
            filter_video.set('name', effect_name)
            
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
        ramp: Optional[Dict] = None,
        preserve_pitch: bool = True,
        frame_blending: str = 'optical-flow'
    ) -> ET.Element:
        """
        Change clip playback speed.
        
        Args:
            clip_id: Target clip
            speed: Speed multiplier (0.5 = half speed, 2.0 = double)
            ramp: Optional speed ramp config {start_speed, end_speed, curve}
            preserve_pitch: Maintain audio pitch
            frame_blending: Interpolation method
        """
        clip = self.clips.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip not found: {clip_id}")
        
        # Get current duration
        current_duration = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
        
        if ramp:
            # Speed ramp - create timeMap with multiple keyframes
            timemap = ET.SubElement(clip, 'timeMap')
            
            start_speed = ramp.get('start_speed', 1.0)
            end_speed = ramp.get('end_speed', speed)
            curve = ramp.get('curve', 'linear')
            
            # Map curve to FCPXML interpolation
            interp_map = {
                'linear': 'linear',
                'ease-in': 'smooth2',
                'ease-out': 'smooth2',
                'ease-in-out': 'smooth'
            }
            interp = interp_map.get(curve, 'linear')
            
            # Calculate output duration based on speed changes
            # This is simplified - real implementation needs integral calculus
            avg_speed = (start_speed + end_speed) / 2
            new_duration_seconds = current_duration.to_seconds() / avg_speed
            
            # Create keyframes
            # Start point
            tp1 = ET.SubElement(timemap, 'timept')
            tp1.set('time', '0s')
            tp1.set('value', '0s')
            tp1.set('interp', 'linear')
            
            # Mid point (speed transition)
            mid_time = new_duration_seconds / 2
            mid_value = current_duration.to_seconds() / 2 / start_speed
            tp2 = ET.SubElement(timemap, 'timept')
            tp2.set('time', f"{mid_time}s")
            tp2.set('value', f"{mid_value}s")
            tp2.set('interp', interp)
            
            # End point
            tp3 = ET.SubElement(timemap, 'timept')
            tp3.set('time', f"{new_duration_seconds}s")
            tp3.set('value', current_duration.to_fcpxml())
            tp3.set('interp', 'linear')
            
            # Update clip duration
            clip.set('duration', f"{new_duration_seconds}s")
            
        else:
            # Constant speed change
            timemap = ET.SubElement(clip, 'timeMap')
            
            new_duration_seconds = current_duration.to_seconds() / speed
            source_duration = current_duration.to_seconds()
            
            # Start keyframe
            tp1 = ET.SubElement(timemap, 'timept')
            tp1.set('time', '0s')
            tp1.set('value', '0s')
            tp1.set('interp', 'linear')
            
            # End keyframe
            tp2 = ET.SubElement(timemap, 'timept')
            tp2.set('time', f"{new_duration_seconds}s")
            tp2.set('value', f"{source_duration}s")
            tp2.set('interp', 'linear')
            
            # Update clip duration
            clip.set('duration', f"{new_duration_seconds}s")
        
        # Add conform-rate for frame blending
        conform = ET.SubElement(clip, 'conform-rate')
        conform.set('scaleEnabled', '1')
        conform.set('srcFrameRate', str(int(self.fps)))
        
        # Frame blending attribute
        blend_map = {
            'none': '0',
            'frame-blending': '1',
            'optical-flow': '2'
        }
        # Note: Actual FCP attribute name may vary
        
        # Audio pitch preservation
        if preserve_pitch:
            audio = clip.find('audio')
            if audio is not None:
                audio.set('preservePitch', '1')
        
        return clip


    # ========================================================================
    # SPLIT OPERATIONS
    # ========================================================================
    
    def split_clip(
        self,
        clip_id: str,
        split_points: List[str],
        split_type: str = 'blade'
    ) -> List[ET.Element]:
        """
        Split a clip at specified timecodes.
        
        Args:
            clip_id: Clip to split
            split_points: Timecodes within the clip to split at
            split_type: 'blade' (this clip only) or 'blade-all' (all tracks)
        
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
        
        # Sort split points
        split_times = sorted([TimeValue.from_timecode(sp, self.fps) for sp in split_points])
        
        # Get clip properties
        clip_offset = TimeValue.from_timecode(clip.get('offset', '0s'), self.fps)
        clip_start = TimeValue.from_timecode(clip.get('start', '0s'), self.fps)
        clip_duration = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
        clip_name = clip.get('name', 'Clip')
        clip_ref = clip.get('ref')
        
        # Remove original clip
        spine.remove(clip)
        
        # Create new clips
        new_clips = []
        current_offset = clip_offset
        current_start = clip_start
        
        for i, split_time in enumerate(split_times + [clip_duration]):
            if i == 0:
                segment_duration = split_time
            else:
                segment_duration = split_time - split_times[i - 1]
            
            # Create new clip element
            new_clip = ET.Element('clip')
            new_clip.set('name', f"{clip_name}")
            new_clip.set('offset', current_offset.to_fcpxml())
            new_clip.set('start', current_start.to_fcpxml())
            new_clip.set('duration', segment_duration.to_fcpxml())
            if clip_ref:
                new_clip.set('ref', clip_ref)
            
            # Copy other attributes
            for attr in ['tcFormat', 'format']:
                if clip.get(attr):
                    new_clip.set(attr, clip.get(attr))
            
            # Insert into spine
            spine.insert(clip_index + i, new_clip)
            new_clips.append(new_clip)
            
            # Update for next iteration
            current_offset = current_offset + segment_duration
            current_start = current_start + segment_duration
        
        # Update clip index
        for new_clip in new_clips:
            self.clips[new_clip.get('id', new_clip.get('name'))] = new_clip
        
        return new_clips


    # ========================================================================
    # DELETE OPERATIONS
    # ========================================================================
    
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
            
            clip_duration = TimeValue.from_timecode(clip.get('duration', '0s'), self.fps)
            clip_offset = TimeValue.from_timecode(clip.get('offset', '0s'), self.fps)
            
            # Find clip index
            clip_index = None
            for i, child in enumerate(spine):
                if child == clip:
                    clip_index = i
                    break
            
            if clip_index is None:
                continue
            
            if ripple:
                # Remove clip and shift others
                spine.remove(clip)
                
                # Shift subsequent clips
                for child in spine[clip_index:]:
                    if child.tag in ('clip', 'video', 'audio', 'gap', 'ref-clip', 'transition'):
                        child_offset = TimeValue.from_timecode(child.get('offset', '0s'), self.fps)
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


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def add_marker(
    project_path: str,
    clip_id: str,
    timecode: str,
    name: str,
    marker_type: str = 'standard',
    color: Optional[str] = None,
    note: Optional[str] = None,
    output_path: Optional[str] = None
) -> str:
    """
    Convenience function to add a marker and save.
    
    Returns:
        Path to the modified FCPXML
    """
    writer = FCPXMLWriter(project_path)
    
    mt = MarkerType[marker_type.upper()]
    mc = MarkerColor[color.upper()] if color else None
    
    writer.add_marker(clip_id, timecode, name, mt, mc, note)
    
    out = output_path or project_path.replace('.fcpxml', '_modified.fcpxml')
    return writer.save(out)


def trim_clip(
    project_path: str,
    clip_id: str,
    trim_start: Optional[str] = None,
    trim_end: Optional[str] = None,
    ripple: bool = True,
    output_path: Optional[str] = None
) -> str:
    """Convenience function to trim a clip and save."""
    writer = FCPXMLWriter(project_path)
    writer.trim_clip(clip_id, trim_start, trim_end, ripple)
    
    out = output_path or project_path.replace('.fcpxml', '_modified.fcpxml')
    return writer.save(out)


def reorder_clips(
    project_path: str,
    clip_ids: List[str],
    target_position: str,
    ripple: bool = True,
    output_path: Optional[str] = None
) -> str:
    """Convenience function to reorder clips and save."""
    writer = FCPXMLWriter(project_path)
    writer.reorder_clips(clip_ids, target_position, ripple)
    
    out = output_path or project_path.replace('.fcpxml', '_modified.fcpxml')
    return writer.save(out)


# Additional convenience functions follow same pattern...
