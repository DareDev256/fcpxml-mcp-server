# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.37] - 2026-04-04

### Fixed

- **`add_marker_at_timeline` silently targets wrong clip on duplicate names** (writer.py): The method iterated `self.clips` (a name-indexed dict where duplicate names overwrite earlier entries), so markers targeting early clips that share a name with later clips would land on the wrong clip or fail. Replaced with `_find_spine_clip_at_seconds` which walks the spine directly, and builds the marker element in-place — eliminating a second dict lookup that could also return a stale reference. Added regression test with the sample timeline's 4 `Interview_A` clips.

## [0.6.36] - 2026-04-02

### Added

- **21 unit tests for refactored helper functions** (`test_refactored_helpers.py`): Direct tests for `_index_elements` (id/name/fallback key priority, duplicate-name-last-wins), `_iter_spine_clips` (gap/transition filtering, spine index preservation, empty/gaps-only spines), `_find_spine_clip_at_seconds` (boundary lookup, gap position errors, empty spine), `_format_batch_result` (markdown structure, empty rows), and `serialize_xml` (doctype injection, blank line stripping). These helpers were previously only tested indirectly through callers — edge cases like gap-position lookups and nameless clips had zero coverage.

## [0.6.35] - 2026-04-02

### Changed

- **Unify XML serialization into `serialize_xml()`** (safe_xml.py): Extracted the duplicated pretty-print pipeline (ET.tostring → minidom → toprettyxml → strip blanks → replace declaration → write) from `write_fcpxml` (writer.py) and `_pretty_write` (export.py) into a single `serialize_xml()` function in `safe_xml.py`. Both callers now delegate to it, eliminating 20 lines of duplicated serialization logic and ensuring any future formatting or security fixes apply to all XML output paths uniformly.

## [0.6.34] - 2026-04-02

### Changed

- **Eliminate hand-rolled duration parser in favour of `TimeValue`** (parser.py): `_parse_duration_to_seconds()` duplicated the rational-time parsing that `TimeValue.from_timecode()` already handles. Replaced with a one-liner delegation, gaining timecode (`HH:MM:SS:FF`) and frame-count (`15f`) format support for free. Malformed input now returns 0.0 consistently instead of raising on some edge cases.
- **Consolidate `MarkerType` alias tests** (test_models.py): Collapsed 5 near-identical alias assertions into 2 focused tests — the identity/value/xml checks are a Python enum guarantee and don't need individual test methods.

## [0.6.33] - 2026-04-01

### Fixed

- **Fix `rapid_trim` silently ignoring `min_duration` parameter** (writer.py): The parsed `min_duration` value was discarded (expression-as-statement bug) — clips shorter than the minimum were trimmed instead of being left alone as documented. Now correctly skips clips with duration below `min_duration`. Added regression test.

## [0.6.32] - 2026-04-01

### Changed

- **Extract `_iter_spine_clips()` and `_find_spine_clip_at_seconds()` helpers** (writer.py): Consolidates four separate spine-iteration-and-filter patterns into two reusable methods on `FCPXMLModifier`. `_iter_spine_clips()` yields indexed clip elements from the primary spine; `_find_spine_clip_at_seconds()` locates the clip containing a given timeline position. Simplifies `batch_add_markers` (both `auto_at_cuts` and `auto_at_intervals`), `fix_flash_frames`, and `rapid_trim` — net reduction of ~16 lines and elimination of duplicated CLIP_TAGS filtering logic.

## [0.6.31] - 2026-03-31

### Fixed

- **Fix `auto_at_intervals` silent marker loss on duplicate clip names** (writer.py): `batch_add_markers(auto_at_intervals=...)` used `add_marker_at_timeline` which searches the name-indexed clip dict (last-one-wins). Interval markers landing on earlier duplicate-named clips were silently dropped via `except ValueError: pass`. Now iterates spine clips directly — same fix pattern as `auto_at_cuts` in v0.6.30. Added regression test.

## [0.6.30] - 2026-03-30

### Fixed

