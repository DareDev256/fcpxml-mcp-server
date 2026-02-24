"""Tests for FCPXML writer/modifier."""

import shutil
import tempfile
from pathlib import Path

import pytest

from fcpxml.parser import FCPXMLParser
from fcpxml.writer import FCPXMLModifier

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.fcpxml"


@pytest.fixture
def temp_fcpxml():
    """Create a temp copy of sample.fcpxml for modification tests."""
    with tempfile.NamedTemporaryFile(suffix='.fcpxml', delete=False) as f:
        shutil.copy(SAMPLE, f.name)
        yield f.name
    Path(f.name).unlink(missing_ok=True)


# ============================================================
# Insert Clip Tests
# ============================================================

def test_insert_clip_at_end(temp_fcpxml):
    """Insert a library clip at the end of the timeline."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Get initial clip count
    initial_count = len(list(modifier._get_spine()))

    # Insert Broll_City (r3) at the end
    result = modifier.insert_clip(
        asset_id='r3',
        position='end',
        duration='2s'
    )

    assert result is not None

    # Verify clip was added
    final_count = len(list(modifier._get_spine()))
    assert final_count == initial_count + 1


def test_insert_clip_at_start(temp_fcpxml):
    """Insert a library clip at the start of the timeline."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Insert clip at start
    modifier.insert_clip(
        asset_id='r4',  # Broll_Studio
        position='start',
        duration='1s'
    )

    # Verify clip is at offset 0
    spine = modifier._get_spine()
    first_clip = list(spine)[0]
    assert first_clip.get('offset') == '0/24s' or first_clip.get('offset') == '0s'


def test_insert_clip_at_timecode(temp_fcpxml):
    """Insert a library clip at a specific timecode."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Insert at 00:00:05:00 (5 seconds)
    result = modifier.insert_clip(
        asset_id='r3',
        position='00:00:05:00',
        duration='1s'
    )

    # Verify clip was inserted
    assert result is not None


def test_insert_clip_with_subclip(temp_fcpxml):
    """Insert a portion of a library clip (subclip)."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Insert with in/out points
    result = modifier.insert_clip(
        asset_id='r2',  # Interview_A (300s long)
        position='end',
        in_point='00:00:10:00',  # Start at 10s in source
        out_point='00:00:15:00'  # End at 15s in source (5s clip)
    )

    # Verify the start attribute matches in_point
    start_attr = result.get('start')
    assert start_attr is not None
    # Should be 10 seconds worth of frames (240/24s at 24fps)
    assert '240' in start_attr or '10s' in start_attr


