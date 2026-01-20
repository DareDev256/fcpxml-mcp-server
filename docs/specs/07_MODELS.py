# models.py - Data Models for FCP MCP Server

"""
Core data models for representing FCPXML structures.

These models provide a clean Python interface for working with
Final Cut Pro timelines, clips, markers, and other elements.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
from datetime import timedelta


# ============================================================================
# ENUMS
# ============================================================================

class MarkerType(Enum):
    """Types of markers in Final Cut Pro."""
    STANDARD = "marker"
    CHAPTER = "chapter-marker"
    TODO = "todo-marker"
    COMPLETED = "completed-marker"


class MarkerColor(Enum):
    """Marker color options (FCP internal values)."""
    BLUE = 0
    CYAN = 1
    GREEN = 2
    YELLOW = 3
    ORANGE = 4
    RED = 5
    PINK = 6
    PURPLE = 7


class TransitionType(Enum):
    """Built-in transition types."""
    CROSS_DISSOLVE = "Cross Dissolve"
    FADE_TO_BLACK = "Fade to Color"
    FADE_FROM_BLACK = "Fade from Color"
    DIP_TO_COLOR = "Dip to Color"
    WIPE = "Wipe"
    SLIDE = "Slide"


class ClipType(Enum):
    """Types of clips in timeline."""
    VIDEO = "video"
    AUDIO = "audio"
    COMPOUND = "compound"
    MULTICAM = "multicam"
    SYNC = "sync"
    GAP = "gap"
    TITLE = "title"
    GENERATOR = "generator"


class PacingStyle(Enum):
    """Pacing presets for rough cut generation."""
    SLOW = "slow"      # 5-10 second cuts
    MEDIUM = "medium"  # 2-5 second cuts
    FAST = "fast"      # 0.5-2 second cuts
    DYNAMIC = "dynamic"  # Varies throughout


# ============================================================================
# TIME VALUE
# ============================================================================

@dataclass
class TimeValue:
    """
    Represents time in FCPXML's rational format.
    
    FCPXML uses fractions of seconds (e.g., "90/30s" for 3 seconds at 30fps).
    This class handles conversion between timecode, seconds, and FCPXML format.
    
    Examples:
        TimeValue(90, 30)  # 3 seconds at 30fps
        TimeValue(1, 1)    # 1 second
        TimeValue.from_timecode("00:01:30:15", fps=30)  # 90.5 seconds
    """
    numerator: int
    denominator: int = 1
    
    @classmethod
    def from_timecode(cls, tc: str, fps: float = 30.0) -> 'TimeValue':
        """
        Create TimeValue from various string formats.
        
        Supported formats:
        - "HH:MM:SS:FF" - Standard timecode
        - "HH:MM:SS;FF" - Drop-frame timecode
        - "30s" - Seconds
        - "90/30s" - FCPXML rational format
        - "15f" - Frames
        """
        if not tc:
            return cls(0, 1)
        
        tc = str(tc).strip()
        
        # FCPXML format: "90/30s" or "30s"
        if tc.endswith('s'):
            tc_val = tc[:-1]
            if '/' in tc_val:
                num, denom = tc_val.split('/')
                return cls(int(num), int(denom))
            else:
                seconds = float(tc_val)
                frames = int(round(seconds * fps))
                return cls(frames, int(fps))
        
        # Frame format: "15f"
        if tc.endswith('f'):
            frames = int(tc[:-1])
            return cls(frames, int(fps))
        
        # Timecode format: "HH:MM:SS:FF" or "HH:MM:SS;FF"
        if ':' in tc or ';' in tc:
            parts = tc.replace(';', ':').split(':')
            if len(parts) == 4:
                h, m, s, f = map(int, parts)
                total_frames = int((h * 3600 + m * 60 + s) * fps + f)
                return cls(total_frames, int(fps))
            elif len(parts) == 3:
                # HH:MM:SS without frames
                h, m, s = map(int, parts)
                total_frames = int((h * 3600 + m * 60 + s) * fps)
                return cls(total_frames, int(fps))
        
        # Try as plain number (seconds)
        try:
            seconds = float(tc)
            frames = int(round(seconds * fps))
            return cls(frames, int(fps))
        except ValueError:
            raise ValueError(f"Invalid timecode format: {tc}")
    
    @classmethod
    def from_seconds(cls, seconds: float, fps: float = 30.0) -> 'TimeValue':
        """Create TimeValue from decimal seconds."""
        frames = int(round(seconds * fps))
        return cls(frames, int(fps))
    
    @classmethod
    def zero(cls) -> 'TimeValue':
        """Return zero time value."""
        return cls(0, 1)
    
    def to_fcpxml(self) -> str:
        """Convert to FCPXML time string (e.g., "90/30s")."""
        simplified = self.simplify()
        if simplified.denominator == 1:
            return f"{simplified.numerator}s"
        return f"{simplified.numerator}/{simplified.denominator}s"
    
    def to_seconds(self) -> float:
        """Convert to decimal seconds."""
        if self.denominator == 0:
            return 0.0
        return self.numerator / self.denominator
    
    def to_timecode(self, fps: float = 30.0) -> str:
        """Convert to HH:MM:SS:FF timecode string."""
        total_seconds = self.to_seconds()
        total_frames = int(round(total_seconds * fps))
        
        frames = int(total_frames % fps)
        total_secs = total_frames // int(fps)
        secs = total_secs % 60
        total_mins = total_secs // 60
        mins = total_mins % 60
        hours = total_mins // 60
        
        return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"
    
    def to_frames(self, fps: float = 30.0) -> int:
        """Convert to frame count."""
        return int(round(self.to_seconds() * fps))
    
    def simplify(self) -> 'TimeValue':
        """Reduce fraction to simplest form."""
        if self.numerator == 0:
            return TimeValue(0, 1)
        from math import gcd
        divisor = gcd(abs(self.numerator), abs(self.denominator))
        return TimeValue(
            self.numerator // divisor,
            self.denominator // divisor
        )
    
    def __add__(self, other: 'TimeValue') -> 'TimeValue':
        new_denom = self.denominator * other.denominator
        new_num = (self.numerator * other.denominator) + (other.numerator * self.denominator)
        return TimeValue(new_num, new_denom).simplify()
    
    def __sub__(self, other: 'TimeValue') -> 'TimeValue':
        new_denom = self.denominator * other.denominator
        new_num = (self.numerator * other.denominator) - (other.numerator * self.denominator)
        return TimeValue(new_num, new_denom).simplify()
    
    def __mul__(self, scalar: float) -> 'TimeValue':
        new_num = int(self.numerator * scalar)
        return TimeValue(new_num, self.denominator).simplify()
    
    def __truediv__(self, scalar: float) -> 'TimeValue':
        new_denom = int(self.denominator * scalar)
        return TimeValue(self.numerator, new_denom).simplify()
    
    def __lt__(self, other: 'TimeValue') -> bool:
        return self.to_seconds() < other.to_seconds()
    
    def __le__(self, other: 'TimeValue') -> bool:
        return self.to_seconds() <= other.to_seconds()
    
    def __gt__(self, other: 'TimeValue') -> bool:
        return self.to_seconds() > other.to_seconds()
    
    def __ge__(self, other: 'TimeValue') -> bool:
        return self.to_seconds() >= other.to_seconds()
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimeValue):
            return False
        return abs(self.to_seconds() - other.to_seconds()) < 0.0001
    
    def __repr__(self) -> str:
        return f"TimeValue({self.numerator}/{self.denominator}s = {self.to_seconds():.3f}s)"


# ============================================================================
# CORE MODELS
# ============================================================================

@dataclass
class Marker:
    """A marker in the timeline."""
    time: float  # Position in seconds
    name: str
    marker_type: str = "standard"
    color: Optional[str] = None
    note: Optional[str] = None
    duration: float = 0.0  # Usually 0 or 1 frame
    
    # Reference to containing clip (if any)
    clip_id: Optional[str] = None


@dataclass
class Keyword:
    """A keyword range applied to a clip or portion of a clip."""
    value: str  # The keyword text
    start: float  # Start time within clip (seconds)
    duration: float  # Duration of keyword range
    
    # Some keywords apply to entire clips
    is_clip_level: bool = False


@dataclass
class Effect:
    """A video or audio effect applied to a clip."""
    name: str
    effect_id: str  # FCP internal identifier
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Effect category
    is_audio: bool = False
    is_transition: bool = False


@dataclass
class Clip:
    """
    A clip in the timeline.
    
    Represents video, audio, gap, or compound clips.
    """
    # Identity
    id: str
    name: str
    clip_type: str = "video"  # video, audio, gap, compound, etc.
    
    # Timeline position
    offset: float  # Position in timeline (seconds)
    duration: float  # Duration in timeline (seconds)
    
    # Source reference
    source_start: float = 0.0  # In-point in source media
    source_path: Optional[str] = None  # Path to source file
    asset_id: Optional[str] = None  # Reference to asset in resources
    
    # Metadata
    keywords: List[str] = field(default_factory=list)
    rating: int = 0  # 0=unrated, 1-5 stars
    is_favorite: bool = False
    is_rejected: bool = False
    notes: str = ""
    
    # Markers within this clip
    markers: List[Marker] = field(default_factory=list)
    
    # Effects applied
    effects: List[Effect] = field(default_factory=list)
    
    # Speed modification
    speed: float = 1.0  # 1.0 = normal, 0.5 = half speed, 2.0 = double
    has_speed_ramp: bool = False
    
    # Audio properties
    is_audio_only: bool = False
    audio_volume: float = 0.0  # dB adjustment
    is_muted: bool = False
    
    # Technical
    resolution: Optional[Tuple[int, int]] = None
    frame_rate: Optional[float] = None
    
    # Relationships
    lane: int = 0  # 0 = primary storyline, negative = audio, positive = connected
    connected_to: Optional[str] = None  # ID of clip this connects to
    
    @property
    def end_offset(self) -> float:
        """Calculate end position in timeline."""
        return self.offset + self.duration
    
    @property
    def source_end(self) -> float:
        """Calculate end point in source media."""
        return self.source_start + (self.duration * self.speed)
    
    def contains_timecode(self, tc: float) -> bool:
        """Check if this clip contains the given timecode."""
        return self.offset <= tc < self.end_offset


@dataclass
class Transition:
    """A transition between clips."""
    name: str
    transition_type: str  # cross-dissolve, fade, wipe, etc.
    offset: float  # Position in timeline
    duration: float
    
    # Which clips it connects
    from_clip_id: Optional[str] = None
    to_clip_id: Optional[str] = None


@dataclass
class Timeline:
    """
    A complete FCP timeline/sequence.
    
    Contains all clips, markers, and metadata for a project.
    """
    # Identity
    name: str
    id: Optional[str] = None
    
    # Technical properties
    frame_rate: float = 30.0
    resolution: Tuple[int, int] = (1920, 1080)
    
    # Content
    clips: List[Clip] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)  # Timeline-level markers
    transitions: List[Transition] = field(default_factory=list)
    
    # Computed properties
    @property
    def duration(self) -> float:
        """Total timeline duration in seconds."""
        if not self.clips:
            return 0.0
        return max(c.end_offset for c in self.clips)
    
    @property
    def clip_count(self) -> int:
        """Number of clips (excluding gaps)."""
        return len([c for c in self.clips if c.clip_type != "gap"])
    
    @property
    def cut_count(self) -> int:
        """Number of cuts (transitions between clips)."""
        return max(0, self.clip_count - 1)
    
    @property
    def cuts_per_minute(self) -> float:
        """Average cuts per minute."""
        if self.duration <= 0:
            return 0.0
        return (self.cut_count / self.duration) * 60
    
    @property
    def average_clip_duration(self) -> float:
        """Average clip duration in seconds."""
        clips = [c for c in self.clips if c.clip_type != "gap"]
        if not clips:
            return 0.0
        return sum(c.duration for c in clips) / len(clips)
    
    def get_clip_at(self, timecode: float) -> Optional[Clip]:
        """Find the clip at a specific timecode."""
        for clip in self.clips:
            if clip.contains_timecode(timecode):
                return clip
        return None
    
    def get_clips_by_keyword(self, keyword: str) -> List[Clip]:
        """Find all clips with a specific keyword."""
        return [c for c in self.clips if keyword in c.keywords]
    
    def get_all_markers(self) -> List[Marker]:
        """Get all markers (timeline + clip-level)."""
        all_markers = list(self.markers)
        for clip in self.clips:
            for marker in clip.markers:
                # Adjust marker time to timeline position
                adjusted = Marker(
                    time=clip.offset + marker.time,
                    name=marker.name,
                    marker_type=marker.marker_type,
                    color=marker.color,
                    note=marker.note,
                    clip_id=clip.id
                )
                all_markers.append(adjusted)
        return sorted(all_markers, key=lambda m: m.time)


# ============================================================================
# ROUGH CUT MODELS
# ============================================================================

@dataclass
class SegmentSpec:
    """Specification for a segment in auto rough cut."""
    name: str
    keywords: List[str] = field(default_factory=list)
    duration: Optional[TimeValue] = None  # Target duration
    duration_seconds: float = 0.0  # Alternative: duration in seconds
    priority: str = "best"  # favorites, longest, shortest, random, best
    
    def get_duration_seconds(self) -> float:
        """Get duration as seconds."""
        if self.duration:
            return self.duration.to_seconds()
        return self.duration_seconds


@dataclass
class PacingConfig:
    """Configuration for rough cut pacing."""
    pacing: str = "medium"  # slow, medium, fast, dynamic
    min_clip_duration: float = 1.0  # Minimum seconds per clip
    max_clip_duration: float = 8.0  # Maximum seconds per clip
    avg_clip_duration: Optional[float] = None  # Target average
    vary_pacing: bool = True  # Randomize within range
    
    def get_duration_range(self) -> Tuple[float, float]:
        """Get min/max based on pacing style."""
        ranges = {
            "slow": (5.0, 10.0),
            "medium": (2.0, 5.0),
            "fast": (0.5, 2.0),
            "dynamic": (1.0, 6.0),
        }
        return ranges.get(self.pacing, (2.0, 5.0))


@dataclass
class ClipSelection:
    """A clip selected for inclusion in rough cut."""
    clip: Clip
    segment: str  # Which segment this belongs to
    in_point: TimeValue  # Where to start in source
    out_point: TimeValue  # Where to end in source
    order: int  # Position in final sequence
    
    @property
    def duration(self) -> TimeValue:
        """Duration of this selection."""
        return self.out_point - self.in_point


@dataclass
class RoughCutResult:
    """Result of auto rough cut generation."""
    output_path: str
    clips_used: int
    clips_available: int
    target_duration: float
    actual_duration: float
    segments: int
    average_clip_duration: float
    
    # Detailed breakdown
    segment_durations: Dict[str, float] = field(default_factory=dict)
    clips_per_segment: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# ASSET MODELS
# ============================================================================

@dataclass
class Asset:
    """A media asset referenced by clips."""
    id: str
    name: str
    src: str  # File path or URL
    
    # Duration in source
    start: float = 0.0
    duration: float = 0.0
    
    # Media properties
    has_video: bool = True
    has_audio: bool = True
    format_id: Optional[str] = None


@dataclass
class Format:
    """A format definition (resolution, frame rate, etc.)."""
    id: str
    name: str
    width: int = 1920
    height: int = 1080
    frame_duration: str = "1/30s"  # FCPXML format
    
    @property
    def frame_rate(self) -> float:
        """Calculate frame rate from frame duration."""
        if '/' in self.frame_duration:
            num, denom = self.frame_duration.replace('s', '').split('/')
            return int(denom) / int(num)
        return 30.0


@dataclass
class FCPXMLDocument:
    """
    Complete FCPXML document structure.
    
    Represents the entire file including resources and library structure.
    """
    version: str = "1.11"
    
    # Resources
    formats: List[Format] = field(default_factory=list)
    assets: List[Asset] = field(default_factory=list)
    effects: List[Effect] = field(default_factory=list)
    
    # Library structure
    library_name: str = "Library"
    events: List[str] = field(default_factory=list)  # Event names
    
    # Projects/Sequences
    timelines: List[Timeline] = field(default_factory=list)
    
    def get_asset(self, asset_id: str) -> Optional[Asset]:
        """Find asset by ID."""
        for asset in self.assets:
            if asset.id == asset_id:
                return asset
        return None
    
    def get_format(self, format_id: str) -> Optional[Format]:
        """Find format by ID."""
        for fmt in self.formats:
            if fmt.id == format_id:
                return fmt
        return None