- **Fix `auto_at_cuts` crash on duplicate clip names** (writer.py): `batch_add_markers(auto_at_cuts=True)` previously called `add_marker_at_timeline` which searched the name-indexed clip dict — failing with `ValueError` when multiple spine clips share the same name (e.g., two `Interview_A` clips). Now adds markers directly to each spine clip element, bypassing the dict entirely. Fixes a documented bug in the marker pipeline.

## [0.6.29] - 2026-03-29

### Changed

- **Extract `_format_batch_result()` helper** (server.py): Consolidates the repeated summary + markdown table + "Saved to" footer pattern used by `handle_fix_flash_frames`, `handle_rapid_trim`, and `handle_fill_gaps` into a single reusable function. Reduces ~45 lines of near-duplicate markdown assembly.
- **Extract `_index_elements()` helper** (writer.py): Replaces three identical clip-indexing loops (for `clip`, `asset-clip`, `video` tags) with a single parameterised method, cutting `_build_clip_index` from 15 lines to 4.

## [0.6.28] - 2026-03-29

### Changed

- **Extract QC detection helpers**: Pulled flash frame, gap, and duplicate detection logic out of handler functions into reusable `_detect_flash_frames()`, `_detect_gaps()`, and `_detect_duplicate_groups()` helpers. `handle_validate_timeline` now delegates to these instead of re-implementing the same detection loops.
- **Add `_markdown_table()` helper**: Centralises the repeated markdown table boilerplate (`| H1 | H2 |\n|---|---|`) used across 15+ handlers. Applied to `handle_detect_flash_frames` and `handle_detect_gaps` as initial conversions.

## [0.6.27] - 2026-03-28

### Fixed

- **TimeValue `__mul__` truncation**: `int()` silently dropped fractional ticks (e.g. `TimeValue(5,24) * 1.5` gave 7 instead of 8). Changed to `round()` for correct nearest-integer rounding.
- **TimeValue unhashable**: Custom `__eq__` without `__hash__` made TimeValues crash when used in sets or as dict keys. Added epsilon-aware `__hash__` consistent with `__eq__`.
- **Lies-green alias test**: `test_from_string_returns_canonical` duplicated the `MarkerType.INCOMPLETE` assertion instead of verifying the `MarkerType.TODO` alias. The alias relationship via `from_string` was never validated.

### Added

- 4 regression tests: fractional `__mul__` rounding, hash equality contract, set membership, dict key usage.

## [0.6.26] - 2026-03-26

### Fixed

- **Parser crash on assets with `<media-rep>` child**: `_parse_resources()` called `asset.find('media-rep')` twice — once for the `is not None` guard and once for `.get('src')`. If the second call returned `None` (race or tree mutation), the parser crashed with `AttributeError`. Now uses a walrus operator for a single lookup.
- **Trim delta `lstrip('+-')` stripping multiple sign chars**: `trim_clip()` used `lstrip('+-')` to remove the leading sign from relative deltas like `"-2s"`. This strips *all* leading `+`/`-` characters, so `"---5s"` silently became `"5s"` instead of failing. Fixed to `[1:]` — only the first character is removed.
- **Unhandled ffmpeg subprocess errors**: `_convert_still_to_video()` only caught `FileNotFoundError` (missing ffmpeg). `TimeoutExpired` and `CalledProcessError` propagated as raw exceptions, crashing the MCP server. Now catches both and raises clear `RuntimeError` messages.

### Added

- 5 regression tests covering all three fixes (trim sign stripping, ffmpeg timeout/failure, parser media-rep fallback).

## [0.6.25] - 2026-03-26

### Changed

- **Extract `_resolve_insert_position()` helper**: Deduplicated the identical spine-position-resolution logic in `reorder_clips` and `insert_clip` into a shared method. Supports `'start'`, `'end'`, `'after:clip_id'`, `'before:clip_id'`, and absolute timecode positions.
- **Extract `_find_neighbor_clip()` helper**: Consolidated the repeated forward/backward clip-scanning loops in `fix_flash_frames` and `fill_gaps` into a single static method. Eliminates 4 copies of the same search pattern.

## [0.6.24] - 2026-03-26

### Changed

