# FCPXML MCP

**The bridge between Final Cut Pro and AI. 53 tools that turn timeline XML into structured data Claude can read, edit, and generate.**

[![CI](https://github.com/DareDev256/fcpxml-mcp-server/actions/workflows/test.yml/badge.svg)](https://github.com/DareDev256/fcpxml-mcp-server/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-1.0-green.svg)](https://modelcontextprotocol.io/)
[![Final Cut Pro](https://img.shields.io/badge/Final%20Cut%20Pro-10.4+-purple.svg)](https://www.apple.com/final-cut-pro/)
[![Tests](https://img.shields.io/badge/tests-604_passing-brightgreen.svg)](#testing)
[![Suites](https://img.shields.io/badge/suites-11-blue.svg)](#testing)
[![Source](https://img.shields.io/badge/source-~9k_LOC-informational.svg)](#architecture)

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

## What Claude Actually Sees

This is the magic trick. When you export XML from Final Cut Pro, your timeline becomes structured data that Claude can reason about:

```xml
<!-- What FCP exports -->
<asset-clip ref="r2" offset="342/24s" name="Interview_A"
            start="120s" duration="720/24s" format="r1">
    <marker start="48/24s" duration="1/24s" value="Key quote"/>
    <keyword start="0s" duration="720/24s" value="Interview"/>
</asset-clip>
```

```python
# What Claude works with (after parsing)
Clip(
    name="Interview_A",
    offset=TimeValue(342, 24),   # timeline position: 14.25s
    start=TimeValue(120, 1),     # source in-point: 2:00
    duration=TimeValue(720, 24), # 30 seconds
    markers=[Marker(value="Key quote", start=TimeValue(48, 24))],
    keywords=["Interview"]
)
```

Every time value stays as a rational fraction — `720/24s`, not `30.0` — so trim, split, and speed operations have **zero rounding error** across any frame rate.

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

## Prompt Cookbook

Copy-paste these into Claude Desktop. Each one maps to a real tool chain under the hood.

**Analysis**
```
"Give me a full breakdown of ProjectX.fcpxml — clips, duration, frame rate, markers, everything"
"Show me pacing analysis for my timeline — where are the slow sections?"
"Export an EDL and CSV of all clips with timecodes"
```

**QC & Fixes**
```
"Run a health check on my timeline and fix anything under 2 frames"
"Find all gaps and flash frames, then auto-fix them"
"Are there any duplicate source clips I can consolidate?"
```

**Markers & Chapters**
```
"Add chapter markers from this transcript: [paste transcript]"
"Import markers from my-subtitles.srt onto the timeline"
"List all markers and export them as YouTube chapter timestamps"
```

**Generation**
```
"Build a 60-second rough cut from clips tagged 'Interview' — medium pacing"
"Generate a montage from all B-roll clips with accelerating pacing"
"Create an A/B roll: Interview_A as primary, B-roll cuts every 8 seconds"
```

**Cross-NLE & Reformat**
```
"Export this timeline for DaVinci Resolve"
"Convert to FCP7 XML so I can open it in Premiere"
"Reformat my 16:9 timeline to 9:16 for Instagram Reels"
```

### Under the Hood

When you say *"Run a health check on my wedding edit"*, Claude chains these tools:

```
analyze_timeline  →  stats, frame rate, resolution
detect_flash_frames  →  clips under threshold duration
detect_gaps  →  unintentional silence/black
detect_duplicates  →  repeated source media
validate_timeline  →  structural health score (0-100)
```

Each tool returns structured text that Claude synthesizes into the summary you see. No magic — just batch XML queries that would take 20 minutes by hand.

---

## Pre-Built Prompts

Select these from Claude's prompt menu (⌘/) — they chain multiple tools automatically.

| Prompt | What It Does |
|--------|-------------|
| **qc-check** | Full quality control — flash frames, gaps, duplicates, health score |
| **youtube-chapters** | Extract chapter markers formatted for YouTube descriptions |
| **rough-cut** | Guided rough cut — shows clips, suggests structure, generates |
| **timeline-summary** | Quick overview — stats, pacing, keywords, markers, assessment |
| **cleanup** | Find and auto-fix flash frames and gaps |

---

## All 47 Tools

| Category | Count | What It Does |
|----------|------:|--------------|
| **Analysis** | 11 | Stats, clips, markers, keywords, EDL/CSV, pacing |
| **Multi-Track** | 3 | Connected clips, compound clips, secondary lanes |
| **Roles** | 4 | List, assign, filter, export stems |
| **QC & Validation** | 4 | Flash frames, duplicates, gaps, health score |
| **Editing** | 9 | Markers, trim, reorder, transitions, speed, split |
| **Batch Fixes** | 3 | Auto-fix flash frames, rapid trim, fill gaps |
| **Comparison** | 1 | Diff two timelines — added/removed/moved/trimmed |
| **Reformat** | 1 | Aspect ratio conversion (9:16, 1:1, 4:5, custom) |
| **Silence** | 2 | Detect and remove silence candidates |
| **NLE Export** | 2 | DaVinci Resolve v1.9, FCP7 XMEML v5 |
| **Generation** | 3 | Rough cuts, montages, A/B roll |
| **Beat Sync** | 2 | Import beat markers, snap cuts to beats |
| **Import** | 2 | SRT/VTT subtitles, YouTube chapters → markers |
| **Audio** | 1 | Add audio clips, music beds at any lane |
| **Compound** | 2 | Create/flatten compound clips |
| **Templates** | 2 | Pre-built timeline structures (intro/outro, lower thirds, music video) |
| **Effects** | 1 | List FCP transition effects with UUIDs |

<details>
<summary><strong>Full tool reference (click to expand)</strong></summary>

#### Analysis — 11 tools
`list_projects` · `analyze_timeline` · `list_clips` · `list_library_clips` · `list_markers` · `find_short_cuts` · `find_long_clips` · `list_keywords` · `export_edl` · `export_csv` · `analyze_pacing`

#### Multi-Track — 3 tools
`list_connected_clips` · `add_connected_clip` · `list_compound_clips`

#### Roles — 4 tools
`list_roles` · `assign_role` · `filter_by_role` · `export_role_stems`

#### QC & Validation — 4 tools
`detect_flash_frames` · `detect_duplicates` · `detect_gaps` · `validate_timeline`

#### Editing — 9 tools
`add_marker` · `batch_add_markers` · `insert_clip` · `trim_clip` · `reorder_clips` · `add_transition` · `change_speed` · `delete_clips` · `split_clip`

#### Batch Fixes — 3 tools
`fix_flash_frames` · `rapid_trim` · `fill_gaps`

#### Comparison · Reformat · Silence
`diff_timelines` · `reformat_timeline` · `detect_silence_candidates` · `remove_silence_candidates`

#### NLE Export — 2 tools
`export_resolve_xml` (DaVinci Resolve FCPXML v1.9) · `export_fcp7_xml` (Premiere Pro / Resolve / Avid XMEML v5)

#### Generation — 3 tools
`auto_rough_cut` · `generate_montage` · `generate_ab_roll`

#### Beat Sync — 2 tools
`import_beat_markers` · `snap_to_beats`

#### Import — 2 tools
`import_srt_markers` · `import_transcript_markers`

#### v0.6.0 — Audio, Compound, Templates, Effects — 6 tools
`list_effects` · `add_audio` · `create_compound_clip` · `flatten_compound_clip` · `list_templates` · `apply_template`

</details>

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FCP_PROJECTS_DIR` | No | `~/Movies` | Root directory for FCPXML file discovery via `list_projects` |
| `OPENAI_BASE_URL` | No | — | Route LLM calls through any OpenAI-compatible proxy (LiteLLM, OpenRouter, Ollama, vLLM) |

---

## Compatibility

| Component | Supported Versions |
|-----------|--------------------|
| FCPXML format | v1.8 – v1.11 |
| Final Cut Pro | 10.4+ |
| Python | 3.10, 3.11, 3.12 |
| MCP protocol | 1.0 |
| **Export targets** | |
| → DaVinci Resolve | FCPXML v1.9 |
| → Premiere Pro / Avid | FCP7 XMEML v5 |

---

## Architecture

```
fcp-mcp-server/           ~7k lines Python
├── server.py              MCP entry point — 53 tools, 5 prompts, resource discovery
├── fcpxml/
│   ├── models.py          TimeValue, Timecode, Clip, ConnectedClip, MarkerType, Timeline
│   ├── parser.py          FCPXML → Python (spine, connected clips, roles, markers)
│   ├── writer.py          Modify & write (markers, trim, gaps, transitions, silence)
│   ├── rough_cut.py       Generate timelines (rough cuts, montages, A/B roll)
│   ├── diff.py            Timeline comparison engine
│   └── export.py          DaVinci Resolve v1.9 + FCP7 XMEML v5 export
├── tests/                 501 tests across 10 suites
│   ├── test_models.py     TimeValue math, Timecode formatting, MarkerType contracts
│   ├── test_parser.py     FCPXML parsing, connected clips, edge cases
│   ├── test_writer.py     Clip editing, marker writing, speed changes
│   ├── test_server.py     MCP tool handlers, dispatch, path validation
│   ├── test_rough_cut.py  Rough cut generation, montage, A/B roll
│   ├── test_features_v05.py  Multi-track, roles, diff, reformat, export
│   ├── test_marker_pipeline.py  Marker builder, batch modes, output format
│   ├── test_pipeline_roundtrip.py  Write→parse symmetry at multiple frame rates
│   └── test_security.py   Input validation, XML sanitization, XXE protection
├── docs/
│   └── WORKFLOWS.md       8 production workflow recipes
└── examples/
    └── sample.fcpxml      9 clips, 24fps — test fixture
```

---

## Security

Every tool handler is hardened against adversarial input — critical for MCP servers where prompts may be LLM-generated, not human-typed.

| Layer | Protection |
|-------|------------|
| **File I/O** | Path traversal blocked, null bytes rejected, symlinks resolved, 100 MB size limit |
| **Output sandbox** | `_validate_output_path(anchor_dir=...)` restricts writes to descendants of the source file's directory |
| **Directory listing** | Confined to `FCP_PROJECTS_DIR` when set — prevents workspace enumeration |
| **XML parsing** | `defusedxml` blocks XXE, billion laughs, entity expansion, remote DTD attacks |
| **Marker strings** | Sanitized via `_sanitize_xml_value()` — null bytes, control chars stripped before write |
| **Role values** | Stripped of control characters before XML attribute assignment |
| **Output suffixes** | Path separators and special characters stripped — no traversal via suffix injection |
| **Marker types** | `completed` attribute strict-matched (`'0'`/`'1'` only) — rejects `"true"`, `"1 OR 1=1"`, whitespace-padded values |

52+ security-specific tests across `test_security.py` and inline hardening tests in other suites.

---

## Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Rational time, never floats** | All durations are fractions (`600/2400s`) matching FCPXML's native format — zero rounding errors across trim, split, speed |
| **Non-destructive by default** | Modified files get `_modified`, `_chapters` suffixes. Originals are never overwritten |
| **Single source of truth** | `MarkerType` enum owns serialization: `from_string()` for input, `from_xml_element()` for parsing, `xml_attrs` for writing |
| **Security-first** | 8-layer defense-in-depth across all 47 handlers — see [Security](#security) for the full matrix |
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

501 tests across 10 suites covering models, parser, writer, server handlers, rough cut generation, marker pipeline roundtrips, security hardening (XXE, entity expansion, path traversal, sandbox boundaries, input validation), connected clips, roles, diff, export, and backward compatibility.

---

## Requirements

- **Python 3.10+** · **Final Cut Pro 10.4+** (FCPXML 1.8+) · **Claude Desktop** or any MCP client
- **Dependencies** (auto-installed): `mcp`, `defusedxml`
- See [Compatibility](#compatibility) for full version matrix

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

## Known Issues

| Issue | Impact | Workaround |
|-------|--------|------------|
| **Still images crash FCP** | PNG/JPEG assets referenced directly in FCPXML crash Final Cut Pro on import (`addAssetClip` null pointer). Confirmed across multiple format configurations, dimension matching, and element types. | Convert stills to short MOVs before referencing: `ffmpeg -loop 1 -i image.png -c:v libx264 -t 2 -pix_fmt yuv420p -r 24 output.mov`. This is an FCP limitation, not an FCPXML spec issue. |
| **Non-standard timebases** | FCP rejects time values with denominators outside its standard set (e.g. `100800/57600s`). Cross-denominator arithmetic previously produced these. | Fixed in v0.5.29 — TimeValue arithmetic now uses LCM, and speed changes snap to frame boundaries in 2400-tick timebase. |

---

## Contributing

PRs welcome. If you're a video editor who codes (or a coder who edits), let's build this together.

## Credits

Built by [@DareDev256](https://github.com/DareDev256) — former music video director (350+ videos), now building AI tools for creators.

## License

MIT — see [LICENSE](LICENSE).
