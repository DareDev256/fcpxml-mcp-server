# FCPXML Structure Reference

How FCPXML represents different elements and what nodes need modification for each editing operation.

---

## Document Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
    <resources>
        <!-- Media assets, formats, effects -->
    </resources>
    <library>
        <event name="My Event">
            <project name="My Project">
                <sequence>
                    <spine>
                        <!-- Primary storyline clips -->
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>
```

---

## Key Elements

### `<asset>` - Media Reference
```xml
<asset id="r1" name="Interview_01" src="file:///path/to/Interview_01.mov" 
       start="0s" duration="300s" hasVideo="1" hasAudio="1">
    <format id="r2" name="FFVideoFormat1080p30"/>
</asset>
```

### `<clip>` - Timeline Clip
```xml
<clip name="Interview_01" offset="0s" duration="120s" start="30s" 
      tcFormat="NDF" ref="r1">
    <!-- offset: position in timeline -->
    <!-- duration: length shown in timeline -->
    <!-- start: in-point in source media -->
    <!-- ref: links to asset id -->
</clip>
```

### `<video>` / `<audio>` - A/V Components
```xml
<video name="B-Roll" offset="120s" duration="60s" start="0s" ref="r3">
    <audio lane="-1" offset="0s" duration="60s" start="0s" ref="r3"/>
</video>
```

### `<gap>` - Empty Space
```xml
<gap name="Gap" offset="180s" duration="30s"/>
```

### `<marker>` - Marker
```xml
<marker start="45s" duration="1/30s" value="Chapter 1"/>

<!-- Chapter marker -->
<chapter-marker start="90s" duration="1/30s" value="Intro" 
                posterOffset="0s"/>

<!-- To-do marker -->
<marker start="120s" duration="1/30s" value="Fix audio">
    <note>Audio levels too low</note>
</marker>
```

### `<keyword>` - Keyword Range
```xml
<clip ref="r1" ...>
    <keyword start="0s" duration="30s" value="Interview"/>
    <keyword start="30s" duration="15s" value="B-Roll"/>
</clip>
```

### `<transition>` - Transition Effect
```xml
<transition name="Cross Dissolve" offset="119/2s" duration="1s">
    <filter-video ref="r10" name="Cross Dissolve"/>
</transition>
```

---

## Edit Operations → XML Changes

### ADD_MARKER

**Target:** Inside `<clip>`, `<video>`, `<audio>`, or `<spine>`

```xml
<!-- Before -->
<clip name="Interview" offset="0s" duration="120s" start="0s" ref="r1">
</clip>

<!-- After: Standard marker at 45s -->
<clip name="Interview" offset="0s" duration="120s" start="0s" ref="r1">
    <marker start="45s" duration="1/30s" value="Review this"/>
</clip>

<!-- After: Chapter marker -->
<clip name="Interview" offset="0s" duration="120s" start="0s" ref="r1">
    <chapter-marker start="45s" duration="1/30s" value="Introduction" posterOffset="0s"/>
</clip>

<!-- After: Colored marker -->
<clip name="Interview" offset="0s" duration="120s" start="0s" ref="r1">
    <marker start="45s" duration="1/30s" value="Needs work">
        <marker-color color="3"/>  <!-- 0=blue, 1=cyan, 2=green, 3=yellow... -->
    </marker>
</clip>
```

---

### TRIM_CLIP

**Target:** `start` and `duration` attributes of `<clip>`

```xml
<!-- Before: 2 minute clip starting at source timecode 30s -->
<clip name="Interview" offset="0s" duration="120s" start="30s" ref="r1"/>

<!-- After: Trim 10s from start (new in-point) -->
<clip name="Interview" offset="0s" duration="110s" start="40s" ref="r1"/>

<!-- After: Trim 10s from end (shorter duration) -->
<clip name="Interview" offset="0s" duration="110s" start="30s" ref="r1"/>
```

**Ripple trim** also requires updating `offset` of all subsequent clips:

```xml
<!-- Before -->
<spine>
    <clip name="A" offset="0s" duration="60s" .../>
    <clip name="B" offset="60s" duration="60s" .../>
    <clip name="C" offset="120s" duration="60s" .../>
</spine>

<!-- After: Trim 10s from end of clip A with ripple -->
<spine>
    <clip name="A" offset="0s" duration="50s" .../>
    <clip name="B" offset="50s" duration="60s" .../>   <!-- offset shifted -->
    <clip name="C" offset="110s" duration="60s" .../>  <!-- offset shifted -->
</spine>
```

---

### REORDER_CLIPS

**Target:** `offset` attributes of all affected clips

```xml
<!-- Before: A, B, C order -->
<spine>
    <clip name="A" offset="0s" duration="30s" .../>
    <clip name="B" offset="30s" duration="30s" .../>
    <clip name="C" offset="60s" duration="30s" .../>
</spine>

<!-- After: Move C to start → C, A, B -->
<spine>
    <clip name="C" offset="0s" duration="30s" .../>
    <clip name="A" offset="30s" duration="30s" .../>
    <clip name="B" offset="60s" duration="30s" .../>
</spine>
```

**Important:** Element order in XML doesn't matter, only `offset` values determine timeline position.

---

### ADD_TRANSITION

**Target:** Insert `<transition>` element between clips

```xml
<!-- Before -->
<spine>
    <clip name="A" offset="0s" duration="60s" .../>
    <clip name="B" offset="60s" duration="60s" .../>
</spine>

