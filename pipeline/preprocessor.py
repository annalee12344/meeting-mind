"""
Step 0 — Preprocessing transcript.

This module cleans raw meeting transcripts and assigns unique sequential
utterance IDs (U001, U002, ...) to every utterance line. This allows later
pipeline stages to reference specific statements unambiguously.
"""
import re
from typing import Optional, NamedTuple
import unicodedata


class PreprocessError(ValueError):
    """Raised when transcript preprocessing fails or no valid utterances are found."""
    pass


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

# Format 3: Speaker (09:00): Text or Speaker (09:00:15): Text
RE_SPEAKER_TIMESTAMP_PARENS = re.compile(
    r"^(?P<speaker>[^:.\n\[\(]{1,60})\s*\((?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\)\s*:\s*(?P<text>.+)$"
)

# Format 4: Speaker [09:00]: Text or Speaker [09:00] - Text
RE_SPEAKER_TIMESTAMP_BRACKETS = re.compile(
    r"^(?P<speaker>[^:.\n\[\(]{1,60})\s*\[(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\]\s*[:\-–—]?\s*(?P<text>.+)$"
)

# Format 5: 09:00 Speaker: Text or 09:00 - Speaker: Text
RE_TIMESTAMP_SPEAKER_NOBRACKETS = re.compile(
    r"^(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(?P<speaker>[^:\n]+?)\s*:\s*(?P<text>.+)$"
)

# Format 6: 09:00 Text or 09:00 - Text (timestamp without brackets, no speaker)
RE_TIMESTAMP_ONLY_NOBRACKETS = re.compile(
    r"^(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(?P<text>.+)$"
)

# Format 7: Speaker: Text (without timestamp, speaker cannot start with bracket or digits)
RE_SPEAKER_ONLY = re.compile(
    r"^(?P<speaker>[^:.\n\[]{1,60})\s*:\s*(?P<text>.+)$"
)

# Format 8: Speaker - Text (without timestamp, speaker followed by space-hyphen-space)
# Rejects leading list bullets like '- item' or '* item'
RE_SPEAKER_HYPHEN = re.compile(
    r"^(?P<speaker>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_\s.]{1,50})\s+[-–—]\s+(?P<text>.+)$"
)


def parse_line(line: str) -> ParsedLine:
    """
    Parse a single raw transcript line into timestamp, speaker, and text.

    Handles:
    - [timestamp] Speaker: text
    - [timestamp] text
    - Speaker (timestamp): text
    - Speaker [timestamp]: text
    - timestamp - Speaker: text
    - timestamp text
    - Speaker: text
    - Speaker - text
    - text without speaker label or timestamp
    """
    cleaned = line.strip()

    # If the line already has an existing utterance ID like [U001] or U001:, strip it
    cleaned = re.sub(r"^\[?U\d{3,}\]?\s*[:\-]?\s*", "", cleaned).strip()

    # Format 1: [09:00] Speaker: Text
    match = RE_TIMESTAMP_SPEAKER_BRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Format 2: [09:00] Text (no speaker label)
    match = RE_TIMESTAMP_ONLY_BRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker="Unknown",
            text=match.group("text").strip(),
        )

    # Format 3: Speaker (09:00): Text
    match = RE_SPEAKER_TIMESTAMP_PARENS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Format 4: Speaker [09:00]: Text
    match = RE_SPEAKER_TIMESTAMP_BRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Format 5: 09:00 - Speaker: Text or 09:00 Speaker: Text
    match = RE_TIMESTAMP_SPEAKER_NOBRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Format 6: 09:00 Text
    match = RE_TIMESTAMP_ONLY_NOBRACKETS.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=match.group("timestamp").strip(),
            speaker="Unknown",
            text=match.group("text").strip(),
        )

    # Format 7: Speaker: Text
    match = RE_SPEAKER_ONLY.match(cleaned)
    if match:
        return ParsedLine(
            timestamp=None,
            speaker=match.group("speaker").strip(),
            text=match.group("text").strip(),
        )

    # Format 8: Speaker - Text
    match = RE_SPEAKER_HYPHEN.match(cleaned)
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


def preprocess(raw_text: str, strict: bool = False) -> str:
    """
    Preprocess raw transcript text by assigning sequential IDs (U001, U002...)
    to each non-empty utterance line.

    Args:
        raw_text: Raw Vietnamese or English transcript text.
        strict: If True, raises PreprocessError when input is empty or has 0 valid lines.

    Returns:
        Formatted transcript with prepended IDs, e.g.:
        [U001] [09:00] An: Chào mọi người...
        [U002] Bình: Tôi đồng ý...
    """
    if not raw_text:
        if strict:
            raise PreprocessError("Nội dung biên bản cuộc họp trống.")
        return ""

    # Strip BOM and normalize line endings + Unicode NFC
    cleaned_raw = raw_text.lstrip("\ufeff")
    cleaned_raw = cleaned_raw.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_raw = unicodedata.normalize("NFC", cleaned_raw)

    if not cleaned_raw.strip():
        if strict:
            raise PreprocessError("Nội dung biên bản cuộc họp trống.")
        return ""

    lines = cleaned_raw.splitlines()
    processed_lines: list[str] = []
    utterance_index = 1

    for raw_line in lines:
        stripped = raw_line.strip()
        # Skip empty lines or pure whitespace
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

    if strict and len(processed_lines) == 0:
        raise PreprocessError("Không tìm thấy dòng hội thoại hợp lệ nào trong biên bản cuộc họp.")

    return "\n".join(processed_lines)
