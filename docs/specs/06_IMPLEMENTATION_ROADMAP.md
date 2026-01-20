# FCP MCP Server - Implementation Roadmap

Step-by-step plan to build all editing features.

---

## Current State

✅ **DONE:**
- Repository structure
- Basic parser (read FCPXML)
- 10 read-only MCP tools
- Claude Desktop integration config

🔄 **IN PROGRESS:**
- Writer module architecture
- Tool schemas for editing

---

## Implementation Order

### Sprint 1: Core Write Operations (Week 1)

**Day 1-2: TimeValue & Writer Foundation**
```
Tasks:
□ Implement TimeValue class with all operations
□ Create FCPXMLWriter base class
□ Implement _detect_fps()
□ Implement _build_clip_index()
□ Implement save()
□ Write unit tests for TimeValue
```

**Day 3-4: Marker Operations**
```
Tasks:
□ Implement add_marker()
□ Implement batch_add_markers()
□ Handle marker types (standard, chapter, todo)
□ Handle marker colors
□ Test with real FCP export
□ Verify re-import into FCP
```

**Day 5-6: Trim Operations**
```
Tasks:
□ Implement trim_clip() - absolute timecodes
□ Implement trim_clip() - delta trimming
□ Implement _ripple_after_clip()
□ Test with ripple=True and ripple=False
□ Edge case: trim to zero duration (should fail)
□ Edge case: trim beyond clip bounds (should clamp)
```

**Day 7: Reorder Operations**
```
Tasks:
□ Implement reorder_clips() - move to start/end
□ Implement reorder_clips() - move to timecode
□ Implement reorder_clips() - after/before clip
□ Implement _recalculate_offsets()
□ Test multi-clip moves
```

---

### Sprint 2: Advanced Edit Operations (Week 2)

**Day 1-2: Transitions**
```
Tasks:
□ Implement add_transition() - cross-dissolve
□ Implement add_transition() - fade variants
□ Find FCP effect reference IDs
□ Test position: start, end, both
□ Handle transition overlap calculation
```

**Day 3-4: Speed Changes**
```
Tasks:
□ Implement change_speed() - constant speed
□ Implement change_speed() - speed ramps
□ Create timeMap XML structure
□ Test slow-mo (0.5x) and fast (2x)
□ Test speed ramp with different curves
□ Verify frame blending options
```

**Day 5-6: Split & Delete**
```
Tasks:
□ Implement split_clip() - single split point
□ Implement split_clip() - multiple split points
□ Implement delete_clip() - with ripple
□ Implement delete_clip() - with gap
□ Test split preserves clip attributes
□ Test delete updates clip index
```

**Day 7: Selection & Batch**
```
Tasks:
□ Implement select_by_keyword()
□ Implement batch_trim()
□ Test keyword matching modes (any, all, none)
□ Test batch operations on 10+ clips
```

---

### Sprint 3: Auto Rough Cut (Week 3)

**Day 1-2: Ingest Phase**
```
Tasks:
□ Implement ingest_source_clips()
□ Parse asset-clips from library exports
□ Parse clips from event exports
□ Extract all metadata (keywords, ratings, favorites)
□ Test with 100+ clip library
```

**Day 3-4: Score Phase**
```
Tasks:
□ Implement score_clips()
□ Implement keyword matching scoring
□ Implement rating/favorite scoring
□ Implement duration fit scoring
□ Test scoring produces sensible rankings
```

**Day 5-6: Select Phase**
```
Tasks:
□ Implement select_clips_for_segment()
□ Implement all priority modes
□ Implement pacing-based duration calculation
□ Test clip selection respects already_used
□ Test segment duration targets
```

**Day 7: Assemble Phase**
```
Tasks:
□ Implement assemble_rough_cut()
□ Create proper FCPXML document structure
□ Add asset resources correctly
□ Add transitions between segments
□ Test complete rough cut generation
□ Import result into FCP - verify it works
```

---

### Sprint 4: Polish & Ship (Week 4)

**Day 1-2: Error Handling**
```
Tasks:
□ Add validation for all inputs
□ Graceful handling of malformed FCPXML
□ Clear error messages for common issues
□ Logging throughout
```

**Day 3-4: Integration Testing**
```
Tasks:
□ Create test suite with real FCP exports
□ Test each tool end-to-end
□ Test tool combinations (marker + trim + reorder)
□ Performance testing with large projects
```

**Day 5-6: Documentation**
```
Tasks:
□ Complete README with all tools
□ Add usage examples for each tool
□ Create tutorial: "Your first rough cut"
□ Add troubleshooting guide
□ Record demo video
```

