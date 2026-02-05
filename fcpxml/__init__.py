"""
FCPXML - Python library for reading, writing, and modifying Final Cut Pro XML files.

This package provides tools to:
- Parse FCPXML files into Python objects
- Modify existing FCPXML files (add markers, trim clips, reorder, etc.)
- Generate new FCPXML files from scratch
- Create AI-powered rough cuts from source material
"""

from .models import (
    # Enums
    MarkerType,
    MarkerColor,
    TransitionType,
    PacingStyle,

    # Time handling
    TimeValue,
    Timecode,

    # Core models
    Keyword,
    Marker,
    Clip,
    AudioClip,
    VideoClip,
    Transition,
    Timeline,
    Project,

    # Rough cut models
    SegmentSpec,
    PacingConfig,
    RoughCutResult,
)

from .parser import FCPXMLParser, parse_fcpxml

from .writer import (
    FCPXMLWriter,
    FCPXMLModifier,
    modify_fcpxml,
    add_marker_to_file,
    trim_clip_in_file,
)

from .rough_cut import (
    RoughCutGenerator,
    generate_rough_cut,
    generate_segmented_rough_cut,
)

__version__ = "0.4.0"
__author__ = "DareDev256"

__all__ = [
    # Version
    "__version__",

    # Enums
    "MarkerType",
    "MarkerColor",
    "TransitionType",
    "PacingStyle",

    # Time
    "TimeValue",
    "Timecode",

    # Models
    "Keyword",
    "Marker",
    "Clip",
    "AudioClip",
    "VideoClip",
    "Transition",
    "Timeline",
    "Project",
    "SegmentSpec",
    "PacingConfig",
    "RoughCutResult",

    # Parser
    "FCPXMLParser",
    "parse_fcpxml",

    # Writer
    "FCPXMLWriter",
    "FCPXMLModifier",
    "modify_fcpxml",
    "add_marker_to_file",
    "trim_clip_in_file",

    # Rough Cut
    "RoughCutGenerator",
    "generate_rough_cut",
    "generate_segmented_rough_cut",
]
