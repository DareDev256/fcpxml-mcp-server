# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.17] - 2026-02-25

### Added

- **MCP Ecosystem guide** (`docs/MCP_ECOSYSTEM.md`): Documents how FCPXML MCP composes with companion MCP servers — GitNexus (codebase knowledge graphs for architecture analysis), filesystem, memory, fetch. Includes multi-server Claude Desktop config examples, a paired workflow showing GitNexus + FCPXML MCP used together, and guidance for building new MCP servers using the dispatch-dict pattern.

## [0.5.16] - 2026-02-25

### Security

- **Defused XML parsing against XXE and billion laughs**: All 5 XML parse sites (parser, writer, export, rough_cut) now use `defusedxml` via centralized `fcpxml/safe_xml.py` module — blocks external entity injection, entity expansion bombs, and remote DTD parameter entities. Added `defusedxml>=0.7.1` as a dependency. 10 new security tests covering billion laughs, XXE file read, and DTD entity attacks across both `safe_parse` and `safe_fromstring` entry points (52 total security tests, 454 total).

## [0.5.15] - 2026-02-25

### Changed

- **Extracted clip-tag constants**: Replaced 13 inline tag-tuple literals across `writer.py` with three named module-level constants (`CLIP_TAGS`, `CLIP_AND_AUDIO_TAGS`, `SPINE_ELEMENT_TAGS`) — eliminates inconsistent tag sets and makes adding new clip types a single-line change
- **Extracted parser clip-tag constant**: Deduplicated `clip_tags` local variable in `_parse_connected_clips` and `_parse_gap_connected_clips` into `_CONNECTED_CLIP_TAGS` module constant
- **Fixed silence marker bypass**: `remove_silence_candidates(mode="mark")` now uses `build_marker_element()` instead of raw `ET.SubElement` — gains input sanitization, fps-aware duration, and correct FCPXML attribute contract
- **Removed dead code**: Deleted unused `_time_to_fcpxml()` wrapper method from `FCPXMLModifier`

## [0.5.14] - 2026-02-25

### Fixed

- **Completed-attribute strict matching**: Added 7 adversarial edge-case tests for `MarkerType.from_xml_element` — whitespace-only `completed`, tab-padded values, leading-zero `'00'`, and Unicode fullwidth digit lookalikes (`０`, `１`). Confirms strict exact-match rejects all non-canonical inputs as STANDARD.

## [0.5.13] - 2026-02-24

### Changed

- **README overhaul**: Fixed stale stats (414→438 tests, 9→10 suites), expanded architecture tree with per-file descriptions for all test suites, added LOC badge, documented unified marker pipeline and security-first validation as key design decisions, added "Recent Highlights" section showcasing marker hardening and cross-NLE export work, updated latest release pointer to v0.5.13

## [0.5.12] - 2026-02-24

### Added

- **17 marker pipeline tests** (`test_marker_pipeline.py`): Direct unit tests for `build_marker_element` shared builder (8 tests), `batch_add_markers` auto_at_cuts and auto_at_intervals modes (4 tests), `_build_clip_index` duplicate-name last-one-wins behavior (2 tests), `write_fcpxml` output format validation (3 tests)
- **Documented `auto_at_cuts` bug**: Test proves `batch_add_markers(auto_at_cuts=True)` fails with `ValueError` when spine contains duplicate clip names — the name-indexed clip dict loses earlier occurrences

## [0.5.11] - 2026-02-24

### Changed

- **Unified marker element construction**: Extracted `build_marker_element()` as a single source of truth for creating marker/chapter-marker XML elements — eliminates duplicated tag selection, attribute setting, and note-guard logic between `FCPXMLModifier.add_marker()` and `FCPXMLWriter._add_marker()`
- **Single-pass marker collection**: `_collect_markers` in the parser now iterates element children once using `MARKER_XML_TAGS` constant instead of calling `findall()` twice (once per tag)
- **New `MARKER_XML_TAGS` constant**: Tuple of recognised marker element tags (`'marker'`, `'chapter-marker'`) exported from models for use across parser and writer modules

## [0.5.10] - 2026-02-24

### Added