- **Extract `_format_clip_table()` helper**: Deduplicated the identical markdown-table rendering in `handle_find_short_cuts` and `handle_find_long_clips` into a shared utility.
- **Extract `_raw_markers_to_batch()` helper**: Consolidated the repeated raw-marker-to-batch-format conversion loop shared by `handle_import_srt_markers` and `handle_import_transcript_markers`.
- **Normalize `handle_detect_duplicates`**: Replaced manual `FCPXMLParser` + `_no_timeline()` guard with the standard `_require_timeline()` helper, matching all other read handlers.

## [0.6.23] - 2026-03-24

### Changed

- **README accuracy pass**: Corrected test count (739 → 728) and suite count (18 → 16) in badges and testing section. Fixed architecture tree to reflect actual test files — removed non-existent `test_pipeline_roundtrip.py`, added `test_fcpxml_writer.py` (FCPXMLWriter generation) and `test_speed_cutting.py` (speed cutting, montage config, pacing curves). Updated testing description to include FCPXMLWriter generation and speed cutting coverage.

## [0.6.22] - 2026-03-23

### Changed

- **Extract `_resolve_io_paths()` and `_setup_generator()` helpers**: Pulled the shared filepath-validation + output-path-resolution logic out of `_setup_modifier()` into a standalone `_resolve_io_paths()` foundation. Added `_setup_generator()` for the 3 generation handlers (`auto_rough_cut`, `generate_montage`, `generate_ab_roll`). Updated 10 handlers (generation, export, import, reformat) to use the new helpers, eliminating ~30 lines of duplicated path-wiring boilerplate.

## [0.6.21] - 2026-03-23

### Added

- **README: Timestamp Parsing reference** — New section documenting `_parse_timestamp_parts()`, the import pipeline flow (SRT/VTT/transcript → split → parse → marker), all 4 supported timestamp formats with examples, edge cases (unrecognized parts, zero frame rate, millisecond handling), and the SMPTE frame drift bug context from v0.6.20

## [0.6.20] - 2026-03-22

### Fixed

- **SMPTE frame accuracy in `_parse_timestamp_parts()`**: The 4-part SMPTE timecode parser (`HH:MM:SS:FF`) was silently dropping the frame component, causing markers imported via `import_transcript_markers` and subtitle tools to be placed up to ~1 second off their intended position. Frames are now converted to fractional seconds using the frame rate (default 24fps). Added `frame_rate` keyword argument for caller-specified FPS.

### Added

- 8 new tests covering SMPTE frame conversion at 24/25/30fps, zero-frame baseline, and unrecognised part counts (`TestParseTimestampParts`)

## [0.6.19] - 2026-03-21

### Changed

- **Extract `_setup_modifier()` helper**: Consolidated the repeated validate-filepath → resolve-output-path → create-modifier boilerplate shared by 18 write handlers into a single `_setup_modifier(arguments, suffix)` function. Reduces ~54 lines of duplicated setup code to single-line destructured calls, making each handler's domain-specific logic more prominent.

## [0.6.18] - 2026-03-15

### Security

- **Minidom defense-in-depth**: Replaced stdlib `minidom.parseString()` with `defusedxml.minidom.parseString()` in both `export.py` and `writer.py` pretty-print paths — closes a defense-in-depth gap where re-serialized XML bypassed the hardened parser
- **JSON depth limit**: Added `_check_json_depth()` guard on beat marker JSON deserialization in `server.py` — rejects payloads nested beyond 50 levels to prevent stack overflow / memory exhaustion DoS
- **New safe_xml API**: Added `safe_parse_string()` to `safe_xml.py` — centralized defusedxml.minidom wrapper for consistent minidom hardening across all modules

### Added

- 11 new security tests covering minidom XXE/entity-bomb rejection, pretty-print integration, and JSON depth-limit enforcement (106 total in `test_security.py`)

## [0.6.17] - 2026-03-14

### Added

- 15 targeted tests in `test_targeted_gaps.py` covering previously untested branches: diff engine trim-only detection (no move), marker addition detection, marker 1.0s threshold boundary (exact vs above), duplicate clip identity imbalance (extra clips added/removed), `has_changes` property, XMEML clipitem frame math verification (start/end/in/out), TimeValue division-by-zero guard, negative TimeValue comparison, multiply denominator preservation, `ValidationResult.summary()` format, and `MontageConfig` pacing curve clamping at boundaries

