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
from fcpxml.models import MarkerType, SegmentSpec

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
