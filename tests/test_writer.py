"""Tests for FCPXML writer/modifier."""

import pytest
from pathlib import Path
import tempfile
import shutil

from fcpxml.writer import FCPXMLModifier
from fcpxml.parser import FCPXMLParser

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
    result = modifier.insert_clip(
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
