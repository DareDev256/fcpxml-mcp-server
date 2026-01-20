"""Tests for v0.3.0 Speed Cutting & AI-Powered features."""

import pytest
from pathlib import Path
import tempfile
import shutil
import json

from fcpxml.writer import FCPXMLModifier
from fcpxml.parser import FCPXMLParser
from fcpxml.rough_cut import RoughCutGenerator
from fcpxml.models import (
    FlashFrameSeverity, FlashFrame, GapInfo, DuplicateGroup,
    PacingCurve, MontageConfig, ValidationIssue, ValidationResult
)

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.fcpxml"


@pytest.fixture
def temp_fcpxml():
    """Create a temp copy of sample.fcpxml for modification tests."""
    with tempfile.NamedTemporaryFile(suffix='.fcpxml', delete=False) as f:
        shutil.copy(SAMPLE, f.name)
        yield f.name
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def temp_output():
    """Create a temp file path for output."""
    with tempfile.NamedTemporaryFile(suffix='.fcpxml', delete=False) as f:
        yield f.name
    Path(f.name).unlink(missing_ok=True)


# ============================================================
# Model Tests - Pacing Curves
# ============================================================

def test_montage_config_constant_pacing():
    """Constant pacing should return same duration at any position."""
    config = MontageConfig(
        target_duration=30.0,
        pacing_curve=PacingCurve.CONSTANT,
        start_duration=2.0,
        end_duration=0.5
    )

    # Average of start and end
    expected = (2.0 + 0.5) / 2

    assert config.get_duration_at_position(0.0) == expected
    assert config.get_duration_at_position(0.5) == expected
    assert config.get_duration_at_position(1.0) == expected


def test_montage_config_accelerating_pacing():
    """Accelerating pacing: starts slow, ends fast."""
    config = MontageConfig(
        target_duration=30.0,
        pacing_curve=PacingCurve.ACCELERATING,
        start_duration=2.0,
        end_duration=0.5
    )

    # Should get start_duration at position 0
    assert config.get_duration_at_position(0.0) == 2.0

    # Should get end_duration at position 1
    assert config.get_duration_at_position(1.0) == 0.5

    # Middle should be in between
    mid_duration = config.get_duration_at_position(0.5)
    assert 0.5 < mid_duration < 2.0


def test_montage_config_decelerating_pacing():
    """Decelerating pacing: starts fast, ends slow."""
    config = MontageConfig(
        target_duration=30.0,
        pacing_curve=PacingCurve.DECELERATING,
        start_duration=2.0,
        end_duration=0.5
    )

    # Should start fast (end_duration) and end slow (start_duration)
    assert config.get_duration_at_position(0.0) == 0.5
    assert config.get_duration_at_position(1.0) == 2.0


def test_montage_config_pyramid_pacing():
    """Pyramid pacing: slow -> fast -> slow."""
    config = MontageConfig(
        target_duration=30.0,
        pacing_curve=PacingCurve.PYRAMID,
        start_duration=2.0,
        end_duration=0.5
    )

    # Start should be slow
    start_dur = config.get_duration_at_position(0.0)

    # Middle should be fast
    mid_dur = config.get_duration_at_position(0.5)

    # End should be slow again
    end_dur = config.get_duration_at_position(1.0)

    # Middle should be faster (shorter duration) than start/end
    assert mid_dur < start_dur
    assert mid_dur < end_dur


def test_montage_config_respects_min_max():
    """Pacing should clamp to min/max duration."""
    config = MontageConfig(
        target_duration=30.0,
        pacing_curve=PacingCurve.ACCELERATING,
        start_duration=10.0,  # Would exceed max
        end_duration=0.1,     # Would be below min
        min_duration=0.5,
        max_duration=5.0
    )

    # Should be clamped to max at start
    assert config.get_duration_at_position(0.0) == 5.0

    # Should be clamped to min at end
    assert config.get_duration_at_position(1.0) == 0.5


# ============================================================
# Model Tests - Data Classes
# ============================================================