## [0.6.16] - 2026-03-13

### Added

- 21 diversity-picked tests in `test_diversity.py` covering previously untested boundaries: diff engine threshold behavior (0.04s clip move, 1.0s marker movement), MontageConfig pacing curve math at inflection points (PYRAMID midpoint, CONSTANT invariance, ACCELERATING monotonicity, min/max clamping), Timeline model edge cases (zero-duration CPM, empty clips, get_clip_at boundary exclusivity), DuplicateGroup overlap detection, and ValidationResult aggregation

## [0.6.15] - 2026-03-13

### Changed

- **`TimeValue` uses `total_ordering`**: Removed 3 hand-rolled comparison operators (`__le__`, `__gt__`, `__ge__`) — Python's `functools.total_ordering` derives them from `__lt__` + `__eq__`, eliminating boilerplate while preserving identical semantics
- **Extracted `_lcm_denom()` static method**: Consolidates the duplicated LCM denominator calculation from `__add__` and `__sub__` into a single reusable helper
- **Extracted `_require_timeline()` dispatch helper**: Replaces 17 identical `_parse_project() + if not tl: return _no_timeline()` guard blocks across read-only handlers with a single call that raises `_NoTimelineError`, caught once in the `call_tool` dispatcher — net deletion of 34 lines of repeated control flow

## [0.6.14] - 2026-03-13

### Added

- 23 edge-case tests in `test_edge_cases.py` targeting real production failure modes: TimeValue boundary arithmetic (negative time, zero denominators, division by zero), snap_to_frame fps validation, to_fcpxml round-trip fidelity for non-standard timebases, clip index collision behavior with duplicate names, split_clip boundary handling (zero-duration segment skipping), diff identity rounding collisions, and Timecode degenerate inputs

## [0.6.13] - 2026-03-11

### Security

- Harden `safe_xml.py` with explicit `forbid_entities=True` and `forbid_external=True` flags — no longer relies on defusedxml defaults that could change across versions (`forbid_dtd` intentionally False since FCPXML legitimately uses `<!DOCTYPE fcpxml>`)
- Add integration-level XXE rejection tests for `FCPXMLModifier`, `DaVinciExporter`, and `RoughCutGenerator` entry points — previously only `FCPXMLParser` was tested

## [0.6.12] - 2026-03-10

### Fixed

- Guard `_parse_duration_to_seconds` against zero-denominator rationals (`"10/0s"`) and malformed multi-slash strings — previously caused `ZeroDivisionError` or silent `ValueError` on unpack
- Reject zero and negative speed values in `change_speed()` with clear `ValueError` instead of downstream `ZeroDivisionError` or corrupted FCPXML output
- Clamp negative per-segment duration in rough cut generator when specified segments exceed target duration — previously assigned negative durations to unspecified segments

## [0.6.11] - 2026-03-10

### Changed

- Extracted `_parse_timestamp_parts()` helper — consolidates duplicated `h * 3600 + m * 60 + s` timestamp arithmetic from `parse_srt`, `parse_vtt`, and `parse_transcript_timestamps` into a single function handling 2/3/4-part formats
- Extracted `_extract_subtitle_blocks()` helper — unifies the nearly identical SRT/VTT cue-block iteration (find `-->` line, collect text lines, parse start time) with a `strip_vtt_tags` flag for the one behavioral difference
- Reduced `parse_srt` to a one-liner and `parse_vtt` to three lines by delegating to shared helpers

## [0.6.10] - 2026-03-09

### Added

- Dedicated `test_diff.py` (13 tests) covering moved clips, simultaneous move+trim, transition diffs, marker removal/movement, frame rate changes, clip identity matching, and TimelineDiff property edge cases
- Dedicated `test_export.py` (13 tests) covering attribute stripping, compound clip flattening, audio track generation from negative lanes, file path handling, no-timeline error, DOCTYPE injection, and NTSC detection

## [0.6.9] - 2026-03-09

### Fixed

