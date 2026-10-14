"""
Step 0 — Preprocessing transcript.

This module cleans raw meeting transcripts and assigns unique sequential
utterance IDs (U001, U002, ...) to every utterance line. This allows later
pipeline stages to reference specific statements unambiguously.
"""
import re
from typing import Optional, NamedTuple


class ParsedLine(NamedTuple):
    """Structured representation of a parsed transcript line."""
    timestamp: Optional[str]
    speaker: str
    text: str


# Format 1: [09:00] Speaker: Text or [09:00:15] Speaker: Text
RE_TIMESTAMP_SPEAKER_BRACKETS = re.compile(
    r"^\[(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<speaker>[^:\n]+?)\s*:\s*(?P<text>.+)$"
)

# Format 2: [09:00] Text (timestamp in brackets, but no speaker label)
RE_TIMESTAMP_ONLY_BRACKETS = re.compile(
    r"^\[(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<text>.+)$"
)

# Format 3: 09:00 Speaker: Text or 09:00 - Speaker: Text
RE_TIMESTAMP_SPEAKER_NOBRACKETS = re.compile(
    r"^(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(?P<speaker>[^:\n]+?)\s*:\s*(?P<text>.+)$"
)

# Format 4: 09:00 Text or 09:00 - Text (timestamp without brackets, no speaker)
RE_TIMESTAMP_ONLY_NOBRACKETS = re.compile(
    r"^(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(?P<text>.+)$"
)

# Format 5: Speaker: Text (without timestamp, speaker cannot start with bracket or digits)
RE_SPEAKER_ONLY = re.compile(
    r"^(?P<speaker>[^:.\n\[]{1,60})\s*:\s*(?P<text>.+)$"
)


def parse_line(line: str) -> ParsedLine:
    """
    Parse a single raw transcript line into timestamp, speaker, and text.

    Handles:
    - [timestamp] Speaker: text
    - [timestamp] text
    - timestamp - Speaker: text
    - timestamp text
    - Speaker: text
    - text without speaker label or timestamp
    """
    cleaned = line.strip()

    # If the line already has an existing utterance ID like [U001] or U001:, strip it
    cleaned = re.sub(r"^\[?U\d{3,}\]?\s*[:\-]?\s*", "", cleaned).strip()

    # Check Format 1: [09:00] Speaker: Text
    match = RE_TIMESTAMP_SPEAKER_BRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Check Format 2: [09:00] Text (no speaker label)
    match = RE_TIMESTAMP_ONLY_BRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker="Unknown",
            text=match.group("text").strip(),
        )

    # Check Format 3: 09:00 - Speaker: Text or 09:00 Speaker: Text
    match = RE_TIMESTAMP_SPEAKER_NOBRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Check Format 4: 09:00 Text
    match = RE_TIMESTAMP_ONLY_NOBRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker="Unknown",
            text=match.group("text").strip(),
        )

    # Check Format 5: Speaker: Text
    match = RE_SPEAKER_ONLY.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=None,
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Default edge case: plain line without speaker label or timestamp
    return ParsedLine(
        timestamp=None,
        speaker="Unknown",
        text=cleaned,
    )


def preprocess(raw_text: str) -> str:
    """
    Preprocess raw transcript text by assigning sequential IDs (U001, U002...)
    to each non-empty utterance line.

    Args:
        raw_text: Raw Vietnamese transcript text.

    Returns:
        Formatted transcript with prepended IDs, e.g.:
        [U001] [09:00] An: Chào mọi người...
        [U002] Bình: Tôi đồng ý...
    """
    if not raw_text or not raw_text.strip():
        return ""

    lines = raw_text.splitlines()
    processed_lines: list[str] = []
    utterance_index = 1

    for raw_line in lines:
        stripped = raw_line.strip()
        # Edge case: skip empty lines or pure whitespace
        if not stripped:
            continue

        parsed = parse_line(stripped)
        # Skip lines that became empty after stripping
        if not parsed.text:
            continue

        utterance_id = f"U{utterance_index:03d}"

        # Reconstruct standardized utterance line with ID prepended
        if parsed.timestamp and parsed.speaker != "Unknown":
            formatted = f"[{utterance_id}] [{parsed.timestamp}] {parsed.speaker}: {parsed.text}"
        elif parsed.timestamp and parsed.speaker == "Unknown":
            formatted = f"[{utterance_id}] [{parsed.timestamp}] Unknown: {parsed.text}"
        elif parsed.speaker != "Unknown":
            formatted = f"[{utterance_id}] {parsed.speaker}: {parsed.text}"
        else:
            formatted = f"[{utterance_id}] Unknown: {parsed.text}"

        processed_lines.append(formatted)
        utterance_index += 1

    return "\n".join(processed_lines)
