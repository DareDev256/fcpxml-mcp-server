# FCP MCP Server - Tool Schemas

Complete MCP tool definitions for all editing capabilities.

---

## Phase 1: Core Editing

### `add_marker`

```json
{
  "name": "add_marker",
  "description": "Add a marker to the timeline at a specific timecode. Supports chapter markers (for YouTube), to-do markers, and standard markers with custom colors.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "timecode": {
        "type": "string",
        "description": "Timecode in format HH:MM:SS:FF or seconds (e.g., '00:01:30:00' or '90.5')"
      },
      "name": {
        "type": "string",
        "description": "Marker name/label"
      },
      "marker_type": {
        "type": "string",
        "enum": ["standard", "chapter", "todo", "completed"],
        "default": "standard",
        "description": "Type of marker to create"
      },
      "color": {
        "type": "string",
        "enum": ["blue", "cyan", "green", "yellow", "orange", "red", "pink", "purple"],
        "default": "blue",
        "description": "Marker color"
      },
      "note": {
        "type": "string",
        "description": "Optional note/description for the marker"
      }
    },
    "required": ["project_path", "timecode", "name"]
  }
}
```

---

### `trim_clip`

```json
{
  "name": "trim_clip",
  "description": "Adjust the in-point and/or out-point of a clip in the timeline. Can trim by timecode or by duration delta.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_id": {
        "type": "string",
        "description": "Unique identifier of the clip (from list_clips)"
      },
      "trim_start": {
        "type": "string",
        "description": "New in-point timecode, or delta like '+00:00:01:00' or '-15f' (frames)"
      },
      "trim_end": {
        "type": "string",
        "description": "New out-point timecode, or delta like '+00:00:02:00' or '-30f'"
      },
      "ripple": {
        "type": "boolean",
        "default": true,
        "description": "If true, subsequent clips shift to fill/accommodate the change"
      }
    },
    "required": ["project_path", "clip_id"]
  }
}
```

---

### `reorder_clips`

```json
{
  "name": "reorder_clips",
  "description": "Move one or more clips to a new position in the timeline. Supports moving single clips or batch reordering.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of clip IDs to move (maintains relative order)"
      },
      "target_position": {
        "type": "string",
        "description": "Where to insert: 'start', 'end', timecode, or 'after:clip_id' / 'before:clip_id'"
      },
      "ripple": {
        "type": "boolean",
        "default": true,
        "description": "If true, other clips shift to accommodate"
      }
    },
    "required": ["project_path", "clip_ids", "target_position"]
  }
}
```

---

### `add_transition`

```json
{
  "name": "add_transition",
  "description": "Apply a transition between two clips or at clip boundaries.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_id": {
        "type": "string",
        "description": "Clip ID to add transition to"
      },
      "position": {
        "type": "string",
        "enum": ["start", "end", "both"],
        "default": "end",
        "description": "Where to apply the transition"
      },
      "transition_type": {
        "type": "string",
        "enum": ["cross-dissolve", "fade-to-black", "fade-from-black", "dip-to-color", "wipe", "slide"],
        "default": "cross-dissolve",
        "description": "Type of transition"
      },
      "duration": {
        "type": "string",
        "default": "00:00:00:15",
        "description": "Transition duration in timecode or frames (e.g., '15f')"
      }
    },
    "required": ["project_path", "clip_id"]
  }
}
```

---

## Phase 2: Speed & Precision

### `change_speed`

```json
{
  "name": "change_speed",
  "description": "Modify the playback speed of a clip. Supports constant speed changes and speed ramps.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_id": {
        "type": "string",
        "description": "Unique identifier of the clip"
      },
      "speed": {
        "type": "number",
        "description": "Speed multiplier (0.5 = 50% slow-mo, 2.0 = 2x fast)"
      },
      "ramp": {
        "type": "object",
        "description": "Optional speed ramp configuration",
        "properties": {
          "start_speed": {"type": "number"},
          "end_speed": {"type": "number"},
          "curve": {
            "type": "string",
            "enum": ["linear", "ease-in", "ease-out", "ease-in-out"]
          }
        }
      },
      "preserve_pitch": {
        "type": "boolean",
        "default": true,
        "description": "Maintain audio pitch when changing speed"
      },
      "frame_blending": {
        "type": "string",
        "enum": ["none", "frame-blending", "optical-flow"],
        "default": "optical-flow",
        "description": "Frame interpolation method for slow-motion"
      }
    },
    "required": ["project_path", "clip_id", "speed"]
  }
}
```