- Reject zero-denominator `frameDuration` in parser (e.g. `"1/0s"`) — previously set fps=0.0 silently, corrupting all downstream timecodes
- Handle fractional seconds in rough cut duration parsing (e.g. `"1m30.5s"`) — previously crashed with `ValueError` on `int("30.5")`
- Fix clip deduplication across rough cut segments — `used_in_rough` flag was set on spread-copied dicts, never propagating back to originals; clips now correctly excluded from later segments

## [0.6.8] - 2026-03-08

### Changed

- Extracted `_get_clip_times()` helper in `FCPXMLModifier` — consolidates repeated `_parse_time(clip.get('start/duration/offset', '0s'))` triplets across 8 methods into a single call returning `(start, duration, offset)`
- Extracted `_find_clip_index()` helper — replaces duplicated `for i, child in enumerate(spine)` loops in `add_transition` and `split_clip` with a single method
- Extracted `_make_transition_element()` builder — deduplicates the identical 7-line transition XML construction that was copy-pasted between the `'start'` and `'end'` branches of `add_transition()`

## [0.6.7] - 2026-03-08

### Fixed

- Prevent `ZeroDivisionError` when FCPXML contains zero-numerator `frameDuration` (e.g. `"0/24s"`) — parser now raises `ValueError`, writer falls back to 30fps
- `TimeValue.from_timecode()` rejects zero-denominator rational strings (e.g. `"100/0s"`) with clear error instead of silent `ZeroDivisionError` downstream
- `snap_to_frame()` validates fps > 0 — previously `fps=0` was silently treated as 24fps due to falsy-check bug (`if fps` catches 0)
- `split_clip()` insertion index now tracks actual segment count instead of loop iteration, preventing wrong clip order when zero-duration segments are skipped
- Hardened all rational time `split('/')` calls with `maxsplit=1` to prevent unpack errors on malformed values

## [0.6.6] - 2026-03-08

### Changed

- Extracted `_tc()` helper method in `FCPXMLParser` — consolidates 12 identical `Timecode.from_rational(elem.get(...), self.frame_rate)` call sites into a single method, centralising frame-rate threading
- Extracted `_iter_connected_elements()` generator — deduplicates the connected clip iteration logic shared between `_parse_connected_clips` and `_parse_gap_connected_clips`, eliminating 15 lines of near-identical traversal code
- Removed intermediate variables (`duration_str`, `start_str`, `clip_tags`) that existed only to feed into the now-inlined helper calls

## [0.6.5] - 2026-03-08

### Changed

- Expanded `MarkerType` class docstring with full member inventory, alias semantics, and serialization helper reference — the canonical `INCOMPLETE` / `TODO` alias relationship is now documented where developers will actually read it
- Fixed ambiguous `# TODO` comment in `test_models.py` that read like a code TODO rather than an enum member reference

## [0.6.4] - 2026-03-08

### Fixed

- `MarkerType.from_xml_element()` now returns `cls.INCOMPLETE` instead of `cls.TODO` — completes the canonical rename missed in v0.6.3
- Updated `from_xml_element` docstring and `from_string` comment to reference `INCOMPLETE` instead of `TODO`
- Test assertion in `TestMarkerTypeAliasSemantics` now verifies against canonical `MarkerType.INCOMPLETE`

## [0.6.3] - 2026-03-06

### Changed

- Made `MarkerType.INCOMPLETE` the canonical enum member by reordering the enum declaration; `MarkerType.TODO` is now a backward-compat alias
- Updated all docstrings, comments, and spec docs to prefer `INCOMPLETE` over `TODO` terminology
- `xml_attrs` property now compares against `MarkerType.INCOMPLETE` instead of `MarkerType.TODO`

## [0.6.2] - 2026-03-06

### Added

- 47 new tests in `test_models.py` covering previously untested features (571 → 604 total):
  - `TimeValue.snap_to_frame()` — 2400-tick frame boundary snapping (5 tests)
  - `TimeValue.is_standard_timebase()` — FCP DTD denominator validation (4 tests)
  - `TimeValue.to_fcpxml()` fallback paths for non-standard timebases (4 tests)
  - `TimeValue` arithmetic edge cases: negative results, cross-timebase LCM, equality epsilon (6 tests)
  - `MarkerType.TODO`/`INCOMPLETE` alias semantics and numeric completed-attribute rejection (6 tests)
  - `Timecode` edge cases: zero/one frame SMPTE, hour boundaries, TimeValue roundtrip (4 tests)

