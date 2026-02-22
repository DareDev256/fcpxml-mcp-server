# CLAUDE.md — fcp-mcp-server

## What This Is

MCP server that reads/writes Final Cut Pro XML (FCPXML) files. 47 tools for timeline analysis, batch editing, QC, generation, multi-track support, and NLE export.

## Architecture

```
server.py           — MCP server entry point. All 47 tool definitions, handlers, resources, prompts.
                      Dispatch dict pattern: TOOL_HANDLERS maps tool names → async handler functions.

fcpxml/parser.py    — Reads FCPXML → Python objects (Timeline, Clip, ConnectedClip, Marker, etc.)
                      Parses spine, connected clips (lanes), secondary storylines, gap-attached clips, roles.
fcpxml/writer.py    — Writes modifications back to FCPXML. Handles markers, trimming, gaps, transitions,
                      connected clips, roles, reformatting, silence detection/removal.
fcpxml/rough_cut.py — Generates new timelines from source clips (rough cuts, montages, A/B rolls).
fcpxml/diff.py      — Timeline comparison engine. Detects added/removed/moved/trimmed clips & markers.
fcpxml/export.py    — DaVinci Resolve FCPXML v1.9 export + FCP7 XMEML v5 export for cross-NLE workflows.
fcpxml/models.py    — Data classes: TimeValue, Timecode, Clip, ConnectedClip, CompoundClip, Timeline, etc.
```

## Key Patterns

- **TimeValue**: All times are rational fractions (numerator/denominator) matching FCPXML's `"600/2400s"` format. Never use floats for time math.
- **_parse_project()**: Helper that parses FCPXML and returns `(tree, timeline, project)` tuple. Most handlers start with this.
- **generate_output_path()**: Creates `_modified`, `_chapters`, etc. suffixed output paths so originals aren't overwritten.
- **Tool handlers**: Each tool has its own `async def handle_<name>(arguments: dict)` function. All return `Sequence[TextContent]`.
- **Connected clips**: Clips with `lane` attribute hang off spine clips. Positive lane = above (video), negative = below (audio). Secondary `<storyline>` elements also contain connected clips.
- **XMEML export**: Converts spine-based model to track-based model. Primary storyline → Track 0, connected clip lanes → higher tracks.

## Running

```bash
uv run server.py                    # Start MCP server
uv run --extra dev pytest tests/ -v # Run tests
```

## Pre-Commit (MANDATORY)

Before committing ANY changes, run both:
```bash
ruff check . --exclude docs/   # Lint — must pass with zero errors
pytest tests/ -v               # Tests — all must pass
```
CI runs both on every push to main. If either fails, the commit gets an X on GitHub. Fix lint errors before committing, not after.

## Testing

348 tests across 5 files. `test_models.py` covers TimeValue arithmetic, Timecode parsing/formatting, Clip properties, validation models, and Timeline helpers. `test_writer.py` covers insert_clip, add_marker (all types), trim_clip, delete_clip, split_clip, and change_speed operations. `test_server.py` covers MCP tool handlers, parsers, and dispatch. `test_rough_cut.py` covers RoughCutGenerator. `test_features_v05.py` covers connected clips, roles, timeline diff, reformat, silence detection, export, and backward compatibility. Tests use `examples/sample.fcpxml` as fixture data and inline XML fixtures. Tests create temp files and clean up after.

## FCPXML Gotchas

- FCPXML uses rational time everywhere: `"3600/2400s"` = 1.5 seconds
- `offset` in clips is the timeline position, `start` is the source media in-point
- Library clips (`<asset-clip>`) are different from timeline clips (`<clip>`)
- Markers are children of clips, not siblings
- The `<spine>` element is the primary storyline — clips go here