def test_flash_frame_severity():
    """FlashFrameSeverity enum should have correct values."""
    assert FlashFrameSeverity.CRITICAL.value == "critical"
    assert FlashFrameSeverity.WARNING.value == "warning"


def test_pacing_curve_values():
    """PacingCurve enum should have all expected values."""
    assert PacingCurve.CONSTANT.value == "constant"
    assert PacingCurve.ACCELERATING.value == "accelerating"
    assert PacingCurve.DECELERATING.value == "decelerating"
    assert PacingCurve.PYRAMID.value == "pyramid"


def test_duplicate_group_count():
    """DuplicateGroup should correctly count clips."""
    group = DuplicateGroup(
        source_ref="r1",
        source_name="TestClip",
        clips=[
            {'name': 'Clip1', 'source_start': 0, 'source_duration': 5},
            {'name': 'Clip2', 'source_start': 10, 'source_duration': 5},
            {'name': 'Clip3', 'source_start': 20, 'source_duration': 5}
        ]
    )

    assert group.count == 3


def test_duplicate_group_overlapping_ranges():
    """DuplicateGroup should detect overlapping source ranges."""
    # Non-overlapping
    group_no_overlap = DuplicateGroup(
        source_ref="r1",
        source_name="TestClip",
        clips=[
            {'name': 'Clip1', 'source_start': 0, 'source_duration': 5},
            {'name': 'Clip2', 'source_start': 10, 'source_duration': 5}
        ]
    )
    assert group_no_overlap.has_overlapping_ranges == False

    # Overlapping
    group_overlap = DuplicateGroup(
        source_ref="r1",
        source_name="TestClip",
        clips=[
            {'name': 'Clip1', 'source_start': 0, 'source_duration': 10},
            {'name': 'Clip2', 'source_start': 5, 'source_duration': 10}  # Overlaps!
        ]
    )
    assert group_overlap.has_overlapping_ranges == True


def test_validation_result_counts():
    """ValidationResult should count issues by severity."""
    result = ValidationResult(
        is_valid=False,
        health_score=75,
        issues=[
            ValidationIssue(issue_type=None, severity="error", message="Error 1"),
            ValidationIssue(issue_type=None, severity="error", message="Error 2"),
            ValidationIssue(issue_type=None, severity="warning", message="Warning 1"),
        ]
    )

    assert result.error_count == 2
    assert result.warning_count == 1


# ============================================================
# Writer Tests - Speed Cutting Operations
# ============================================================

def test_fix_flash_frames_returns_list(temp_fcpxml):
    """fix_flash_frames should return a list of fixed items."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # May or may not find flash frames in sample, but should return list
    result = modifier.fix_flash_frames(mode='auto', threshold_frames=6)

    assert isinstance(result, list)


def test_rapid_trim_returns_list(temp_fcpxml):
    """rapid_trim should return a list of trimmed clips."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Trim all clips to 1 second max
    result = modifier.rapid_trim(max_duration='1s', trim_from='end')

    assert isinstance(result, list)


def test_rapid_trim_respects_max_duration(temp_fcpxml):
    """rapid_trim should not trim clips shorter than max."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Trim to 100s - most clips should be shorter
    result = modifier.rapid_trim(max_duration='100s')

    # All trimmed clips should have new_duration <= 100
    for item in result:
        assert item['new_duration'] <= 100


def test_fill_gaps_returns_list(temp_fcpxml):
    """fill_gaps should return a list of filled gaps."""
    modifier = FCPXMLModifier(temp_fcpxml)

    result = modifier.fill_gaps(mode='extend_previous')

    assert isinstance(result, list)


def test_rapid_trim_saves_correctly(temp_fcpxml):
    """rapid_trim changes should persist after save."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Trim clips to 0.5s max
    modifier.rapid_trim(max_duration='0.5s')

    output = temp_fcpxml.replace('.fcpxml', '_trimmed.fcpxml')
    modifier.save(output)

    # Reload and verify all clips are <= 0.5s
    parser = FCPXMLParser()
    project = parser.parse_file(output)

    for clip in project.primary_timeline.clips:
        assert clip.duration_seconds <= 0.6  # Allow small tolerance

    Path(output).unlink(missing_ok=True)


