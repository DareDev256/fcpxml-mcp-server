"""
Data models for Final Cut Pro FCPXML structures.

Provides a clean Python interface for working with Final Cut Pro
timelines, clips, markers, and other elements.
"""

from dataclasses import dataclass, field
from enum import Enum
from math import gcd
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# ENUMS
# ============================================================================

# Maximum length for marker type strings to prevent memory abuse
_MAX_MARKER_TYPE_LENGTH = 64


class MarkerType(Enum):
    """Types of markers in Final Cut Pro."""
    STANDARD = "standard"
    TODO = "todo"
    CHAPTER = "chapter"
    COMPLETED = "completed"

    @classmethod
    def from_string(cls, value: str) -> 'MarkerType':
        """Convert a string to MarkerType, accepting both enum names and values.

        Includes input validation: rejects null bytes, control characters,
        and excessively long strings to prevent injection and memory abuse.

        Examples:
            MarkerType.from_string("todo")      -> MarkerType.TODO
            MarkerType.from_string("TODO")       -> MarkerType.TODO
            MarkerType.from_string("completed")  -> MarkerType.COMPLETED
        """
        if not isinstance(value, str):
            raise TypeError(f"Expected str, got {type(value).__name__}")
        if '\x00' in value or any(ord(c) < 32 and c not in ('\n', '\r', '\t') for c in value):
            raise ValueError("Marker type contains invalid control characters")
        if len(value) > _MAX_MARKER_TYPE_LENGTH:
            raise ValueError(
                f"Marker type exceeds maximum length ({_MAX_MARKER_TYPE_LENGTH} chars)"
            )
        lowered = value.strip().lower()
        if not lowered:
            raise ValueError("Marker type cannot be empty")
        # Accept legacy aliases from older specs (e.g. "todo-marker" → TODO)
        aliases = {
            "todo-marker": "todo",
            "completed-marker": "completed",
            "chapter-marker": "chapter",
        }
        lowered = aliases.get(lowered, lowered)
        try:
            return cls(lowered)
        except ValueError:
            raise ValueError(
                f"Invalid marker type: '{value}'. "
                f"Valid types: {', '.join(m.value for m in cls)}"
            )

    @classmethod
    def from_xml_element(cls, elem) -> 'MarkerType':
        """Determine MarkerType from an XML element's tag and attributes.

        Centralises the parse-side mapping so the parser doesn't need to
        know about completed-attribute semantics.
        """
        if elem.tag == 'chapter-marker':
            return cls.CHAPTER
        completed = elem.get('completed')
        if completed == '1':
            return cls.COMPLETED
        if completed == '0':
            return cls.TODO
        return cls.STANDARD

    @property
    def xml_tag(self) -> str:
        """Return the FCPXML element tag for this marker type."""
        return 'chapter-marker' if self == MarkerType.CHAPTER else 'marker'

    @property
    def xml_attrs(self) -> dict:
        """Return extra XML attributes this marker type requires when writing.

        Centralises the write-side mapping so both FCPXMLModifier and
        FCPXMLWriter use a single source of truth.
        """
        if self == MarkerType.CHAPTER:
            return {'posterOffset': '0s'}
        if self == MarkerType.TODO:
            return {'completed': '0'}
        if self == MarkerType.COMPLETED:
            return {'completed': '1'}
        return {}


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


class FlashFrameSeverity(Enum):
    """Severity levels for flash frame detection."""
    CRITICAL = "critical"  # < 2 frames, almost certainly an error
    WARNING = "warning"    # < 6 frames, potentially intentional but suspicious


class PacingCurve(Enum):
    """Pacing curves for montage generation."""
    CONSTANT = "constant"        # Same clip duration throughout
    ACCELERATING = "accelerating"  # Starts slow, gets faster
    DECELERATING = "decelerating"  # Starts fast, gets slower
    PYRAMID = "pyramid"          # Slow → fast → slow


class ValidationIssueType(Enum):
    """Types of timeline validation issues."""
    FLASH_FRAME = "flash_frame"
    GAP = "gap"
    DUPLICATE = "duplicate"
    ORPHAN_REF = "orphan_ref"
    INVALID_OFFSET = "invalid_offset"


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

    # Roles (FCP audio/video role assignments)
    audio_role: str = ""
    video_role: str = ""

    # Connected clips (B-roll, titles, audio attached to this clip)
    connected_clips: List['ConnectedClip'] = field(default_factory=list)

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
class ConnectedClip:
    """A clip connected to a primary storyline clip (B-roll, titles, audio).

    In FCP's magnetic timeline, connected clips hang off spine clips via lanes.
    Positive lanes are above (video overlays), negative lanes are below (audio).
    """
    name: str
    start: Timecode
    duration: Timecode
    lane: int = 1
    offset: Optional[Timecode] = None
    source_start: Optional[Timecode] = None
    media_path: str = ""
    clip_type: str = "asset-clip"
    role: str = ""
    ref_id: str = ""
    parent_clip_name: str = ""
    markers: List[Marker] = field(default_factory=list)
    keywords: List[Keyword] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return self.duration.seconds


@dataclass
class CompoundClip:
    """A compound clip (ref-clip) containing a nested timeline."""
    name: str
    ref_id: str
    duration: Timecode
    start: Timecode
    clips: List[Clip] = field(default_factory=list)
    connected_clips: List[ConnectedClip] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return self.duration.seconds