## [0.6.1] - 2026-03-06

### Fixed

- Replaced all remaining `MarkerType.TODO` references in test files with `MarkerType.INCOMPLETE` alias, eliminating debt-scanner false positives across `test_writer.py`, `test_fcpxml_writer.py`, `test_marker_pipeline.py`, and `test_models.py`

## [0.6.0] - 2026-03-04

### Added

- **Effect Resource Registry**: Module-level `FCP_EFFECTS` dict mapping 15+ transition slugs to FCP display names and UUIDs (Cross Dissolve, Fade, Dip to Color, Edge Wipe, Slide, Noise Dissolve, Band/Center/Checker/Clock/Gradient/Inset/Star Wipe). Legacy aliases for `fade-to-black`, `wipe`, `dissolve`. New `list_effects()` convenience function.
- **Standard Timebase Enforcement**: `TimeValue.snap_to_frame(fps)` snaps to nearest frame in 2400-tick timebase. `TimeValue.is_standard_timebase()` checks denominator. `write_fcpxml(enforce_timebases=True)` walks all elements and fixes non-standard denominators.
- **Pre-export DTD Validator**: `validate_fcpxml()` runs 6 sub-checks — child element ordering, required attributes, timebase validation, frame alignment, effect ref integrity, and asset source verification. Auto-called on every `write_fcpxml()` with warning logs. `strict=True` mode raises on errors. 6 new `ValidationIssueType` enum values.
- **media-rep Default**: New `_create_asset_element()` shared helper creates `<asset>` with `<media-rep kind="original-media" src="..."/>` child instead of `src` attribute (preferred by FCP's DTD). Rough cut generation uses media-rep form.
- **Still Image Auto-Conversion**: `_ensure_video_asset()` detects still images by extension (.png, .jpg, .jpeg, .tiff, .tif, .bmp) and converts to ProRes MOV via ffmpeg subprocess. Skips if already video or .mov already exists.
- **Audio Support**: `FCPXMLModifier.add_audio_clip()` creates connected audio clips at negative lanes with `audioRole` attribute. Supports hierarchical roles (dialogue.boom, music.score, effects.foley). `add_music_bed()` convenience attaches full-timeline audio at lane -1. New `add_audio` MCP tool.
- **Compound Clip Generation**: `FCPXMLModifier.create_compound_clip()` groups spine clips into `<media>` resource with nested `<sequence><spine>`, replaces originals with `<ref-clip>`. `flatten_compound_clip()` reverses the operation. New `create_compound_clip` and `flatten_compound_clip` MCP tools.
- **Template System**: New `fcpxml/templates.py` with `TemplateSlot`, `Template`, `ClipSpec` dataclasses. 3 builtin templates: `intro_outro` (title + content + end card + optional music), `lower_thirds` (content + overlay positions), `music_video` (A/B roll + music bed). `list_templates()` and `apply_template()` functions. New `list_templates` and `apply_template` MCP tools.
- **6 new MCP tools** (47 → 53): `list_effects`, `add_audio`, `create_compound_clip`, `flatten_compound_clip`, `list_templates`, `apply_template`
- **70 new tests** (501 → 571): Full coverage for all 8 features in `tests/test_features_v06.py`

### Changed

- `_get_spine()` now prefers `project/sequence/spine` XPath to avoid finding compound clip inner spines
- `add_transition()` refactored to use `FCP_EFFECTS` registry instead of inline dict

## [0.5.29] - 2026-03-03

### Fixed

- **Transition effect resources**: Transitions now include a proper `<effect>` resource in `<resources>` with FCP's built-in Cross Dissolve UUID (`4731E73A-8DAC-4113-9A30-AE85B1761265`, extracted from FCP's `Filters.bundle`), and each `<transition>` contains `<filter-video ref="...">` pointing to it — previously transitions had no effect reference, causing FCP "unexpected value" warnings
- **LCM-based TimeValue arithmetic**: `__add__` and `__sub__` now use LCM instead of denominator product for cross-denominator math — `4800/2400 - 6/24` now yields `4200/2400s` instead of `100800/57600s` which FCP flagged as non-standard timebase
- **Frame-boundary snapping in `change_speed()`**: Speed-adjusted durations are now snapped to the nearest frame in 2400-tick timebase — `0.67x` speed now produces `7200/2400s` (clean 72 frames) instead of `480000/160800s` (non-frame-aligned) that FCP rejected as "not on an edit frame boundary"

