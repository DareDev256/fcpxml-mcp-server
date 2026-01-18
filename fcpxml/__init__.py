"""
FCPXML - Python library for Final Cut Pro XML processing.
"""

from .models import (
    Project,
    Timeline,
    Clip,
    VideoClip,
    AudioClip,
    Marker,
    MarkerType,
    Keyword,
    Timecode,
    Transition,
)
from .parser import FCPXMLParser, parse_fcpxml

__all__ = [
    "Project",
    "Timeline", 
    "Clip",
    "VideoClip",
    "AudioClip",
    "Marker",
    "MarkerType",
    "Keyword",
    "Timecode",
    "Transition",
    "FCPXMLParser",
    "parse_fcpxml",
]
