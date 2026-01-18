# Final Cut Pro MCP Server

> 🎬 The first AI-powered MCP server for Final Cut Pro. Control your edits with natural language.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

## What This Does

This MCP server lets AI assistants (Claude, GPT, etc.) interact with Final Cut Pro projects through FCPXML:

- **Analyze timelines** — Get stats on cuts, clip durations, pacing
- **Extract markers** — Pull chapter markers, to-do markers, keywords
- **Generate edit lists** — Create EDLs, shot lists, CSV exports
- **Modify projects** — Add markers, reorder clips, apply bulk changes
- **AI-powered suggestions** — Get cutting recommendations based on pacing analysis

## Why This Exists

As someone who directed 350+ music videos, I know the pain of repetitive editing tasks. This server bridges the gap between AI assistants and professional video editing workflows.

No more manually:
- Counting cuts or calculating average shot lengths
- Extracting chapter markers for YouTube descriptions
- Finding flash frames or pacing issues
- Generating EDLs for color/audio handoffs

Just ask Claude.

## Installation

```bash
# Clone the repo
git clone https://github.com/DareDev256/fcp-mcp-server.git
cd fcp-mcp-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fcp": {
      "command": "python",
      "args": ["/path/to/fcp-mcp-server/server.py"],
      "env": {
        "FCP_PROJECTS_DIR": "/Users/you/Movies"
      }
    }
  }
}
```

## Usage Examples

Once connected, you can ask Claude:

```
"Analyze my latest FCP project and tell me the average cut length"

"Extract all chapter markers from timeline.fcpxml as YouTube timestamps"

"Find all clips shorter than 1 second — might be flash frames"

"Add a 'Review' marker at every jump cut"

"Generate a shot list CSV from this project"

"What's the pacing like in the first vs last quarter of my edit?"
```

## Available Tools

| Tool | Description |
|------|-------------|
| `analyze_timeline` | Get comprehensive stats on a timeline |
| `list_clips` | List all clips with in/out points and durations |
| `list_markers` | Extract markers with timestamps |
| `list_keywords` | Get all keywords/tags applied to clips |
| `find_short_cuts` | Find cuts below a threshold (flash frame detection) |
| `find_long_clips` | Find clips above a threshold |
| `export_edl` | Generate an EDL file |
| `export_csv` | Export timeline data to CSV |
| `analyze_pacing` | AI analysis of pacing with cut suggestions |

## How It Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Claude/GPT    │────▶│  MCP Server     │────▶│  FCPXML Files   │
│   (AI Client)   │◀────│  (This Project) │◀────│  (FCP Projects) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        Parse & Modify
                        FCPXML via Python
```

1. **Export from FCP**: File → Export XML
2. **AI analyzes**: Claude reads the FCPXML through this server
3. **AI suggests/modifies**: Server generates new FCPXML
4. **Import to FCP**: File → Import → XML

## Project Structure

```
fcp-mcp-server/
├── server.py              # MCP server entry point
├── fcpxml/
│   ├── __init__.py
│   ├── parser.py          # FCPXML parsing logic
│   ├── writer.py          # FCPXML generation/modification
│   └── models.py          # Data models (Timeline, Clip, Marker, etc.)
├── tools/
│   └── __init__.py
├── tests/
│   └── test_parser.py
├── examples/
│   └── sample.fcpxml      # Sample project for testing
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Requirements

- Python 3.10+
- Final Cut Pro 10.4+ (for FCPXML 1.8+)
- MCP-compatible AI client (Claude Desktop, etc.)

## Roadmap

- [x] Core FCPXML parsing
- [x] Timeline analysis tools
- [x] Marker extraction
- [x] EDL/CSV export
- [x] Pacing analysis
- [ ] Marker insertion/modification
- [ ] Batch operations
- [ ] Color grading analysis
- [ ] Audio sync detection
- [ ] Multi-timeline comparison
- [ ] Premiere Pro XML support

## Contributing

PRs welcome! This is an open project. If you're a video editor who codes (or vice versa), let's build this together.

## Credits

Built by [@DareDev256](https://github.com/DareDev256) — Former music video director (350+ videos for Chief Keef, Migos, Masicka), now building AI tools for creators.

## License

MIT License — see [LICENSE](LICENSE) for details.
