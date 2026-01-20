# Auto Rough Cut Algorithm

The killer feature: AI-powered automatic rough cut generation from source footage.

---

## Overview

`auto_rough_cut` takes:
1. Source clips with keywords/metadata
2. Target duration
3. Structure template (optional)
4. Pacing preferences

And outputs:
- A complete FCPXML timeline with AI-selected clips
- Clips ordered by structure, selected by keywords
- Paced according to preferences

---

## Algorithm Phases

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AUTO ROUGH CUT PIPELINE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│  │  INGEST  │ → │  SCORE   │ → │  SELECT  │ → │ ASSEMBLE │         │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘         │
│       │              │              │              │                 │
│       ▼              ▼              ▼              ▼                 │
│  Parse clips    Rank clips    Pick clips     Build FCPXML           │
│  Extract meta   by relevance  per segment    with transitions       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: INGEST

Parse source FCPXML and extract all usable clips with metadata.

```python
@dataclass
class SourceClip:
    id: str
    name: str
    source_path: str
    duration: TimeValue
    start: TimeValue  # In-point in source
    end: TimeValue    # Out-point in source
    
    # Metadata
    keywords: List[str]
    rating: int  # 1-5 stars, 0 = unrated
    is_favorite: bool
    is_rejected: bool
    notes: str
    
    # Technical
    resolution: Tuple[int, int]
    frame_rate: float
    has_audio: bool
    
    # Computed
    usable_duration: TimeValue  # Excluding handles


def ingest_source_clips(fcpxml_path: str) -> List[SourceClip]:
    """
    Parse FCPXML and extract all clips with their metadata.
    
    Sources can be:
    - Library export (all events/clips)
    - Event export (single event)
    - Project export (existing timeline - use clips from it)
    
    Returns list of SourceClip objects.
    """
    tree = ET.parse(fcpxml_path)
    root = tree.getroot()
    
    clips = []
    
    # Find all asset-clips (browser clips) or clips (timeline clips)
    for asset_clip in root.findall('.//asset-clip'):
        clip = parse_asset_clip(asset_clip)
        if not clip.is_rejected:  # Skip rejected clips
            clips.append(clip)
    
    # Also check for clips in existing timelines (for re-cut workflows)
    for clip_elem in root.findall('.//clip'):
        clip = parse_timeline_clip(clip_elem)
        if not clip.is_rejected:
            clips.append(clip)
    
    return clips
```

---

## Phase 2: SCORE

Score each clip's relevance for each segment in the structure.

```python
@dataclass
class ScoredClip:
    clip: SourceClip
    segment_scores: Dict[str, float]  # segment_name -> relevance score
    

def score_clips(
    clips: List[SourceClip],
    structure: List[SegmentSpec]
) -> List[ScoredClip]:
    """
    Score each clip's relevance to each segment.
    
    Scoring factors:
    1. Keyword match (highest weight)
    2. Rating (higher = better)
    3. Favorite status (bonus)
    4. Duration fit (clips close to target get bonus)
    """
    scored = []
    
    for clip in clips:
        segment_scores = {}
        
        for segment in structure:
            score = 0.0
            
            # Keyword matching (0-50 points)
            keyword_matches = set(clip.keywords) & set(segment.keywords)
            if segment.keywords:
                keyword_score = len(keyword_matches) / len(segment.keywords) * 50
            else:
                keyword_score = 25  # No keywords specified = neutral
            score += keyword_score
            
            # Rating (0-20 points)
            if clip.rating > 0:
                score += clip.rating * 4  # 5 stars = 20 points
            else:
                score += 10  # Unrated = neutral
            
            # Favorite bonus (0-15 points)
            if clip.is_favorite:
                score += 15
            
            # Duration fit (0-15 points)
            # Clips close to ideal segment clip duration get bonus
            target_clip_duration = calculate_ideal_clip_duration(segment)
            duration_ratio = clip.usable_duration.to_seconds() / target_clip_duration
            if 0.5 <= duration_ratio <= 2.0:
                # Within usable range
                fit_score = 15 - abs(1.0 - duration_ratio) * 10
                score += max(0, fit_score)
            
            segment_scores[segment.name] = score
        
        scored.append(ScoredClip(clip=clip, segment_scores=segment_scores))
    
    return scored
```

### Scoring Weights

