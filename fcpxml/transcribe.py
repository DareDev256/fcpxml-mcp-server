"""Transcript intelligence — local Whisper transcription + text-driven editing.

v0.13 slice 1: transcript-based editing. Transcription runs locally via
faster-whisper (optional ``[transcribe]`` extra) with word-level timestamps;
without it, or when media is missing/unreadable, ``transcribe`` returns
``None`` so callers degrade to an install hint instead of crashing — the
same contract as ``media_intel.detect_beats``.

The matching helpers below are pure functions over word lists so they are
fully testable without any model installed, and so tools can accept
pre-computed transcripts (from a previous ``transcribe_media`` run) instead
of re-transcribing.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Model names are used to resolve (and download) model weights, so they are
# validated against an allowlist, not trusted.
ALLOWED_MODELS = (
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large-v2", "large-v3", "distil-large-v3",
)

# Conservative by default: interjections that are near-universally filler.
# "like" / "so" / "actually" are speech, not noise, unless the user opts in.
DEFAULT_FILLERS = ("um", "uh", "uhh", "umm", "erm", "ehm", "mmm", "hmm", "mhm")

_NORM_RE = re.compile(r"[^\w']+")


def normalize_word(word: str) -> str:
    """Lowercase a word and strip punctuation so matching survives Whisper's
    tokenization quirks (leading spaces, trailing commas, case)."""
    return _NORM_RE.sub("", word.lower())


def find_phrase_spans(
    words: Sequence[dict], phrase: str
) -> List[Tuple[float, float]]:
    """Find every occurrence of ``phrase`` in a word-level transcript.

    ``words`` is a sequence of ``{"word", "start", "end"}`` dicts in source
    seconds. Matching is case- and punctuation-insensitive. Returns
    ``(start, end)`` source-second ranges spanning first to last matched word.
    """
    target = [normalize_word(w) for w in phrase.split()]
    target = [t for t in target if t]
    if not target:
        return []
    normed = [normalize_word(w.get("word", "")) for w in words]
    spans: List[Tuple[float, float]] = []
    i = 0
    n, m = len(normed), len(target)
    while i <= n - m:
        if normed[i:i + m] == target:
            spans.append((float(words[i]["start"]), float(words[i + m - 1]["end"])))
            i += m
        else:
            i += 1
    return spans


def find_filler_spans(
    words: Sequence[dict], fillers: Sequence[str] = DEFAULT_FILLERS
) -> List[Tuple[float, float]]:
    """Find filler-word occurrences (single- or multi-word fillers)."""
    spans: List[Tuple[float, float]] = []
    for filler in fillers:
        spans.extend(find_phrase_spans(words, filler))
    spans.sort()
    return spans


def merge_ranges(
    ranges: Sequence[Tuple[float, float]], min_gap: float = 0.0
) -> List[Tuple[float, float]]:
    """Merge overlapping (or nearly touching, within ``min_gap``) ranges."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + min_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def invert_ranges(
    ranges: Sequence[Tuple[float, float]], window_start: float, window_end: float
) -> List[Tuple[float, float]]:
    """Complement of ``ranges`` within ``[window_start, window_end]`` —
    turns keep-ranges into cut-ranges for keep_only mode."""
    if window_end <= window_start:
        return []
    kept = merge_ranges(
        [(max(s, window_start), min(e, window_end)) for s, e in ranges
         if min(e, window_end) > max(s, window_start)]
    )
    if not kept:
        return [(window_start, window_end)]
    out: List[Tuple[float, float]] = []
    cursor = window_start
    for start, end in kept:
        if start > cursor:
            out.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window_end:
        out.append((cursor, window_end))
    return out


def transcribe(
    path: str, model_size: str = "base", language: Optional[str] = None
) -> Optional[dict]:
    """Transcribe an audio/video file locally with word-level timestamps.

    Requires the optional ``[transcribe]`` extra (faster-whisper). Returns
    ``None`` when the model is unavailable or the file is missing/unreadable.

    Returns:
        ``{"language": str, "duration": float, "text": str,
           "segments": [{"text", "start", "end"}, ...],
           "words": [{"word", "start", "end"}, ...]}``
    """
    if model_size not in ALLOWED_MODELS:
        raise ValueError(
            f"model_size must be one of {', '.join(ALLOWED_MODELS)}, got {model_size!r}"
        )
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.info("faster-whisper not installed; transcription unavailable")
        return None
    try:
        model = WhisperModel(model_size, compute_type="int8")
        segments_iter, info = model.transcribe(
            str(file_path), language=language, word_timestamps=True
        )
        segments: List[dict] = []
        words: List[dict] = []
        for seg in segments_iter:
            segments.append(
                {"text": seg.text.strip(), "start": float(seg.start), "end": float(seg.end)}
            )
            for w in seg.words or []:
                words.append(
                    {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
                )
    except Exception:
        logger.warning("whisper transcription failed for %s", file_path)
        return None
    return {
        "language": info.language,
        "duration": float(info.duration),
        "text": " ".join(s["text"] for s in segments),
        "segments": segments,
        "words": words,
    }


def segments_to_srt(segments: Sequence[dict]) -> str:
    """Render transcript segments as an SRT string (for captions import)."""

    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = []
    for i, seg in enumerate(segments, 1):
        blocks.append(f"{i}\n{stamp(seg['start'])} --> {stamp(seg['end'])}\n{seg['text']}\n")
    return "\n".join(blocks)