- **3 strict whitespace parser tests**: `test_whitespace_padded_completed_zero_is_standard`, `test_whitespace_padded_completed_one_is_standard`, `test_empty_completed_attribute_is_standard` — parser-level defense-in-depth for `from_xml_element` strict matching
- **3 `from_string` whitespace strip tests**: Verifies `from_string("  completed  ")`, `from_string("  todo  ")`, and `from_string("  chapter  ")` all strip correctly before enum lookup
- **2 writer strict attribute tests**: `test_marker_completed_attr_no_whitespace` confirms written `completed` attributes are exact `'0'`/`'1'` with no padding; `test_from_string_whitespace_roundtrip` confirms padded `from_string` input survives write→parse roundtrip

## [0.5.9] - 2026-02-23

### Fixed

- **Strict whitespace matching documented and unit-tested at contract level**: `from_xml_element` now has explicit docstring documenting priority order and strict matching behavior — whitespace-padded completed attributes like `' 0 '` are correctly rejected as STANDARD
- **Chapter-marker tag priority over completed attribute**: Added unit test confirming `<chapter-marker completed="0">` resolves to CHAPTER, not TODO — tag check takes priority
- **Writer docstring listed only 3 of 4 marker types**: `add_marker()` docstring now lists STANDARD, TODO, COMPLETED, and CHAPTER

### Added

- **4 new `from_xml_element` unit tests**: whitespace-padded '0', whitespace-padded '1', empty completed attribute, and chapter-marker-with-completed edge case — closes the gap between integration tests (test_security.py) and unit contract tests (test_models.py)

## [0.5.8] - 2026-02-23

### Changed

- **Consolidated marker serialization contract into `MarkerType`**: New `from_xml_element()` classmethod and `xml_attrs` property centralise the completed-attribute and posterOffset logic that was previously duplicated across parser and both writer classes
- **Unified parser marker methods**: Replaced separate `_parse_marker()` and `_parse_chapter_marker()` with a single `_parse_marker_element()` that delegates type detection to `MarkerType.from_xml_element()`
- **Extracted `_collect_markers()` helper**: Eliminated 4 duplicated `findall('marker') + findall('chapter-marker')` loops in `_parse_clip`, `_parse_one_connected_clip`, and `_parse_project`
- **Both writer paths use `xml_attrs`**: `FCPXMLModifier.add_marker()` and `FCPXMLWriter._add_marker()` now loop over `marker_type.xml_attrs` instead of manual if/elif chains

### Added

- **11 new tests** for `MarkerType.from_xml_element()`, `xml_attrs`, and round-trip symmetry (`TestMarkerTypeXmlContract`)

## [0.5.7] - 2026-02-23

### Fixed

- **Chapter markers on connected clips silently dropped**: `_parse_one_connected_clip` only parsed `<marker>` children, missing `<chapter-marker>` elements entirely — chapter markers placed on B-roll, lower-thirds, or any lane clip were lost during parse. Now parses both marker types, matching `_parse_clip` behavior.

## [0.5.6] - 2026-02-23

### Fixed

- **Marker completed-attribute edge cases**: Added 5 security tests for whitespace-padded (`" 0 "`, `" 1 "`), negative (`"-1"`), and case-variant (`"TRUE"`, `"false"`) completed attribute values — all correctly rejected as STANDARD by the strict parser
- **`from_string` → write → parse round-trip test**: New integration test proving `MarkerType.from_string('todo')` and legacy alias `'todo-marker'` both survive the full write/re-parse cycle as TODO markers

## [0.5.5] - 2026-02-23

### Added

- **TODO/COMPLETED marker tests for FCPXMLWriter**: 4 new tests covering the object-model-to-XML path (`_add_marker`) that was previously untested for task markers — catches regressions in rough cut and export generation
- **Mixed-case `from_string` tests**: 6 parametrized cases ("Todo", "tOdO", "Completed", "cOMPLETED") proving case insensitivity
- **Whitespace + legacy alias combo tests**: 3 cases ensuring " todo-marker " and similar inputs resolve correctly
- **Enum value contract test**: Asserts `.value` properties stay lowercase — they're used as dict keys across the codebase
- **Multi-marker-type parser test**: Verifies all four marker types coexist on one clip without cross-contamination
- **STANDARD marker negative test**: Confirms plain `<marker>` without `completed` attr never becomes TODO

## [0.5.4] - 2026-02-23

### Security

