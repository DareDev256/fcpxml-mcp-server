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
    """Add a TODO marker to a clip."""
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