---

### `split_clip`

```json
{
  "name": "split_clip",
  "description": "Split a clip at one or more timecodes, creating separate clips.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_id": {
        "type": "string",
        "description": "Unique identifier of the clip to split"
      },
      "split_points": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of timecodes within the clip to split at"
      },
      "split_type": {
        "type": "string",
        "enum": ["blade", "blade-all"],
        "default": "blade",
        "description": "'blade' splits only this clip, 'blade-all' splits all tracks at this point"
      }
    },
    "required": ["project_path", "clip_id", "split_points"]
  }
}
```

---

### `delete_clip`

```json
{
  "name": "delete_clip",
  "description": "Remove a clip from the timeline. Supports ripple delete or leaving a gap.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of clip IDs to delete"
      },
      "ripple": {
        "type": "boolean",
        "default": true,
        "description": "If true, subsequent clips shift to fill the gap"
      }
    },
    "required": ["project_path", "clip_ids"]
  }
}
```

---

## Phase 3: Batch & AI-Powered

### `select_by_keyword`

```json
{
  "name": "select_by_keyword",
  "description": "Find and return clips matching specific keywords, ratings, or metadata criteria.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "keywords": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Keywords to match (OR logic by default)"
      },
      "match_mode": {
        "type": "string",
        "enum": ["any", "all", "none"],
        "default": "any",
        "description": "'any' = OR, 'all' = AND, 'none' = exclude these keywords"
      },
      "rating": {
        "type": "object",
        "properties": {
          "min": {"type": "integer", "minimum": 1, "maximum": 5},
          "max": {"type": "integer", "minimum": 1, "maximum": 5}
        },
        "description": "Filter by star rating range"
      },
      "favorites_only": {
        "type": "boolean",
        "default": false,
        "description": "Only return favorited clips"
      },
      "exclude_rejected": {
        "type": "boolean",
        "default": true,
        "description": "Exclude clips marked as rejected"
      }
    },
    "required": ["project_path", "keywords"]
  }
}
```

---

### `batch_trim`

```json
{
  "name": "batch_trim",
  "description": "Apply trim operations to multiple clips at once based on criteria.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of clip IDs to trim (or use selection_criteria)"
      },
      "selection_criteria": {
        "type": "object",
        "description": "Alternative to clip_ids: select clips dynamically",
        "properties": {
          "keywords": {"type": "array", "items": {"type": "string"}},
          "min_duration": {"type": "string"},
          "max_duration": {"type": "string"}
        }
      },
      "trim_operation": {
        "type": "object",
        "properties": {
          "trim_start_by": {"type": "string", "description": "Amount to trim from start"},
          "trim_end_by": {"type": "string", "description": "Amount to trim from end"},
          "set_duration": {"type": "string", "description": "Set all clips to this exact duration"}
        }
      },
      "ripple": {
        "type": "boolean",
        "default": true
      }
    },
    "required": ["project_path", "trim_operation"]
  }
}
```

---

### `auto_rough_cut`

