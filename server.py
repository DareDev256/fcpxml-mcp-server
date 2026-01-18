#!/usr/bin/env python3
"""
Final Cut Pro MCP Server - The first AI-powered MCP server for Final Cut Pro.
Author: DareDev256 (https://github.com/DareDev256)
"""

import os
from pathlib import Path
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from fcpxml.parser import FCPXMLParser
from fcpxml.models import MarkerType

server = Server("fcp-mcp-server")
PROJECTS_DIR = os.environ.get("FCP_PROJECTS_DIR", os.path.expanduser("~/Movies"))


def find_fcpxml_files(directory: str) -> list[str]:
    path = Path(directory)
    files = list(str(f) for f in path.rglob("*.fcpxml"))
    files.extend(str(f) for f in path.rglob("*.fcpxmld"))
    return files


def format_timecode(tc) -> str:
    return tc.to_smpte() if tc else "00:00:00:00"


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    return f"{int(seconds // 60)}m {seconds % 60:.1f}s"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="list_projects", description="List all FCPXML projects in directory",
             inputSchema={"type": "object", "properties": {"directory": {"type": "string"}}}),
        Tool(name="analyze_timeline", description="Get comprehensive timeline statistics",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}),
        Tool(name="list_clips", description="List all clips with timecodes and durations",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["filepath"]}),
        Tool(name="list_markers", description="Extract markers (chapter, todo, standard)",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}, "marker_type": {"type": "string", "enum": ["all", "chapter", "todo", "standard"]}, "format": {"type": "string", "enum": ["detailed", "youtube", "simple"]}}, "required": ["filepath"]}),
        Tool(name="find_short_cuts", description="Find clips shorter than threshold (flash frame detection)",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}, "threshold_seconds": {"type": "number"}}, "required": ["filepath"]}),
        Tool(name="find_long_clips", description="Find clips longer than threshold",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}, "threshold_seconds": {"type": "number"}}, "required": ["filepath"]}),
        Tool(name="list_keywords", description="Extract all keywords/tags from project",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}),
        Tool(name="export_edl", description="Generate EDL from timeline",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}),
        Tool(name="export_csv", description="Export timeline data to CSV",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}, "include": {"type": "array", "items": {"type": "string"}}}, "required": ["filepath"]}),
        Tool(name="analyze_pacing", description="Analyze edit pacing with suggestions",
             inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    try:
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
            result = f"# Clips in {tl.name}\n\n| # | Name | Start | Duration |\n|---|------|-------|----------|\n"
            for i, c in enumerate(clips, 1):
                result += f"| {i} | {c.name} | {format_timecode(c.start)} | {format_duration(c.duration_seconds)} |\n"
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
            csv = "Name,Start,End,Duration\n"
            for c in tl.clips:
                csv += f'"{c.name}",{format_timecode(c.start)},{format_timecode(c.end)},{c.duration_seconds:.3f}\n'
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
                suggestions.append(f"📹 {len(long)} long takes (> 30s)")
            if len(seg_avgs) >= 4 and seg_avgs[3] < seg_avgs[0] * 0.7:
                suggestions.append("🎬 Pacing accelerates toward end")
            result = f"""# Pacing Analysis: {tl.name}

- **Avg Cut**: {format_duration(avg)}
- **Cuts/Min**: {(tl.total_cuts / (tl.duration.seconds / 60)):.1f}

## By Section
| Q1 | Q2 | Q3 | Q4 |
|----|----|----|----|
| {format_duration(seg_avgs[0]) if len(seg_avgs) > 0 else 'N/A'} | {format_duration(seg_avgs[1]) if len(seg_avgs) > 1 else 'N/A'} | {format_duration(seg_avgs[2]) if len(seg_avgs) > 2 else 'N/A'} | {format_duration(seg_avgs[3]) if len(seg_avgs) > 3 else 'N/A'} |

## Suggestions
{"".join(f"- {s}\n" for s in suggestions) if suggestions else "- ✅ No issues detected"}
"""
            return [TextContent(type="text", text=result)]
        
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