def test_insert_clip_ripples_subsequent(temp_fcpxml):
    """Inserting a clip should shift subsequent clips forward."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Get second clip's original offset
    spine = modifier._get_spine()
    clips = [c for c in spine if c.tag in ('asset-clip', 'clip')]
    original_second_clip_offset = clips[1].get('offset')

    # Insert 2 seconds at start
    modifier.insert_clip(
        asset_id='r4',
        position='start',
        duration='2s',
        ripple=True
    )

    # Verify second clip shifted
    spine = modifier._get_spine()
    clips = [c for c in spine if c.tag in ('asset-clip', 'clip')]
    # Original second clip is now at index 2 (after new clip at 0)
    new_second_clip = clips[2]  # Was clips[1], now clips[2]

    # Original offset was 72/24s = 3s, now should be 120/24s = 5s (+2s)
    new_offset = new_second_clip.get('offset')
    assert new_offset != original_second_clip_offset


def test_insert_clip_by_name(temp_fcpxml):
    """Can insert a clip by asset name instead of ID."""
    modifier = FCPXMLModifier(temp_fcpxml)

    result = modifier.insert_clip(
        asset_name='Broll_City',  # Instead of asset_id='r3'
        position='end',
        duration='1s'
    )

    assert result is not None
    assert result.get('ref') == 'r3'


def test_insert_clip_after_specific_clip(temp_fcpxml):
    """Insert clip after a specific clip."""
    modifier = FCPXMLModifier(temp_fcpxml)

    result = modifier.insert_clip(
        asset_id='r3',
        position='after:Interview_A',  # After first Interview_A
        duration='1s'
    )

    assert result is not None


def test_insert_clip_saves_correctly(temp_fcpxml):
    """Inserted clip should persist after save and reload."""
    modifier = FCPXMLModifier(temp_fcpxml)
    initial_count = len(list(modifier._get_spine()))

    modifier.insert_clip(
        asset_id='r3',
        position='end',
        duration='2s'
    )

    # Save to temp file
    output = temp_fcpxml.replace('.fcpxml', '_modified.fcpxml')
    modifier.save(output)

    # Reload and verify
    parser = FCPXMLParser()
    project = parser.parse_file(output)
    reloaded_clip_count = len(project.primary_timeline.clips)

    # Clean up
    Path(output).unlink(missing_ok=True)

    assert reloaded_clip_count == initial_count + 1


# ============================================================
# Add Marker Tests
# ============================================================

def test_add_marker_standard(temp_fcpxml):
    """Add a standard marker to a clip."""
    modifier = FCPXMLModifier(temp_fcpxml)

    marker = modifier.add_marker(
        clip_id='Broll_City',
        timecode='00:00:01:00',
        name='Review this'
    )

    assert marker is not None
    assert marker.tag == 'marker'
    assert marker.get('value') == 'Review this'
    assert marker.get('start') is not None


def test_add_marker_chapter(temp_fcpxml):
    """Add a chapter marker to a clip."""
    from fcpxml.models import MarkerType

    modifier = FCPXMLModifier(temp_fcpxml)

    marker = modifier.add_marker(
        clip_id='Broll_City',
        timecode='00:00:00:12',
        name='Chapter Start',
        marker_type=MarkerType.CHAPTER
    )

    assert marker.tag == 'chapter-marker'
    assert marker.get('value') == 'Chapter Start'
    assert marker.get('posterOffset') == '0s'


def test_add_marker_todo(temp_fcpxml):
    """Add a TODO marker to a clip — must set completed='0' for round-trip fidelity."""
    from fcpxml.models import MarkerType

    modifier = FCPXMLModifier(temp_fcpxml)

    marker = modifier.add_marker(
        clip_id='Broll_City',
        timecode='00:00:00:06',
        name='Fix color',
        marker_type=MarkerType.TODO
    )

    assert marker.tag == 'marker'
    assert marker.get('value') == 'Fix color'
    assert marker.get('completed') == '0'


def test_add_marker_completed(temp_fcpxml):
    """Add a completed marker to a clip."""
    from fcpxml.models import MarkerType

    modifier = FCPXMLModifier(temp_fcpxml)

    marker = modifier.add_marker(
        clip_id='Broll_City',
        timecode='00:00:00:06',
        name='Done item',
        marker_type=MarkerType.COMPLETED
    )

    assert marker.get('completed') == '1'


def test_marker_type_roundtrip(temp_fcpxml, tmp_path):
    """TODO and COMPLETED markers survive save/re-parse without losing their type."""
    from fcpxml.models import MarkerType
    from fcpxml.parser import FCPXMLParser

    modifier = FCPXMLModifier(temp_fcpxml)
    modifier.add_marker('Broll_City', '00:00:00:06', 'Todo task', MarkerType.TODO)
    modifier.add_marker('Broll_City', '00:00:00:12', 'Done task', MarkerType.COMPLETED)

    output = str(tmp_path / 'roundtrip.fcpxml')
    modifier.save(output)

    project = FCPXMLParser().parse_file(output)
    # Collect all markers across all clips (duplicate names mean markers land on last Broll_City)
    all_markers = []
    for clip in project.primary_timeline.clips:
        all_markers.extend(clip.markers)
    types = {m.name: m.marker_type for m in all_markers}
    assert types['Todo task'] == MarkerType.TODO
    assert types['Done task'] == MarkerType.COMPLETED


def test_marker_type_from_string_roundtrip(temp_fcpxml, tmp_path):
    """MarkerType.from_string('todo') → write → parse must survive as TODO, not STANDARD."""
    from fcpxml.models import MarkerType
    from fcpxml.parser import FCPXMLParser

    modifier = FCPXMLModifier(temp_fcpxml)
    # Use from_string (the path batch_add_markers takes) instead of enum directly
    modifier.add_marker('Broll_City', '00:00:00:06', 'Via string',
                        MarkerType.from_string('todo'))
    modifier.add_marker('Broll_City', '00:00:00:12', 'Via alias',
                        MarkerType.from_string('todo-marker'))

    output = str(tmp_path / 'from_string_rt.fcpxml')
    modifier.save(output)

    project = FCPXMLParser().parse_file(output)
    all_markers = []
    for clip in project.primary_timeline.clips:
        all_markers.extend(clip.markers)
    types = {m.name: m.marker_type for m in all_markers}
    assert types['Via string'] == MarkerType.TODO
    assert types['Via alias'] == MarkerType.TODO


def test_marker_completed_attr_no_whitespace(temp_fcpxml):
    """Written completed attributes must be exact '0' or '1' — no whitespace padding."""
    from fcpxml.models import MarkerType

    modifier = FCPXMLModifier(temp_fcpxml)
    todo = modifier.add_marker('Broll_City', '00:00:00:06', 'Strict0', MarkerType.TODO)
    done = modifier.add_marker('Broll_City', '00:00:00:12', 'Strict1', MarkerType.COMPLETED)

    assert todo.get('completed') == '0', "TODO marker must write exact '0'"
    assert done.get('completed') == '1', "COMPLETED marker must write exact '1'"
    # Verify no leading/trailing whitespace
    assert todo.get('completed').strip() == todo.get('completed')
    assert done.get('completed').strip() == done.get('completed')


def test_from_string_whitespace_roundtrip(temp_fcpxml, tmp_path):
    """from_string('  completed  ') must roundtrip as COMPLETED, not STANDARD."""
    from fcpxml.models import MarkerType
    from fcpxml.parser import FCPXMLParser

    modifier = FCPXMLModifier(temp_fcpxml)
    modifier.add_marker('Broll_City', '00:00:00:06', 'Padded type',
                        MarkerType.from_string('  completed  '))

    output = str(tmp_path / 'padded_type_rt.fcpxml')
    modifier.save(output)

    project = FCPXMLParser().parse_file(output)
    all_markers = []
    for clip in project.primary_timeline.clips:
        all_markers.extend(clip.markers)
    types = {m.name: m.marker_type for m in all_markers}
    assert types['Padded type'] == MarkerType.COMPLETED


def test_add_marker_with_note(temp_fcpxml):
    """Add a marker with a note."""
    modifier = FCPXMLModifier(temp_fcpxml)

    marker = modifier.add_marker(
        clip_id='Broll_City',
        timecode='00:00:00:06',
        name='Note marker',
        note='Needs color correction'
    )

    assert marker.get('note') == 'Needs color correction'


def test_add_marker_invalid_clip(temp_fcpxml):
    """Adding a marker to a nonexistent clip raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="Clip not found"):
        modifier.add_marker(
            clip_id='nonexistent_clip',
            timecode='00:00:01:00',
            name='Should fail'
        )


