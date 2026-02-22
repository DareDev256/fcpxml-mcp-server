# FCPXML MCP

**47 tools for Final Cut Pro timelines — analysis, batch editing, QC, generation, and cross-NLE export — driven by Claude.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-1.0-green.svg)](https://modelcontextprotocol.io/)
[![Final Cut Pro](https://img.shields.io/badge/Final%20Cut%20Pro-10.4+-purple.svg)](https://www.apple.com/final-cut-pro/)
[![Tests](https://img.shields.io/badge/tests-348-brightgreen.svg)](#testing)

---

## Why This Exists

After directing 350+ music videos (Chief Keef, Migos, Masicka), I noticed the same editing bottlenecks on every project: counting cuts manually, extracting chapter markers one by one, hunting flash frames by scrubbing, building rough cuts clip by clip.

These are batch operations that don't need visual feedback. Export the XML, let Claude handle the tedium, import the result. That's the entire philosophy.

---

## How It Works

```
                    FCPXML MCP Server
                    ─────────────────
  ┌──────────┐      ┌──────────────────────────────┐      ┌──────────┐
  │ Final Cut│      │  parser.py   → Python objects │      │ Final Cut│
  │   Pro    │─XML─>│  writer.py   → Modify & save  │─XML─>│   Pro    │
  │          │      │  rough_cut.py→ Generate new   │      │          │
  └──────────┘      │  diff.py     → Compare        │      └──────────┘
                    │  export.py   → Resolve / FCP7 │
                    └──────────────────────────────┘
                              ▲
                     Claude Desktop / MCP client
```

1. **Export from FCP**: `File → Export XML...`
2. **Run MCP tools**: Analyze, modify, generate via Claude
3. **Import back**: `File → Import → XML`

This is a roundtrip workflow. Each edit cycle is an export-and-import.

### What This Is NOT

- **Not a plugin** that runs inside Final Cut Pro
- **Not real-time editing** — you work with the XML between exports
- **Not a replacement** for creative decisions that need visual feedback

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/DareDev256/fcp-mcp-server.git
cd fcp-mcp-server
pip install -e .
```

### 2. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

**Using uv (recommended):**
```json
{
  "mcpServers": {
    "fcpxml": {
      "command": "uv",
      "args": ["--directory", "/path/to/fcp-mcp-server", "run", "server.py"],
      "env": { "FCP_PROJECTS_DIR": "/Users/you/Movies" }
    }
  }
}
```

**Using pip:**
```json
{
  "mcpServers": {
    "fcpxml": {
      "command": "python",
      "args": ["/path/to/fcp-mcp-server/server.py"],
      "env": { "FCP_PROJECTS_DIR": "/Users/you/Movies" }
    }
  }
}
```

### 3. Use It

Export XML from Final Cut Pro, open Claude Desktop, and ask it to work with your timeline.

---

## When To Use This

| Good For | Not Ideal For |
|----------|---------------|
| Batch marker insertion (100 chapters from a transcript) | Creative editing decisions (no visual feedback) |
| QC before delivery (flash frames, gaps, duplicates) | Real-time adjustments (export/import cycle) |
| Data extraction (EDL, CSV, chapter markers) | Fine-tuning cuts (faster directly in FCP) |
| Template generation (rough cuts from tagged clips) | Anything visual (color, framing, motion) |
| Automated assembly (montages from keywords + pacing) | |
| Timeline health checks (validation, stats, scoring) | |

---

## Pre-Built Workflows

Select these from Claude's prompt menu — they chain multiple tools together automatically.

| Prompt | What It Does |
|--------|-------------|
| **qc-check** | Full quality control — flash frames, gaps, duplicates, health score |
| **youtube-chapters** | Extract chapter markers formatted for YouTube descriptions |
| **rough-cut** | Guided rough cut — shows clips, suggests structure, generates |
| **timeline-summary** | Quick overview — stats, pacing, keywords, markers, assessment |
| **cleanup** | Find and auto-fix flash frames and gaps |

---

## All 47 Tools

### Analysis — 11 tools
| Tool | Description |
|------|-------------|
| `list_projects` | Find all FCPXML files in a directory |
| `analyze_timeline` | Stats on duration, resolution, pacing |
| `list_clips` | All clips with timecodes, durations, keywords |
| `list_library_clips` | Source clips available in the library |
| `list_markers` | Markers with timestamps (YouTube chapter format) |
| `find_short_cuts` | Potential flash frames (< threshold) |
| `find_long_clips` | Clips that might need trimming |
| `list_keywords` | All keywords/tags from project |
| `export_edl` | EDL for color/audio handoffs |
| `export_csv` | Timeline data to CSV |
| `analyze_pacing` | Pacing metrics with suggestions |

### Multi-Track & Connected Clips — 3 tools
| Tool | Description |
|------|-------------|
| `list_connected_clips` | B-roll, titles, audio on secondary lanes |
| `add_connected_clip` | Attach a clip at a specified lane |
| `list_compound_clips` | Inspect ref-clip compound clips |

### Roles — 4 tools
| Tool | Description |
|------|-------------|
| `list_roles` | Audio/video roles with clip counts |
| `assign_role` | Set role on a clip |
| `filter_by_role` | Clips matching a specific role |
| `export_role_stems` | Clip list grouped by role for mixing |

### QC & Validation — 4 tools
| Tool | Description |
|------|-------------|
| `detect_flash_frames` | Ultra-short clips with severity levels |
| `detect_duplicates` | Clips using same source media |
| `detect_gaps` | Unintentional gaps in timeline |
| `validate_timeline` | Health check with score (0-100%) |

### Editing — 9 tools
| Tool | Description |
|------|-------------|
| `add_marker` | Single marker at a timecode |
| `batch_add_markers` | Multiple markers, or auto-generate at cuts/intervals |
| `insert_clip` | Library clip onto timeline at any position |
| `trim_clip` | Adjust in/out points with optional ripple |
| `reorder_clips` | Move clips to new positions |
| `add_transition` | Cross-dissolve, fade, wipe between clips |
| `change_speed` | Slow motion or speed ramps |
| `delete_clips` | Remove clips with optional ripple |
| `split_clip` | Split at specified timecodes |

### Batch Fixes — 3 tools
| Tool | Description |
|------|-------------|
| `fix_flash_frames` | Auto-fix by extending neighbors or deleting |
| `rapid_trim` | Batch trim clips to max duration |
| `fill_gaps` | Close gaps by extending adjacent clips |

### Timeline Comparison — 1 tool
| Tool | Description |
|------|-------------|
| `diff_timelines` | Compare two FCPXMLs — added/removed/moved/trimmed clips |

### Reformat — 1 tool
| Tool | Description |
|------|-------------|
| `reformat_timeline` | New resolution (9:16, 1:1, 4:5, 4:3, custom) |

### Silence Detection — 2 tools
| Tool | Description |
|------|-------------|
| `detect_silence_candidates` | Flag potential silence via heuristics |
| `remove_silence_candidates` | Delete or mark detected silence candidates |

### NLE Export — 2 tools
| Tool | Description |
|------|-------------|
| `export_resolve_xml` | FCPXML v1.9 for DaVinci Resolve |
| `export_fcp7_xml` | XMEML for Premiere Pro / Resolve / Avid |

### Generation — 3 tools
| Tool | Description |
|------|-------------|
| `auto_rough_cut` | Timeline from keywords, duration, pacing |
| `generate_montage` | Montages with pacing curves (accelerating/decelerating/pyramid) |
| `generate_ab_roll` | Documentary-style A/B roll alternating edits |

### Beat Sync — 2 tools
| Tool | Description |
|------|-------------|
| `import_beat_markers` | Import beat markers from JSON audio analysis |
| `snap_to_beats` | Align cuts to nearest beat markers |

### Import — 2 tools
| Tool | Description |
|------|-------------|
| `import_srt_markers` | SRT/VTT subtitles into timeline markers |
| `import_transcript_markers` | Timestamped text (YouTube chapters) into markers |

---

## Architecture

```
fcp-mcp-server/           ~7k lines Python
├── server.py              MCP entry point — 47 tools, 5 prompts, resource discovery
├── fcpxml/
│   ├── parser.py          FCPXML → Python (spine, connected clips, roles)
│   ├── writer.py          Modify & write (markers, trim, gaps, transitions, silence)
│   ├── rough_cut.py       Generate timelines (rough cuts, montages, A/B roll)
│   ├── diff.py            Timeline comparison engine
│   ├── export.py          DaVinci Resolve v1.9 + FCP7 XMEML v5 export
│   └── models.py          TimeValue, Timecode, Clip, ConnectedClip, Timeline
├── tests/                 348 tests across 8 files
└── examples/
    └── sample.fcpxml      9 clips, 24fps — test fixture
```

**Key design decisions:**
- **Rational time arithmetic** — all times are fractions (`600/2400s`), never floats. Matches FCPXML's native format and eliminates rounding errors.
- **Dispatch dict pattern** — `TOOL_HANDLERS` maps tool names to async handlers. No 1000-line if/elif chains.
- **Non-destructive output** — modified files get `_modified`, `_chapters`, etc. suffixes. Originals are never overwritten.
- **Path validation** — all 47 handlers validate inputs against traversal attacks, null bytes, symlinks, and a 100MB size limit.

---

## Usage Examples

```
"Analyze my latest FCP project"
"Add chapter markers at these timestamps: [list]"
"Export an EDL for the colorist"
"Create a 3-minute rough cut using clips tagged 'broll'"
"Run a health check on my timeline"
"Snap all cuts to the nearest beat"
"Fix all flash frames by extending previous clips"
"Generate a montage with accelerating pacing"
"Compare my current edit with yesterday's version"
"Reformat my timeline for Instagram Reels (9:16)"
```

For multi-step workflow recipes (QC pipelines, beat-synced assembly, cross-NLE handoffs), see **[docs/WORKFLOWS.md](docs/WORKFLOWS.md)**.

---

## Testing

```bash
uv run --extra dev pytest tests/ -v    # or: python3 -m pytest tests/ -v
ruff check . --exclude docs/           # lint — must pass before committing
```

348 tests covering models, parser, writer, server handlers, rough cut generation, connected clips, roles, diff, export, and backward compatibility.

---

## Requirements

- **Python 3.10+**
- **Final Cut Pro 10.4+** (FCPXML 1.8+)
- **Claude Desktop** or any MCP-compatible client
- **Dependencies:** `mcp`, `lxml` (installed automatically)

---

## Releases

See [CHANGELOG.md](CHANGELOG.md) for full version history.

**Latest: v0.5.3** — Workflow recipes guide, multi-track connected clips, roles management, timeline diff, silence detection, DaVinci Resolve + FCP7 XMEML export. 47 tools.

---

## Roadmap

- [x] Core FCPXML parsing (v1.8–1.11)
- [x] Timeline analysis, markers, EDL/CSV export
- [x] Clip editing (trim, reorder, split, speed, transitions)
- [x] QC tools (flash frames, gaps, duplicates, health scoring)
- [x] Generation (rough cuts, montages, A/B roll, beat sync)
- [x] MCP Prompts + Resources (auto-discovery)
- [x] Subtitle & transcript import as markers
- [x] Multi-track (connected clips, compound clips, roles)
- [x] Timeline diff + social media reformat
- [x] Silence detection & cleanup
- [x] Cross-NLE export (DaVinci Resolve, Premiere Pro, Avid)
- [ ] Audio sync detection
- [ ] Premiere Pro native XML support

---

## Contributing

PRs welcome. If you're a video editor who codes (or a coder who edits), let's build this together.

## Credits

Built by [@DareDev256](https://github.com/DareDev256) — former music video director (350+ videos), now building AI tools for creators.

## License

MIT — see [LICENSE](LICENSE).
