#!/usr/bin/env python3
"""
Final Cut Pro MCP Server - AI-powered editing through natural language.

The first MCP server for Final Cut Pro. Analyze timelines, add markers,
trim clips, reorder edits, and generate rough cuts - all via conversation.

Author: DareDev256 (https://github.com/DareDev256)
"""

import os
from pathlib import Path
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from fcpxml.parser import FCPXMLParser
from fcpxml.writer import FCPXMLModifier
from fcpxml.rough_cut import RoughCutGenerator, generate_rough_cut
from fcpxml.models import (
    MarkerType, SegmentSpec, FlashFrameSeverity, FlashFrame,
    GapInfo, DuplicateGroup, PacingCurve, MontageConfig
)

server = Server("fcp-mcp-server")
PROJECTS_DIR = os.environ.get("FCP_PROJECTS_DIR", os.path.expanduser("~/Movies"))


# ============================================================================
# UTILITIES
# ============================================================================

def find_fcpxml_files(directory: str) -> list[str]:
    """Find all FCPXML files in a directory."""
    path = Path(directory)
    files = list(str(f) for f in path.rglob("*.fcpxml"))
    files.extend(str(f) for f in path.rglob("*.fcpxmld"))
    return files


def format_timecode(tc) -> str:
    """Format a Timecode object to SMPTE string."""
    return tc.to_smpte() if tc else "00:00:00:00"


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    return f"{int(seconds // 60)}m {seconds % 60:.1f}s"