# ============================================================
# Trim Clip Tests
# ============================================================

def test_trim_clip_end_delta(temp_fcpxml):
    """Trim the end of a clip by a delta."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Broll_Studio at offset 222/24s has duration 120/24s = 5s
    clip = modifier.trim_clip(
        clip_id='Broll_Studio',
        trim_end='-1s',
        ripple=False
    )

    # Duration should decrease by 1s (24 frames at 24fps)
    new_duration = modifier._parse_time(clip.get('duration'))
    assert new_duration.to_seconds() == pytest.approx(4.0, abs=0.1)


def test_trim_clip_start_delta(temp_fcpxml):
    """Trim the start of a clip by a delta."""
    modifier = FCPXMLModifier(temp_fcpxml)

    original_clip = modifier.clips['Broll_Studio']
    original_start = modifier._parse_time(original_clip.get('start')).to_seconds()
    original_duration = modifier._parse_time(original_clip.get('duration')).to_seconds()

    clip = modifier.trim_clip(
        clip_id='Broll_Studio',
        trim_start='+1s',
        ripple=False
    )

    new_start = modifier._parse_time(clip.get('start')).to_seconds()
    new_duration = modifier._parse_time(clip.get('duration')).to_seconds()

    # Start moved forward by 1s, duration decreased by 1s
    assert new_start == pytest.approx(original_start + 1.0, abs=0.1)
    assert new_duration == pytest.approx(original_duration - 1.0, abs=0.1)


def test_trim_clip_invalid_clip(temp_fcpxml):
    """Trimming a nonexistent clip raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="Clip not found"):
        modifier.trim_clip(clip_id='ghost_clip', trim_end='-1s')


# ============================================================
# Delete Clip Tests
# ============================================================

def test_delete_clip_ripple(temp_fcpxml):
    """Delete a clip with ripple (shifts subsequent clips)."""
    modifier = FCPXMLModifier(temp_fcpxml)
    initial_count = len(list(modifier._get_spine()))

    modifier.delete_clip(clip_ids=['Broll_City'], ripple=True)

    final_count = len(list(modifier._get_spine()))
    assert final_count == initial_count - 1
    assert 'Broll_City' not in modifier.clips


