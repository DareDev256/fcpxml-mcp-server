#!/usr/bin/env python3
"""
FCPXML MCP Server — Batch operations and analysis for Final Cut Pro XML files.

Provides 47 tools, MCP resources for file discovery, and pre-built prompt
workflows for common editing tasks.

Author: DareDev256 (https://github.com/DareDev256)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
)

from fcpxml.diff import compare_timelines
from fcpxml.export import DaVinciExporter
from fcpxml.models import (
    DuplicateGroup,
    FlashFrame,
    FlashFrameSeverity,
    GapInfo,
    MarkerType,
    SegmentSpec,
    Timecode,
)
from fcpxml.parser import FCPXMLParser
from fcpxml.rough_cut import RoughCutGenerator
from fcpxml.writer import FCPXMLModifier

server = Server("fcp-mcp-server")
PROJECTS_DIR = os.environ.get("FCP_PROJECTS_DIR", os.path.expanduser("~/Movies"))

# Maximum file size for parsing (100 MB).
MAX_FILE_SIZE = 100 * 1024 * 1024


# ============================================================================
# SECURITY UTILITIES
# ============================================================================

def _validate_filepath(filepath: str, allowed_extensions: tuple[str, ...] | None = None) -> str:
    """Validate a user-provided file path against traversal and size attacks.

    Resolves symlinks, blocks null bytes, enforces extension whitelist, and
    checks file size before any parsing takes place.

    Raises:
        ValueError: For invalid paths (null bytes, bad extensions, oversized).
        FileNotFoundError: When the resolved path does not exist.
    """
    if '\x00' in filepath:
        raise ValueError("Invalid file path: null byte detected")

    resolved = Path(filepath).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if not resolved.is_file():
        raise ValueError(f"Not a regular file: {filepath}")

    if allowed_extensions and resolved.suffix.lower() not in allowed_extensions:
        raise ValueError(
            f"Invalid file type '{resolved.suffix}'. "
            f"Allowed: {', '.join(allowed_extensions)}"
        )

    if resolved.stat().st_size > MAX_FILE_SIZE:
        size_mb = resolved.stat().st_size / (1024 * 1024)
        raise ValueError(f"File too large ({size_mb:.1f} MB). Maximum: {MAX_FILE_SIZE // (1024 * 1024)} MB")

    return str(resolved)


def _validate_output_path(output_path: str) -> str:
    """Validate an output path: resolve traversal, block null bytes, ensure parent exists."""
    if '\x00' in output_path:
        raise ValueError("Invalid output path: null byte detected")

    resolved = Path(output_path).resolve()

    if not resolved.parent.exists():
        raise ValueError(f"Output directory does not exist: {resolved.parent}")

    return str(resolved)


def _validate_directory(directory: str) -> str:
    """Validate a user-provided directory path against traversal and injection.

    Resolves symlinks, blocks null bytes, and verifies the path is a real
    directory. Used by handlers that accept directory arguments (e.g.,
    list_projects) to prevent filesystem enumeration attacks.

    Raises:
        ValueError: For invalid paths (null bytes, not a directory).
    """
    if '\x00' in directory:
        raise ValueError("Invalid directory path: null byte detected")

    resolved = Path(directory).resolve()

    if not resolved.is_dir():
        raise ValueError(f"Not a valid directory: {directory}")

    return str(resolved)


# ============================================================================
# UTILITIES
# ============================================================================

def find_fcpxml_files(directory: str) -> list[str]:
    """Find all FCPXML files in a directory."""
    path = Path(directory)
    files = list(str(f) for f in path.rglob("*.fcpxml"))
    files.extend(str(f) for f in path.rglob("*.fcpxmld"))
    return sorted(files)


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


def _fmt_suggestions(suggestions: list[str]) -> str:
    """Format pacing suggestions as markdown list (Python 3.10 compatible)."""
    if not suggestions:
        return "- Pacing looks good!"
    nl = "\n"
    return nl.join(f"- {s}" for s in suggestions)


def generate_output_path(input_path: str, suffix: str = "_modified") -> str:
    """Generate output path from input path."""
    p = Path(input_path)
    return str(p.parent / f"{p.stem}{suffix}{p.suffix}")


def _parse_project(filepath: str):
    """Parse an FCPXML file and return the project with its primary timeline."""
    filepath = _validate_filepath(filepath, ('.fcpxml', '.fcpxmld'))
    project = FCPXMLParser().parse_file(filepath)
    if not project.timelines:
        return None, None
    return project, project.primary_timeline


def _no_timeline():
    """Standard response when no timelines are found."""
    return [TextContent(type="text", text="No timelines found")]


def parse_srt(text: str) -> list[dict]:
    """Parse SRT subtitle format into timestamp/text pairs."""
    markers = []
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
        # Find the timestamp line (contains -->)
        ts_line = None
        text_lines = []
        for line in lines:
            if '-->' in line:
                ts_line = line
            elif ts_line is not None:
                text_lines.append(line)
        if not ts_line:
            continue
        # Parse start time: "00:01:30,500 --> 00:01:35,000"
        start_str = ts_line.split('-->')[0].strip()
        start_str = start_str.replace(',', '.')  # SRT uses comma for ms
        parts = start_str.split(':')
        if len(parts) == 3:
            h, m = int(parts[0]), int(parts[1])
            s = float(parts[2])
            total_seconds = h * 3600 + m * 60 + s
            markers.append({
                'seconds': total_seconds,
                'text': ' '.join(text_lines).strip(),
            })
    return markers


def parse_vtt(text: str) -> list[dict]:
    """Parse WebVTT subtitle format into timestamp/text pairs."""
    markers = []
    # Strip WEBVTT header
    text = re.sub(r'^WEBVTT.*?\n', '', text, flags=re.MULTILINE)
    # Remove NOTE blocks
    text = re.sub(r'NOTE\n.*?\n\n', '', text, flags=re.DOTALL)
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        ts_line = None
        text_lines = []
        for line in lines:
            if '-->' in line:
                ts_line = line
            elif ts_line is not None:
                # Strip VTT formatting tags
                clean = re.sub(r'<[^>]+>', '', line)
                if clean.strip():
                    text_lines.append(clean.strip())
        if not ts_line or not text_lines:
            continue
        start_str = ts_line.split('-->')[0].strip()
        start_str = start_str.replace(',', '.')
        parts = start_str.split(':')
        if len(parts) == 3:
            h, m = int(parts[0]), int(parts[1])
            s = float(parts[2])
            total_seconds = h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m = int(parts[0])
            s = float(parts[1])
            total_seconds = m * 60 + s
        else:
            continue
        markers.append({
            'seconds': total_seconds,
            'text': ' '.join(text_lines).strip(),
        })
    return markers


def parse_transcript_timestamps(text: str) -> list[dict]:
    """Parse timestamped text (YouTube description format) into markers.

    Supports formats like:
      0:00 Introduction
      00:01:30 Main Topic
      1:05:30 Conclusion
      00:00:00:00 SMPTE timecode
    """
    markers = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        # Match timestamp at start of line
        match = re.match(
            r'^(\d{1,2}:\d{2}(?::\d{2}){0,2})\s+(.+)$', line
        )
        if match:
            ts_str = match.group(1)
            label = match.group(2).strip()
            parts = ts_str.split(':')
            if len(parts) == 2:
                m, s = int(parts[0]), int(parts[1])
                total_seconds = m * 60 + s
            elif len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                total_seconds = h * 3600 + m * 60 + s
            elif len(parts) == 4:
                # SMPTE: HH:MM:SS:FF — ignore frames for marker placement
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                total_seconds = h * 3600 + m * 60 + s
            else:
                continue
            markers.append({
                'seconds': total_seconds,
                'text': label,
            })
    return markers


# ============================================================================
# MCP RESOURCES — File discovery
# ============================================================================

@server.list_resources()
async def list_resources() -> list[Resource]:
    """Expose discovered FCPXML files as MCP resources."""
    files = find_fcpxml_files(PROJECTS_DIR)
    resources = []
    for f in files:
        p = Path(f)
        resources.append(Resource(
            uri=f"file://{f}",
            name=p.stem,
            description=f"FCPXML project: {p.name} ({format_duration(0)})",
            mimeType="application/xml",
        ))
    return resources


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read an FCPXML file and return a summary."""
    filepath = str(uri).replace("file://", "")
    try:
        filepath = _validate_filepath(filepath, ('.fcpxml', '.fcpxmld'))
    except (ValueError, FileNotFoundError) as e:
        return str(e)

    project, tl = _parse_project(filepath)
    if not tl:
        return f"No timelines found in {filepath}"

    return f"""FCPXML Project: {tl.name}
Duration: {format_duration(tl.duration.seconds)}
Resolution: {tl.width}x{tl.height} @ {tl.frame_rate}fps
Clips: {tl.total_clips}
Markers: {len(tl.markers)}
Cuts/min: {tl.cuts_per_minute:.1f}
Path: {filepath}"""