| Factor | Weight | Notes |
|--------|--------|-------|
| Keyword match | 50% | Primary selection criteria |
| Rating | 20% | Editor's quality signal |
| Favorite | 15% | Strong preference signal |
| Duration fit | 15% | Practical editing fit |

---

## Phase 3: SELECT

Select clips for each segment based on scores and constraints.

```python
@dataclass
class SegmentSpec:
    name: str
    keywords: List[str]
    duration: TimeValue
    priority: str  # 'favorites', 'longest', 'shortest', 'random', 'best'


@dataclass
class ClipSelection:
    clip: SourceClip
    segment: str
    in_point: TimeValue
    out_point: TimeValue
    order: int


def select_clips_for_segment(
    scored_clips: List[ScoredClip],
    segment: SegmentSpec,
    pacing_config: PacingConfig,
    already_used: Set[str]
) -> List[ClipSelection]:
    """
    Select clips for a single segment.
    
    Algorithm:
    1. Filter to clips with positive relevance
    2. Sort by priority method
    3. Greedily select until duration target met
    4. Adjust in/out points to fit
    """
    # Filter and sort
    candidates = [
        sc for sc in scored_clips 
        if sc.segment_scores.get(segment.name, 0) > 0
        and sc.clip.id not in already_used
    ]
    
    # Sort by priority
    if segment.priority == 'favorites':
        candidates.sort(key=lambda x: (x.clip.is_favorite, x.segment_scores[segment.name]), reverse=True)
    elif segment.priority == 'longest':
        candidates.sort(key=lambda x: x.clip.usable_duration.to_seconds(), reverse=True)
    elif segment.priority == 'shortest':
        candidates.sort(key=lambda x: x.clip.usable_duration.to_seconds())
    elif segment.priority == 'random':
        import random
        random.shuffle(candidates)
    else:  # 'best' - default
        candidates.sort(key=lambda x: x.segment_scores[segment.name], reverse=True)
    
    # Greedy selection
    selections = []
    remaining_duration = segment.duration.to_seconds()
    
    for scored_clip in candidates:
        if remaining_duration <= 0:
            break
        
        clip = scored_clip.clip
        
        # Determine clip duration for this segment
        ideal_duration = calculate_ideal_clip_duration_for_pacing(
            pacing_config, 
            remaining_duration
        )
        
        # Clip the clip to fit
        actual_duration = min(
            clip.usable_duration.to_seconds(),
            ideal_duration,
            remaining_duration
        )
        
        if actual_duration < pacing_config.min_clip_duration:
            continue  # Skip clips that would be too short
        
        # Determine in/out points
        # Default: use clip's existing in-point
        in_point = clip.start
        out_point = clip.start + TimeValue.from_seconds(actual_duration)
        
        selections.append(ClipSelection(
            clip=clip,
            segment=segment.name,
            in_point=in_point,
            out_point=out_point,
            order=len(selections)
        ))
        
        remaining_duration -= actual_duration
        already_used.add(clip.id)
    
    return selections


def calculate_ideal_clip_duration_for_pacing(
    config: PacingConfig,
    remaining: float
) -> float:
    """
    Calculate ideal clip duration based on pacing settings.
    
    Pacing styles:
    - slow: 5-10 second cuts
    - medium: 2-5 second cuts
    - fast: 0.5-2 second cuts
    - dynamic: varies based on position
    """
    pacing_ranges = {
        'slow': (5.0, 10.0),
        'medium': (2.0, 5.0),
        'fast': (0.5, 2.0),
        'dynamic': (1.0, 6.0)
    }
    
    min_dur, max_dur = pacing_ranges.get(config.pacing, (2.0, 5.0))
    
    if config.avg_clip_duration:
        # User specified exact average
        target = config.avg_clip_duration
    else:
        # Random within range for organic feel
        if config.vary_pacing:
            import random
            target = random.uniform(min_dur, max_dur)
        else:
            target = (min_dur + max_dur) / 2
    
    # Don't exceed remaining duration
    return min(target, remaining)
```

---

## Phase 4: ASSEMBLE

Build the final FCPXML from selected clips.

