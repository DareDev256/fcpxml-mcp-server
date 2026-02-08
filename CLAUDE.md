# CLAUDE.md — fcp-mcp-server

## What This Is

MCP server that reads/writes Final Cut Pro XML (FCPXML) files. 34 tools for timeline analysis, batch editing, QC, and generation.

## Architecture

```
server.py          — MCP server entry point. All 34 tool definitions, handlers, resources, prompts.
                     Dispatch dict pattern: TOOL_HANDLERS maps tool names → async handler functions.

fcpxml/parser.py   — Reads FCPXML → Python objects (Timeline, Clip, Marker, etc.)
fcpxml/writer.py   — Writes modifications back to FCPXML. Handles markers, trimming, gaps, transitions.
fcpxml/rough_cut.py — Generates new timelines from source clips (rough cuts, montages, A/B rolls).
fcpxml/models.py   — Data classes: TimeValue (rational time), Timecode, Clip, Timeline, Project, etc.
```

## Key Patterns

- **TimeValue**: All times are rational fractions (numerator/denominator) matching FCPXML's `"600/2400s"` format. Never use floats for time math.
- **_parse_project()**: Helper that parses FCPXML and returns `(tree, timeline, project)` tuple. Most handlers start with this.
- **generate_output_path()**: Creates `_modified`, `_chapters`, etc. suffixed output paths so originals aren't overwritten.
- **Tool handlers**: Each tool has its own `async def handle_<name>(arguments: dict)` function. All return `Sequence[TextContent]`.

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

283 tests across 4 files. `test_models.py` covers TimeValue arithmetic, Timecode parsing/formatting, Clip properties, validation models, and Timeline helpers. `test_writer.py` covers insert_clip, add_marker (all types), trim_clip, delete_clip, split_clip, and change_speed operations. `test_server.py` covers MCP tool handlers, parsers, and dispatch. `test_rough_cut.py` covers RoughCutGenerator. Tests use `examples/sample.fcpxml` as fixture data. Tests create temp files and clean up after.

## FCPXML Gotchas

- FCPXML uses rational time everywhere: `"3600/2400s"` = 1.5 seconds
- `offset` in clips is the timeline position, `start` is the source media in-point
- Library clips (`<asset-clip>`) are different from timeline clips (`<clip>`)
- Markers are children of clips, not siblings
- The `<spine>` element is the primary storyline — clips go here
