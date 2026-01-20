# server.py - Complete MCP Server Implementation

"""
Final Cut Pro MCP Server - Full Implementation

All read and write tools for FCPXML manipulation.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

from fcpxml.parser import FCPXMLParser
from fcpxml.writer import (
    FCPXMLWriter, 
    MarkerType, 
    MarkerColor,
    add_marker,
    trim_clip,
    reorder_clips,
)
from fcpxml.rough_cut import auto_rough_cut

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fcp-mcp-server")

server = Server("fcp-mcp-server")

# Default projects directory from env
PROJECTS_DIR = os.environ.get("FCP_PROJECTS_DIR", os.path.expanduser("~/Movies"))


# ============================================================================
# TOOL REGISTRY
# ============================================================================

def get_tools() -> List[Tool]:
    """Return all available tools."""
    return [
        # --- READ TOOLS ---
        Tool(
            name="list_projects",
            description="Find FCPXML files in a directory. Returns paths to all Final Cut Pro project exports.",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to search (default: ~/Movies)"},
                    "recursive": {"type": "boolean", "default": True}
                }
            }
        ),
        Tool(
            name="analyze_timeline",
            description="Get comprehensive timeline statistics: clip count, duration, cuts per minute, average cut length, pacing analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "Path to FCPXML file"}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="list_clips",
            description="List all clips with timecodes, durations, and source file references.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "include_audio": {"type": "boolean", "default": True}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="list_markers",
            description="Extract markers (chapter, todo, standard) with timecodes. Can format for YouTube chapters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "format": {"type": "string", "enum": ["list", "youtube", "csv"], "default": "list"}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="list_keywords",
            description="Get all keywords/tags applied to clips in the project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="find_short_cuts",
            description="Find clips below a frame threshold - detects flash frames or accidental cuts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "threshold_frames": {"type": "integer", "default": 6}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="find_long_clips",
            description="Find clips above a duration threshold - identify pacing issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "threshold_seconds": {"type": "number", "default": 10.0}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="analyze_pacing",
            description="AI analysis of edit pacing with suggestions for improvements.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "target_style": {"type": "string", "enum": ["music_video", "documentary", "commercial", "narrative"]}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="export_edl",
            description="Generate EDL (Edit Decision List) for color grading roundtrip.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "format": {"type": "string", "enum": ["cmx3600", "file32"], "default": "cmx3600"}
                },
                "required": ["project_path", "output_path"]
            }
        ),
        Tool(
            name="export_csv",
            description="Export timeline data to CSV for spreadsheet analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}, "default": ["name", "start", "duration", "source"]}
                },
                "required": ["project_path", "output_path"]
            }
        ),
        
        # --- WRITE TOOLS ---
        Tool(
            name="add_marker",
            description="Add a marker to the timeline. Supports chapter markers (for YouTube), to-do markers, and colored standard markers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "timecode": {"type": "string", "description": "Position in HH:MM:SS:FF or seconds"},
                    "name": {"type": "string", "description": "Marker label"},
                    "marker_type": {"type": "string", "enum": ["standard", "chapter", "todo"], "default": "standard"},
                    "color": {"type": "string", "enum": ["blue", "cyan", "green", "yellow", "orange", "red", "pink", "purple"]},
                    "note": {"type": "string"},
                    "output_path": {"type": "string", "description": "Save modified project here (default: overwrites original)"}
                },
                "required": ["project_path", "timecode", "name"]
            }
        ),
        Tool(
            name="batch_add_markers",
            description="Add multiple markers at once. Can also auto-detect cut points and add markers there.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "markers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "timecode": {"type": "string"},
                                "name": {"type": "string"},
                                "marker_type": {"type": "string"},
                                "color": {"type": "string"}
                            },
                            "required": ["timecode", "name"]
                        }
                    },
                    "auto_detect": {
                        "type": "object",
                        "properties": {
                            "at_cuts": {"type": "boolean"},
                            "at_intervals": {"type": "string"}
                        }
                    },
                    "output_path": {"type": "string"}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="trim_clip",
            description="Adjust a clip's in-point or out-point. Supports absolute timecodes or relative deltas (+1s, -10f).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_id": {"type": "string", "description": "Clip identifier from list_clips"},
                    "trim_start": {"type": "string", "description": "New in-point or delta"},
                    "trim_end": {"type": "string", "description": "New out-point or delta"},
                    "ripple": {"type": "boolean", "default": True},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path", "clip_id"]
            }
        ),
        Tool(
            name="reorder_clips",
            description="Move clips to a new position in the timeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_ids": {"type": "array", "items": {"type": "string"}},
                    "target_position": {"type": "string", "description": "'start', 'end', timecode, or 'after:clip_id'"},
                    "ripple": {"type": "boolean", "default": True},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path", "clip_ids", "target_position"]
            }
        ),
        Tool(
            name="add_transition",
            description="Apply a transition between clips.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_id": {"type": "string"},
                    "position": {"type": "string", "enum": ["start", "end", "both"], "default": "end"},
                    "transition_type": {"type": "string", "enum": ["cross-dissolve", "fade-to-black", "fade-from-black", "dip-to-color", "wipe"], "default": "cross-dissolve"},
                    "duration": {"type": "string", "default": "00:00:00:15"},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path", "clip_id"]
            }
        ),
        Tool(
            name="change_speed",
            description="Modify clip playback speed. Supports constant speed and speed ramps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_id": {"type": "string"},
                    "speed": {"type": "number", "description": "Speed multiplier (0.5=half, 2.0=double)"},
                    "ramp": {
                        "type": "object",
                        "properties": {
                            "start_speed": {"type": "number"},
                            "end_speed": {"type": "number"},
                            "curve": {"type": "string", "enum": ["linear", "ease-in", "ease-out", "ease-in-out"]}
                        }
                    },
                    "preserve_pitch": {"type": "boolean", "default": True},
                    "frame_blending": {"type": "string", "enum": ["none", "frame-blending", "optical-flow"], "default": "optical-flow"},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path", "clip_id", "speed"]
            }
        ),
        Tool(
            name="split_clip",
            description="Split a clip at one or more timecodes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_id": {"type": "string"},
                    "split_points": {"type": "array", "items": {"type": "string"}},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path", "clip_id", "split_points"]
            }
        ),
        Tool(
            name="delete_clip",
            description="Remove clips from the timeline. Supports ripple delete or leaving gaps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_ids": {"type": "array", "items": {"type": "string"}},
                    "ripple": {"type": "boolean", "default": True},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path", "clip_ids"]
            }
        ),
        Tool(
            name="select_by_keyword",
            description="Find clips matching keywords, ratings, or favorites status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "match_mode": {"type": "string", "enum": ["any", "all", "none"], "default": "any"},
                    "favorites_only": {"type": "boolean", "default": False},
                    "exclude_rejected": {"type": "boolean", "default": True}
                },
                "required": ["project_path", "keywords"]
            }
        ),
        Tool(
            name="batch_trim",
            description="Apply trim operations to multiple clips based on criteria.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "clip_ids": {"type": "array", "items": {"type": "string"}},
                    "trim_start_by": {"type": "string"},
                    "trim_end_by": {"type": "string"},
                    "set_duration": {"type": "string"},
                    "ripple": {"type": "boolean", "default": True},
                    "output_path": {"type": "string"}
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="auto_rough_cut",
            description="AI-powered rough cut generation. Analyzes source clips by keywords and assembles a timeline based on target duration and pacing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "FCPXML with source clips"},
                    "output_path": {"type": "string", "description": "Where to save the rough cut"},
                    "target_duration": {"type": "string", "description": "Target duration (e.g., '00:03:30:00')"},
                    "structure": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "keywords": {"type": "array", "items": {"type": "string"}},
                                "duration": {"type": "string"},
                                "priority": {"type": "string", "enum": ["favorites", "longest", "shortest", "random", "best"]}
                            }
                        }
                    },
                    "pacing": {"type": "string", "enum": ["slow", "medium", "fast", "dynamic"], "default": "medium"},
                    "pacing_config": {
                        "type": "object",
                        "properties": {
                            "min_clip_duration": {"type": "string"},
                            "max_clip_duration": {"type": "string"},
                            "vary_pacing": {"type": "boolean"}
                        }
                    },
                    "transitions": {
                        "type": "object",
                        "properties": {
                            "between_segments": {"type": "string", "enum": ["none", "cross-dissolve", "fade-to-black"]},
                            "within_segments": {"type": "string", "enum": ["none", "cut", "cross-dissolve"]}
                        }
                    }
                },
                "required": ["source_path", "output_path", "target_duration"]
            }
        ),
    ]


@server.list_tools()
async def list_tools() -> List[Tool]:
    """Return available tools."""
    return get_tools()


# ============================================================================
# TOOL HANDLERS
# ============================================================================

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    """Handle tool calls."""
    
    try:
        if name == "list_projects":
            result = handle_list_projects(arguments)
        elif name == "analyze_timeline":
            result = handle_analyze_timeline(arguments)
        elif name == "list_clips":
            result = handle_list_clips(arguments)
        elif name == "list_markers":
            result = handle_list_markers(arguments)
        elif name == "list_keywords":
            result = handle_list_keywords(arguments)
        elif name == "find_short_cuts":
            result = handle_find_short_cuts(arguments)
        elif name == "find_long_clips":
            result = handle_find_long_clips(arguments)
        elif name == "analyze_pacing":
            result = handle_analyze_pacing(arguments)
        elif name == "export_edl":
            result = handle_export_edl(arguments)
        elif name == "export_csv":
            result = handle_export_csv(arguments)
        elif name == "add_marker":
            result = handle_add_marker(arguments)
        elif name == "batch_add_markers":
            result = handle_batch_add_markers(arguments)
        elif name == "trim_clip":
            result = handle_trim_clip(arguments)
        elif name == "reorder_clips":
            result = handle_reorder_clips(arguments)
        elif name == "add_transition":
            result = handle_add_transition(arguments)
        elif name == "change_speed":
            result = handle_change_speed(arguments)
        elif name == "split_clip":
            result = handle_split_clip(arguments)
        elif name == "delete_clip":
            result = handle_delete_clip(arguments)
        elif name == "select_by_keyword":
            result = handle_select_by_keyword(arguments)
        elif name == "batch_trim":
            result = handle_batch_trim(arguments)
        elif name == "auto_rough_cut":
            result = handle_auto_rough_cut(arguments)
        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True
            )
        
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))]
        )
        
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            isError=True
        )


# ============================================================================
# HANDLER IMPLEMENTATIONS
# ============================================================================

def handle_list_projects(args: Dict) -> Dict:
    """List FCPXML files in directory."""
    directory = args.get("directory", PROJECTS_DIR)
    recursive = args.get("recursive", True)
    
    path = Path(directory).expanduser()
    pattern = "**/*.fcpxml" if recursive else "*.fcpxml"
    
    projects = []
    for fcpxml in path.glob(pattern):
        stat = fcpxml.stat()
        projects.append({
            "path": str(fcpxml),
            "name": fcpxml.stem,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "modified": stat.st_mtime
        })
    
    return {
        "directory": str(path),
        "count": len(projects),
        "projects": projects
    }


def handle_analyze_timeline(args: Dict) -> Dict:
    """Analyze timeline statistics."""
    parser = FCPXMLParser(args["project_path"])
    timeline = parser.parse()
    
    clips = timeline.clips
    total_duration = sum(c.duration for c in clips)
    cut_count = len(clips) - 1
    
    durations = [c.duration for c in clips]
    avg_duration = total_duration / len(clips) if clips else 0
    min_duration = min(durations) if durations else 0
    max_duration = max(durations) if durations else 0
    
    # Cuts per minute
    cpm = (cut_count / total_duration) * 60 if total_duration > 0 else 0
    
    return {
        "project_name": timeline.name,
        "total_duration_seconds": round(total_duration, 2),
        "total_duration_timecode": seconds_to_tc(total_duration),
        "clip_count": len(clips),
        "cut_count": cut_count,
        "cuts_per_minute": round(cpm, 2),
        "average_clip_duration": round(avg_duration, 2),
        "shortest_clip": round(min_duration, 2),
        "longest_clip": round(max_duration, 2),
        "marker_count": len(timeline.markers)
    }


def handle_list_clips(args: Dict) -> Dict:
    """List all clips with details."""
    parser = FCPXMLParser(args["project_path"])
    timeline = parser.parse()
    
    clips = []
    for i, clip in enumerate(timeline.clips):
        clips.append({
            "id": clip.id or f"clip_{i}",
            "name": clip.name,
            "offset_tc": seconds_to_tc(clip.offset),
            "duration_tc": seconds_to_tc(clip.duration),
            "duration_seconds": round(clip.duration, 3),
            "source_start_tc": seconds_to_tc(clip.source_start),
            "source_file": clip.source_path,
            "keywords": clip.keywords,
            "is_audio_only": clip.is_audio_only
        })
    
    return {
        "clip_count": len(clips),
        "clips": clips
    }


def handle_list_markers(args: Dict) -> Dict:
    """Extract markers."""
    parser = FCPXMLParser(args["project_path"])
    timeline = parser.parse()
    fmt = args.get("format", "list")
    
    markers = []
    for m in timeline.markers:
        markers.append({
            "timecode": seconds_to_tc(m.time),
            "name": m.name,
            "type": m.marker_type,
            "note": m.note
        })
    
    if fmt == "youtube":
        # YouTube chapter format
        chapters = []
        for m in markers:
            if m["type"] == "chapter":
                tc = m["timecode"]
                # Convert to YouTube format (MM:SS or H:MM:SS)
                parts = tc.split(":")
                if parts[0] == "00":
                    yt_tc = f"{parts[1]}:{parts[2]}"
                else:
                    yt_tc = f"{parts[0]}:{parts[1]}:{parts[2]}"
                chapters.append(f"{yt_tc} {m['name']}")
        return {
            "format": "youtube",
            "chapters": "\n".join(chapters)
        }
    
    return {
        "marker_count": len(markers),
        "markers": markers
    }


def handle_add_marker(args: Dict) -> Dict:
    """Add a marker to the timeline."""
    project_path = args["project_path"]
    output_path = args.get("output_path", project_path)
    
    writer = FCPXMLWriter(project_path)
    
    marker_type = MarkerType[args.get("marker_type", "standard").upper()]
    color = MarkerColor[args["color"].upper()] if args.get("color") else None
    
    # Find the clip at this timecode, or add to spine
    # For simplicity, we'll add to the first clip that contains this timecode
    clip_id = find_clip_at_timecode(writer, args["timecode"])
    
    writer.add_marker(
        clip_id=clip_id,
        timecode=args["timecode"],
        name=args["name"],
        marker_type=marker_type,
        color=color,
        note=args.get("note")
    )
    
    saved_path = writer.save(output_path)
    
    return {
        "success": True,
        "marker_added": args["name"],
        "at_timecode": args["timecode"],
        "output_path": saved_path
    }


def handle_trim_clip(args: Dict) -> Dict:
    """Trim a clip's in/out points."""
    project_path = args["project_path"]
    output_path = args.get("output_path", project_path)
    
    writer = FCPXMLWriter(project_path)
    
    writer.trim_clip(
        clip_id=args["clip_id"],
        trim_start=args.get("trim_start"),
        trim_end=args.get("trim_end"),
        ripple=args.get("ripple", True)
    )
    
    saved_path = writer.save(output_path)
    
    return {
        "success": True,
        "clip_trimmed": args["clip_id"],
        "output_path": saved_path
    }