```python
def assemble_rough_cut(
    selections: List[ClipSelection],
    structure: List[SegmentSpec],
    transitions_config: Dict,
    output_path: str
) -> str:
    """
    Build FCPXML from clip selections.
    
    Steps:
    1. Create FCPXML document structure
    2. Add resources for all source clips
    3. Build spine with clips in order
    4. Add transitions between segments
    5. Write to file
    """
    # Create document
    root = ET.Element('fcpxml', version='1.11')
    
    # Resources section
    resources = ET.SubElement(root, 'resources')
    add_format_resource(resources)
    
    asset_refs = {}
    for selection in selections:
        if selection.clip.source_path not in asset_refs:
            asset_id = f"r{len(asset_refs) + 1}"
            add_asset_resource(resources, selection.clip, asset_id)
            asset_refs[selection.clip.source_path] = asset_id
    
    # Library/Event/Project structure
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name='Rough Cut')
    project = ET.SubElement(event, 'project', name='AI Rough Cut')
    sequence = ET.SubElement(project, 'sequence')
    spine = ET.SubElement(sequence, 'spine')
    
    # Build timeline
    current_offset = TimeValue(0)
    current_segment = None
    
    for selection in selections:
        # Check if segment changed (for transition)
        if selection.segment != current_segment:
            if current_segment is not None:
                # Add segment transition
                trans_type = transitions_config.get('between_segments', 'cross-dissolve')
                if trans_type != 'none':
                    add_transition(spine, current_offset, trans_type, duration='1s')
            current_segment = selection.segment
        
        # Add clip
        asset_id = asset_refs[selection.clip.source_path]
        duration = selection.out_point - selection.in_point
        
        clip_elem = ET.SubElement(spine, 'clip')
        clip_elem.set('name', selection.clip.name)
        clip_elem.set('offset', current_offset.to_fcpxml())
        clip_elem.set('duration', duration.to_fcpxml())
        clip_elem.set('start', selection.in_point.to_fcpxml())
        clip_elem.set('ref', asset_id)
        
        current_offset = current_offset + duration
    
    # Write file
    tree = ET.ElementTree(root)
    tree.write(output_path, encoding='UTF-8', xml_declaration=True)
    
    return output_path
```

---

## Complete Algorithm

```python
def auto_rough_cut(
    source_path: str,
    output_path: str,
    target_duration: str,
    structure: Optional[List[Dict]] = None,
    pacing: str = 'medium',
    pacing_config: Optional[Dict] = None,
    transitions: Optional[Dict] = None
) -> Dict:
    """
    Main entry point for auto rough cut.
    
    Args:
        source_path: FCPXML with source clips
        output_path: Where to save the rough cut
        target_duration: Target total duration (timecode string)
        structure: Optional segment structure
        pacing: Pacing preset ('slow', 'medium', 'fast', 'dynamic')
        pacing_config: Override pacing settings
        transitions: Transition settings
    
    Returns:
        Dict with stats about the generated cut
    """
    # Parse target duration
    target = TimeValue.from_timecode(target_duration)
    
    # Default structure if not provided
    if structure is None:
        structure = [
            SegmentSpec(
                name='Main',
                keywords=[],  # Use all clips
                duration=target,
                priority='best'
            )
        ]
    else:
        structure = [SegmentSpec(**s) for s in structure]
    
    # Normalize segment durations to match target
    structure = normalize_segment_durations(structure, target)
    
    # Build pacing config
    config = PacingConfig(
        pacing=pacing,
        min_clip_duration=pacing_config.get('min_clip_duration', 1.0) if pacing_config else 1.0,
        max_clip_duration=pacing_config.get('max_clip_duration', 8.0) if pacing_config else 8.0,
        avg_clip_duration=pacing_config.get('avg_clip_duration') if pacing_config else None,
        vary_pacing=pacing_config.get('vary_pacing', True) if pacing_config else True
    )
    
    # Transition config
    trans_config = transitions or {
        'between_segments': 'cross-dissolve',
        'within_segments': 'cut'
    }
    
    # === EXECUTE PIPELINE ===
    
    # Phase 1: Ingest
    clips = ingest_source_clips(source_path)
    print(f"Ingested {len(clips)} source clips")
    
    # Phase 2: Score
    scored_clips = score_clips(clips, structure)
    
    # Phase 3: Select
    all_selections = []
    used_clips = set()
    
    for segment in structure:
        segment_selections = select_clips_for_segment(
            scored_clips,
            segment,
            config,
            used_clips
        )
        all_selections.extend(segment_selections)
        print(f"Selected {len(segment_selections)} clips for '{segment.name}'")
    
    # Phase 4: Assemble
    assemble_rough_cut(
        all_selections,
        structure,
        trans_config,
        output_path
    )
    
    # Calculate stats
    actual_duration = sum(
        (s.out_point - s.in_point).to_seconds() 
        for s in all_selections
    )
    
    return {
        'output_path': output_path,
        'clips_used': len(all_selections),
        'clips_available': len(clips),
        'target_duration': target.to_seconds(),
        'actual_duration': actual_duration,
        'segments': len(structure),
        'average_clip_duration': actual_duration / len(all_selections) if all_selections else 0
    }
```