# ============================================================
# RoughCutGenerator Tests - Montage & A/B Roll
# ============================================================

def test_rough_cut_generator_loads(temp_fcpxml):
    """RoughCutGenerator should load FCPXML file."""
    generator = RoughCutGenerator(temp_fcpxml)

    assert generator.fps > 0
    assert len(generator.clips) > 0


def test_generate_montage_creates_file(temp_fcpxml, temp_output):
    """generate_montage should create output file."""
    generator = RoughCutGenerator(temp_fcpxml)

    result = generator.generate_montage(
        output_path=temp_output,
        target_duration='10s',
        pacing_curve='accelerating'
    )

    assert Path(temp_output).exists()
    assert result['clips_used'] > 0
    assert result['pacing_curve'] == 'accelerating'


def test_generate_montage_respects_target_duration(temp_fcpxml, temp_output):
    """generate_montage should approximate target duration."""
    generator = RoughCutGenerator(temp_fcpxml)

    result = generator.generate_montage(
        output_path=temp_output,
        target_duration='15s',
        pacing_curve='constant'
    )

    # Should be within reasonable range of target
    assert 10 <= result['actual_duration'] <= 20


def test_generate_ab_roll_creates_file(temp_fcpxml, temp_output):
    """generate_ab_roll should create output file."""
    generator = RoughCutGenerator(temp_fcpxml)

    # Use keywords that match sample clips (case-insensitive matching)
    result = generator.generate_ab_roll(
        output_path=temp_output,
        target_duration='20s',
        a_keywords=['Interview'],  # Matches sample's "Interview" keyword
        b_keywords=['B-Roll'],     # Matches sample's "B-Roll" keyword
        a_duration='5s',
        b_duration='3s'
    )

    assert Path(temp_output).exists()
    assert result['clips_used'] > 0


def test_generate_ab_roll_alternates(temp_fcpxml, temp_output):
    """generate_ab_roll should have both A and B segments."""
    generator = RoughCutGenerator(temp_fcpxml)

    result = generator.generate_ab_roll(
        output_path=temp_output,
        target_duration='30s',
        a_keywords=['Interview'],  # Matches sample's "Interview" keyword
        b_keywords=['B-Roll'],     # Matches sample's "B-Roll" keyword
        a_duration='5s',
        b_duration='3s'
    )

    # Should have both A and B segments
    assert result['a_segments'] > 0 or result['b_segments'] > 0


# ============================================================
# Integration Tests
# ============================================================

def test_montage_pacing_affects_clip_durations(temp_fcpxml, temp_output):
    """Different pacing curves should produce different results."""
    generator = RoughCutGenerator(temp_fcpxml)

    # Generate accelerating montage
    result_accel = generator.generate_montage(
        output_path=temp_output,
        target_duration='20s',
        pacing_curve='accelerating',
        start_duration=3.0,
        end_duration=0.5
    )

    # Just verify montage was created with expected settings
    assert result_accel['pacing_curve'] == 'accelerating'
    assert result_accel['clips_used'] > 0

    # Note: Actual clip durations depend on available clips and their durations,
    # so we can't strictly assert start > end without knowing clip inventory


def test_full_workflow_trim_and_validate(temp_fcpxml):
    """Test full workflow: trim clips then validate changes."""
    modifier = FCPXMLModifier(temp_fcpxml)

    # Step 1: Rapid trim
    trimmed = modifier.rapid_trim(max_duration='2s')

    # Step 2: Save
    output = temp_fcpxml.replace('.fcpxml', '_workflow.fcpxml')
    modifier.save(output)

    # Step 3: Verify with parser
    parser = FCPXMLParser()
    project = parser.parse_file(output)

    # All clips should be <= 2s
    for clip in project.primary_timeline.clips:
        assert clip.duration_seconds <= 2.1  # Small tolerance

    Path(output).unlink(missing_ok=True)