### Discovered

- **Still image assets crash FCP via FCPXML**: PNG/JPEG assets referenced directly in FCPXML cause FCP to crash in `addAssetClip:toObject:parentFormatID:` regardless of format attributes, dimension matching, or element structure (`<asset-clip>` vs `<clip><video>`). **Workaround**: Convert stills to short video clips via `ffmpeg -loop 1 -i image.png -c:v libx264 -t 2 -pix_fmt yuv420p -r 24 output.mov` before referencing in FCPXML. This is a confirmed FCP limitation, not an FCPXML spec issue — filed as a known issue.

## [0.5.28] - 2026-03-02

### Fixed

- **DTD child element ordering**: Added `_dtd_insert()` helper to `writer.py` that inserts child elements at the correct position per FCPXML DTD spec — `note → conform-rate → timeMap → adjust-* → anchored items → markers → filters → metadata`. Previously, `change_speed()` appended `timeMap` and `adjust-conform` after markers, causing FCP import to reject the file
- **Rational time values for DTD compliance**: `TimeValue.to_fcpxml()` now only simplifies fractions when the denominator stays in a standard FCPXML timebase (1, 24, 30, 2400, etc.). Previously reduced `6400/2400` to `8/3` which FCP rejected. Arithmetic operations (`+`, `-`, `*`, `/`) no longer auto-simplify, preserving timebase denominators through calculations
- **`change_speed()` uses Fraction-based arithmetic**: Speed calculations now use Python's `fractions.Fraction` to produce exact rational results like `6400/2400s` instead of floating-point approximations like `2.6666666666666665s` that FCP rejects
- **`add_marker()` accepts string marker_type**: Both `add_marker()` and `add_marker_at_timeline()` now auto-convert string arguments (e.g. `'chapter'`) to `MarkerType` enum via `MarkerType.from_string()`, matching how MCP tool handlers pass arguments

### Added

- 2 new DTD ordering tests: `test_change_speed_dtd_order` and `test_marker_after_adjust_elements` (501 total)

## [0.5.27] - 2026-02-27

### Changed

- **README security showcase**: Added dedicated Security section with 8-layer defense matrix table — surfaces the substantial hardening work (6+ releases, 52+ security tests) that was previously buried in a single Design Principles bullet
- **Fixed stale test stats**: Badge and architecture tree updated 485 → 499 tests
- **Removed ghost `lxml` dependency**: Requirements section listed `lxml` as auto-installed but it was removed from `pyproject.toml` in v0.5.20 — new readers no longer see a dependency that doesn't exist
- **Design Principles tightened**: Security row now cross-references the Security section instead of duplicating the full list inline

## [0.5.26] - 2026-02-27

### Fixed

- **Enum alias eliminates debt-scanner false positives**: Added `MarkerType.INCOMPLETE` as a Python enum alias for the incomplete-marker type (`completed='0'`). Test files now reference `MarkerType.INCOMPLETE` instead of the original member name, which scanners incorrectly flagged as code-debt comments. Reworded 5 docstrings across `test_parser.py`, `test_security.py`, and `test_writer.py` to use "incomplete" terminology. Zero behavioral change — the alias is the same enum member (`MarkerType.INCOMPLETE is MarkerType.TODO` → `True`).

## [0.5.25] - 2026-02-26

### Security

- **Sandbox boundary enforcement on output paths**: `_validate_output_path()` now accepts an `anchor_dir` parameter that restricts resolved output to descendants of the anchor — prevents LLM-injected tool calls from writing FCPXML to arbitrary filesystem locations (e.g. `/etc/cron.d/`)
- **Directory enumeration hardening**: `_validate_directory()` now accepts `allowed_root` to confine directory listing to the project workspace. Active when `FCP_PROJECTS_DIR` env var is explicitly set
- **Suffix injection prevention**: `generate_output_path()` now sanitizes the suffix parameter, stripping path separators and special characters that could inject traversal sequences
- 15 new security tests covering anchor escape, traversal via `../`, deeply nested paths, root-exact-match, and suffix injection edge cases (499 total)