**Day 7: Launch**
```
Tasks:
□ Final testing pass
□ Version bump to 1.0.0
□ Push to GitHub
□ Submit to MCP registry
□ Write launch posts
□ Share with FCP communities
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_timevalue.py
def test_from_timecode_hmsf():
    tv = TimeValue.from_timecode("00:01:30:15", fps=30)
    assert tv.to_seconds() == 90.5

def test_from_timecode_fcpxml():
    tv = TimeValue.from_timecode("2700/30s")
    assert tv.to_seconds() == 90.0

def test_addition():
    a = TimeValue(30, 30)  # 1 second
    b = TimeValue(60, 30)  # 2 seconds
    c = a + b
    assert c.to_seconds() == 3.0

def test_simplify():
    tv = TimeValue(60, 30)
    simplified = tv.simplify()
    assert simplified.numerator == 2
    assert simplified.denominator == 1
```

### Integration Tests

```python
# tests/test_writer_integration.py
def test_add_marker_reimports():
    """Marker added by writer should be visible in FCP."""
    # 1. Create modified FCPXML
    writer = FCPXMLWriter("fixtures/sample.fcpxml")
    writer.add_marker("clip_0", "00:00:10:00", "Test Marker", MarkerType.CHAPTER)
    writer.save("output/test_marker.fcpxml")
    
    # 2. Parse it back
    parser = FCPXMLParser("output/test_marker.fcpxml")
    timeline = parser.parse()
    
    # 3. Verify marker exists
    marker_names = [m.name for m in timeline.markers]
    assert "Test Marker" in marker_names

def test_trim_preserves_structure():
    """Trimming shouldn't corrupt other timeline elements."""
    writer = FCPXMLWriter("fixtures/sample.fcpxml")
    original_clip_count = len(writer.clips)
    
    writer.trim_clip("clip_0", trim_end="-1s")
    writer.save("output/test_trim.fcpxml")
    
    parser = FCPXMLParser("output/test_trim.fcpxml")
    timeline = parser.parse()
    
    # Same number of clips
    assert len(timeline.clips) == original_clip_count
```

### Golden Set Tests

```python
# tests/golden_set.py
"""
Golden set: known-good FCPXML files that must parse correctly.
If any fail, we broke backward compatibility.
"""

GOLDEN_FILES = [
    "fixtures/golden/simple_timeline.fcpxml",
    "fixtures/golden/multicam_project.fcpxml",
    "fixtures/golden/compound_clips.fcpxml",
    "fixtures/golden/with_effects.fcpxml",
    "fixtures/golden/fcp_10_6_export.fcpxml",
    "fixtures/golden/fcp_10_7_export.fcpxml",
    "fixtures/golden/fcp_10_8_export.fcpxml",
]

@pytest.mark.parametrize("filepath", GOLDEN_FILES)
def test_golden_file_parses(filepath):
    parser = FCPXMLParser(filepath)
    timeline = parser.parse()
    assert timeline is not None
    assert len(timeline.clips) > 0
```

---

## Risk Mitigation

### Risk: FCPXML format changes between FCP versions

**Mitigation:**
- Test against multiple FCP export versions (10.6, 10.7, 10.8)
- Use conservative parsing (ignore unknown elements)
- Version detection in parser
- Golden set tests for each version

### Risk: Generated FCPXML rejected by FCP

**Mitigation:**
- Always validate output XML
- Round-trip testing (export → modify → import)
- Use FCP's own exports as templates
- Keep original attributes we don't understand

### Risk: Data loss from edit operations

**Mitigation:**
- Never overwrite original by default
- Backup before destructive operations
- Validate timeline integrity after each operation
- Undo capability (save original state)

### Risk: Performance with large projects

**Mitigation:**
- Lazy loading of clip metadata
- Index-based clip lookup
- Stream parsing for very large files
- Progress callbacks for long operations

---

## File Structure (Final)

```
fcp-mcp-server/
├── server.py                 # MCP server entry point
├── fcpxml/
│   ├── __init__.py
│   ├── parser.py             # Read operations
│   ├── writer.py             # Write operations
│   ├── rough_cut.py          # Auto rough cut algorithm
│   ├── models.py             # Data classes
│   └── utils.py              # TimeValue, converters
├── tests/
│   ├── __init__.py
│   ├── test_parser.py
│   ├── test_writer.py
│   ├── test_rough_cut.py
│   ├── test_timevalue.py
│   ├── golden_set.py
│   └── fixtures/
│       ├── sample.fcpxml
│       └── golden/
├── examples/
│   ├── basic_usage.py
│   ├── rough_cut_example.py
│   └── batch_markers.py
├── docs/
│   ├── TOOL_REFERENCE.md
│   ├── FCPXML_GUIDE.md
│   └── TROUBLESHOOTING.md
├── pyproject.toml
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Definition of Done

A feature is complete when:

1. ✅ Code implemented and working
2. ✅ Unit tests passing
3. ✅ Integration test with real FCP export
4. ✅ Re-import into FCP verified
5. ✅ Error handling for edge cases
6. ✅ Documented in README
7. ✅ Example usage provided
