"""
FCPXML - Python library for reading, writing, and modifying Final Cut Pro XML files.

This package provides tools to:
- Parse FCPXML files into Python objects
- Modify existing FCPXML files (add markers, trim clips, reorder, etc.)
- Generate new FCPXML files from scratch
- Create AI-powered rough cuts from source material
- Compare timelines and export to other NLE formats
"""

from .diff import ClipDiff, MarkerDiff, TimelineDiff, compare_timelines
from .export import DaVinciExporter
from .models import (
    AudioClip,
    Clip,
    CompoundClip,
    ConnectedClip,
    # Core models
    Keyword,
    Marker,
    MarkerColor,
    # Enums
    MarkerType,
    PacingConfig,
    PacingStyle,
    Project,
    RoughCutResult,
    # Rough cut models
    SegmentSpec,
    SilenceCandidate,
    Timecode,
    Timeline,
    # Time handling
    TimeValue,
    Transition,
    TransitionType,
    VideoClip,
)
from .parser import FCPXMLParser, parse_fcpxml
from .rough_cut import (
    RoughCutGenerator,
    generate_rough_cut,
    generate_segmented_rough_cut,
)
from .writer import (
    FCPXMLModifier,
    FCPXMLWriter,
    add_marker_to_file,
    modify_fcpxml,
    trim_clip_in_file,
    write_fcpxml,
)

__version__ = "0.5.0"
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
    "ConnectedClip",
    "CompoundClip",
    "SilenceCandidate",
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
    "write_fcpxml",

    # Rough Cut
    "RoughCutGenerator",
    "generate_rough_cut",
    "generate_segmented_rough_cut",

    # Diff
    "compare_timelines",
    "TimelineDiff",
    "ClipDiff",
    "MarkerDiff",

    # Export
    "DaVinciExporter",
]
