"""
Data models for Final Cut Pro FCPXML structures.

Provides a clean Python interface for working with Final Cut Pro
timelines, clips, markers, and other elements.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from math import gcd


# ============================================================================
# ENUMS
# ============================================================================

class MarkerType(Enum):
    """Types of markers in Final Cut Pro."""
    STANDARD = "standard"
    TODO = "todo"
    CHAPTER = "chapter"
    COMPLETED = "completed"


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


class PacingStyle(Enum):
    """Pacing presets for rough cut generation."""
    SLOW = "slow"      # 5-10 second cuts
    MEDIUM = "medium"  # 2-5 second cuts
    FAST = "fast"      # 0.5-2 second cuts
    DYNAMIC = "dynamic"  # Varies throughout


# ============================================================================
# TIME VALUE - Rational Time Representation
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
# TIMECODE (Legacy compatibility - wraps TimeValue)
# ============================================================================

@dataclass
class Timecode:
    """
    Represents a timecode value.

    Note: This class exists for backwards compatibility with the parser.
    New code should prefer TimeValue for rational time math.
    """
    frames: int
    frame_rate: float = 24.0
    drop_frame: bool = False

    @property
    def seconds(self) -> float:
        return self.frames / self.frame_rate

    @property
    def total_frames(self) -> int:
        return self.frames

    def to_smpte(self) -> str:
        """Convert to SMPTE timecode string (HH:MM:SS:FF)."""
        total_seconds = int(self.seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        frames = int((self.seconds - total_seconds) * self.frame_rate)
        separator = ";" if self.drop_frame else ":"
        return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{frames:02d}"

    @classmethod
    def from_rational(cls, rational_str: str, frame_rate: float = 24.0) -> "Timecode":
        """Parse FCPXML rational time format (e.g., '3600/24s')."""
        if not rational_str:
            return cls(frames=0, frame_rate=frame_rate)
        if rational_str.endswith('s'):
            rational_str = rational_str[:-1]
        if '/' in rational_str:
            num, denom = rational_str.split('/')
            seconds = int(num) / int(denom)
        else:
            seconds = float(rational_str)
        frames = int(seconds * frame_rate)
        return cls(frames=frames, frame_rate=frame_rate)

    def to_rational(self) -> str:
        """Convert to FCPXML rational format."""
        return f"{self.frames}/{int(self.frame_rate)}s"

    def to_time_value(self) -> TimeValue:
        """Convert to TimeValue for rational math."""
        return TimeValue(self.frames, int(self.frame_rate))


# ============================================================================
# CORE MODELS
# ============================================================================

@dataclass
class Keyword:
    """Represents a keyword/tag applied to a clip."""
    value: str
    start: Optional[Timecode] = None
    duration: Optional[Timecode] = None


@dataclass
class Marker:
    """Represents a marker in the timeline."""
    name: str
    start: Timecode
    duration: Optional[Timecode] = None
    marker_type: MarkerType = MarkerType.STANDARD
    note: str = ""
    color: Optional[MarkerColor] = None

    def to_youtube_timestamp(self) -> str:
        """Format as YouTube chapter timestamp."""
        total_seconds = int(self.start.seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"


@dataclass
class Clip:
    """Represents a clip in the timeline."""
    name: str
    start: Timecode
    duration: Timecode
    source_start: Optional[Timecode] = None
    source_end: Optional[Timecode] = None
    media_path: str = ""
    markers: List[Marker] = field(default_factory=list)
    keywords: List[Keyword] = field(default_factory=list)

    # Extended metadata
    rating: int = 0  # 0=unrated, 1-5 stars
    is_favorite: bool = False
    is_rejected: bool = False

    @property
    def end(self) -> Timecode:
        return Timecode(
            frames=self.start.frames + self.duration.frames,
            frame_rate=self.start.frame_rate
        )

    @property
    def duration_seconds(self) -> float:
        return self.duration.seconds

    @property
    def keyword_values(self) -> List[str]:
        """Get list of keyword strings."""
        return [k.value for k in self.keywords]


@dataclass
class AudioClip(Clip):
    """Audio-specific clip."""
    channels: int = 2
    sample_rate: int = 48000
    role: str = "dialogue"


@dataclass
class VideoClip(Clip):
    """Video-specific clip."""
    width: int = 1920
    height: int = 1080
    has_audio: bool = True


@dataclass
class Transition:
    """Represents a transition between clips."""
    name: str
    duration: Timecode
    start: Timecode
    transition_type: str = "cross-dissolve"


@dataclass
class Timeline:
    """Represents a Final Cut Pro timeline/sequence."""
    name: str
    duration: Timecode
    frame_rate: float = 24.0
    width: int = 1920
    height: int = 1080
    clips: List[Clip] = field(default_factory=list)
    audio_clips: List[AudioClip] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)

    @property
    def total_clips(self) -> int:
        return len(self.clips)

    @property
    def total_cuts(self) -> int:
        return max(0, len(self.clips) - 1)

    @property
    def average_clip_duration(self) -> float:
        if not self.clips:
            return 0.0
        return sum(c.duration_seconds for c in self.clips) / len(self.clips)

    @property
    def cuts_per_minute(self) -> float:
        """Average cuts per minute."""
        if self.duration.seconds <= 0:
            return 0.0
        return (self.total_cuts / self.duration.seconds) * 60

    def get_clips_shorter_than(self, seconds: float) -> List[Clip]:
        """Find clips shorter than threshold (flash frame detection)."""
        return [c for c in self.clips if c.duration_seconds < seconds]

    def get_clips_longer_than(self, seconds: float) -> List[Clip]:
        """Find clips longer than threshold."""
        return [c for c in self.clips if c.duration_seconds > seconds]

    def get_clip_at(self, timecode: float) -> Optional[Clip]:
        """Find the clip at a specific timecode (seconds)."""
        for clip in self.clips:
            start_sec = clip.start.seconds
            end_sec = clip.end.seconds
            if start_sec <= timecode < end_sec:
                return clip
        return None

    def get_clips_by_keyword(self, keyword: str) -> List[Clip]:
        """Find all clips with a specific keyword."""
        return [c for c in self.clips if keyword in c.keyword_values]


@dataclass
class Project:
    """Represents a Final Cut Pro project/library."""
    name: str
    timelines: List[Timeline] = field(default_factory=list)
    fcpxml_version: str = "1.11"

    @property
    def primary_timeline(self) -> Optional[Timeline]:
        return self.timelines[0] if self.timelines else None


# ============================================================================
# ROUGH CUT MODELS
# ============================================================================

@dataclass
class SegmentSpec:
    """Specification for a segment in auto rough cut."""
    name: str
    keywords: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    priority: str = "best"  # favorites, longest, shortest, random, best


@dataclass
class PacingConfig:
    """Configuration for rough cut pacing."""
    pacing: str = "medium"  # slow, medium, fast, dynamic
    min_clip_duration: float = 1.0
    max_clip_duration: float = 8.0
    avg_clip_duration: Optional[float] = None
    vary_pacing: bool = True

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
class RoughCutResult:
    """Result of auto rough cut generation."""
    output_path: str
    clips_used: int
    clips_available: int
    target_duration: float
    actual_duration: float
    segments: int
    average_clip_duration: float