# ============================================================================
# MCP PROMPTS — Pre-built workflows
# ============================================================================

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="qc-check",
            description="Run a full quality control check on your timeline — flash frames, gaps, duplicates, and health score",
            arguments=[
                PromptArgument(name="filepath", description="Path to FCPXML file", required=True),
            ],
        ),
        Prompt(
            name="youtube-chapters",
            description="Extract chapter markers formatted for YouTube descriptions",
            arguments=[
                PromptArgument(name="filepath", description="Path to FCPXML file", required=True),
            ],
        ),
        Prompt(
            name="rough-cut",
            description="Guided rough cut generation — choose keywords, pacing, and duration",
            arguments=[
                PromptArgument(name="filepath", description="Path to source FCPXML with clips", required=True),
                PromptArgument(name="duration", description="Target duration (e.g., '3m', '90s')", required=True),
            ],
        ),
        Prompt(
            name="timeline-summary",
            description="Quick overview of a timeline — stats, pacing, and potential issues",
            arguments=[
                PromptArgument(name="filepath", description="Path to FCPXML file", required=True),
            ],
        ),
        Prompt(
            name="cleanup",
            description="Find and fix common timeline issues — flash frames, gaps, and duplicates",
            arguments=[
                PromptArgument(name="filepath", description="Path to FCPXML file", required=True),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    args = arguments or {}
    filepath = args.get("filepath", "<path to your .fcpxml file>")

    if name == "qc-check":
        return GetPromptResult(
            description="Full QC check on timeline",
            messages=[PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Run a complete quality control check on my timeline.

File: {filepath}

Please:
1. Use `validate_timeline` to get the health score
2. Use `detect_flash_frames` to find any ultra-short clips
3. Use `detect_gaps` to find unintentional gaps
4. Use `detect_duplicates` to find repeated source clips
5. Summarize all issues and recommend fixes

If there are critical issues, offer to fix them automatically with `fix_flash_frames` and `fill_gaps`."""
                ),
            )],
        )

    elif name == "youtube-chapters":
        return GetPromptResult(
            description="Export YouTube chapter markers",
            messages=[PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Extract chapter markers from my timeline and format them for YouTube.

File: {filepath}

Please:
1. Use `list_markers` with format "youtube" to get chapter timestamps
2. Format the output so I can copy-paste directly into a YouTube description
3. If there are no chapter markers, suggest good chapter points based on the timeline structure using `analyze_pacing`"""
                ),
            )],
        )

    elif name == "rough-cut":
        duration = args.get("duration", "3m")
        return GetPromptResult(
            description="Guided rough cut generation",
            messages=[PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Help me create a rough cut from my source clips.

File: {filepath}
Target duration: {duration}

Please:
1. Use `list_library_clips` to show me what clips are available
2. Use `list_keywords` to show me the tags I can filter by
3. Suggest a structure (segments, pacing) based on what's available
4. Generate the rough cut with `auto_rough_cut` using my preferences
5. Show me a summary of what was created"""
                ),
            )],
        )

    elif name == "timeline-summary":
        return GetPromptResult(
            description="Quick timeline overview",
            messages=[PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Give me a quick overview of my timeline.

File: {filepath}

Please:
1. Use `analyze_timeline` for stats (duration, resolution, clip count)
2. Use `analyze_pacing` for pacing metrics and suggestions
3. Use `list_keywords` to show what tags are in use
4. Use `list_markers` to show any markers
5. Give me a brief assessment of the edit"""
                ),
            )],
        )

    elif name == "cleanup":
        return GetPromptResult(
            description="Find and fix timeline issues",
            messages=[PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Help me clean up my timeline by finding and fixing common issues.

File: {filepath}

Please:
1. Use `validate_timeline` to get the health score
2. If there are flash frames, use `fix_flash_frames` to remove them
3. If there are gaps, use `fill_gaps` to close them
4. Report what was fixed and the new health score"""
                ),
            )],
        )

    raise ValueError(f"Unknown prompt: {name}")


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
                    "marker_type": {"type": "string", "enum": ["all", "chapter", "todo", "standard", "completed"]},
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

        # ===== QC / VALIDATION TOOLS =====
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
                    "marker_type": {"type": "string", "enum": ["standard", "chapter", "todo", "completed"], "default": "standard"},
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

        # ===== BATCH FIX TOOLS =====
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

        # ===== GENERATION TOOLS =====
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

        # ===== BEAT SYNC TOOLS =====
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

        # ===== SUBTITLE / TRANSCRIPT TOOLS =====
        Tool(
            name="import_srt_markers",
            description="Import SRT or VTT subtitles as chapter markers on the timeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "srt_path": {"type": "string", "description": "Path to SRT or VTT subtitle file"},
                    "mode": {"type": "string", "enum": ["all", "first_per_minute", "scene_changes"], "default": "first_per_minute", "description": "How to create markers: every subtitle, first per minute, or on text changes"},
                    "marker_type": {"type": "string", "enum": ["standard", "chapter"], "default": "chapter"},
                    "max_label_length": {"type": "integer", "default": 50, "description": "Truncate marker labels to this length"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _subtitled suffix)"}
                },
                "required": ["filepath", "srt_path"]
            }
        ),
        Tool(
            name="import_transcript_markers",
            description="Import timestamped transcript (YouTube chapter format) as markers. Supports '0:00 Title' and 'HH:MM:SS Title' formats",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "transcript": {"type": "string", "description": "Timestamped text (one per line: '0:00 Introduction')"},
                    "transcript_path": {"type": "string", "description": "Path to text file with timestamps (alternative to inline transcript)"},
                    "marker_type": {"type": "string", "enum": ["standard", "chapter"], "default": "chapter"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _chapters suffix)"}
                },
                "required": ["filepath"]
            }
        ),

        # ===== CONNECTED CLIPS & COMPOUND CLIPS (v0.5.0) =====
        Tool(
            name="list_connected_clips",
            description="List all connected clips (B-roll, titles, audio) with their lanes and parent clips",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "lane": {"type": "integer", "description": "Filter by lane number (positive=above, negative=below)"},
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="add_connected_clip",
            description="Connect a library clip to an existing timeline clip (B-roll overlay, audio, title)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "parent_clip_id": {"type": "string", "description": "Name/ID of the clip to attach to"},
                    "asset_id": {"type": "string", "description": "Asset reference ID"},
                    "asset_name": {"type": "string", "description": "Asset name (alternative to asset_id)"},
                    "offset": {"type": "string", "default": "0s", "description": "Position relative to parent clip start"},
                    "duration": {"type": "string", "description": "Duration (default: full asset)"},
                    "lane": {"type": "integer", "default": 1, "description": "Lane number (positive=above, negative=below)"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath", "parent_clip_id"]
            }
        ),
        Tool(
            name="list_compound_clips",
            description="List compound clips (ref-clips) and their nested content",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                },
                "required": ["filepath"]
            }
        ),

        # ===== ROLES MANAGEMENT (v0.5.0) =====
        Tool(
            name="list_roles",
            description="List all audio/video roles used in the timeline with clip counts",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="assign_role",
            description="Set the audio or video role on a clip (dialogue, music, effects, titles, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "clip_id": {"type": "string", "description": "Clip name or ID"},
                    "audio_role": {"type": "string", "description": "Audio role (e.g., dialogue, music, effects)"},
                    "video_role": {"type": "string", "description": "Video role (e.g., video, titles)"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _modified suffix)"}
                },
                "required": ["filepath", "clip_id"]
            }
        ),
        Tool(
            name="filter_by_role",
            description="List all clips matching a specific audio or video role",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "role": {"type": "string", "description": "Role name to filter by"},
                    "role_type": {"type": "string", "enum": ["audio", "video", "any"], "default": "any", "description": "Which role type to search"},
                },
                "required": ["filepath", "role"]
            }
        ),
        Tool(
            name="export_role_stems",
            description="Export clip list grouped by role for audio mixing stem planning",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                },
                "required": ["filepath"]
            }
        ),

        # ===== TIMELINE DIFF (v0.5.0) =====
        Tool(
            name="diff_timelines",
            description="Compare two FCPXML files and report differences in clips, markers, transitions, and format",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath_a": {"type": "string", "description": "Path to first FCPXML file (baseline)"},
                    "filepath_b": {"type": "string", "description": "Path to second FCPXML file (comparison)"},
                },
                "required": ["filepath_a", "filepath_b"]
            }
        ),

        # ===== SOCIAL MEDIA REFORMAT (v0.5.0) =====
        Tool(
            name="reformat_timeline",
            description="Create new FCPXML with different resolution/aspect ratio (9:16 for TikTok, 1:1 for Instagram, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "format": {"type": "string", "enum": ["9:16", "1:1", "4:5", "16:9", "4:3", "custom"], "description": "Target format preset"},
                    "width": {"type": "integer", "description": "Custom width (only with format='custom')"},
                    "height": {"type": "integer", "description": "Custom height (only with format='custom')"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _reformatted suffix)"}
                },
                "required": ["filepath", "format"]
            }
        ),

        # ===== SILENCE DETECTION (v0.5.0) =====
        Tool(
            name="detect_silence_candidates",
            description="Detect potential silence/dead air using timeline heuristics (gaps, ultra-short clips, name patterns, duration anomalies)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "min_gap_seconds": {"type": "number", "default": 0.5, "description": "Minimum gap duration to flag"},
                    "patterns": {"type": "array", "items": {"type": "string"}, "description": "Name patterns to match (default: gap, silence, room tone)"},
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="remove_silence_candidates",
            description="Remove or mark detected silence candidates from timeline",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "mode": {"type": "string", "enum": ["delete", "mark"], "default": "mark", "description": "delete=remove clips/gaps, mark=add red markers"},
                    "min_gap_seconds": {"type": "number", "default": 0.5},
                    "min_confidence": {"type": "number", "default": 0.7, "description": "Only act on candidates above this confidence"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _silence_cleaned suffix)"}
                },
                "required": ["filepath"]
            }
        ),

        # ===== NLE EXPORT (v0.5.0) =====
        Tool(
            name="export_resolve_xml",
            description="Export timeline as DaVinci Resolve compatible FCPXML (simplified v1.9)",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "flatten_compounds": {"type": "boolean", "default": True, "description": "Flatten compound clips for compatibility"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _resolve suffix)"},
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="export_fcp7_xml",
            description="Export timeline as FCP7 XML (XMEML) for Premiere Pro, DaVinci Resolve, and Avid compatibility",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to FCPXML file"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _fcp7.xml suffix)"},
                },
                "required": ["filepath"]
            }
        ),
    ]


# ============================================================================
# TOOL HANDLERS — Each tool gets its own function
# ============================================================================

# ----- READ HANDLERS -----

async def handle_list_projects(arguments: dict) -> Sequence[TextContent]:
    directory = arguments.get("directory", PROJECTS_DIR)
    resolved_dir = _validate_directory(directory)
    files = find_fcpxml_files(resolved_dir)
    if not files:
        return [TextContent(type="text", text=f"No FCPXML files found in {directory}")]
    return [TextContent(type="text", text=f"Found {len(files)} FCPXML file(s):\n" + "\n".join(f"  - {f}" for f in files))]


async def handle_analyze_timeline(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    durs = [c.duration_seconds for c in tl.clips]
    avg, med, mn, mx = (0, 0, 0, 0) if not durs else (
        sum(durs)/len(durs), sorted(durs)[len(durs)//2], min(durs), max(durs))
    return [TextContent(type="text", text=f"""# Timeline Analysis: {tl.name}

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
""")]


async def handle_list_clips(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    limit = arguments.get("limit")
    clips = tl.clips[:limit] if limit else tl.clips
    result = f"# Clips in {tl.name}\n\n| # | Name | Start | Duration | Keywords |\n|---|------|-------|----------|----------|\n"
    for i, c in enumerate(clips, 1):
        kws = ", ".join(k.value for k in c.keywords) if c.keywords else "-"
        result += f"| {i} | {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} | {kws} |\n"
    return [TextContent(type="text", text=result)]


async def handle_list_markers(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    markers = list(tl.markers)
    for clip in tl.clips:
        markers.extend(clip.markers)
    marker_type = arguments.get("marker_type", "all")
    if marker_type != "all":
        markers = [m for m in markers if m.marker_type == MarkerType.from_string(marker_type)]
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


async def handle_find_short_cuts(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    threshold = arguments.get("threshold_seconds", 0.5)
    short = tl.get_clips_shorter_than(threshold)
    if not short:
        return [TextContent(type="text", text=f"No clips shorter than {threshold}s")]
    result = f"# Short Clips (< {threshold}s) - {len(short)} found\n\n| Name | TC | Duration |\n|------|----|---------|\n"
    result += "\n".join(f"| {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} |" for c in short)
    return [TextContent(type="text", text=result)]


async def handle_find_long_clips(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    threshold = arguments.get("threshold_seconds", 10.0)
    long = tl.get_clips_longer_than(threshold)
    if not long:
        return [TextContent(type="text", text=f"No clips longer than {threshold}s")]
    result = f"# Long Clips (> {threshold}s) - {len(long)} found\n\n| Name | TC | Duration |\n|------|----|---------|\n"
    result += "\n".join(f"| {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} |" for c in long)
    return [TextContent(type="text", text=result)]


async def handle_list_keywords(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    keywords = {}
    for clip in tl.clips:
        for kw in clip.keywords:
            keywords.setdefault(kw.value, []).append(clip.name)
    if not keywords:
        return [TextContent(type="text", text="No keywords found")]
    result = f"# Keywords ({len(keywords)})\n\n"
    for kw, clips in sorted(keywords.items()):
        result += f"**{kw}** ({len(clips)} clips)\n"
    return [TextContent(type="text", text=result)]


async def handle_export_edl(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    edl = f"TITLE: {tl.name}\nFCM: NON-DROP FRAME\n\n"
    for i, c in enumerate(tl.clips, 1):
        edl += f"{i:03d}  AX       V     C        {format_timecode(c.source_start)} {format_timecode(c.end)} {format_timecode(c.start)} {format_timecode(c.end)}\n"
        edl += f"* FROM CLIP NAME: {c.name}\n\n"
    return [TextContent(type="text", text=f"```edl\n{edl}```")]


async def handle_export_csv(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    csv = "Name,Start,End,Duration,Keywords\n"
    for c in tl.clips:
        kws = "|".join(k.value for k in c.keywords)
        csv += f'"{c.name}",{format_timecode(c.start)},{format_timecode(c.end)},{c.duration_seconds:.3f},"{kws}"\n'
    return [TextContent(type="text", text=f"```csv\n{csv}```")]


async def handle_analyze_pacing(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
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
        suggestions.append(f"  {len(flash)} potential flash frames (< 0.2s)")
    long = [c for c in tl.clips if c.duration_seconds > 30]
    if long:
        suggestions.append(f"  {len(long)} long takes (> 30s) - consider trimming")
    if len(seg_avgs) >= 4 and seg_avgs[3] < seg_avgs[0] * 0.7:
        suggestions.append("  Pacing accelerates toward end - good for building energy")
    elif len(seg_avgs) >= 4 and seg_avgs[3] > seg_avgs[0] * 1.3:
        suggestions.append("  Pacing slows toward end - consider tightening")
    return [TextContent(type="text", text=f"""# Pacing Analysis: {tl.name}

## Overall
- **Avg Cut**: {format_duration(avg)}
- **Cuts/Min**: {tl.cuts_per_minute:.1f}

## By Section
| Q1 | Q2 | Q3 | Q4 |
|----|----|----|----|
| {format_duration(seg_avgs[0]) if len(seg_avgs) > 0 else 'N/A'} | {format_duration(seg_avgs[1]) if len(seg_avgs) > 1 else 'N/A'} | {format_duration(seg_avgs[2]) if len(seg_avgs) > 2 else 'N/A'} | {format_duration(seg_avgs[3]) if len(seg_avgs) > 3 else 'N/A'} |

## Suggestions
{_fmt_suggestions(suggestions)}
""")]


async def handle_list_library_clips(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    parser = FCPXMLParser()
    parser.parse_file(filepath)
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
        result += f"| {c['asset_id']} | {c['name']} | {format_duration(c['duration_seconds'])} | {'Y' if c['has_video'] else 'N'} | {'Y' if c['has_audio'] else 'N'} |\n"
    result += "\n*Use `insert_clip` to add these to your timeline.*"
    return [TextContent(type="text", text=result)]


# ----- QC / VALIDATION HANDLERS -----

async def handle_detect_flash_frames(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    fps = tl.frame_rate
    critical_threshold = arguments.get("critical_threshold_frames", 2)
    warning_threshold = arguments.get("warning_threshold_frames", 6)

    flash_frames = []
    for clip in tl.clips:
        duration_frames = int(clip.duration_seconds * fps)
        if duration_frames < warning_threshold:
            severity = FlashFrameSeverity.CRITICAL if duration_frames < critical_threshold else FlashFrameSeverity.WARNING
            flash_frames.append(FlashFrame(
                clip_name=clip.name, clip_id=clip.name,
                start=clip.start, duration_frames=duration_frames,
                duration_seconds=clip.duration_seconds, severity=severity,
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


async def handle_detect_duplicates(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    parser = FCPXMLParser()
    project = parser.parse_file(filepath)
    if not project.timelines:
        return _no_timeline()
    tl = project.primary_timeline
    mode = arguments.get("mode", "same_source")

    source_groups = {}
    for clip in tl.clips:
        source_key = clip.media_path or clip.name
        if source_key not in source_groups:
            source_groups[source_key] = []
        source_groups[source_key].append({
            'name': clip.name, 'start': clip.start.seconds,
            'duration': clip.duration_seconds,
            'source_start': clip.source_start.seconds if clip.source_start else 0,
            'source_duration': clip.duration_seconds,
            'timecode': format_timecode(clip.start),
        })

    duplicates = []
    for source_key, clips in source_groups.items():
        if len(clips) > 1:
            group = DuplicateGroup(
                source_ref=source_key,
                source_name=source_key.split('/')[-1] if '/' in source_key else source_key,
                clips=clips,
            )
            if mode == "same_source":
                duplicates.append(group)
            elif mode == "overlapping_ranges" and group.has_overlapping_ranges:
                duplicates.append(group)
            elif mode == "identical":
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


async def handle_detect_gaps(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
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
            gaps.append(GapInfo(
                start=Timecode(frames=int(current_end * fps), frame_rate=fps),
                duration_frames=int(gap_duration * fps),
                duration_seconds=gap_duration,
                previous_clip=sorted_clips[i].name,
                next_clip=sorted_clips[i + 1].name,
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
        result += f"| {gap.timecode} | {gap.duration_frames}f ({format_duration(gap.duration_seconds)}) | {gap.previous_clip} -> {gap.next_clip} |\n"

    result += "\n*Use `fill_gaps` to automatically close these gaps.*"
    return [TextContent(type="text", text=result)]


# ----- WRITE HANDLERS -----

async def handle_add_marker(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    marker_type = MarkerType.from_string(arguments.get("marker_type", "standard"))
    modifier.add_marker_at_timeline(
        timecode=arguments["timecode"], name=arguments["name"],
        marker_type=marker_type, note=arguments.get("note"),
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=f"Added marker '{arguments['name']}' at {arguments['timecode']}\n\nSaved to: {output_path}")]


async def handle_batch_add_markers(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    markers_added = modifier.batch_add_markers(
        markers=arguments.get("markers", []),
        auto_at_cuts=arguments.get("auto_at_cuts", False),
        auto_at_intervals=arguments.get("auto_at_intervals"),
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=f"Added {len(markers_added)} markers\n\nSaved to: {output_path}")]


async def handle_trim_clip(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.trim_clip(
        clip_id=arguments["clip_id"],
        trim_start=arguments.get("trim_start"),
        trim_end=arguments.get("trim_end"),
        ripple=arguments.get("ripple", True),
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=f"Trimmed clip '{arguments['clip_id']}'\n\nSaved to: {output_path}")]


async def handle_reorder_clips(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.reorder_clips(
        clip_ids=arguments["clip_ids"],
        target_position=arguments["target_position"],
        ripple=arguments.get("ripple", True),
    )
    modifier.save(output_path)
    clips_moved = ", ".join(arguments["clip_ids"])
    return [TextContent(type="text", text=f"Moved clips [{clips_moved}] to {arguments['target_position']}\n\nSaved to: {output_path}")]


async def handle_add_transition(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.add_transition(
        clip_id=arguments["clip_id"],
        position=arguments.get("position", "end"),
        transition_type=arguments.get("transition_type", "cross-dissolve"),
        duration=arguments.get("duration", "00:00:00:15"),
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=f"Added {arguments.get('transition_type', 'cross-dissolve')} to '{arguments['clip_id']}'\n\nSaved to: {output_path}")]


async def handle_change_speed(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.change_speed(
        clip_id=arguments["clip_id"],
        speed=arguments["speed"],
        preserve_pitch=arguments.get("preserve_pitch", True),
    )
    modifier.save(output_path)
    speed = arguments["speed"]
    speed_desc = f"{speed}x" if speed >= 1 else f"{int(1/speed)}x slow motion"
    return [TextContent(type="text", text=f"Changed speed of '{arguments['clip_id']}' to {speed_desc}\n\nSaved to: {output_path}")]


async def handle_delete_clips(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.delete_clip(
        clip_ids=arguments["clip_ids"],
        ripple=arguments.get("ripple", True),
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=f"Deleted {len(arguments['clip_ids'])} clip(s)\n\nSaved to: {output_path}")]


async def handle_split_clip(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    new_clips = modifier.split_clip(
        clip_id=arguments["clip_id"],
        split_points=arguments["split_points"],
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=f"Split '{arguments['clip_id']}' into {len(new_clips)} clips\n\nSaved to: {output_path}")]


async def handle_insert_clip(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    new_clip = modifier.insert_clip(
        asset_id=arguments.get("asset_id"),
        asset_name=arguments.get("asset_name"),
        position=arguments["position"],
        duration=arguments.get("duration"),
        in_point=arguments.get("in_point"),
        out_point=arguments.get("out_point"),
        ripple=arguments.get("ripple", True),
    )
    modifier.save(output_path)
    clip_name = new_clip.get('name', 'Unknown')
    pos = arguments["position"]
    return [TextContent(type="text", text=f"Inserted '{clip_name}' at position '{pos}'\n\nSaved to: {output_path}")]


# ----- BATCH FIX HANDLERS -----

async def handle_fix_flash_frames(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_flash_fixed")
    )
    modifier = FCPXMLModifier(filepath)
    fixed = modifier.fix_flash_frames(
        mode=arguments.get("mode", "auto"),
        threshold_frames=arguments.get("threshold_frames", 6),
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


async def handle_rapid_trim(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_rapid_trim")
    )
    modifier = FCPXMLModifier(filepath)
    trimmed = modifier.rapid_trim(
        max_duration=arguments["max_duration"],
        min_duration=arguments.get("min_duration"),
        keywords=arguments.get("keywords"),
        trim_from=arguments.get("trim_from", "end"),
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


async def handle_fill_gaps(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_gaps_filled")
    )
    modifier = FCPXMLModifier(filepath)
    filled = modifier.fill_gaps(
        mode=arguments.get("mode", "extend_previous"),
        max_gap=arguments.get("max_gap"),
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


async def handle_validate_timeline(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()
    fps = tl.frame_rate
    checks = arguments.get("checks", ["all"])
    run_all = "all" in checks

    issues = []
    flash_count = 0
    gap_count = 0
    duplicate_count = 0

    if run_all or "flash_frames" in checks:
        for clip in tl.clips:
            duration_frames = int(clip.duration_seconds * fps)
            if duration_frames < 6:
                flash_count += 1
                severity = "error" if duration_frames < 2 else "warning"
                issues.append(f"- [{severity.upper()}] Flash frame: {clip.name} ({duration_frames}f) at {format_timecode(clip.start)}")

    if run_all or "gaps" in checks:
        sorted_clips = sorted(tl.clips, key=lambda c: c.start.seconds)
        for i in range(len(sorted_clips) - 1):
            current_end = sorted_clips[i].end.seconds
            next_start = sorted_clips[i + 1].start.seconds
            gap_duration = next_start - current_end
            if gap_duration > 0.001:
                gap_count += 1
                gap_frames = int(gap_duration * fps)
                gap_tc = Timecode(frames=int(current_end * fps), frame_rate=fps)
                issues.append(f"- [WARNING] Gap: {gap_frames}f at {gap_tc.to_smpte()}")

    if run_all or "duplicates" in checks:
        source_groups = {}
        for clip in tl.clips:
            source_key = clip.media_path or clip.name
            source_groups.setdefault(source_key, []).append(clip)
        for source, clips in source_groups.items():
            if len(clips) > 1:
                duplicate_count += len(clips)
                issues.append(f"- [INFO] Duplicate source: {source.split('/')[-1]} ({len(clips)} uses)")

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
| Flash Frames | {flash_count} | {'PASS' if flash_count == 0 else 'FAIL'} |
| Gaps | {gap_count} | {'PASS' if gap_count == 0 else 'WARN'} |
| Duplicate Sources | {duplicate_count} | {'PASS' if duplicate_count == 0 else 'INFO'} |

## Issues ({len(issues)})
"""
    if issues:
        result += "\n".join(issues[:20])
        if len(issues) > 20:
            result += f"\n... and {len(issues) - 20} more issues"
    else:
        result += "_No issues found!_"

    result += "\n\n*Use `fix_flash_frames` and `fill_gaps` to automatically resolve issues.*"
    return [TextContent(type="text", text=result)]


# ----- GENERATION HANDLERS -----

async def handle_auto_rough_cut(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(arguments["output_path"])

    segments = None
    if arguments.get("segments"):
        segments = [
            SegmentSpec(
                name=s.get("name", "Segment"),
                keywords=s.get("keywords", []),
                duration_seconds=s.get("duration", 0),
                priority=s.get("priority", "best"),
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
        add_transitions=arguments.get("add_transitions", False),
    )

    return [TextContent(type="text", text=f"""# Rough Cut Generated

## Summary
- **Clips Used**: {result.clips_used} of {result.clips_available} available
- **Target Duration**: {format_duration(result.target_duration)}
- **Actual Duration**: {format_duration(result.actual_duration)}
- **Average Clip**: {format_duration(result.average_clip_duration)}

## Output
Saved to: `{result.output_path}`

**Next step**: Import this FCPXML into Final Cut Pro (File > Import > XML)
""")]


async def handle_generate_montage(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(arguments["output_path"])

    generator = RoughCutGenerator(filepath)
    result = generator.generate_montage(
        output_path=output_path,
        target_duration=arguments["target_duration"],
        pacing_curve=arguments.get("pacing_curve", "accelerating"),
        start_duration=arguments.get("start_duration", 2.0),
        end_duration=arguments.get("end_duration", 0.5),
        keywords=arguments.get("keywords"),
        add_transitions=arguments.get("add_transitions", False),
    )

    curve_desc = {
        'accelerating': 'slow to fast (builds energy)',
        'decelerating': 'fast to slow (winds down)',
        'pyramid': 'slow to fast to slow (dramatic arc)',
        'constant': 'same duration throughout',
    }

    return [TextContent(type="text", text=f"""# Montage Generated

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


async def handle_generate_ab_roll(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(arguments["output_path"])

    generator = RoughCutGenerator(filepath)
    result = generator.generate_ab_roll(
        output_path=output_path,
        target_duration=arguments["target_duration"],
        a_keywords=arguments["a_keywords"],
        b_keywords=arguments["b_keywords"],
        a_duration=arguments.get("a_duration", "5s"),
        b_duration=arguments.get("b_duration", "3s"),
        start_with=arguments.get("start_with", "a"),
        add_transitions=arguments.get("add_transitions", True),
    )

    return [TextContent(type="text", text=f"""# A/B Roll Edit Generated

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

**Next step**: Import this FCPXML into Final Cut Pro (File > Import > XML)
""")]


# ----- BEAT SYNC HANDLERS -----

async def handle_import_beat_markers(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    beats_path = _validate_filepath(arguments["beats_path"], ('.json',))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_beats")
    )

    with open(beats_path, 'r') as f:
        beats_data = json.load(f)

    beat_times = []
    if isinstance(beats_data, list):
        beat_times = beats_data
    elif isinstance(beats_data, dict):
        beat_times = beats_data.get('beats', beats_data.get('times', beats_data.get('markers', [])))

    beat_filter = arguments.get("beat_filter", "all")
    if beat_filter == "downbeat" and isinstance(beats_data, dict):
        beat_times = beats_data.get('downbeats', beat_times[::4])
    elif beat_filter == "measure" and isinstance(beats_data, dict):
        beat_times = beats_data.get('measures', beat_times[::4])

    markers = []
    marker_type = arguments.get("marker_type", "standard")
    for i, beat_time in enumerate(beat_times):
        if isinstance(beat_time, (int, float)):
            markers.append({
                'timecode': f"{beat_time}s",
                'name': f"Beat {i+1}",
                'marker_type': marker_type.upper(),
            })
        elif isinstance(beat_time, dict):
            markers.append({
                'timecode': f"{beat_time.get('time', beat_time.get('position', 0))}s",
                'name': beat_time.get('label', f"Beat {i+1}"),
                'marker_type': marker_type.upper(),
            })

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


async def handle_snap_to_beats(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_synced")
    )
    max_shift = arguments.get("max_shift_frames", 6)
    prefer = arguments.get("prefer", "nearest")

    parser = FCPXMLParser()
    project = parser.parse_file(filepath)
    if not project.timelines:
        return _no_timeline()

    tl = project.primary_timeline
    fps = tl.frame_rate

    markers = list(tl.markers)
    for clip in tl.clips:
        markers.extend(clip.markers)

    if not markers:
        return [TextContent(type="text", text="No markers found. Use `import_beat_markers` first.")]

    marker_times = sorted([m.start.seconds for m in markers])

    modifier = FCPXMLModifier(filepath)
    spine = modifier._get_spine()
    adjusted_count = 0
    total_shift = 0

    clips_list = [c for c in spine if c.tag in ('clip', 'asset-clip', 'video', 'ref-clip')]

    for i, clip in enumerate(clips_list[1:], 1):
        cut_offset = modifier._parse_time(clip.get('offset', '0s'))
        cut_seconds = cut_offset.to_seconds()

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
            shift = best_marker - cut_seconds
            shift_frames = int(shift * fps)

            prev_clip = clips_list[i - 1]
            prev_dur = modifier._parse_time(prev_clip.get('duration', '0s'))
            new_prev_dur = prev_dur + modifier._parse_time(f"{shift}s")
            prev_clip.set('duration', new_prev_dur.to_fcpxml())

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


# ----- SUBTITLE / TRANSCRIPT HANDLERS -----

async def handle_import_srt_markers(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    srt_path = _validate_filepath(arguments["srt_path"], ('.srt', '.vtt'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_subtitled")
    )
    mode = arguments.get("mode", "first_per_minute")
    marker_type = arguments.get("marker_type", "chapter")
    max_label = arguments.get("max_label_length", 50)

    text = Path(srt_path).read_text(encoding='utf-8')

    # Detect format and parse
    if srt_path.endswith('.vtt') or text.strip().startswith('WEBVTT'):
        raw_markers = parse_vtt(text)
        fmt_name = "WebVTT"
    else:
        raw_markers = parse_srt(text)
        fmt_name = "SRT"

    if not raw_markers:
        return [TextContent(type="text", text=f"No subtitles found in {srt_path}")]

    # Apply mode filtering
    filtered = []
    if mode == "all":
        filtered = raw_markers
    elif mode == "first_per_minute":
        seen_minutes = set()
        for m in raw_markers:
            minute = int(m['seconds'] // 60)
            if minute not in seen_minutes:
                seen_minutes.add(minute)
                filtered.append(m)
    elif mode == "scene_changes":
        # Group by similar text, take first occurrence of each unique line
        seen_texts = set()
        for m in raw_markers:
            # Normalize: lowercase, strip punctuation
            normalized = re.sub(r'[^\w\s]', '', m['text'].lower()).strip()
            words = normalized.split()[:3]  # First 3 words as key
            key = ' '.join(words)
            if key and key not in seen_texts:
                seen_texts.add(key)
                filtered.append(m)

    # Convert to marker format
    markers = []
    for m in filtered:
        label = m['text'][:max_label] if len(m['text']) > max_label else m['text']
        markers.append({
            'timecode': f"{m['seconds']}s",
            'name': label,
            'marker_type': marker_type.upper(),
        })

    modifier = FCPXMLModifier(filepath)
    added = modifier.batch_add_markers(markers=markers)
    modifier.save(output_path)

    return [TextContent(type="text", text=f"""# Subtitle Markers Imported

## Summary
- **Format**: {fmt_name}
- **Subtitles Parsed**: {len(raw_markers)}
- **Mode**: {mode}
- **Markers Added**: {len(added)}
- **Marker Type**: {marker_type}

## Output
Saved to: `{output_path}`
""")]


async def handle_import_transcript_markers(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_chapters")
    )
    marker_type = arguments.get("marker_type", "chapter")

    # Get transcript text from inline or file
    transcript = arguments.get("transcript")
    transcript_path = arguments.get("transcript_path")

    if not transcript and not transcript_path:
        return [TextContent(type="text", text="Provide either 'transcript' (inline text) or 'transcript_path' (path to file)")]

    if transcript_path:
        transcript_path = _validate_filepath(transcript_path, ('.txt', '.srt', '.vtt'))
        transcript = Path(transcript_path).read_text(encoding='utf-8')

    raw_markers = parse_transcript_timestamps(transcript or "")

    if not raw_markers:
        return [TextContent(type="text", text="No timestamps found. Expected format: '0:00 Title' or 'HH:MM:SS Title', one per line.")]

    markers = []
    for m in raw_markers:
        markers.append({
            'timecode': f"{m['seconds']}s",
            'name': m['text'],
            'marker_type': marker_type.upper(),
        })

    modifier = FCPXMLModifier(filepath)
    added = modifier.batch_add_markers(markers=markers)
    modifier.save(output_path)

    return [TextContent(type="text", text=f"""# Transcript Markers Imported

## Summary
- **Timestamps Found**: {len(raw_markers)}
- **Markers Added**: {len(added)}
- **Marker Type**: {marker_type}

## Markers
""" + "\n".join(f"- `{m['timecode']}` {m['name']}" for m in markers) + f"""

## Output
Saved to: `{output_path}`
""")]


# ----- CONNECTED CLIPS & COMPOUND CLIPS HANDLERS (v0.5.0) -----

async def handle_list_connected_clips(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()

    lane_filter = arguments.get("lane")
    clips = tl.connected_clips
    if lane_filter is not None:
        clips = [c for c in clips if c.lane == lane_filter]

    if not clips:
        return [TextContent(type="text", text="No connected clips found in timeline.")]

    result = f"# Connected Clips in {tl.name}\n\n**Total**: {len(clips)}\n\n"
    result += "| # | Name | Lane | Type | Duration | Parent | Role |\n"
    result += "|---|------|------|------|----------|--------|------|\n"
    for i, c in enumerate(clips, 1):
        result += (
            f"| {i} | {c.name} | {c.lane} | {c.clip_type} | "
            f"{format_duration(c.duration_seconds)} | {c.parent_clip_name} | "
            f"{c.role or '-'} |\n"
        )
    return [TextContent(type="text", text=result)]


async def handle_add_connected_clip(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.add_connected_clip(
        parent_clip_id=arguments["parent_clip_id"],
        asset_id=arguments.get("asset_id"),
        asset_name=arguments.get("asset_name"),
        offset=arguments.get("offset", "0s"),
        duration=arguments.get("duration"),
        lane=arguments.get("lane", 1),
    )
    modifier.save(output_path)
    return [TextContent(type="text", text=(
        f"Connected clip added to '{arguments['parent_clip_id']}' on lane {arguments.get('lane', 1)}\n\n"
        f"Saved to: `{output_path}`"
    ))]


async def handle_list_compound_clips(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()

    if not tl.compound_clips:
        return [TextContent(type="text", text="No compound clips found in timeline.")]

    result = f"# Compound Clips in {tl.name}\n\n"
    for i, cc in enumerate(tl.compound_clips, 1):
        result += f"### {i}. {cc.name}\n"
        result += f"- **Ref ID**: {cc.ref_id}\n"
        result += f"- **Duration**: {format_duration(cc.duration_seconds)}\n"
        result += f"- **Clips inside**: {len(cc.clips)}\n\n"
    return [TextContent(type="text", text=result)]


# ----- ROLES HANDLERS (v0.5.0) -----

async def handle_list_roles(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()

    audio_roles: dict[str, int] = {}
    video_roles: dict[str, int] = {}

    for clip in tl.clips:
        if clip.audio_role:
            audio_roles[clip.audio_role] = audio_roles.get(clip.audio_role, 0) + 1
        if clip.video_role:
            video_roles[clip.video_role] = video_roles.get(clip.video_role, 0) + 1

    for cc in tl.connected_clips:
        if cc.role:
            # Determine type from clip_type
            if cc.clip_type in ('audio', 'audio-clip'):
                audio_roles[cc.role] = audio_roles.get(cc.role, 0) + 1
            else:
                video_roles[cc.role] = video_roles.get(cc.role, 0) + 1

    result = f"# Roles in {tl.name}\n\n"
    if audio_roles:
        result += "## Audio Roles\n\n| Role | Clips |\n|------|-------|\n"
        for role, count in sorted(audio_roles.items()):
            result += f"| {role} | {count} |\n"
    else:
        result += "## Audio Roles\n\nNo audio roles assigned.\n"

    result += "\n"
    if video_roles:
        result += "## Video Roles\n\n| Role | Clips |\n|------|-------|\n"
        for role, count in sorted(video_roles.items()):
            result += f"| {role} | {count} |\n"
    else:
        result += "## Video Roles\n\nNo video roles assigned.\n"

    return [TextContent(type="text", text=result)]


async def handle_assign_role(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath)
    )
    modifier = FCPXMLModifier(filepath)
    modifier.assign_role(
        clip_id=arguments["clip_id"],
        audio_role=arguments.get("audio_role"),
        video_role=arguments.get("video_role"),
    )
    modifier.save(output_path)

    roles_set = []
    if arguments.get("audio_role"):
        roles_set.append(f"audioRole={arguments['audio_role']}")
    if arguments.get("video_role"):
        roles_set.append(f"videoRole={arguments['video_role']}")

    return [TextContent(type="text", text=(
        f"Set {', '.join(roles_set)} on '{arguments['clip_id']}'\n\n"
        f"Saved to: `{output_path}`"
    ))]


async def handle_filter_by_role(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()

    role = arguments["role"].lower()
    role_type = arguments.get("role_type", "any")
    matches = []

    for clip in tl.clips:
        if role_type in ("audio", "any") and clip.audio_role.lower() == role:
            matches.append((clip.name, "audio", clip.audio_role, format_duration(clip.duration_seconds)))
        if role_type in ("video", "any") and clip.video_role.lower() == role:
            matches.append((clip.name, "video", clip.video_role, format_duration(clip.duration_seconds)))

    if not matches:
        return [TextContent(type="text", text=f"No clips found with role '{role}'.")]

    result = f"# Clips with role '{role}'\n\n"
    result += "| Clip | Type | Role | Duration |\n|------|------|------|----------|\n"
    for name, rtype, rval, dur in matches:
        result += f"| {name} | {rtype} | {rval} | {dur} |\n"
    return [TextContent(type="text", text=result)]


async def handle_export_role_stems(arguments: dict) -> Sequence[TextContent]:
    project, tl = _parse_project(arguments["filepath"])
    if not tl:
        return _no_timeline()

    stems: dict[str, list] = {}
    for clip in tl.clips:
        role = clip.audio_role or "unassigned"
        stems.setdefault(role, []).append(clip)

    for cc in tl.connected_clips:
        role = cc.role or "unassigned"
        stems.setdefault(role, []).append(cc)

    result = f"# Audio Stem Plan for {tl.name}\n\n"
    for role, clips in sorted(stems.items()):
        total_dur = sum(c.duration_seconds for c in clips)
        result += f"## {role.title()} ({len(clips)} clips, {format_duration(total_dur)})\n\n"
        for c in clips:
            result += f"- {c.name} ({format_duration(c.duration_seconds)})\n"
        result += "\n"

    return [TextContent(type="text", text=result)]


# ----- TIMELINE DIFF HANDLER (v0.5.0) -----

async def handle_diff_timelines(arguments: dict) -> Sequence[TextContent]:
    filepath_a = _validate_filepath(arguments["filepath_a"], ('.fcpxml', '.fcpxmld'))
    filepath_b = _validate_filepath(arguments["filepath_b"], ('.fcpxml', '.fcpxmld'))

    diff = compare_timelines(filepath_a, filepath_b)

    if not diff.has_changes:
        return [TextContent(type="text", text=(
            f"# Timeline Diff: No Changes\n\n"
            f"**{diff.timeline_a_name}** vs **{diff.timeline_b_name}** are identical."
        ))]

    result = (
        f"# Timeline Diff\n\n"
        f"**Baseline**: {diff.timeline_a_name}\n"
        f"**Comparison**: {diff.timeline_b_name}\n"
        f"**Total changes**: {diff.total_changes}\n\n"
    )

    if diff.format_changes:
        result += "## Format Changes\n\n"
        for change in diff.format_changes:
            result += f"- {change}\n"
        result += "\n"

    clip_changes = [d for d in diff.clip_diffs if d.action != "unchanged"]
    if clip_changes:
        result += "## Clip Changes\n\n| Action | Clip | Details |\n|--------|------|--------|\n"
        for d in clip_changes:
            result += f"| {d.action.upper()} | {d.clip_name} | {d.details} |\n"
        result += "\n"

    if diff.marker_diffs:
        result += "## Marker Changes\n\n| Action | Marker | Details |\n|--------|--------|--------|\n"
        for d in diff.marker_diffs:
            result += f"| {d.action.upper()} | {d.marker_name} | {d.details} |\n"
        result += "\n"

    if diff.transition_diffs:
        result += "## Transition Changes\n\n"
        for change in diff.transition_diffs:
            result += f"- {change}\n"

    return [TextContent(type="text", text=result)]


# ----- SOCIAL MEDIA REFORMAT HANDLER (v0.5.0) -----

async def handle_reformat_timeline(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_reformatted")
    )

    fmt = arguments["format"]
    if fmt == "custom":
        width = arguments.get("width")
        height = arguments.get("height")
        if not width or not height:
            return [TextContent(type="text", text="Custom format requires both 'width' and 'height' parameters.")]
    else:
        formats = FCPXMLModifier.SOCIAL_FORMATS
        if fmt not in formats:
            return [TextContent(type="text", text=f"Unknown format: {fmt}. Valid: {', '.join(formats.keys())}")]
        width, height = formats[fmt]

    modifier = FCPXMLModifier(filepath)
    modifier.reformat_resolution(width, height)
    modifier.save(output_path)

    return [TextContent(type="text", text=(
        f"# Timeline Reformatted\n\n"
        f"- **Format**: {fmt} ({width}x{height})\n"
        f"- **Aspect ratio**: {width}:{height}\n\n"
        f"Saved to: `{output_path}`\n\n"
        f"**Next step**: Import into FCP (File > Import > XML). "
        f"FCP will handle spatial conforming automatically."
    ))]


# ----- SILENCE DETECTION HANDLERS (v0.5.0) -----

async def handle_detect_silence_candidates(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    modifier = FCPXMLModifier(filepath)
    candidates = modifier.detect_silence_candidates(
        min_gap_seconds=arguments.get("min_gap_seconds", 0.5),
        patterns=arguments.get("patterns"),
    )

    if not candidates:
        return [TextContent(type="text", text="No silence candidates detected.")]

    result = f"# Silence Candidates Detected\n\n**Found**: {len(candidates)}\n\n"
    result += "| # | Timecode | Duration | Reason | Confidence | Clip |\n"
    result += "|---|----------|----------|--------|------------|------|\n"
    for i, c in enumerate(candidates, 1):
        result += (
            f"| {i} | {c['start_timecode']} | {format_duration(c['duration_seconds'])} | "
            f"{c['reason']} | {c['confidence']:.0%} | {c.get('clip_name') or '-'} |\n"
        )
    result += (
        "\n**Note**: Detection uses timeline heuristics (gaps, ultra-short clips, name patterns). "
        "Review candidates before removing — some may be intentional."
    )
    return [TextContent(type="text", text=result)]


async def handle_remove_silence_candidates(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_silence_cleaned")
    )
    modifier = FCPXMLModifier(filepath)
    actions = modifier.remove_silence_candidates(
        mode=arguments.get("mode", "mark"),
        min_gap_seconds=arguments.get("min_gap_seconds", 0.5),
        min_confidence=arguments.get("min_confidence", 0.7),
    )
    modifier.save(output_path)

    if not actions:
        return [TextContent(type="text", text="No silence candidates met the confidence threshold.")]

    mode = arguments.get("mode", "mark")
    result = f"# Silence Candidates {'Marked' if mode == 'mark' else 'Removed'}\n\n"
    result += f"**Actions taken**: {len(actions)}\n\n"
    for a in actions:
        result += f"- **{a['action']}** {a.get('clip_name', 'gap')} ({a['reason']})\n"
    result += f"\nSaved to: `{output_path}`"
    return [TextContent(type="text", text=result)]


# ----- NLE EXPORT HANDLERS (v0.5.0) -----

async def handle_export_resolve_xml(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    output_path = _validate_output_path(
        arguments.get("output_path") or generate_output_path(filepath, "_resolve")
    )
    exporter = DaVinciExporter(filepath)
    exporter.export_simplified_fcpxml(
        output_path,
        flatten_compounds=arguments.get("flatten_compounds", True),
    )
    return [TextContent(type="text", text=(
        f"# Exported for DaVinci Resolve\n\n"
        f"- **Format**: Simplified FCPXML v1.9\n"
        f"- **Compound clips flattened**: {arguments.get('flatten_compounds', True)}\n\n"
        f"Saved to: `{output_path}`\n\n"
        f"**Next step**: In DaVinci Resolve, go to File > Import > Timeline > Import AAF/EDL/XML"
    ))]


async def handle_export_fcp7_xml(arguments: dict) -> Sequence[TextContent]:
    filepath = _validate_filepath(arguments["filepath"], ('.fcpxml', '.fcpxmld'))
    default_out = str(Path(filepath).with_suffix('')) + "_fcp7.xml"
    output_path = _validate_output_path(
        arguments.get("output_path") or default_out
    )
    exporter = DaVinciExporter(filepath)
    exporter.export_xmeml(output_path)
    return [TextContent(type="text", text=(
        f"# Exported as FCP7 XML (XMEML)\n\n"
        f"- **Format**: XMEML v5\n"
        f"- **Compatible with**: Premiere Pro, DaVinci Resolve, Avid Media Composer\n\n"
        f"Saved to: `{output_path}`\n\n"
        f"**Next step**: Import via File > Import in your target NLE"
    ))]


# ============================================================================
# TOOL DISPATCH
# ============================================================================

TOOL_HANDLERS = {
    # Read
    "list_projects": handle_list_projects,
    "analyze_timeline": handle_analyze_timeline,
    "list_clips": handle_list_clips,
    "list_markers": handle_list_markers,
    "find_short_cuts": handle_find_short_cuts,
    "find_long_clips": handle_find_long_clips,
    "list_keywords": handle_list_keywords,
    "export_edl": handle_export_edl,
    "export_csv": handle_export_csv,
    "analyze_pacing": handle_analyze_pacing,
    "list_library_clips": handle_list_library_clips,
    # QC
    "detect_flash_frames": handle_detect_flash_frames,
    "detect_duplicates": handle_detect_duplicates,
    "detect_gaps": handle_detect_gaps,
    # Write
    "add_marker": handle_add_marker,
    "batch_add_markers": handle_batch_add_markers,
    "trim_clip": handle_trim_clip,
    "reorder_clips": handle_reorder_clips,
    "add_transition": handle_add_transition,
    "change_speed": handle_change_speed,
    "delete_clips": handle_delete_clips,
    "split_clip": handle_split_clip,
    "insert_clip": handle_insert_clip,
    # Batch Fix
    "fix_flash_frames": handle_fix_flash_frames,
    "rapid_trim": handle_rapid_trim,
    "fill_gaps": handle_fill_gaps,
    "validate_timeline": handle_validate_timeline,
    # Generation
    "auto_rough_cut": handle_auto_rough_cut,
    "generate_montage": handle_generate_montage,
    "generate_ab_roll": handle_generate_ab_roll,
    # Beat Sync
    "import_beat_markers": handle_import_beat_markers,
    "snap_to_beats": handle_snap_to_beats,
    # SRT / Transcript
    "import_srt_markers": handle_import_srt_markers,
    "import_transcript_markers": handle_import_transcript_markers,
    # Connected Clips & Compound Clips (v0.5.0)
    "list_connected_clips": handle_list_connected_clips,
    "add_connected_clip": handle_add_connected_clip,
    "list_compound_clips": handle_list_compound_clips,
    # Roles (v0.5.0)
    "list_roles": handle_list_roles,
    "assign_role": handle_assign_role,
    "filter_by_role": handle_filter_by_role,
    "export_role_stems": handle_export_role_stems,
    # Timeline Diff (v0.5.0)
    "diff_timelines": handle_diff_timelines,
    # Social Media Reformat (v0.5.0)
    "reformat_timeline": handle_reformat_timeline,
    # Silence Detection (v0.5.0)
    "detect_silence_candidates": handle_detect_silence_candidates,
    "remove_silence_candidates": handle_remove_silence_candidates,
    # NLE Export (v0.5.0)
    "export_resolve_xml": handle_export_resolve_xml,
    "export_fcp7_xml": handle_export_fcp7_xml,
}


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        return await handler(arguments)
    except FileNotFoundError as e:
        return [TextContent(type="text", text=f"File not found: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Validation error: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}")]


# ============================================================================
# MAIN
# ============================================================================

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main_sync():
    """Synchronous entry point for use as a console script."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