def test_delete_clip_no_ripple_leaves_gap(temp_fcpxml):
    """Delete a clip without ripple replaces it with a gap."""
    modifier = FCPXMLModifier(temp_fcpxml)
    initial_count = len(list(modifier._get_spine()))

    modifier.delete_clip(clip_ids=['Broll_City'], ripple=False)

    # Element count stays the same (clip replaced by gap)
    final_count = len(list(modifier._get_spine()))
    assert final_count == initial_count

    # Verify a gap element was created
    spine = modifier._get_spine()
    gaps = [c for c in spine if c.tag == 'gap']
    assert len(gaps) >= 1


def test_delete_nonexistent_clip_is_noop(temp_fcpxml):
    """Deleting a nonexistent clip silently succeeds."""
    modifier = FCPXMLModifier(temp_fcpxml)
    initial_count = len(list(modifier._get_spine()))

    modifier.delete_clip(clip_ids=['does_not_exist'])

    final_count = len(list(modifier._get_spine()))
    assert final_count == initial_count


# ============================================================
# Split Clip Tests
# ============================================================

def test_split_clip_single_point(temp_fcpxml):
    """Split a clip at one point produces two segments."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # The indexed Interview_A is the last one: offset 1122/24s, duration 168/24s = 7s
    original_duration = modifier._parse_time(
        modifier.clips['Interview_A'].get('duration')
    ).to_seconds()

    results = modifier.split_clip(
        clip_id='Interview_A',
        split_points=['00:00:03:00']  # Split 3s into a 7s clip
    )

    assert len(results) == 2

    # Both segments should have duration summing to original
    dur1 = modifier._parse_time(results[0].get('duration')).to_seconds()
    dur2 = modifier._parse_time(results[1].get('duration')).to_seconds()
    assert dur1 + dur2 == pytest.approx(original_duration, abs=0.5)


def test_split_clip_invalid_clip(temp_fcpxml):
    """Splitting a nonexistent clip raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="Clip not found"):
        modifier.split_clip(clip_id='ghost', split_points=['00:00:01:00'])


# ============================================================
# Change Speed Tests
# ============================================================

def test_change_speed_double(temp_fcpxml):
    """Doubling speed halves clip duration."""
    modifier = FCPXMLModifier(temp_fcpxml)

    original_duration = modifier._parse_time(
        modifier.clips['Broll_Studio'].get('duration')
    ).to_seconds()

    clip = modifier.change_speed(clip_id='Broll_Studio', speed=2.0)

    new_duration = modifier._parse_time(clip.get('duration')).to_seconds()
    assert new_duration == pytest.approx(original_duration / 2.0, abs=0.1)

    # Should have a timeMap element
    timemap = clip.find('timeMap')
    assert timemap is not None


def test_change_speed_half(temp_fcpxml):
    """Halving speed doubles clip duration."""
    modifier = FCPXMLModifier(temp_fcpxml)

    original_duration = modifier._parse_time(
        modifier.clips['Broll_Studio'].get('duration')
    ).to_seconds()

    clip = modifier.change_speed(clip_id='Broll_Studio', speed=0.5)

    new_duration = modifier._parse_time(clip.get('duration')).to_seconds()
    assert new_duration == pytest.approx(original_duration * 2.0, abs=0.1)


def test_change_speed_invalid_clip(temp_fcpxml):
    """Changing speed on nonexistent clip raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="Clip not found"):
        modifier.change_speed(clip_id='ghost', speed=2.0)


# ============================================================
# Add Transition Tests
# ============================================================

def test_add_transition_at_end(temp_fcpxml):
    """Add a cross-dissolve transition at the end of a clip."""
    modifier = FCPXMLModifier(temp_fcpxml)
    spine = modifier._get_spine()
    initial_count = len(list(spine))

    transition = modifier.add_transition(
        clip_id='Broll_City',
        position='end',
        transition_type='cross-dissolve',
        duration='00:00:00:12'
    )

    assert transition.tag == 'transition'
    assert transition.get('name') == 'Cross Dissolve'
    assert transition.get('duration') is not None
    assert transition.find('filter-video') is not None
    assert len(list(modifier._get_spine())) == initial_count + 1


def test_add_transition_at_both(temp_fcpxml):
    """Add transitions at both ends inserts two elements."""
    modifier = FCPXMLModifier(temp_fcpxml)
    initial_count = len(list(modifier._get_spine()))

    result = modifier.add_transition(
        clip_id='Broll_City', position='both',
        transition_type='cross-dissolve', duration='00:00:00:12'
    )

    assert isinstance(result, list) or result.tag == 'transition'
    assert len(list(modifier._get_spine())) == initial_count + 2


def test_add_transition_invalid_clip(temp_fcpxml):
    """Adding a transition to a nonexistent clip raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="Clip not found"):
        modifier.add_transition(clip_id='ghost_clip', position='end')