<!-- After: Add 1s cross-dissolve between A and B -->
<spine>
    <clip name="A" offset="0s" duration="60s" .../>
    <transition name="Cross Dissolve" offset="59s" duration="1s">
        <filter-video ref="r_dissolve" name="Cross Dissolve"/>
    </transition>
    <clip name="B" offset="60s" duration="60s" .../>
</spine>
```

**Note:** Transition `offset` is typically `clip_end - (transition_duration / 2)`

---

### CHANGE_SPEED

**Target:** Add `<timeMap>` or `<conform-rate>` inside clip

```xml
<!-- Constant speed change (50% slow-mo) -->
<clip name="Action" offset="0s" duration="120s" start="0s" ref="r1">
    <conform-rate scaleEnabled="1" srcFrameRate="30"/>
    <timeMap>
        <timept time="0s" value="0s" interp="linear"/>
        <timept time="120s" value="60s" interp="linear"/>
    </timeMap>
</clip>

<!-- Speed ramp (100% → 50% → 100%) -->
<clip name="Action" offset="0s" duration="90s" start="0s" ref="r1">
    <timeMap>
        <timept time="0s" value="0s" interp="linear"/>
        <timept time="30s" value="30s" interp="smooth2"/>
        <timept time="60s" value="45s" interp="smooth2"/>
        <timept time="90s" value="75s" interp="linear"/>
    </timeMap>
</clip>
```

**Interpolation values:**
- `linear` - constant speed
- `smooth2` - ease in/out
- `smooth` - smoother ease

---

### SPLIT_CLIP

**Target:** Create two clips from one, adjusting `start`, `duration`, `offset`

```xml
<!-- Before: Single 60s clip -->
<spine>
    <clip name="Interview" offset="0s" duration="60s" start="0s" ref="r1"/>
</spine>

<!-- After: Split at 30s mark -->
<spine>
    <clip name="Interview" offset="0s" duration="30s" start="0s" ref="r1"/>
    <clip name="Interview" offset="30s" duration="30s" start="30s" ref="r1"/>
</spine>
```

---

### DELETE_CLIP

**Ripple delete:** Remove clip, shift subsequent clips

```xml
<!-- Before -->
<spine>
    <clip name="A" offset="0s" duration="30s" .../>
    <clip name="B" offset="30s" duration="30s" .../>
    <clip name="C" offset="60s" duration="30s" .../>
</spine>

<!-- After: Delete B with ripple -->
<spine>
    <clip name="A" offset="0s" duration="30s" .../>
    <clip name="C" offset="30s" duration="30s" .../>  <!-- offset updated -->
</spine>
```

**Non-ripple delete:** Replace with gap

```xml
<!-- After: Delete B without ripple -->
<spine>
    <clip name="A" offset="0s" duration="30s" .../>
    <gap name="Gap" offset="30s" duration="30s"/>
    <clip name="C" offset="60s" duration="30s" .../>
</spine>
```

---

## Time Format Conversions

FCPXML uses rational time (fractions of seconds):

| Timecode | FCPXML Time |
|----------|-------------|
| 00:00:01:00 @ 30fps | `1s` or `30/30s` |
| 00:00:00:15 @ 30fps | `15/30s` or `1/2s` |
| 00:01:00:00 | `60s` |
| 00:00:02:10 @ 24fps | `58/24s` |

**Conversion formula:**
```
fcpxml_time = (hours * 3600) + (minutes * 60) + seconds + (frames / fps)
```

**Frame-accurate time:**
```
frames_total = (hours * 3600 * fps) + (minutes * 60 * fps) + (seconds * fps) + frames
fcpxml_time = f"{frames_total}/{fps}s"
```

---

## Resource References

Every clip references resources by `id`:

```xml
<resources>
    <format id="r1" name="FFVideoFormat1080p30" width="1920" height="1080" 
            frameDuration="1/30s"/>
    <asset id="r2" name="Interview" src="file:///path/to/file.mov" 
           start="0s" duration="3600s" format="r1"/>
    <effect id="r3" name="Cross Dissolve" uid=".../Cross Dissolve"/>
</resources>

<!-- In timeline -->
<clip ref="r2" .../>
<transition>
    <filter-video ref="r3"/>
</transition>
```

---

## Compound Clips & Nested Timelines

```xml
<ref-clip name="Nested Sequence" ref="r5" offset="0s" duration="120s">
    <!-- r5 points to another sequence -->
</ref-clip>

<!-- Inline compound (multicam, synchronized) -->
<mc-clip name="Multicam" offset="0s" duration="60s">
    <mc-source angleID="angle1">
        <clip ref="r10" .../>
    </mc-source>
    <mc-source angleID="angle2">
        <clip ref="r11" .../>
    </mc-source>
</mc-clip>
```

---

## Audio Specifics

```xml
<!-- Detached audio -->
<clip ref="r1" ...>
    <audio lane="-1" ref="r1" offset="0s" duration="60s"/>
</clip>

<!-- Audio only clip -->
<audio-clip name="Music" lane="-2" offset="0s" duration="180s" ref="r20"/>

<!-- Audio adjustments -->
<clip ref="r1" ...>
    <adjust-volume amount="-6dB"/>
    <audio lane="-1" ref="r1">
        <adjust-volume amount="3dB"/>
    </audio>
</clip>
```

---

## Critical Implementation Notes

1. **Always validate XML** after modification - FCP will reject malformed FCPXML
2. **Maintain resource integrity** - never orphan asset references
3. **Recalculate all offsets** after any operation that changes clip positions
4. **Preserve existing attributes** - don't strip attributes you don't understand
5. **Handle connected clips** - clips on other lanes may connect to spine clips
6. **Time precision matters** - use rational fractions, not floats