def generate_output_path(input_path: str, suffix: str = "_modified") -> str:
    """Generate output path from input path."""
    p = Path(input_path)
    return str(p.parent / f"{p.stem}{suffix}{p.suffix}")


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ===== READ TOOLS =====
        Tool(
            name="list_projects",
            description="List all FCPXML projects in directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to search (default: ~/Movies)"}
                }
            }
        ),
        Tool(
            name="analyze_timeline",
            description="Get comprehensive timeline statistics including duration, resolution, clip count, pacing metrics",
            inputSchema={
                "type": "object",
                "properties": {"filepath": {"type": "string", "description": "Path to FCPXML file"}},
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_clips",
            description="List all clips with timecodes, durations, and metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max clips to return"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_markers",
            description="Extract markers (chapter, todo, standard) with timestamps",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "marker_type": {"type": "string", "enum": ["all", "chapter", "todo", "standard"]},
                    "format": {"type": "string", "enum": ["detailed", "youtube", "simple"]}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="find_short_cuts",
            description="Find clips shorter than threshold (flash frame detection)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "threshold_seconds": {"type": "number", "default": 0.5}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="find_long_clips",
            description="Find clips longer than threshold",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "threshold_seconds": {"type": "number", "default": 10.0}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_keywords",
            description="Extract all keywords/tags from project",
            inputSchema={
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
                "required": ["filepath"]
            }
        ),
        Tool(
            name="export_edl",
            description="Generate EDL (Edit Decision List) from timeline",
            inputSchema={
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
                "required": ["filepath"]
            }
        ),
        Tool(
            name="export_csv",
            description="Export timeline data to CSV format",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "include": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="analyze_pacing",
            description="Analyze edit pacing with suggestions for improvements",
            inputSchema={
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_library_clips",
            description="List all available clips in the library (source media, not yet on timeline)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "Filter by keywords"},
                    "limit": {"type": "integer", "description": "Max clips to return"}
                },
                "required": ["filepath"]
            }
        ),

        # ===== SPEED CUTTING ANALYSIS TOOLS (v0.3.0) =====
        Tool(
            name="detect_flash_frames",
            description="Find ultra-short clips (flash frames) that are likely errors, with severity categorization",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "critical_threshold_frames": {"type": "integer", "default": 2, "description": "Frames below this = critical (default: 2)"},
                    "warning_threshold_frames": {"type": "integer", "default": 6, "description": "Frames below this = warning (default: 6)"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="detect_duplicates",
            description="Find clips using the same source media (potential duplicates)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "mode": {"type": "string", "enum": ["same_source", "overlapping_ranges", "identical"], "default": "same_source", "description": "Detection mode"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="detect_gaps",
            description="Find unintentional gaps in the timeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "min_gap_frames": {"type": "integer", "default": 1, "description": "Minimum gap size to detect (default: 1 frame)"}
                },
                "required": ["filepath"]
            }
        ),

        # ===== WRITE TOOLS =====
        Tool(
            name="add_marker",
            description="Add a marker at a specific timecode",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "timecode": {"type": "string", "description": "Position (00:00:10:00 or 10s)"},
                    "name": {"type": "string", "description": "Marker label"},
                    "marker_type": {"type": "string", "enum": ["standard", "chapter", "todo"], "default": "standard"},
                    "note": {"type": "string", "description": "Optional note"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath", "timecode", "name"]
            }
        ),
        Tool(
            name="batch_add_markers",
            description="Add multiple markers at once, or auto-generate at cuts/intervals",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "markers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "timecode": {"type": "string"},
                                "name": {"type": "string"},
                                "marker_type": {"type": "string"},
                                "note": {"type": "string"}
                            }
                        },
                        "description": "List of markers to add"
                    },
                    "auto_at_cuts": {"type": "boolean", "description": "Add marker at every cut"},
                    "auto_at_intervals": {"type": "string", "description": "Add markers every N seconds (e.g., '30s')"},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="trim_clip",
            description="Trim a clip's in-point and/or out-point",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "clip_id": {"type": "string", "description": "Clip name or ID"},
                    "trim_start": {"type": "string", "description": "New in-point or delta (+1s, -10f)"},
                    "trim_end": {"type": "string", "description": "New out-point or delta"},
                    "ripple": {"type": "boolean", "default": True, "description": "Shift subsequent clips"},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath", "clip_id"]
            }
        ),
        Tool(
            name="reorder_clips",
            description="Move clips to a new position in the timeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "clip_ids": {"type": "array", "items": {"type": "string"}, "description": "Clips to move"},
                    "target_position": {"type": "string", "description": "'start', 'end', timecode, or 'after:clip_id'"},
                    "ripple": {"type": "boolean", "default": True},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath", "clip_ids", "target_position"]
            }
        ),
        Tool(
            name="add_transition",
            description="Add a transition between clips",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "clip_id": {"type": "string", "description": "Clip to add transition to"},
                    "position": {"type": "string", "enum": ["start", "end", "both"], "default": "end"},
                    "transition_type": {"type": "string", "enum": ["cross-dissolve", "fade-to-black", "fade-from-black", "wipe"], "default": "cross-dissolve"},
                    "duration": {"type": "string", "default": "00:00:00:15"},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath", "clip_id"]
            }
        ),
        Tool(
            name="change_speed",
            description="Change clip playback speed (slow motion or speed up)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "clip_id": {"type": "string"},
                    "speed": {"type": "number", "description": "Speed multiplier (0.5 = half, 2.0 = double)"},
                    "preserve_pitch": {"type": "boolean", "default": True},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath", "clip_id", "speed"]
            }
        ),
        Tool(
            name="delete_clips",
            description="Delete clips from timeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "clip_ids": {"type": "array", "items": {"type": "string"}},
                    "ripple": {"type": "boolean", "default": True, "description": "Close gaps after deletion"},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath", "clip_ids"]
            }
        ),
        Tool(
            name="split_clip",
            description="Split a clip at specified timecodes",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "clip_id": {"type": "string"},
                    "split_points": {"type": "array", "items": {"type": "string"}, "description": "Timecodes to split at"},
                    "output_path": {"type": "string"}
                },
                "required": ["filepath", "clip_id", "split_points"]
            }
        ),
        Tool(
            name="insert_clip",
            description="Insert a library clip onto the timeline at a specific position",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "asset_id": {"type": "string", "description": "Asset reference ID (e.g., 'r3')"},
                    "asset_name": {"type": "string", "description": "Asset name (alternative to asset_id)"},
                    "position": {"type": "string", "description": "'start', 'end', timecode, or 'after:clip_name'"},
                    "duration": {"type": "string", "description": "Clip duration (if not using in/out points)"},
                    "in_point": {"type": "string", "description": "Source in-point for subclip"},
                    "out_point": {"type": "string", "description": "Source out-point for subclip"},
                    "ripple": {"type": "boolean", "default": True, "description": "Shift subsequent clips"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath", "position"]
            }
        ),

        # ===== SPEED CUTTING WRITE TOOLS (v0.3.0) =====
        Tool(
            name="fix_flash_frames",
            description="Automatically fix detected flash frames by extending neighbors or deleting",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "mode": {"type": "string", "enum": ["extend_previous", "extend_next", "delete", "auto"], "default": "auto", "description": "How to fix: extend previous/next clip, delete, or auto"},
                    "threshold_frames": {"type": "integer", "default": 6, "description": "Frames below this threshold are flash frames"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="rapid_trim",
            description="Batch trim clips to a maximum duration for fast-paced montages",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "max_duration": {"type": "string", "description": "Maximum clip duration (e.g., '2s', '00:00:02:00')"},
                    "min_duration": {"type": "string", "description": "Minimum clip duration (optional)"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "Only trim clips with these keywords"},
                    "trim_from": {"type": "string", "enum": ["start", "end", "center"], "default": "end", "description": "Where to trim from"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath", "max_duration"]
            }
        ),
        Tool(
            name="fill_gaps",
            description="Automatically fill gaps in the timeline by extending adjacent clips",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "mode": {"type": "string", "enum": ["extend_previous", "extend_next", "delete"], "default": "extend_previous", "description": "How to fill gaps"},
                    "max_gap": {"type": "string", "description": "Only fill gaps smaller than this (e.g., '1s')"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="validate_timeline",
            description="Comprehensive timeline health check for flash frames, gaps, duplicates, and issues",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "checks": {"type": "array", "items": {"type": "string", "enum": ["all", "flash_frames", "gaps", "duplicates", "offsets"]}, "default": ["all"], "description": "Which checks to run"}
                },
                "required": ["filepath"]
            }
        ),

        # ===== AI-POWERED TOOLS =====
        Tool(
            name="auto_rough_cut",
            description="Generate a rough cut from source clips based on keywords, duration, and pacing",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Source FCPXML with clips"},
                    "output_path": {"type": "string", "description": "Where to save rough cut"},
                    "target_duration": {"type": "string", "description": "Target length (3m, 00:03:00:00)"},
                    "pacing": {"type": "string", "enum": ["slow", "medium", "fast", "dynamic"], "default": "medium"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "Filter clips by keywords"},
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "keywords": {"type": "array", "items": {"type": "string"}},
                                "duration": {"type": "number"}
                            }
                        },
                        "description": "Segment structure [{name, keywords, duration_seconds}]"
                    },
                    "priority": {"type": "string", "enum": ["best", "favorites", "longest", "shortest", "random"], "default": "best"},
                    "favorites_only": {"type": "boolean", "default": False},
                    "add_transitions": {"type": "boolean", "default": False}
                },
                "required": ["filepath", "output_path", "target_duration"]
            }
        ),
        Tool(
            name="generate_montage",
            description="Create rapid-fire montages with pacing curves (accelerating, decelerating, pyramid)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Source FCPXML with clips"},
                    "output_path": {"type": "string", "description": "Where to save montage"},
                    "target_duration": {"type": "string", "description": "Total montage length (e.g., '30s', '00:00:30:00')"},
                    "pacing_curve": {"type": "string", "enum": ["accelerating", "decelerating", "pyramid", "constant"], "default": "accelerating", "description": "How clip duration changes over time"},
                    "start_duration": {"type": "number", "default": 2.0, "description": "Clip duration at start (seconds)"},
                    "end_duration": {"type": "number", "default": 0.5, "description": "Clip duration at end (seconds)"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "Filter clips by keywords"},
                    "add_transitions": {"type": "boolean", "default": False, "description": "Add quick dissolves"}
                },
                "required": ["filepath", "output_path", "target_duration"]
            }
        ),
        Tool(
            name="generate_ab_roll",
            description="Create documentary-style A/B roll edits alternating between main content and cutaways",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Source FCPXML with clips"},
                    "output_path": {"type": "string", "description": "Where to save A/B roll edit"},
                    "target_duration": {"type": "string", "description": "Total duration (e.g., '3m', '00:03:00:00')"},
                    "a_keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords for A-roll (main content, interviews)"},
                    "b_keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords for B-roll (cutaways, visuals)"},
                    "a_duration": {"type": "string", "default": "5s", "description": "Duration of each A-roll segment"},
                    "b_duration": {"type": "string", "default": "3s", "description": "Duration of each B-roll cutaway"},
                    "start_with": {"type": "string", "enum": ["a", "b"], "default": "a", "description": "Which roll to start with"},
                    "add_transitions": {"type": "boolean", "default": True, "description": "Add cross-dissolves"}
                },
                "required": ["filepath", "output_path", "target_duration", "a_keywords", "b_keywords"]
            }
        ),

        # ===== BEAT SYNC TOOLS (v0.3.0) =====
        Tool(
            name="import_beat_markers",
            description="Import beat markers from external audio analysis (JSON format)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "beats_path": {"type": "string", "description": "Path to beats JSON file"},
                    "marker_type": {"type": "string", "enum": ["standard", "chapter"], "default": "standard"},
                    "beat_filter": {"type": "string", "enum": ["all", "downbeat", "measure"], "default": "all", "description": "Which beats to import"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _beats suffix)"}
                },
                "required": ["filepath", "beats_path"]
            }
        ),
        Tool(
            name="snap_to_beats",
            description="Align cuts to nearest beat markers for music-synced edits",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file with beat markers"},
                    "max_shift_frames": {"type": "integer", "default": 6, "description": "Maximum frames to shift a cut"},
                    "prefer": {"type": "string", "enum": ["earlier", "later", "nearest"], "default": "nearest", "description": "Which beat to prefer when equidistant"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _synced suffix)"}
                },
                "required": ["filepath"]
            }
        ),
    ]


