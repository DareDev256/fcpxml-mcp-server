# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.3] - 2026-02-20

### Changed

- Consolidated three separate marker type lookup patterns (manual dict, `MarkerType[str.upper()]`, enum value match) into single `MarkerType.from_string()` classmethod
- Added `MarkerType.xml_tag` property — eliminates `tag_map` dicts and inline ternaries for XML element name resolution
- `add_marker` and `list_markers` tool schemas now expose `"completed"` as a valid marker type
- Parser `_parse_clip()` now finds `<chapter-marker>` elements on clips (previously only `<marker>` was parsed at clip level)
- Tightened TODO marker detection: `completed` attribute must be exactly `"0"` (was `is not None`, which matched any value)
- `FCPXMLWriter._add_marker` now emits `posterOffset="0s"` on chapter markers (matches `FCPXMLModifier` behavior)
- `FCPXMLModifier.add_marker` no longer adds `note` attribute to chapter markers (invalid FCPXML, FCP ignores them)

## [0.4.2] - 2026-02-18

### Fixed

- TODO markers now set `completed="0"` attribute so they survive round-trip (save → re-parse) without degrading to STANDARD markers
- COMPLETED markers (`completed="1"`) are now correctly distinguished from TODO markers (`completed="0"`) during parsing — previously both were mapped to TODO
- FCPXMLWriter generator now emits `completed` attribute for TODO and COMPLETED markers
- `list_markers` tool now supports filtering by "completed" marker type

## [Unreleased]

### Added

- 285 unit tests across 7 test files covering models, parser, writer, server handlers, and rough cut generation
- GitHub Actions CI pipeline with linting (ruff) and test execution
- MCP registry metadata files for discoverability

### Fixed

- Import sort order in test files for ruff I001 compliance

### Security

- Add path validation to all 34 tool handlers — blocks path traversal, null bytes, symlink attacks, and oversized files (100 MB limit)
- Enforce file extension whitelists: `.fcpxml`/`.fcpxmld` for projects, `.json` for beats, `.srt`/`.vtt` for subtitles
- Validate output paths to prevent writing to arbitrary filesystem locations
- Harden error handler to avoid leaking internal paths and stack traces in unexpected errors

## [0.4.0] - 2026-02-05

### Added

- 5 pre-built MCP prompt workflows: QC check, YouTube chapters, rough cut, timeline summary, cleanup
- MCP resources for automatic FCPXML file discovery in project directories
- SRT/VTT subtitle import as timeline markers (`import_srt_markers`)
- YouTube chapter/transcript import as markers (`import_transcript_markers`)
- Server architecture refactored to dispatch-dict pattern (`TOOL_HANDLERS`)

## [0.3.0] - 2026-01-20

### Added

- AI-powered rough cut generation from source clips (`auto_rough_cut`)
- Montage generator with pacing curves: accelerating, decelerating, pyramid (`generate_montage`)
- A/B roll generator for documentary-style edits (`generate_ab_roll`)
- Beat sync tools: `import_beat_markers`, `snap_to_beats`
- Flash frame detection and auto-fix (`detect_flash_frames`, `fix_flash_frames`)
- Duplicate clip detection (`detect_duplicates`)
- Gap detection (`detect_gaps`, `fill_gaps`)
- Timeline validation with health score (`validate_timeline`)
- Batch rapid trim (`rapid_trim`)
- Speed change tool (`change_speed`)
- Clip splitting at timecodes (`split_clip`)
- Clip deletion with ripple support (`delete_clips`)
- Transition insertion: cross-dissolve, fade, wipe (`add_transition`)

## [0.2.0] - 2026-01-20

### Added

- Library clip listing (`list_library_clips`)
- Timeline clip insertion from library (`insert_clip`)
- Clip trimming with ripple (`trim_clip`)
- Clip reordering with ripple support (`reorder_clips`)
- Batch marker operations (`batch_add_markers`)
- Pacing analysis with suggestions (`analyze_pacing`)
- Keyword listing and selection (`list_keywords`, `select_by_keyword`)
- EDL export (`export_edl`)
- CSV export (`export_csv`)

## [0.1.0] - 2026-01-18

### Added

- Initial release — first MCP server for Final Cut Pro
- FCPXML parser supporting versions 1.8–1.11
- Timeline analysis (`analyze_timeline`)
- Clip listing with timecodes (`list_clips`)
- Marker listing (`list_markers`)
- Short cut and long clip detection (`find_short_cuts`, `find_long_clips`)
- Single marker insertion (`add_marker`)
- Project file discovery (`list_projects`)
- Python data models: TimeValue (rational time arithmetic), Timecode, Clip, Timeline, Project
