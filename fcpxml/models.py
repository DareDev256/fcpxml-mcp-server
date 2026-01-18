"""
Data models for Final Cut Pro FCPXML structures.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class MarkerType(Enum):
    STANDARD = "standard"
    TODO = "todo"
    CHAPTER = "chapter"
    

@dataclass
class Timecode:
    """Represents a timecode value."""
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


@dataclass
class Marker:
    """Represents a marker in the timeline."""
    name: str
    start: Timecode
    duration: Optional[Timecode] = None
    marker_type: MarkerType = MarkerType.STANDARD
    note: str = ""
    
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
class Keyword:
    """Represents a keyword/tag applied to a clip."""
    value: str
    start: Optional[Timecode] = None
    duration: Optional[Timecode] = None


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
    
    @property
    def end(self) -> Timecode:
        return Timecode(
            frames=self.start.frames + self.duration.frames,
            frame_rate=self.start.frame_rate
        )
    
    @property
    def duration_seconds(self) -> float:
        return self.duration.seconds


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
    
    def get_clips_shorter_than(self, seconds: float) -> List[Clip]:
        """Find clips shorter than threshold (flash frame detection)."""
        return [c for c in self.clips if c.duration_seconds < seconds]
    
    def get_clips_longer_than(self, seconds: float) -> List[Clip]:
        """Find clips longer than threshold."""
        return [c for c in self.clips if c.duration_seconds > seconds]


@dataclass
class Project:
    """Represents a Final Cut Pro project/library."""
    name: str
    timelines: List[Timeline] = field(default_factory=list)
    fcpxml_version: str = "1.11"
    
    @property
    def primary_timeline(self) -> Optional[Timeline]:
        return self.timelines[0] if self.timelines else None