---

## Example Usage

```python
# Music video rough cut
result = auto_rough_cut(
    source_path='/path/to/raw_footage.fcpxml',
    output_path='/path/to/rough_cut.fcpxml',
    target_duration='00:03:30:00',  # 3:30 music video
    structure=[
        {
            'name': 'Intro',
            'keywords': ['Wide', 'Establishing'],
            'duration': '00:00:15:00',
            'priority': 'best'
        },
        {
            'name': 'Verse 1',
            'keywords': ['Performance', 'Artist'],
            'duration': '00:00:45:00',
            'priority': 'favorites'
        },
        {
            'name': 'Chorus',
            'keywords': ['Energy', 'B-Roll', 'Crowd'],
            'duration': '00:00:30:00',
            'priority': 'best'
        },
        {
            'name': 'Verse 2',
            'keywords': ['Performance', 'Close-up'],
            'duration': '00:00:45:00',
            'priority': 'longest'
        },
        {
            'name': 'Bridge',
            'keywords': ['Cinematic', 'Slow-mo'],
            'duration': '00:00:20:00',
            'priority': 'best'
        },
        {
            'name': 'Final Chorus',
            'keywords': ['Energy', 'Performance', 'Crowd'],
            'duration': '00:00:40:00',
            'priority': 'random'  # Mix it up
        },
        {
            'name': 'Outro',
            'keywords': ['Wide', 'Fade'],
            'duration': '00:00:15:00',
            'priority': 'best'
        }
    ],
    pacing='dynamic',
    pacing_config={
        'min_clip_duration': '00:00:00:15',  # 15 frames min
        'max_clip_duration': '00:00:04:00',  # 4 seconds max
        'vary_pacing': True
    },
    transitions={
        'between_segments': 'cross-dissolve',
        'within_segments': 'cut'
    }
)

print(f"Generated {result['actual_duration']:.1f}s rough cut using {result['clips_used']} clips")
```

---

## Future Enhancements

### 1. Beat Detection Integration
```python
# Sync cuts to music beats
auto_rough_cut(
    ...
    music_track='/path/to/song.mp3',
    sync_to_beats=True,
    beat_detection_sensitivity=0.8
)
```

### 2. AI Content Analysis
```python
# Use vision AI to analyze clip content
auto_rough_cut(
    ...
    analyze_content=True,  # Run clips through vision model
    prefer_faces=True,     # Prioritize clips with faces
    avoid_duplicates=True  # Don't repeat similar shots
)
```

### 3. Style Templates
```python
# Pre-built pacing templates for genres
auto_rough_cut(
    ...
    style='music_video_hiphop'  # Fast cuts, lots of variety
    # or 'documentary_interview'  # Longer clips, less cuts
    # or 'commercial_30sec'       # Punchy, tight
)
```

### 4. Multi-cam Support
```python
# Select from multiple camera angles
auto_rough_cut(
    ...
    multicam_mode=True,
    angle_variety=0.7,  # How much to switch angles
    prefer_angle='A-Cam'  # Default camera
)
```

---

## Performance Considerations

| Clips | Segments | Expected Time |
|-------|----------|---------------|
| 100 | 5 | < 1 second |
| 500 | 10 | 2-3 seconds |
| 1000 | 20 | 5-8 seconds |
| 5000+ | 50+ | 15-30 seconds |

The algorithm is O(clips × segments) for scoring, O(clips log clips) for sorting, and O(selections) for assembly.

For very large projects, consider:
- Pre-filtering clips by keyword before scoring
- Caching scored clips between runs
- Parallel processing of segments