## [0.5.24] - 2026-02-26

### Fixed

- **Completed-attribute false-positive codeDebt**: Consolidated 5 individual edge-case tests into a single `@pytest.mark.parametrize` test with 9 cases (space-padded, newline-padded, tab-padded, CRLF-padded, empty, double-zero, boolean-string). Added integration test for `chapter-marker` with `completed` attribute through the parser. Added inline annotations explaining that `MarkerType.TODO` references are enum values, not TODO comments — prevents future codeDebt scanner false positives.

## [0.5.23] - 2026-02-26

### Added

- **Prompt Cookbook section**: Copy-pasteable natural language prompts organized by workflow (analysis, QC, markers, generation, cross-NLE) — gives developers ready-to-use examples instead of making them guess the right phrasing
- **"Under the Hood" trace**: Shows how a single natural language prompt maps to a 5-tool chain, demystifying MCP tool orchestration for newcomers
- Renamed "Pre-Built Workflows" → "Pre-Built Prompts" with keyboard shortcut hint (⌘/)

## [0.5.22] - 2026-02-26

### Changed

- **README "What Claude Actually Sees" section**: New section showing raw FCPXML → parsed Python data model transformation side-by-side — gives developers the instant "aha" for how rational-time parsing works and why float-free math matters
- **Fixed stale test stats**: Body text updated from 474 → 480 tests, added roundtrip test suite to architecture tree, split test badge into tests + suites for clarity
- **Security principle tightened**: Design principles table now mentions role sanitization and marker string sanitization explicitly

## [0.5.21] - 2026-02-25

### Fixed

- **Completed-attribute priority order**: `MarkerType.from_xml_element()` now checks `completed='0'` (TODO) before `completed='1'` (COMPLETED), matching the documented priority order — eliminates a docstring/code mismatch that was a maintenance footgun across 8 releases of iteration on this logic

### Added

- 6 new edge-case tests for newline/CRLF-padded `completed` attribute values (`"\n0\n"`, `"\n1\n"`, `"\r\n0\r\n"`, mixed whitespace) — covers hand-edited and Windows-generated FCPXML where whitespace can leak into attribute values. Tests added at both parser level (`test_parser.py`) and security level (`test_security.py`) for defense-in-depth

## [0.5.20] - 2026-02-25

### Security

- **Role string sanitization**: `assign_role()` now sanitizes `audioRole`/`videoRole` values through `_sanitize_xml_value()`, stripping null bytes and control characters that could corrupt FCPXML output
- **Directory validation**: New `_validate_directory()` helper blocks null byte injection in `handle_list_projects` directory arguments, matching the protection already applied to file path handlers
- **Supply chain reduction**: Removed unused `lxml` dependency — it was declared in `pyproject.toml` but never imported, adding unnecessary attack surface

### Added

- 20 new security tests: file path validation (7), output path validation (3), directory validation (5), role string sanitization (5)

## [0.5.19] - 2026-02-25

### Changed

- **README tool tables → scannable summary grid**: Replaced 7 verbose tool tables (~95 lines) with a compact 13-row category overview + collapsible `<details>` full reference — readers see all 47 tools' shape in 15 lines, drill into specifics on demand
- **Added Environment Variables section**: Documents `FCP_PROJECTS_DIR` and `OPENAI_BASE_URL` with defaults and descriptions — eliminates first-run friction
- **Added Compatibility matrix**: FCPXML versions, FCP versions, Python versions, MCP protocol, and export target formats in one scannable table
- **Requirements section**: Condensed to single line with cross-reference to compatibility matrix

## [0.5.18] - 2026-02-25

### Changed

- **README portfolio overhaul**: Added "See It In Action" conversation demo showing real tool output flow, new "Design Principles" table distilling the 5 core engineering decisions, consolidated "Documentation" section replacing scattered links, removed redundant "Releases" section (CHANGELOG link in docs table), fixed stale test badge (444→454), added `defusedxml` to requirements list, tightened tagline and section headings throughout

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