```json
{
  "name": "auto_rough_cut",
  "description": "AI-powered rough cut generation. Analyzes source clips by keywords and assembles a timeline based on target duration and pacing preferences.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "source_path": {
        "type": "string",
        "description": "Path to FCPXML with source clips (library or event export)"
      },
      "output_path": {
        "type": "string",
        "description": "Path to write the generated rough cut FCPXML"
      },
      "target_duration": {
        "type": "string",
        "description": "Desired final duration (e.g., '00:03:30:00' for 3.5 minutes)"
      },
      "structure": {
        "type": "array",
        "description": "Ordered list of segments with keywords and duration targets",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string", "description": "Segment name (e.g., 'Intro', 'Verse 1')"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "duration": {"type": "string", "description": "Target duration for this segment"},
            "priority": {"type": "string", "enum": ["favorites", "longest", "shortest", "random"]}
          }
        }
      },
      "pacing": {
        "type": "string",
        "enum": ["slow", "medium", "fast", "dynamic"],
        "default": "medium",
        "description": "Overall pacing feel - affects average cut length"
      },
      "pacing_config": {
        "type": "object",
        "description": "Advanced pacing controls",
        "properties": {
          "min_clip_duration": {"type": "string", "default": "00:00:01:00"},
          "max_clip_duration": {"type": "string", "default": "00:00:08:00"},
          "avg_clip_duration": {"type": "string"},
          "vary_pacing": {"type": "boolean", "default": true, "description": "Vary cut lengths for organic feel"}
        }
      },
      "transitions": {
        "type": "object",
        "properties": {
          "between_segments": {"type": "string", "enum": ["none", "cross-dissolve", "fade-to-black"], "default": "cross-dissolve"},
          "within_segments": {"type": "string", "enum": ["none", "cut", "cross-dissolve"], "default": "cut"}
        }
      },
      "include_audio": {
        "type": "boolean",
        "default": true,
        "description": "Include audio from clips"
      },
      "music_track": {
        "type": "string",
        "description": "Optional path to music file to lay under the rough cut"
      }
    },
    "required": ["source_path", "output_path", "target_duration"]
  }
}
```

---

## Utility Tools

### `batch_add_markers`

```json
{
  "name": "batch_add_markers",
  "description": "Add multiple markers at once from a list or based on detection criteria.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "markers": {
        "type": "array",
        "description": "List of markers to add",
        "items": {
          "type": "object",
          "properties": {
            "timecode": {"type": "string"},
            "name": {"type": "string"},
            "marker_type": {"type": "string"},
            "color": {"type": "string"}
          },
          "required": ["timecode", "name"]
        }
      },
      "auto_detect": {
        "type": "object",
        "description": "Auto-generate markers based on detection",
        "properties": {
          "at_cuts": {"type": "boolean", "description": "Add marker at every cut point"},
          "at_keywords": {"type": "array", "items": {"type": "string"}, "description": "Add marker where keyword appears"},
          "at_intervals": {"type": "string", "description": "Add markers at regular intervals (e.g., '00:00:30:00')"}
        }
      }
    },
    "required": ["project_path"]
  }
}
```

---

### `apply_effect`

```json
{
  "name": "apply_effect",
  "description": "Apply a video or audio effect to one or more clips.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "clip_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Clips to apply effect to"
      },
      "effect_type": {
        "type": "string",
        "enum": ["color-correction", "lut", "blur", "sharpen", "stabilize", "denoise", "transform"],
        "description": "Type of effect to apply"
      },
      "parameters": {
        "type": "object",
        "description": "Effect-specific parameters (varies by effect_type)"
      }
    },
    "required": ["project_path", "clip_ids", "effect_type"]
  }
}
```

---

### `generate_proxies_list`

```json
{
  "name": "generate_proxies_list",
  "description": "Analyze project and generate a list of source files that need proxy generation.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "threshold_resolution": {
        "type": "string",
        "default": "1920x1080",
        "description": "Flag sources above this resolution"
      },
      "output_format": {
        "type": "string",
        "enum": ["json", "csv", "shell-script"],
        "default": "json",
        "description": "Output format for the list"
      }
    },
    "required": ["project_path"]
  }
}
```

---

### `export_for_color`

```json
{
  "name": "export_for_color",
  "description": "Export timeline in formats optimized for color grading roundtrip (DaVinci Resolve, Baselight).",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {
        "type": "string",
        "description": "Path to the FCPXML file"
      },
      "output_path": {
        "type": "string",
        "description": "Path for the exported file"
      },
      "format": {
        "type": "string",
        "enum": ["fcpxml", "edl", "aaf", "xml-resolve"],
        "default": "fcpxml",
        "description": "Export format"
      },
      "include_grades": {
        "type": "boolean",
        "default": false,
        "description": "Include existing color adjustments"
      },
      "handle_frames": {
        "type": "integer",
        "default": 24,
        "description": "Frames of handles to include for each clip"
      }
    },
    "required": ["project_path", "output_path"]
  }
}
```