- **Input validation hardening:** `MarkerType.from_string()` now rejects null bytes, control characters, empty strings, and inputs exceeding 64 characters — prevents injection and memory abuse via crafted marker type strings
- **XML value sanitization:** New `_sanitize_xml_value()` helper strips null bytes and control characters from marker names and notes before writing to XML, with configurable length limits (1024 chars for names, 4096 for notes)
- **Parser file size limit:** `FCPXMLParser.parse_file()` enforces a 50 MB file size ceiling before parsing, preventing memory exhaustion from maliciously large XML files
- **Strict completed-attribute validation:** Parser now only accepts `'0'` and `'1'` for the marker `completed` attribute — any other value (e.g. `"true"`, `"yes"`, `"1 OR 1=1"`) falls through to `MarkerType.STANDARD` instead of being misinterpreted
- Added 25 security tests covering all hardening vectors

## [0.5.3] - 2026-02-22

### Added

- **Workflow recipes guide** (`docs/WORKFLOWS.md`): 8 real-world multi-step workflow recipes — delivery QC pipeline, YouTube chapter export, beat-synced music video assembly, cross-NLE handoff, documentary A/B roll, social media reformat, timeline version comparison, silence cleanup
- Each recipe documents the scenario, natural-language prompt, tool chain, and practical notes
- Section on composing tools in AI agent workflows — how to describe multi-tool pipelines in a single prompt
- README now links to workflows guide from Usage Examples section

## [0.5.2] - 2026-02-22

### Fixed

- **Spec drift:** Updated `docs/specs/03_WRITER_PSEUDOCODE.py` and `docs/specs/07_MODELS.py` MarkerType enums to match implementation — old values (`"todo-marker"`, `"completed-marker"`) replaced with correct values (`"todo"`, `"completed"`)
- **Legacy alias support:** `MarkerType.from_string()` now accepts legacy spec values (`"todo-marker"`, `"completed-marker"`, `"chapter-marker"`) and maps them to current enum values, preventing hard failures from stale references
- Added 10 new MarkerType tests covering `from_string` current values, legacy aliases, invalid input, and `xml_tag` mapping (348 total tests)

## [0.5.1] - 2026-02-22

### Changed

- **README rewrite:** Portfolio-grade overhaul — stronger narrative hook (personal story leads), architecture diagram with data flow, consolidated release history (points to CHANGELOG instead of duplicating it), tighter tool tables, updated stats (337 tests, ~7k LOC)
- Roadmap condensed from 27 line items to 12 grouped milestones for scannability
- "Why This Exists" moved from bottom of page to top — emotional hook before technical proof
- Added test badge to header badges

## [0.5.0] - 2026-02-21

### Added

- **Connected Clips:** Full multi-track support — parser extracts B-roll, titles, and audio from secondary lanes (`lane` attribute), secondary storylines (`<storyline>` elements), and gap-attached clips
- **Compound Clips:** Parse and inspect `ref-clip` compound clips with nested timelines
- **Roles Management:** 4 new tools — `list_roles`, `assign_role`, `filter_by_role`, `export_role_stems` for audio/video role workflows
- **Timeline Diff:** `compare_timelines()` engine detects added/removed/moved/trimmed clips, marker changes, transition changes, and format changes between two FCPXMLs
- **Social Media Reformat:** `reformat_timeline` with preset aspect ratios (9:16, 1:1, 4:5, 4:3, 16:9) and custom resolution support
- **Silence Detection:** Heuristic-based `detect_silence_candidates` (gaps, ultra-short clips, name patterns, duration anomalies) and `remove_silence_candidates` (mark or delete modes)
- **DaVinci Resolve Export:** `export_resolve_xml` generates simplified FCPXML v1.9 with compound clip flattening and unsupported attribute stripping
- **XMEML Export:** `export_fcp7_xml` converts spine-based FCPXML to track-based FCP7 XML (XMEML v5) for Premiere Pro / Resolve / Avid
- New dataclasses: `ConnectedClip`, `CompoundClip`, `SilenceCandidate`
- `audio_role` and `video_role` fields on `Clip` dataclass
- `connected_clips` and `compound_clips` lists on `Timeline` dataclass
- 52 new tests (337 total) covering all 6 features
- 13 new tools → 47 total

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