# ============================================================
# Reorder Clips Tests
# ============================================================

def test_reorder_clips_to_end(temp_fcpxml):
    """Move a clip to the end of the timeline."""
    modifier = FCPXMLModifier(temp_fcpxml)
    initial_count = len(list(modifier._get_spine()))

    modifier.reorder_clips(
        clip_ids=['Broll_City'], target_position='end', ripple=True
    )

    spine_list = list(modifier._get_spine())
    assert len(spine_list) == initial_count
    assert spine_list[-1].get('name') == 'Broll_City'


def test_reorder_clips_to_start(temp_fcpxml):
    """Move a clip to the start of the timeline."""
    modifier = FCPXMLModifier(temp_fcpxml)

    modifier.reorder_clips(
        clip_ids=['Broll_City'], target_position='start', ripple=True
    )

    first_clip = list(modifier._get_spine())[0]
    assert first_clip.get('name') == 'Broll_City'
    assert first_clip.get('offset') in ('0s', '0/24s')


def test_reorder_clips_invalid_raises(temp_fcpxml):
    """Reordering nonexistent clips raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="No clips found"):
        modifier.reorder_clips(clip_ids=['nonexistent'], target_position='start')


# ============================================================
# Add Marker at Timeline Tests
# ============================================================

def test_add_marker_at_timeline_position(temp_fcpxml):
    """Add a marker at a timeline position within an indexed clip."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Broll_Studio (last indexed): offset 222/24s=9.25s, dur 120/24s=5s
    marker = modifier.add_marker_at_timeline(
        timecode='00:00:10:00', name='Timeline marker'
    )

    assert marker is not None
    assert marker.get('value') == 'Timeline marker'


def test_add_marker_at_timeline_invalid_position(temp_fcpxml):
    """Adding a marker past the timeline end raises ValueError."""
    modifier = FCPXMLModifier(temp_fcpxml)

    with pytest.raises(ValueError, match="No clip found"):
        modifier.add_marker_at_timeline(timecode='99:00:00:00', name='Way past end')


# ============================================================
# Batch Add Markers Tests
# ============================================================

def test_batch_add_markers_explicit(temp_fcpxml):
    """Add multiple explicit markers in a batch."""
    modifier = FCPXMLModifier(temp_fcpxml)

    markers = [
        {'timecode': '00:00:10:00', 'name': 'Marker A'},
        {'timecode': '00:00:48:00', 'name': 'Marker B'},
    ]

    created = modifier.batch_add_markers(markers=markers)

    assert len(created) == 2
    assert created[0].get('value') == 'Marker A'
    assert created[1].get('value') == 'Marker B'


def test_batch_add_markers_with_type(temp_fcpxml):
    """Batch markers respect marker_type parameter."""
    modifier = FCPXMLModifier(temp_fcpxml)

    markers = [
        {'timecode': '00:00:10:00', 'name': 'Chapter 1', 'marker_type': 'chapter'},
    ]

    created = modifier.batch_add_markers(markers=markers)

    assert len(created) == 1
    assert created[0].tag == 'chapter-marker'


# ============================================================
# Select by Keyword Tests
# ============================================================

def test_select_by_keyword_any(temp_fcpxml):
    """Select clips matching any of the given keywords."""
    modifier = FCPXMLModifier(temp_fcpxml)

    matches = modifier.select_by_keyword(keywords=['B-Roll'], match_mode='any')

    assert len(matches) >= 1
    for clip_id in matches:
        clip = modifier.clips[clip_id]
        kw_values = [kw.get('value', '') for kw in clip.findall('keyword')]
        assert 'B-Roll' in kw_values


def test_select_by_keyword_no_matches(temp_fcpxml):
    """Selecting with a nonexistent keyword returns empty list."""
    modifier = FCPXMLModifier(temp_fcpxml)

    matches = modifier.select_by_keyword(keywords=['FakeKeyword'], match_mode='any')
    assert matches == []


def test_select_by_keyword_all_mode(temp_fcpxml):
    """'all' mode requires clips to have every keyword."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # No clip has both 'Interview' AND 'B-Roll'
    matches = modifier.select_by_keyword(
        keywords=['Interview', 'B-Roll'], match_mode='all'
    )
    assert matches == []