@dataclass
class SilenceCandidate:
    """A potential silence region detected by timeline heuristics."""
    start_timecode: str
    duration_seconds: float
    reason: str  # "gap", "ultra_short", "name_match", "duration_anomaly"
    confidence: float = 0.5  # 0.0 to 1.0
    clip_name: Optional[str] = None
    clip_index: Optional[int] = None


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
    connected_clips: List[ConnectedClip] = field(default_factory=list)
    compound_clips: List[CompoundClip] = field(default_factory=list)

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


# ============================================================================
# SPEED CUTTING & VALIDATION MODELS (v0.3.0)
# ============================================================================

@dataclass
class FlashFrame:
    """
    Represents a detected flash frame (ultra-short clip).

    Flash frames are typically editing errors - clips that are too short
    to be perceived as intentional cuts.
    """
    clip_name: str
    clip_id: str
    start: Timecode
    duration_frames: int
    duration_seconds: float
    severity: 'FlashFrameSeverity'

    @property
    def is_critical(self) -> bool:
        """Check if this is a critical flash frame."""
        from . import models  # avoid circular import
        return self.severity == models.FlashFrameSeverity.CRITICAL


@dataclass
class GapInfo:
    """
    Represents a detected gap in the timeline.

    Gaps can be intentional (black frames) or errors from deleted clips.
    """
    start: Timecode
    duration_frames: int
    duration_seconds: float
    previous_clip: Optional[str] = None  # Clip name before the gap
    next_clip: Optional[str] = None      # Clip name after the gap

    @property
    def timecode(self) -> str:
        """Get timecode string for the gap start."""
        return self.start.to_smpte()


@dataclass
class DuplicateGroup:
    """
    Represents a group of clips using the same source media.

    Useful for detecting duplicate clips that may be unintentional.
    """
    source_ref: str  # The asset/media reference ID
    source_name: str  # Human-readable source name
    clips: List[Dict[str, Any]] = field(default_factory=list)  # List of clip info dicts

    @property
    def count(self) -> int:
        """Number of clips using this source."""
        return len(self.clips)

    @property
    def has_overlapping_ranges(self) -> bool:
        """Check if any clips use overlapping portions of the source."""
        # Sort clips by source_start
        sorted_clips = sorted(self.clips, key=lambda c: c.get('source_start', 0))
        for i in range(len(sorted_clips) - 1):
            curr_end = sorted_clips[i].get('source_start', 0) + sorted_clips[i].get('source_duration', 0)
            next_start = sorted_clips[i + 1].get('source_start', 0)
            if curr_end > next_start:
                return True
        return False


@dataclass
class ValidationIssue:
    """
    Represents a single validation issue found in a timeline.

    Used by validate_timeline to report problems.
    """
    issue_type: 'ValidationIssueType'
    severity: str  # "error", "warning", "info"
    message: str
    timecode: Optional[str] = None
    clip_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """
    Result of timeline validation.

    Provides a health score and categorized list of issues.
    """
    is_valid: bool
    health_score: int  # 0-100 percentage
    issues: List[ValidationIssue] = field(default_factory=list)
    flash_frames: List[FlashFrame] = field(default_factory=list)
    gaps: List[GapInfo] = field(default_factory=list)
    duplicates: List[DuplicateGroup] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len([i for i in self.issues if i.severity == "error"])

    @property
    def warning_count(self) -> int:
        return len([i for i in self.issues if i.severity == "warning"])

    def summary(self) -> str:
        """Generate a summary string."""
        return (
            f"Timeline Health: {self.health_score}% | "
            f"Errors: {self.error_count} | Warnings: {self.warning_count} | "
            f"Flash frames: {len(self.flash_frames)} | Gaps: {len(self.gaps)}"
        )


@dataclass
class MontageConfig:
    """Configuration for montage generation with pacing curves."""
    target_duration: float  # Target duration in seconds
    pacing_curve: 'PacingCurve'
    start_duration: float = 2.0  # Clip duration at start
    end_duration: float = 0.5    # Clip duration at end
    min_duration: float = 0.2    # Minimum allowed clip duration
    max_duration: float = 5.0    # Maximum allowed clip duration

    def get_duration_at_position(self, position: float) -> float:
        """
        Calculate clip duration for a given position (0.0 to 1.0).

        Args:
            position: Position in montage (0.0 = start, 1.0 = end)

        Returns:
            Target duration in seconds for a clip at this position
        """
        from . import models

        if self.pacing_curve == models.PacingCurve.CONSTANT:
            return (self.start_duration + self.end_duration) / 2

        elif self.pacing_curve == models.PacingCurve.ACCELERATING:
            # Linear interpolation from start to end duration
            duration = self.start_duration + (self.end_duration - self.start_duration) * position

        elif self.pacing_curve == models.PacingCurve.DECELERATING:
            # Reverse: start fast, end slow
            duration = self.end_duration + (self.start_duration - self.end_duration) * position

        elif self.pacing_curve == models.PacingCurve.PYRAMID:
            # Slow → fast → slow (parabolic curve)
            if position < 0.5:
                # First half: slow to fast
                duration = self.start_duration + (self.end_duration - self.start_duration) * (position * 2)
            else:
                # Second half: fast to slow
                duration = self.end_duration + (self.start_duration - self.end_duration) * ((position - 0.5) * 2)
        else:
            duration = self.start_duration

        # Clamp to min/max
        return max(self.min_duration, min(self.max_duration, duration))
