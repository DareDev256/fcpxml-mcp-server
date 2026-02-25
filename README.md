# FCPXML MCP

**The bridge between Final Cut Pro and AI. 47 tools that turn timeline XML into structured data Claude can read, edit, and generate.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-1.0-green.svg)](https://modelcontextprotocol.io/)
[![Final Cut Pro](https://img.shields.io/badge/Final%20Cut%20Pro-10.4+-purple.svg)](https://www.apple.com/final-cut-pro/)
[![Tests](https://img.shields.io/badge/tests-454_across_10_suites-brightgreen.svg)](#testing)
[![LOC](https://img.shields.io/badge/codebase-~7k_LOC-informational.svg)](#architecture)

---

## Why This Exists

After directing 350+ music videos (Chief Keef, Migos, Masicka), I noticed the same editing bottlenecks on every project: counting cuts manually, extracting chapter markers one by one, hunting flash frames by scrubbing, building rough cuts clip by clip.

These are batch operations that don't need visual feedback. Export the XML, let Claude handle the tedium, import the result. That's the entire philosophy.

---

## See It In Action

```
You:    "Run a health check on my wedding edit"

Claude: ✓ Analyzed WeddingFinal.fcpxml
        ├─ 247 clips · 42:18 total · 24fps · 1920×1080
        ├─ 3 flash frames detected (clips 44, 112, 198)
        ├─ 2 unintentional gaps at 12:04 and 31:47
        ├─ 14 duplicate source clips
        └─ Health score: 72/100

You:    "Fix the flash frames and gaps, then add chapter markers from
         this transcript"

Claude: ✓ Extended adjacent clips to cover 3 flash frames
        ✓ Filled 2 gaps by extending previous clips
        ✓ Added 18 chapter markers from transcript
        → Saved: WeddingFinal_modified.fcpxml
```

Import the modified XML back into Final Cut Pro. Every change is non-destructive — your original file is never touched.

---

## How It Works

```
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

1. **Export from FCP** — `File → Export XML...`
2. **Ask Claude** — analyze, edit, generate, QC, export
3. **Import back** — `File → Import → XML`

### What This Is NOT

- **Not a plugin** — it doesn't run inside Final Cut Pro
- **Not real-time** — you work with the XML between exports
- **Not for creative calls** — color, framing, motion still need your eyes

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
│   ├── models.py          TimeValue, Timecode, Clip, ConnectedClip, MarkerType, Timeline
│   ├── parser.py          FCPXML → Python (spine, connected clips, roles, markers)
│   ├── writer.py          Modify & write (markers, trim, gaps, transitions, silence)
│   ├── rough_cut.py       Generate timelines (rough cuts, montages, A/B roll)
│   ├── diff.py            Timeline comparison engine
│   └── export.py          DaVinci Resolve v1.9 + FCP7 XMEML v5 export
├── tests/                 444 tests across 10 suites
│   ├── test_models.py     TimeValue math, Timecode formatting, MarkerType contracts
│   ├── test_parser.py     FCPXML parsing, connected clips, edge cases
│   ├── test_writer.py     Clip editing, marker writing, speed changes
│   ├── test_server.py     MCP tool handlers, dispatch, path validation
│   ├── test_rough_cut.py  Rough cut generation, montage, A/B roll
│   ├── test_features_v05.py  Multi-track, roles, diff, reformat, export
│   ├── test_marker_pipeline.py  Marker builder, batch modes, output format
│   └── test_security.py   Input validation, XML sanitization, XXE protection
├── docs/
│   └── WORKFLOWS.md       8 production workflow recipes
└── examples/
    └── sample.fcpxml      9 clips, 24fps — test fixture
```

---

## Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Rational time, never floats** | All durations are fractions (`600/2400s`) matching FCPXML's native format — zero rounding errors across trim, split, speed |
| **Non-destructive by default** | Modified files get `_modified`, `_chapters` suffixes. Originals are never overwritten |
| **Single source of truth** | `MarkerType` enum owns serialization: `from_string()` for input, `from_xml_element()` for parsing, `xml_attrs` for writing |
| **Security-first** | All 47 handlers validate against path traversal, null bytes, symlinks, 100MB limit. XML parsing uses `defusedxml` (XXE, billion laughs, entity expansion) |
| **Dispatch, not conditionals** | `TOOL_HANDLERS` dict maps names → async handlers. No 1000-line if/elif |

---

## Documentation

| Guide | What's Inside |
|-------|---------------|
| **[WORKFLOWS.md](docs/WORKFLOWS.md)** | 8 production recipes — QC pipelines, beat-synced assembly, cross-NLE handoffs, documentary A/B roll |
| **[MCP_ECOSYSTEM.md](docs/MCP_ECOSYSTEM.md)** | How this server composes with GitNexus, filesystem, and memory MCP servers |
| **[CHANGELOG.md](CHANGELOG.md)** | Full version history from v0.1.0 to present |

---

## Testing

```bash
uv run --extra dev pytest tests/ -v    # or: python3 -m pytest tests/ -v
ruff check . --exclude docs/           # lint — must pass before committing
```

454 tests across 10 suites covering models, parser, writer, server handlers, rough cut generation, marker pipeline, security hardening (XXE, entity expansion, input validation), connected clips, roles, diff, export, and backward compatibility.

---

## Requirements

- **Python 3.10+**
- **Final Cut Pro 10.4+** (FCPXML 1.8+)
- **Claude Desktop** or any MCP-compatible client
- **Dependencies:** `mcp`, `lxml`, `defusedxml` (installed automatically)

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