# ============================================================================
# TOOL HANDLERS
# ============================================================================

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    try:
        # ===== READ TOOLS =====
        if name == "list_projects":
            directory = arguments.get("directory", PROJECTS_DIR)
            files = find_fcpxml_files(directory)
            if not files:
                return [TextContent(type="text", text=f"No FCPXML files found in {directory}")]
            return [TextContent(type="text", text=f"Found {len(files)} FCPXML file(s):\n" + "\n".join(f"  • {f}" for f in files))]

        elif name == "analyze_timeline":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            durs = [c.duration_seconds for c in tl.clips]
            avg, med, mn, mx = (0, 0, 0, 0) if not durs else (
                sum(durs)/len(durs), sorted(durs)[len(durs)//2], min(durs), max(durs))
            result = f"""# Timeline Analysis: {tl.name}

## Overview
- **Duration**: {format_duration(tl.duration.seconds)}
- **Resolution**: {tl.width}x{tl.height} @ {tl.frame_rate}fps

## Clip Statistics
- **Total Clips**: {tl.total_clips}
- **Total Cuts**: {tl.total_cuts}
- **Transitions**: {len(tl.transitions)}

## Pacing
- **Average**: {format_duration(avg)}
- **Median**: {format_duration(med)}
- **Shortest**: {format_duration(mn)}
- **Longest**: {format_duration(mx)}
- **Cuts/Minute**: {tl.cuts_per_minute:.1f}

## Markers
- **Total**: {len(tl.markers)}
- **Chapters**: {len([m for m in tl.markers if m.marker_type == MarkerType.CHAPTER])}
"""
            return [TextContent(type="text", text=result)]

        elif name == "list_clips":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            limit = arguments.get("limit")
            clips = tl.clips[:limit] if limit else tl.clips
            result = f"# Clips in {tl.name}\n\n| # | Name | Start | Duration | Keywords |\n|---|------|-------|----------|----------|\n"
            for i, c in enumerate(clips, 1):
                kws = ", ".join(k.value for k in c.keywords) if c.keywords else "-"
                result += f"| {i} | {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} | {kws} |\n"
            return [TextContent(type="text", text=result)]

        elif name == "list_markers":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            markers = list(tl.markers)
            for clip in tl.clips:
                markers.extend(clip.markers)
            marker_type = arguments.get("marker_type", "all")
            if marker_type != "all":
                type_map = {"chapter": MarkerType.CHAPTER, "todo": MarkerType.TODO, "standard": MarkerType.STANDARD}
                markers = [m for m in markers if m.marker_type == type_map.get(marker_type)]
            markers.sort(key=lambda m: m.start.frames)
            fmt = arguments.get("format", "detailed")
            if fmt == "youtube":
                result = "# YouTube Chapters\n\n" + "\n".join(f"{m.to_youtube_timestamp()} {m.name}" for m in markers)
            elif fmt == "simple":
                result = "\n".join(f"{format_timecode(m.start)} - {m.name}" for m in markers)
            else:
                result = f"# Markers ({len(markers)})\n\n| TC | Name | Type |\n|---|------|------|\n"
                result += "\n".join(f"| {format_timecode(m.start)} | {m.name} | {m.marker_type.value} |" for m in markers)
            return [TextContent(type="text", text=result)]

        elif name == "find_short_cuts":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            threshold = arguments.get("threshold_seconds", 0.5)
            short = project.primary_timeline.get_clips_shorter_than(threshold)
            if not short:
                return [TextContent(type="text", text=f"No clips shorter than {threshold}s")]
            result = f"# Short Clips (< {threshold}s) - {len(short)} found\n\n| Name | TC | Duration |\n|------|----|---------|\n"
            result += "\n".join(f"| {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} |" for c in short)
            return [TextContent(type="text", text=result)]

        elif name == "find_long_clips":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            threshold = arguments.get("threshold_seconds", 10.0)
            long = project.primary_timeline.get_clips_longer_than(threshold)
            if not long:
                return [TextContent(type="text", text=f"No clips longer than {threshold}s")]
            result = f"# Long Clips (> {threshold}s) - {len(long)} found\n\n| Name | TC | Duration |\n|------|----|---------|\n"
            result += "\n".join(f"| {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} |" for c in long)
            return [TextContent(type="text", text=result)]

        elif name == "list_keywords":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            keywords = {}
            for clip in project.primary_timeline.clips:
                for kw in clip.keywords:
                    keywords.setdefault(kw.value, []).append(clip.name)
            if not keywords:
                return [TextContent(type="text", text="No keywords found")]
            result = f"# Keywords ({len(keywords)})\n\n"
            for kw, clips in sorted(keywords.items()):
                result += f"**{kw}** ({len(clips)} clips)\n"
            return [TextContent(type="text", text=result)]

        elif name == "export_edl":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            edl = f"TITLE: {tl.name}\nFCM: NON-DROP FRAME\n\n"
            for i, c in enumerate(tl.clips, 1):
                edl += f"{i:03d}  AX       V     C        {format_timecode(c.source_start)} {format_timecode(c.end)} {format_timecode(c.start)} {format_timecode(c.end)}\n"
                edl += f"* FROM CLIP NAME: {c.name}\n\n"
            return [TextContent(type="text", text=f"```edl\n{edl}```")]

        elif name == "export_csv":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            csv = "Name,Start,End,Duration,Keywords\n"
            for c in tl.clips:
                kws = "|".join(k.value for k in c.keywords)
                csv += f'"{c.name}",{format_timecode(c.start)},{format_timecode(c.end)},{c.duration_seconds:.3f},"{kws}"\n'
            return [TextContent(type="text", text=f"```csv\n{csv}```")]

        elif name == "analyze_pacing":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            if not tl.clips:
                return [TextContent(type="text", text="No clips to analyze")]
            durs = [c.duration_seconds for c in tl.clips]
            avg = sum(durs) / len(durs)
            q_len = len(durs) // 4 or 1
            segments = [durs[i:i+q_len] for i in range(0, len(durs), q_len)][:4]
            seg_avgs = [sum(s)/len(s) if s else 0 for s in segments]
            suggestions = []
            flash = [c for c in tl.clips if c.duration_seconds < 0.2]
            if flash:
                suggestions.append(f"⚠️ {len(flash)} potential flash frames (< 0.2s)")
            long = [c for c in tl.clips if c.duration_seconds > 30]
            if long:
                suggestions.append(f"📹 {len(long)} long takes (> 30s) - consider trimming")
            if len(seg_avgs) >= 4 and seg_avgs[3] < seg_avgs[0] * 0.7:
                suggestions.append("🎬 Pacing accelerates toward end - good for building energy")
            elif len(seg_avgs) >= 4 and seg_avgs[3] > seg_avgs[0] * 1.3:
                suggestions.append("⏱️ Pacing slows toward end - consider tightening")
            result = f"""# Pacing Analysis: {tl.name}

## Overall
- **Avg Cut**: {format_duration(avg)}
- **Cuts/Min**: {tl.cuts_per_minute:.1f}

## By Section
| Q1 | Q2 | Q3 | Q4 |
|----|----|----|----|
| {format_duration(seg_avgs[0]) if len(seg_avgs) > 0 else 'N/A'} | {format_duration(seg_avgs[1]) if len(seg_avgs) > 1 else 'N/A'} | {format_duration(seg_avgs[2]) if len(seg_avgs) > 2 else 'N/A'} | {format_duration(seg_avgs[3]) if len(seg_avgs) > 3 else 'N/A'} |

## Suggestions
{"".join(f"- {s}\n" for s in suggestions) if suggestions else "- ✅ Pacing looks good!"}
"""
            return [TextContent(type="text", text=result)]

        elif name == "list_library_clips":
            parser = FCPXMLParser()
            parser.parse_file(arguments["filepath"])
            keywords = arguments.get("keywords")
            library_clips = parser.get_library_clips(keywords=keywords)
            limit = arguments.get("limit")
            if limit:
                library_clips = library_clips[:limit]
            if not library_clips:
                return [TextContent(type="text", text="No library clips found")]
            result = f"# Library Clips ({len(library_clips)} available)\n\n"
            result += "| ID | Name | Duration | Has Video | Has Audio |\n"
            result += "|----|------|----------|-----------|----------|\n"
            for c in library_clips:
                result += f"| {c['asset_id']} | {c['name']} | {format_duration(c['duration_seconds'])} | {'✓' if c['has_video'] else '✗'} | {'✓' if c['has_audio'] else '✗'} |\n"
            result += "\n*Use `insert_clip` to add these to your timeline.*"
            return [TextContent(type="text", text=result)]

        # ===== SPEED CUTTING ANALYSIS TOOLS (v0.3.0) =====
        elif name == "detect_flash_frames":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            fps = tl.frame_rate

            critical_threshold = arguments.get("critical_threshold_frames", 2)
            warning_threshold = arguments.get("warning_threshold_frames", 6)

            flash_frames = []
            for clip in tl.clips:
                duration_frames = int(clip.duration_seconds * fps)
                if duration_frames < warning_threshold:
                    severity = FlashFrameSeverity.CRITICAL if duration_frames < critical_threshold else FlashFrameSeverity.WARNING
                    flash_frames.append(FlashFrame(
                        clip_name=clip.name,
                        clip_id=clip.name,  # Using name as ID for now
                        start=clip.start,
                        duration_frames=duration_frames,
                        duration_seconds=clip.duration_seconds,
                        severity=severity
                    ))

            if not flash_frames:
                return [TextContent(type="text", text=f"No flash frames detected (threshold: {warning_threshold} frames)")]

            critical = [f for f in flash_frames if f.severity == FlashFrameSeverity.CRITICAL]
            warnings = [f for f in flash_frames if f.severity == FlashFrameSeverity.WARNING]

            result = f"""# Flash Frame Detection

## Summary
- **Critical** (< {critical_threshold} frames): {len(critical)} found
- **Warning** (< {warning_threshold} frames): {len(warnings)} found
- **Total**: {len(flash_frames)} flash frames

## Critical Flash Frames
"""
            if critical:
                result += "| Clip | Timecode | Frames | Duration |\n|------|----------|--------|----------|\n"
                for f in critical:
                    result += f"| {f.clip_name} | {format_timecode(f.start)} | {f.duration_frames}f | {format_duration(f.duration_seconds)} |\n"
            else:
                result += "_None_\n"

            result += "\n## Warning Flash Frames\n"
            if warnings:
                result += "| Clip | Timecode | Frames | Duration |\n|------|----------|--------|----------|\n"
                for f in warnings:
                    result += f"| {f.clip_name} | {format_timecode(f.start)} | {f.duration_frames}f | {format_duration(f.duration_seconds)} |\n"
            else:
                result += "_None_\n"

            result += "\n*Use `fix_flash_frames` to automatically resolve these issues.*"
            return [TextContent(type="text", text=result)]

        elif name == "detect_duplicates":
            parser = FCPXMLParser()
            project = parser.parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            mode = arguments.get("mode", "same_source")

            # Group clips by their source reference
            # We need to access the raw XML to get ref attributes
            # For now, we'll use media_path as a proxy for source reference
            source_groups = {}
            for clip in tl.clips:
                # Use media_path as the grouping key (or name if no media_path)
                source_key = clip.media_path or clip.name
                if source_key not in source_groups:
                    source_groups[source_key] = []
                source_groups[source_key].append({
                    'name': clip.name,
                    'start': clip.start.seconds,
                    'duration': clip.duration_seconds,
                    'source_start': clip.source_start.seconds if clip.source_start else 0,
                    'source_duration': clip.duration_seconds,
                    'timecode': format_timecode(clip.start)
                })

            # Filter to only groups with duplicates
            duplicates = []
            for source_key, clips in source_groups.items():
                if len(clips) > 1:
                    group = DuplicateGroup(
                        source_ref=source_key,
                        source_name=source_key.split('/')[-1] if '/' in source_key else source_key,
                        clips=clips
                    )

                    # Filter by mode
                    if mode == "same_source":
                        duplicates.append(group)
                    elif mode == "overlapping_ranges" and group.has_overlapping_ranges:
                        duplicates.append(group)
                    elif mode == "identical":
                        # Check for clips with identical source ranges
                        seen_ranges = set()
                        identical_clips = []
                        for c in clips:
                            range_key = (c['source_start'], c['source_duration'])
                            if range_key in seen_ranges:
                                identical_clips.append(c)
                            seen_ranges.add(range_key)
                        if identical_clips:
                            group.clips = identical_clips
                            duplicates.append(group)

            if not duplicates:
                return [TextContent(type="text", text=f"No duplicate clips found (mode: {mode})")]

            result = f"""# Duplicate Clip Detection

## Summary
- **Mode**: {mode}
- **Duplicate Groups**: {len(duplicates)}
- **Total Duplicate Clips**: {sum(g.count for g in duplicates)}

## Duplicate Groups
"""
            for group in duplicates:
                result += f"\n### {group.source_name} ({group.count} uses)\n"
                result += "| Clip Name | Timeline Position | Duration |\n|-----------|-------------------|----------|\n"
                for c in group.clips:
                    result += f"| {c['name']} | {c['timecode']} | {format_duration(c['duration'])} |\n"

            return [TextContent(type="text", text=result)]

        elif name == "detect_gaps":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            fps = tl.frame_rate
            min_gap_frames = arguments.get("min_gap_frames", 1)
            min_gap_seconds = min_gap_frames / fps

            gaps = []
            sorted_clips = sorted(tl.clips, key=lambda c: c.start.seconds)

            for i in range(len(sorted_clips) - 1):
                current_end = sorted_clips[i].end.seconds
                next_start = sorted_clips[i + 1].start.seconds
                gap_duration = next_start - current_end

                if gap_duration >= min_gap_seconds:
                    from fcpxml.models import Timecode
                    gaps.append(GapInfo(
                        start=Timecode(frames=int(current_end * fps), frame_rate=fps),
                        duration_frames=int(gap_duration * fps),
                        duration_seconds=gap_duration,
                        previous_clip=sorted_clips[i].name,
                        next_clip=sorted_clips[i + 1].name
                    ))

            if not gaps:
                return [TextContent(type="text", text=f"No gaps detected (minimum: {min_gap_frames} frame(s))")]

            result = f"""# Gap Detection

## Summary
- **Gaps Found**: {len(gaps)}
- **Total Gap Duration**: {format_duration(sum(g.duration_seconds for g in gaps))}
- **Minimum Detection**: {min_gap_frames} frame(s)

## Gaps
| Position | Duration | Between |
|----------|----------|---------|
"""
            for gap in gaps:
                result += f"| {gap.timecode} | {gap.duration_frames}f ({format_duration(gap.duration_seconds)}) | {gap.previous_clip} → {gap.next_clip} |\n"

            result += "\n*Use `fill_gaps` to automatically close these gaps.*"
            return [TextContent(type="text", text=result)]

        # ===== WRITE TOOLS =====
        elif name == "add_marker":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            marker_type = MarkerType[arguments.get("marker_type", "standard").upper()]
            modifier.add_marker_at_timeline(
                timecode=arguments["timecode"],
                name=arguments["name"],
                marker_type=marker_type,
                note=arguments.get("note")
            )
            modifier.save(output_path)
            return [TextContent(type="text", text=f"✅ Added marker '{arguments['name']}' at {arguments['timecode']}\n\nSaved to: {output_path}")]

        elif name == "batch_add_markers":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            markers_added = modifier.batch_add_markers(
                markers=arguments.get("markers", []),
                auto_at_cuts=arguments.get("auto_at_cuts", False),
                auto_at_intervals=arguments.get("auto_at_intervals")
            )
            modifier.save(output_path)
            return [TextContent(type="text", text=f"✅ Added {len(markers_added)} markers\n\nSaved to: {output_path}")]

        elif name == "trim_clip":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            modifier.trim_clip(
                clip_id=arguments["clip_id"],
                trim_start=arguments.get("trim_start"),
                trim_end=arguments.get("trim_end"),
                ripple=arguments.get("ripple", True)
            )
            modifier.save(output_path)
            return [TextContent(type="text", text=f"✅ Trimmed clip '{arguments['clip_id']}'\n\nSaved to: {output_path}")]

        elif name == "reorder_clips":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            modifier.reorder_clips(
                clip_ids=arguments["clip_ids"],
                target_position=arguments["target_position"],
                ripple=arguments.get("ripple", True)
            )
            modifier.save(output_path)
            clips_moved = ", ".join(arguments["clip_ids"])
            return [TextContent(type="text", text=f"✅ Moved clips [{clips_moved}] to {arguments['target_position']}\n\nSaved to: {output_path}")]

        elif name == "add_transition":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            modifier.add_transition(
                clip_id=arguments["clip_id"],
                position=arguments.get("position", "end"),
                transition_type=arguments.get("transition_type", "cross-dissolve"),
                duration=arguments.get("duration", "00:00:00:15")
            )
            modifier.save(output_path)
            return [TextContent(type="text", text=f"✅ Added {arguments.get('transition_type', 'cross-dissolve')} to '{arguments['clip_id']}'\n\nSaved to: {output_path}")]

        elif name == "change_speed":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            modifier.change_speed(
                clip_id=arguments["clip_id"],
                speed=arguments["speed"],
                preserve_pitch=arguments.get("preserve_pitch", True)
            )
            modifier.save(output_path)
            speed = arguments["speed"]
            speed_desc = f"{speed}x" if speed >= 1 else f"{int(1/speed)}x slow motion"
            return [TextContent(type="text", text=f"✅ Changed speed of '{arguments['clip_id']}' to {speed_desc}\n\nSaved to: {output_path}")]

        elif name == "delete_clips":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            modifier.delete_clip(
                clip_ids=arguments["clip_ids"],
                ripple=arguments.get("ripple", True)
            )
            modifier.save(output_path)
            return [TextContent(type="text", text=f"✅ Deleted {len(arguments['clip_ids'])} clip(s)\n\nSaved to: {output_path}")]

        elif name == "split_clip":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            new_clips = modifier.split_clip(
                clip_id=arguments["clip_id"],
                split_points=arguments["split_points"]
            )
            modifier.save(output_path)
            return [TextContent(type="text", text=f"✅ Split '{arguments['clip_id']}' into {len(new_clips)} clips\n\nSaved to: {output_path}")]

        elif name == "insert_clip":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath)
            modifier = FCPXMLModifier(filepath)
            new_clip = modifier.insert_clip(
                asset_id=arguments.get("asset_id"),
                asset_name=arguments.get("asset_name"),
                position=arguments["position"],
                duration=arguments.get("duration"),
                in_point=arguments.get("in_point"),
                out_point=arguments.get("out_point"),
                ripple=arguments.get("ripple", True)
            )
            modifier.save(output_path)
            clip_name = new_clip.get('name', 'Unknown')
            pos = arguments["position"]
            return [TextContent(type="text", text=f"✅ Inserted '{clip_name}' at position '{pos}'\n\nSaved to: {output_path}")]

        # ===== SPEED CUTTING WRITE TOOLS (v0.3.0) =====
        elif name == "fix_flash_frames":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath, "_flash_fixed")
            modifier = FCPXMLModifier(filepath)
            fixed = modifier.fix_flash_frames(
                mode=arguments.get("mode", "auto"),
                threshold_frames=arguments.get("threshold_frames", 6)
            )
            modifier.save(output_path)

            if not fixed:
                return [TextContent(type="text", text="No flash frames found to fix.")]

            result = f"""# Flash Frames Fixed

## Summary
- **Fixed**: {len(fixed)} flash frames
- **Mode**: {arguments.get('mode', 'auto')}

## Details
| Clip | Frames | Action | Result |
|------|--------|--------|--------|
"""
            for f in fixed:
                extended = f.get('extended_clip', 'N/A')
                result += f"| {f['clip_name']} | {f['duration_frames']}f | {f['action']} | Extended: {extended} |\n"

            result += f"\nSaved to: `{output_path}`"
            return [TextContent(type="text", text=result)]

        elif name == "rapid_trim":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath, "_rapid_trim")
            modifier = FCPXMLModifier(filepath)
            trimmed = modifier.rapid_trim(
                max_duration=arguments["max_duration"],
                min_duration=arguments.get("min_duration"),
                keywords=arguments.get("keywords"),
                trim_from=arguments.get("trim_from", "end")
            )
            modifier.save(output_path)

            if not trimmed:
                return [TextContent(type="text", text=f"No clips exceeded {arguments['max_duration']} - nothing trimmed.")]

            total_before = sum(t['original_duration'] for t in trimmed)
            total_after = sum(t['new_duration'] for t in trimmed)

            result = f"""# Rapid Trim Complete

## Summary
- **Clips Trimmed**: {len(trimmed)}
- **Max Duration**: {arguments['max_duration']}
- **Trim From**: {arguments.get('trim_from', 'end')}
- **Time Saved**: {format_duration(total_before - total_after)}

## Trimmed Clips
| Clip | Before | After |
|------|--------|-------|
"""
            for t in trimmed:
                result += f"| {t['clip_name']} | {format_duration(t['original_duration'])} | {format_duration(t['new_duration'])} |\n"

            result += f"\nSaved to: `{output_path}`"
            return [TextContent(type="text", text=result)]

        elif name == "fill_gaps":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath, "_gaps_filled")
            modifier = FCPXMLModifier(filepath)
            filled = modifier.fill_gaps(
                mode=arguments.get("mode", "extend_previous"),
                max_gap=arguments.get("max_gap")
            )
            modifier.save(output_path)

            if not filled:
                return [TextContent(type="text", text="No gaps found to fill.")]

            result = f"""# Gaps Filled

## Summary
- **Gaps Filled**: {len(filled)}
- **Mode**: {arguments.get('mode', 'extend_previous')}

## Details
| Position | Duration | Action |
|----------|----------|--------|
"""
            for g in filled:
                result += f"| {g['timecode']} | {g['duration_frames']}f | {g['action']} |\n"

            result += f"\nSaved to: `{output_path}`"
            return [TextContent(type="text", text=result)]

        elif name == "validate_timeline":
            project = FCPXMLParser().parse_file(arguments["filepath"])
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]
            tl = project.primary_timeline
            fps = tl.frame_rate
            checks = arguments.get("checks", ["all"])
            run_all = "all" in checks

            issues = []
            flash_count = 0
            gap_count = 0
            duplicate_count = 0

            # Flash frame check
            if run_all or "flash_frames" in checks:
                for clip in tl.clips:
                    duration_frames = int(clip.duration_seconds * fps)
                    if duration_frames < 6:
                        flash_count += 1
                        severity = "error" if duration_frames < 2 else "warning"
                        issues.append(f"- [{severity.upper()}] Flash frame: {clip.name} ({duration_frames}f) at {format_timecode(clip.start)}")

            # Gap check
            if run_all or "gaps" in checks:
                sorted_clips = sorted(tl.clips, key=lambda c: c.start.seconds)
                for i in range(len(sorted_clips) - 1):
                    current_end = sorted_clips[i].end.seconds
                    next_start = sorted_clips[i + 1].start.seconds
                    gap_duration = next_start - current_end
                    if gap_duration > 0.001:  # More than 1ms
                        gap_count += 1
                        gap_frames = int(gap_duration * fps)
                        from fcpxml.models import Timecode
                        gap_tc = Timecode(frames=int(current_end * fps), frame_rate=fps)
                        issues.append(f"- [WARNING] Gap: {gap_frames}f at {gap_tc.to_smpte()}")

            # Duplicate check
            if run_all or "duplicates" in checks:
                source_groups = {}
                for clip in tl.clips:
                    source_key = clip.media_path or clip.name
                    if source_key not in source_groups:
                        source_groups[source_key] = []
                    source_groups[source_key].append(clip)
                for source, clips in source_groups.items():
                    if len(clips) > 1:
                        duplicate_count += len(clips)
                        issues.append(f"- [INFO] Duplicate source: {source.split('/')[-1]} ({len(clips)} uses)")

            # Calculate health score
            error_weight = 10
            warning_weight = 3
            info_weight = 1
            errors = len([i for i in issues if "[ERROR]" in i])
            warnings = len([i for i in issues if "[WARNING]" in i])
            infos = len([i for i in issues if "[INFO]" in i])
            penalty = (errors * error_weight) + (warnings * warning_weight) + (infos * info_weight)
            health_score = max(0, 100 - penalty)

            result = f"""# Timeline Validation: {tl.name}

## Health Score: {health_score}%

## Summary
| Check | Count | Status |
|-------|-------|--------|
| Flash Frames | {flash_count} | {'✅' if flash_count == 0 else '⚠️'} |
| Gaps | {gap_count} | {'✅' if gap_count == 0 else '⚠️'} |
| Duplicate Sources | {duplicate_count} | {'✅' if duplicate_count == 0 else 'ℹ️'} |

## Issues ({len(issues)})
"""
            if issues:
                result += "\n".join(issues[:20])  # Limit to first 20
                if len(issues) > 20:
                    result += f"\n... and {len(issues) - 20} more issues"
            else:
                result += "_No issues found!_"

            result += "\n\n*Use `fix_flash_frames` and `fill_gaps` to automatically resolve issues.*"
            return [TextContent(type="text", text=result)]

        # ===== AI-POWERED TOOLS =====
        elif name == "auto_rough_cut":
            filepath = arguments["filepath"]
            output_path = arguments["output_path"]

            # Handle segments if provided
            segments = None
            if arguments.get("segments"):
                segments = [
                    SegmentSpec(
                        name=s.get("name", "Segment"),
                        keywords=s.get("keywords", []),
                        duration_seconds=s.get("duration", 0),
                        priority=s.get("priority", "best")
                    )
                    for s in arguments["segments"]
                ]

            generator = RoughCutGenerator(filepath)
            result = generator.generate(
                output_path=output_path,
                target_duration=arguments["target_duration"],
                pacing=arguments.get("pacing", "medium"),
                keywords=arguments.get("keywords"),
                segments=segments,
                priority=arguments.get("priority", "best"),
                favorites_only=arguments.get("favorites_only", False),
                add_transitions=arguments.get("add_transitions", False)
            )

            return [TextContent(type="text", text=f"""# Rough Cut Generated! 🎬

## Summary
- **Clips Used**: {result.clips_used} of {result.clips_available} available
- **Target Duration**: {format_duration(result.target_duration)}
- **Actual Duration**: {format_duration(result.actual_duration)}
- **Average Clip**: {format_duration(result.average_clip_duration)}

## Output
Saved to: `{result.output_path}`

**Next step**: Import this FCPXML into Final Cut Pro (File → Import → XML)
""")]

        elif name == "generate_montage":
            filepath = arguments["filepath"]
            output_path = arguments["output_path"]

            generator = RoughCutGenerator(filepath)
            result = generator.generate_montage(
                output_path=output_path,
                target_duration=arguments["target_duration"],
                pacing_curve=arguments.get("pacing_curve", "accelerating"),
                start_duration=arguments.get("start_duration", 2.0),
                end_duration=arguments.get("end_duration", 0.5),
                keywords=arguments.get("keywords"),
                add_transitions=arguments.get("add_transitions", False)
            )

            curve_desc = {
                'accelerating': 'slow → fast (builds energy)',
                'decelerating': 'fast → slow (winds down)',
                'pyramid': 'slow → fast → slow (dramatic arc)',
                'constant': 'same duration throughout'
            }

            return [TextContent(type="text", text=f"""# Montage Generated! 🎬

## Summary
- **Clips Used**: {result['clips_used']} of {result['clips_available']} available
- **Target Duration**: {format_duration(result['target_duration'])}
- **Actual Duration**: {format_duration(result['actual_duration'])}
- **Pacing Curve**: {result['pacing_curve']} - {curve_desc.get(result['pacing_curve'], '')}

## Pacing
- **Start Clip Duration**: {format_duration(result['start_clip_duration'])}
- **End Clip Duration**: {format_duration(result['end_clip_duration'])}

## Output
Saved to: `{result['output_path']}`
""")]

        elif name == "generate_ab_roll":
            filepath = arguments["filepath"]
            output_path = arguments["output_path"]

            generator = RoughCutGenerator(filepath)
            result = generator.generate_ab_roll(
                output_path=output_path,
                target_duration=arguments["target_duration"],
                a_keywords=arguments["a_keywords"],
                b_keywords=arguments["b_keywords"],
                a_duration=arguments.get("a_duration", "5s"),
                b_duration=arguments.get("b_duration", "3s"),
                start_with=arguments.get("start_with", "a"),
                add_transitions=arguments.get("add_transitions", True)
            )

            return [TextContent(type="text", text=f"""# A/B Roll Edit Generated! 🎬

## Summary
- **A-Roll Segments**: {result['a_segments']} (from {result['a_clips_available']} available)
- **B-Roll Segments**: {result['b_segments']} (from {result['b_clips_available']} available)
- **Total Clips**: {result['clips_used']}

## Timing
- **Target Duration**: {format_duration(result['target_duration'])}
- **Actual Duration**: {format_duration(result['actual_duration'])}
- **A-Roll Duration**: {result['a_duration_setting']} per segment
- **B-Roll Duration**: {result['b_duration_setting']} per cutaway

## Output
Saved to: `{result['output_path']}`

**Next step**: Import this FCPXML into Final Cut Pro (File → Import → XML)
""")]

        # ===== BEAT SYNC TOOLS (v0.3.0) =====
        elif name == "import_beat_markers":
            import json
            filepath = arguments["filepath"]
            beats_path = arguments["beats_path"]
            output_path = arguments.get("output_path") or generate_output_path(filepath, "_beats")

            # Load beats JSON
            with open(beats_path, 'r') as f:
                beats_data = json.load(f)

            # Extract beat times (support various formats)
            beat_times = []
            if isinstance(beats_data, list):
                # Simple list of times
                beat_times = beats_data
            elif isinstance(beats_data, dict):
                # Common formats: {"beats": [...]} or {"times": [...]}
                beat_times = beats_data.get('beats', beats_data.get('times', beats_data.get('markers', [])))

            # Filter beats if requested
            beat_filter = arguments.get("beat_filter", "all")
            if beat_filter == "downbeat" and isinstance(beats_data, dict):
                # Use downbeats if available
                beat_times = beats_data.get('downbeats', beat_times[::4])  # Every 4th beat
            elif beat_filter == "measure" and isinstance(beats_data, dict):
                beat_times = beats_data.get('measures', beat_times[::4])

            # Convert to marker format
            markers = []
            marker_type = arguments.get("marker_type", "standard")
            for i, beat_time in enumerate(beat_times):
                if isinstance(beat_time, (int, float)):
                    markers.append({
                        'timecode': f"{beat_time}s",
                        'name': f"Beat {i+1}",
                        'marker_type': marker_type.upper()
                    })
                elif isinstance(beat_time, dict):
                    markers.append({
                        'timecode': f"{beat_time.get('time', beat_time.get('position', 0))}s",
                        'name': beat_time.get('label', f"Beat {i+1}"),
                        'marker_type': marker_type.upper()
                    })

            # Add markers to timeline
            modifier = FCPXMLModifier(filepath)
            added = modifier.batch_add_markers(markers=markers)
            modifier.save(output_path)

            return [TextContent(type="text", text=f"""# Beat Markers Imported

## Summary
- **Beats Found**: {len(beat_times)}
- **Markers Added**: {len(added)}
- **Filter**: {beat_filter}
- **Marker Type**: {marker_type}

## Output
Saved to: `{output_path}`

*Use `snap_to_beats` to align your cuts to these markers.*
""")]

        elif name == "snap_to_beats":
            filepath = arguments["filepath"]
            output_path = arguments.get("output_path") or generate_output_path(filepath, "_synced")
            max_shift = arguments.get("max_shift_frames", 6)
            prefer = arguments.get("prefer", "nearest")

            # Parse timeline to get markers and clips
            parser = FCPXMLParser()
            project = parser.parse_file(filepath)
            if not project.timelines:
                return [TextContent(type="text", text="No timelines found")]

            tl = project.primary_timeline
            fps = tl.frame_rate

            # Collect all markers (timeline + clip markers)
            markers = list(tl.markers)
            for clip in tl.clips:
                # Add clip's markers with adjusted timecodes
                for m in clip.markers:
                    markers.append(m)

            if not markers:
                return [TextContent(type="text", text="No markers found. Use `import_beat_markers` first.")]

            marker_times = sorted([m.start.seconds for m in markers])

            # Load modifier for editing
            modifier = FCPXMLModifier(filepath)
            spine = modifier._get_spine()
            adjusted_count = 0
            total_shift = 0

            # Get cuts (clip start offsets after the first clip)
            clips_list = [c for c in spine if c.tag in ('clip', 'asset-clip', 'video', 'ref-clip')]

            for i, clip in enumerate(clips_list[1:], 1):  # Skip first clip
                cut_offset = modifier._parse_time(clip.get('offset', '0s'))
                cut_seconds = cut_offset.to_seconds()

                # Find nearest marker
                best_marker = None
                best_distance = float('inf')

                for marker_time in marker_times:
                    distance = abs(marker_time - cut_seconds)
                    distance_frames = distance * fps

                    if distance_frames <= max_shift:
                        if prefer == "earlier" and marker_time <= cut_seconds:
                            if distance < best_distance:
                                best_distance = distance
                                best_marker = marker_time
                        elif prefer == "later" and marker_time >= cut_seconds:
                            if distance < best_distance:
                                best_distance = distance
                                best_marker = marker_time
                        elif prefer == "nearest":
                            if distance < best_distance:
                                best_distance = distance
                                best_marker = marker_time

                if best_marker is not None and best_distance > 0.001:
                    # Adjust this clip and ripple
                    shift = best_marker - cut_seconds
                    shift_frames = int(shift * fps)

                    # Adjust previous clip duration
                    prev_clip = clips_list[i - 1]
                    prev_dur = modifier._parse_time(prev_clip.get('duration', '0s'))
                    new_prev_dur = prev_dur + modifier._parse_time(f"{shift}s")
                    prev_clip.set('duration', new_prev_dur.to_fcpxml())

                    # Adjust current clip offset
                    new_offset = modifier._parse_time(f"{best_marker}s")
                    clip.set('offset', new_offset.to_fcpxml())

                    adjusted_count += 1
                    total_shift += abs(shift_frames)

            modifier.save(output_path)

            avg_shift = total_shift / adjusted_count if adjusted_count > 0 else 0

            return [TextContent(type="text", text=f"""# Cuts Snapped to Beats

## Summary
- **Cuts Adjusted**: {adjusted_count}
- **Max Shift Allowed**: {max_shift} frames
- **Preference**: {prefer}
- **Average Shift**: {avg_shift:.1f} frames

## Output
Saved to: `{output_path}`

Your edits are now synced to the beat!
""")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ============================================================================
# MAIN
# ============================================================================

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