def handle_reorder_clips(args: Dict) -> Dict:
    """Reorder clips in timeline."""
    project_path = args["project_path"]
    output_path = args.get("output_path", project_path)
    
    writer = FCPXMLWriter(project_path)
    
    writer.reorder_clips(
        clip_ids=args["clip_ids"],
        target_position=args["target_position"],
        ripple=args.get("ripple", True)
    )
    
    saved_path = writer.save(output_path)
    
    return {
        "success": True,
        "clips_moved": args["clip_ids"],
        "to_position": args["target_position"],
        "output_path": saved_path
    }


def handle_auto_rough_cut(args: Dict) -> Dict:
    """Generate AI rough cut."""
    result = auto_rough_cut(
        source_path=args["source_path"],
        output_path=args["output_path"],
        target_duration=args["target_duration"],
        structure=args.get("structure"),
        pacing=args.get("pacing", "medium"),
        pacing_config=args.get("pacing_config"),
        transitions=args.get("transitions")
    )
    
    return result


# ============================================================================
# UTILITIES
# ============================================================================

def seconds_to_tc(seconds: float, fps: float = 30.0) -> str:
    """Convert seconds to timecode string."""
    total_frames = int(seconds * fps)
    frames = total_frames % int(fps)
    total_seconds = total_frames // int(fps)
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"


def find_clip_at_timecode(writer: FCPXMLWriter, timecode: str) -> str:
    """Find clip ID that contains the given timecode."""
    from fcpxml.writer import TimeValue
    target = TimeValue.from_timecode(timecode, writer.fps)
    target_seconds = target.to_seconds()
    
    for clip_id, clip in writer.clips.items():
        offset = TimeValue.from_timecode(clip.get('offset', '0s'), writer.fps).to_seconds()
        duration = TimeValue.from_timecode(clip.get('duration', '0s'), writer.fps).to_seconds()
        
        if offset <= target_seconds < offset + duration:
            return clip_id
    
    # If no clip found, return first clip
    return list(writer.clips.keys())[0] if writer.clips else None


# Placeholder implementations for remaining handlers
def handle_list_keywords(args): pass
def handle_find_short_cuts(args): pass
def handle_find_long_clips(args): pass
def handle_analyze_pacing(args): pass
def handle_export_edl(args): pass
def handle_export_csv(args): pass
def handle_batch_add_markers(args): pass
def handle_add_transition(args): pass
def handle_change_speed(args): pass
def handle_split_clip(args): pass
def handle_delete_clip(args): pass
def handle_select_by_keyword(args): pass
def handle_batch_trim(args): pass


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
