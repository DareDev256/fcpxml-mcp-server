# FCPXML MCP

**The bridge between Final Cut Pro and AI. 53 tools that turn timeline XML into structured data Claude can read, edit, and generate.**

[![CI](https://github.com/DareDev256/fcpxml-mcp-server/actions/workflows/test.yml/badge.svg)](https://github.com/DareDev256/fcpxml-mcp-server/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-1.0-green.svg)](https://modelcontextprotocol.io/)
[![Final Cut Pro](https://img.shields.io/badge/Final%20Cut%20Pro-10.4+-purple.svg)](https://www.apple.com/final-cut-pro/)
[![Tests](https://img.shields.io/badge/tests-819_passing-brightgreen.svg)](#testing)
[![Suites](https://img.shields.io/badge/suites-17-blue.svg)](#testing)
[![Source](https://img.shields.io/badge/source-~8.9k_LOC-informational.svg)](#architecture)

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

## All 53 Tools

| Category | Tools | What It Does |
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
| | **53** | |

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
`import_srt_markers` · `import_transcript_markers` (supports SMPTE `HH:MM:SS:FF` with frame-accurate placement)

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
fcp-mcp-server/           ~8.9k lines Python
├── server.py              MCP entry point — 53 tools, 5 prompts, resource discovery
│                          _resolve_io_paths() / _setup_modifier() / _setup_generator()
│                          _format_clip_table() / _markdown_table() / _format_batch_result()
│                          _raw_markers_to_batch()
│                          _detect_flash_frames() / _detect_gaps() / _detect_duplicate_groups()
│                          consolidate path validation, QC detection, rendering, handler boilerplate
├── fcpxml/
│   ├── README.md          Developer guide — TimeValue, clip hierarchy, modifier patterns
│   ├── models.py          TimeValue, Timecode, Clip, ConnectedClip, MarkerType, Timeline
│   ├── parser.py          FCPXML → Python (spine, connected clips, roles, markers)
│   ├── writer.py          Modify & write (markers, trim, gaps, transitions, silence)
│   │                       FCPXMLModifier: index-based editing (clips/resources/formats dicts)
│   │                       FCPXMLWriter: generate new FCPXML from Python objects
│   │                       Helpers: _resolve_asset, _absorb_into_neighbor, _ripple_from_index
│   ├── rough_cut.py       Generate timelines (rough cuts, montages, A/B roll)
│   ├── diff.py            Timeline comparison engine (identity matching, threshold docs)
│   ├── export.py          DaVinci Resolve v1.9 + FCP7 XMEML v5 export
│   ├── safe_xml.py        Centralized defusedxml wrappers (XXE/entity-bomb protection) + serialize_xml()
│   └── templates.py       Template system (intro/outro, lower thirds, music video)
├── tests/                 812 tests across 17 suites
│   ├── test_models.py     TimeValue math, Timecode formatting, MarkerType contracts
│   ├── test_parser.py     FCPXML parsing, connected clips, edge cases
│   ├── test_writer.py     Clip editing, marker writing, speed changes
│   ├── test_fcpxml_writer.py  FCPXMLWriter generation from Python objects
│   ├── test_server.py     MCP tool handlers, dispatch, path validation
│   ├── test_rough_cut.py  Rough cut generation, montage, A/B roll
│   ├── test_diff.py       Moved clips, transitions, markers, clip identity
│   ├── test_export.py     Attribute stripping, compound flattening, audio tracks
│   ├── test_features_v05.py  Multi-track, roles, diff, reformat, export
│   ├── test_features_v06.py  Audio, compound clips, templates, effects, validation
│   ├── test_marker_pipeline.py  Marker builder, batch modes, output format
│   ├── test_speed_cutting.py  Speed cutting, montage config, pacing curves
│   ├── test_security.py   Input validation, XML sanitization, XXE protection
│   ├── test_edge_cases.py Boundary arithmetic, clip collisions, split/diff edges
│   ├── test_diversity.py  Boundary conditions across diff, models, validation
│   ├── test_refactored_helpers.py  _index_elements, _iter_spine_clips, serialize_xml edges
│   └── test_targeted_gaps.py  Targeted branch coverage for diff, export, models
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
| **Output sandbox** | All generation, write, export, beat sync, subtitle, and reformat handlers enforce `_validate_output_path(anchor_dir=...)` — restricts writes to descendants of the source file's directory, blocking LLM-generated path escapes |
| **Subprocess bounds** | `_validate_subprocess_params()` bounds-checks duration (0 < d ≤ 300s), fps (1–120), width/height (even, ≤ 7680) before `subprocess.run()` — blocks `inf`/`NaN`, negative values, odd dimensions, string injection, and oversized resolutions that could hang or exhaust ffmpeg |
| **Directory listing** | Confined to `FCP_PROJECTS_DIR` when set, 10K file cap on `rglob`, symlink files skipped during discovery — prevents workspace enumeration and traversal DoS |
| **XML parsing** | `defusedxml` with explicit `forbid_entities/external=True` blocks XXE, billion laughs, entity expansion, remote DTD attacks at all 4 entry points (parser, writer, exporter, rough cut) — minidom pretty-print path also hardened via `defusedxml.minidom`. Ruff `S314`/`S320` rules enforce safe parsing in CI |
| **JSON depth limit** | Iterative BFS depth checker rejects payloads nested beyond 50 levels — immune to RecursionError even at ~1000 nesting |
| **Batch limits** | Marker batch operations capped at 10,000 entries — prevents memory exhaustion from adversarial payloads with millions of markers |
| **Inline text limits** | Inline transcript arguments capped at ~1 MB — file-based inputs go through `_validate_filepath`, but inline strings from MCP tool arguments bypass file checks |
| **Symlink filtering** | `find_fcpxml_files` skips symlinks during discovery — prevents sandbox escape via symlink chains pointing outside the allowed project directory |
| **Marker strings** | Sanitized via `_sanitize_xml_value()` — null bytes, control chars stripped before write |
| **Role values** | Stripped of control characters before XML attribute assignment |
| **URI parsing** | MCP resource URIs parsed via `urllib.parse.urlparse()` — rejects scheme confusion and handles percent-encoded paths correctly |
| **Output suffixes** | Path separators and special characters stripped — no traversal via suffix injection |
| **Marker types** | `completed` attribute strict-matched (`'0'`/`'1'` only) — rejects `"true"`, `"1 OR 1=1"`, whitespace-padded values |

121 security-specific tests across `test_security.py` covering XXE, path traversal, sandbox boundaries, output path anchoring, input validation, subprocess bounds, minidom hardening, JSON depth limits, role sanitization, ffmpeg parameter bounds, symlink filtering, file count caps, and write-handler sandbox enforcement. Ruff `S` (bandit) rules enforced in CI — `S314`/`S320` block unsafe XML parsing, `S105` catches hardcoded passwords, `S108` flags insecure temp paths. Security events (null bytes, sandbox escapes, unhandled exceptions) are logged via Python `logging` for audit trails.

---

## Timestamp Parsing — How Import Tools Place Markers

All subtitle and transcript import tools (`import_srt_markers`, `import_transcript_markers`) funnel through a single internal function: **`_parse_timestamp_parts()`** in `server.py`. Understanding it matters when timestamps don't land where you expect.

### Supported Formats

| Format | Example | Parts | Result |
|--------|---------|-------|--------|
| **Minutes:Seconds** | `1:30` | 2 | 90.0s |
| **H:MM:SS** | `1:05:30` | 3 | 3930.0s |
| **HH:MM:SS.ms** | `00:02:15.500` | 3 | 135.5s |
| **SMPTE** (HH:MM:SS:FF) | `01:00:10:12` | 4 | 3610.5s @ 24fps |

The SMPTE 4-part format converts the frame component to fractional seconds: `frames / frame_rate`. The default rate is **24fps** — pass `frame_rate=` to override for 25fps (PAL) or 30fps (NTSC) projects.

### The Import Pipeline

```
SRT / VTT / YouTube chapters / plain transcript
        │
        ▼
  parse_srt()  /  parse_vtt()  /  parse_transcript_timestamps()
        │                │                      │
        └────────────────┴──────────────────────┘
                         │
                    split on ':'
                         │
                         ▼
             _parse_timestamp_parts(parts, frame_rate=24.0)
                         │
                         ▼
                   total seconds (float)
                         │
                         ▼
               marker placed on timeline
```

### Edge Cases

- **Unrecognized part counts** (1 part, 5+ parts) return `None` — the marker is silently skipped, not placed incorrectly
- **Zero frame rate** — falls back to base seconds (frames ignored) rather than dividing by zero
- **Milliseconds** — only carried in 3-part format via `float()` on the seconds component (`"15.500"` → `15.5`)
- **Frame rounding** — SMPTE frames are divided exactly (`12/24 = 0.5`), not rounded to the nearest frame boundary. The resulting float is converted to FCPXML's rational `TimeValue` downstream, preserving precision

### Why This Matters

Before v0.6.20, the 4-part SMPTE parser silently dropped frames — `01:00:10:12` became `3610.0s` instead of `3610.5s`. At 24fps, that's up to **~0.96 seconds** of drift per marker. If you imported a subtitle file with SMPTE timecodes, every marker was slightly off. This was subtle enough to pass QC but visible when scrubbing.

---

## Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Rational time, never floats** | All durations are fractions (`600/2400s`) matching FCPXML's native format — zero rounding errors across trim, split, speed |
| **Non-destructive by default** | Modified files get `_modified`, `_chapters` suffixes. Originals are never overwritten |
| **Single source of truth** | `MarkerType` enum owns serialization: `from_string()` for input, `from_xml_element()` for parsing, `xml_attrs` for writing. `INCOMPLETE` is canonical; `TODO` is a backward-compat alias (same object) |
| **Security-first** | 10-layer defense-in-depth across all 53 handlers — see [Security](#security) for the full matrix |
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

795 tests across 17 suites covering models, parser, writer, FCPXMLWriter generation, server handlers, rough cut generation, speed cutting & pacing curves, marker pipeline, refactored helper functions (_index_elements, _iter_spine_clips, _find_spine_clip_at_seconds, _require_clip, _require_spine_clip, _resolve_asset, serialize_xml), recent fix regressions (rapid_trim directions, min_duration, offset recalculation, interval timing accuracy, gap skipping, duplicate-name clip operations across trim/speed/split/delete/markers), security hardening (XXE, entity expansion, path traversal, sandbox boundaries, minidom defense-in-depth, JSON depth limits, input validation, ffmpeg bounds, write-handler sandboxing), connected clips, roles, diff, export, compound clip flattening, audio track generation, templates, effects, boundary conditions, and backward compatibility.

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
| **Malformed frameDuration crash** | A `frameDuration` with zero or negative denominator (e.g. `"0/0s"`) in the writer's `_detect_fps` would silently produce 0.0 fps, causing downstream ZeroDivisionError in speed/trim operations. The parser already validated this correctly. | Fixed in v0.6.23 — writer now validates both numerator and denominator, falling back to 30.0 fps. |
| **Duplicate clip names corrupt edits** | When multiple spine clips share the same name (e.g. `Interview_A` ×4), operations using the name-indexed dict silently target the wrong clip (last-indexed instead of first). Affected: `delete_clip`, `add_marker_at_timeline`, `trim_clip`, `change_speed`, `split_clip`, `add_transition`, `reorder_clips`. | Fixed in v0.6.37–0.6.39 — all methods now resolve clips via `_resolve_clip()` which walks the spine directly, returning the first match. |

---

## Contributing

PRs welcome. If you're a video editor who codes (or a coder who edits), let's build this together.

## Credits

Built by [@DareDev256](https://github.com/DareDev256) — former music video director (350+ videos), now building AI tools for creators.

## License

MIT — see [LICENSE](LICENSE).
