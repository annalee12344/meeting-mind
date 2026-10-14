"""
Pipeline Deadlines Module.

Handles:
1. Extracting/resolving the meeting date (User input -> Transcript preamble -> Today).
2. Converting relative and informal deadline strings (Vietnamese & English) into
   absolute ISO 8601 dates (YYYY-MM-DD) relative to the meeting date.
3. Strict parsing: returns None on unknown or unparseable phrases without guesswork.
"""
import calendar
from datetime import date, datetime, timedelta
import re
from typing import Literal, Optional, Tuple
import unicodedata


# Vietnamese day of week mapping: (0 = Monday, ..., 6 = Sunday)
DOW_MAP_VI: dict[str, int] = {
    "thứ hai": 0,
    "thứ 2": 0,
    "t2": 0,
    "thứ ba": 1,
    "thứ 3": 1,
    "t3": 1,
    "thứ tư": 2,
    "thứ 4": 2,
    "t4": 2,
    "thứ năm": 3,
    "thứ 5": 3,
    "t5": 3,
    "thứ sáu": 4,
    "thứ 6": 4,
    "t6": 4,
    "thứ bảy": 5,
    "thứ 7": 5,
    "t7": 5,
    "chủ nhật": 6,
    "cn": 6,
}

DOW_MAP_EN: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def normalize_text(text: str) -> str:
    """Normalize text into NFC and clean whitespace."""
    if not text:
        return ""
    nfc = unicodedata.normalize("NFC", text)
    return " ".join(nfc.strip().split())


def parse_transcript_preamble_date(transcript: str) -> Optional[date]:
    """
    Scan the beginning of transcript (preamble) for date patterns.
    Examples:
    - [2026-10-14] or [14/10/2026]
    - Ngày 15/06/2026, Ngày 15-06-2026, Ngày 15 tháng 6 năm 2026
    - Date: 2026-06-15, Date: 15/06/2026
    """
    if not transcript:
        return None

    # Inspect first 15 lines or 1500 chars
    lines = transcript.splitlines()[:15]
    preamble = "\n".join(lines)
    preamble = unicodedata.normalize("NFC", preamble)

    # 1. ISO format: YYYY-MM-DD
    iso_match = re.search(r"\b(?P<year>20\d{2})[-/.](?P<month>0?[1-9]|1[0-2])[-/.](?P<day>0?[1-9]|[12]\d|3[01])\b", preamble)
    if iso_match:
        try:
            return date(int(iso_match.group("year")), int(iso_match.group("month")), int(iso_match.group("day")))
        except ValueError:
            pass

    # 2. DD/MM/YYYY or DD-MM-YYYY
    dmy_match = re.search(r"\b(?P<day>0?[1-9]|[12]\d|3[01])[-/.](?P<month>0?[1-9]|1[0-2])[-/.](?P<year>20\d{2})\b", preamble)
    if dmy_match:
        try:
            return date(int(dmy_match.group("year")), int(dmy_match.group("month")), int(dmy_match.group("day")))
        except ValueError:
            pass

    # 3. Vietnamese textual: "Ngày 15 tháng 6 năm 2026" or "Ngày 15/6/2026"
    vn_match = re.search(
        r"(?:ngày|họp ngày)\s+(?P<day>\d{1,2})\s*(?:tháng|/|-)\s*(?P<month>\d{1,2})(?:\s*(?:năm|/|-)\s*(?P<year>20\d{2}))?",
        preamble,
        re.IGNORECASE,
    )
    if vn_match:
        try:
            d = int(vn_match.group("day"))
            m = int(vn_match.group("month"))
            y = int(vn_match.group("year")) if vn_match.group("year") else date.today().year
            return date(y, m, d)
        except ValueError:
            pass

    return None


def resolve_meeting_date(
    user_input_date: Optional[str] = None,
    transcript: Optional[str] = None,
) -> Tuple[date, Literal["user", "transcript", "fallback_today"]]:
    """
    Resolve the meeting date following strict priority:
    1. Optional user input date string (YYYY-MM-DD or DD/MM/YYYY) -> 'user'
    2. Parsed date from transcript preamble -> 'transcript'
    3. Today's date -> 'fallback_today'
    """
    # 1. User input
    if user_input_date and user_input_date.strip():
        clean_input = user_input_date.strip()
        # Try ISO
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                parsed = datetime.strptime(clean_input, fmt).date()
                return parsed, "user"
            except ValueError:
                continue

    # 2. Transcript preamble
    if transcript:
        preamble_date = parse_transcript_preamble_date(transcript)
        if preamble_date:
            return preamble_date, "transcript"

    # 3. Fallback today
    return date.today(), "fallback_today"


def _get_target_dow_date(base_date: date, target_dow: int, next_week: bool = False) -> date:
    """
    Find target day of week relative to base_date.
    If next_week is True, target will be in base_date's following week.
    If next_week is False, target will be the next occurrence on or after base_date.
    """
    base_dow = base_date.weekday()
    if next_week:
        # Move to next week's Monday first
        days_until_next_monday = (7 - base_dow)
        next_monday = base_date + timedelta(days=days_until_next_monday)
        return next_monday + timedelta(days=target_dow)

    # In current week or coming
    days_ahead = target_dow - base_dow
    if days_ahead < 0:
        # Already passed in current week -> next occurrence
        days_ahead += 7
    return base_date + timedelta(days=days_ahead)


def convert_deadline_to_iso(
    deadline_raw: Optional[str],
    meeting_date: date,
    is_relative_allowed: bool = True,
) -> Optional[str]:
    """
    Convert relative/informal deadline text to absolute ISO 8601 (YYYY-MM-DD).
    
    Handles:
    - "hôm nay", "today", "trong ngày" -> meeting_date
    - "mai", "ngày mai", "tomorrow" -> meeting_date + 1
    - "ngày kia", "mốt", "ngày mốt" -> meeting_date + 2
    - "thứ Sáu tuần này", "thứ Sáu tuần sau", "next Friday", "this Friday"
    - "cuối tuần", "weekend" -> coming Saturday
    - "cuối tháng", "end of month" -> last day of meeting_date's month
    - "trước ngày 20", "ngày 20", "by the 20th", "20/10", "20/10/2026"
    
    If is_relative_allowed is False (e.g. meeting date is unknown/fallback_today),
    relative date phrases (like "ngày mai", "thứ Tư", "cuối tuần") return None
    to prevent inventing a calendar date without a known reference date.
    
    Returns ISO date string, or None if parsing fails (no guesswork).
    """
    if not deadline_raw or not deadline_raw.strip():
        return None

    norm = normalize_text(deadline_raw).lower()

    # 1. Exact full ISO dates: 2026-10-25
    iso_full = re.search(r"\b(20\d{2})-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])\b", norm)
    if iso_full:
        try:
            d = date(int(iso_full.group(1)), int(iso_full.group(2)), int(iso_full.group(3)))
            return d.isoformat()
        except ValueError:
            return None

    # 2. Full DMY dates: 25/10/2026 or 25-10-2026
    dmy_full = re.search(r"\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2})\b", norm)
    if dmy_full:
        try:
            d = date(int(dmy_full.group(3)), int(dmy_full.group(2)), int(dmy_full.group(1)))
            return d.isoformat()
        except ValueError:
            return None

    # If relative dates are not allowed because meeting date is unknown, do not invent a date
    if not is_relative_allowed:
        return None

    # 3. Day / Month without year: "20/10", "15/6", "ngày 20/10"
    dm_match = re.search(r"\b(0?[1-9]|[12]\d|3[01])/(0?[1-9]|1[0-2])\b", norm)
    if dm_match:
        try:
            day = int(dm_match.group(1))
            month = int(dm_match.group(2))
            year = meeting_date.year
            # If the month is earlier in the year than meeting_date, could be next year
            if month < meeting_date.month:
                year += 1
            d = date(year, month, day)
            return d.isoformat()
        except ValueError:
            return None

    # 4. Immediate relative words: "hôm nay", "today"
    if re.search(r"\b(hôm nay|today|trong ngày|ngay)\b", norm):
        return meeting_date.isoformat()

    # 5. Tomorrow: "mai", "ngày mai", "tomorrow"
    if re.search(r"\b(ngày mai|mai|tomorrow)\b", norm):
        return (meeting_date + timedelta(days=1)).isoformat()

    # 6. Day after tomorrow: "ngày kia", "ngày mốt", "mốt"
    if re.search(r"\b(ngày kia|ngày mốt|mốt)\b", norm):
        return (meeting_date + timedelta(days=2)).isoformat()

    # 7. End of week / weekend: "cuối tuần", "weekend"
    if re.search(r"\b(cuối tuần|weekend)\b", norm):
        target = _get_target_dow_date(meeting_date, target_dow=5)  # Saturday
        return target.isoformat()

    # 8. End of month: "cuối tháng", "end of month"
    if re.search(r"\b(cuối tháng|end of month|cuối tháng này)\b", norm):
        last_day = calendar.monthrange(meeting_date.year, meeting_date.month)[1]
        return date(meeting_date.year, meeting_date.month, last_day).isoformat()

    # 9. Day of week expressions (Vietnamese & English)
    # Check for "tuần sau" or "next"
    is_next_week = bool(re.search(r"\b(tuần sau|sang tuần|next)\b", norm))

    # Match Vietnamese days of week: "thứ Sáu tuần sau", "thứ 6", "trước thứ Ba"
    for phrase, dow in DOW_MAP_VI.items():
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, norm):
            target = _get_target_dow_date(meeting_date, dow, next_week=is_next_week)
            return target.isoformat()

    # Match English days of week: "next Friday", "this Friday", "Friday"
    for phrase, dow in DOW_MAP_EN.items():
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, norm):
            target = _get_target_dow_date(meeting_date, dow, next_week=is_next_week)
            return target.isoformat()

    # 10. Day of month expressions: "trước ngày 20", "ngày 20", "by the 20th", "20th"
    dom_match = re.search(
        r"(?:(?:ngày|trước ngày|by the|the)\s+)?\b(\d{1,2})(?:th|st|nd|rd)\b|(?:ngày|trước ngày|by the|the)\s+(\d{1,2})\b",
        norm,
    )
    if dom_match:
        try:
            day_str = dom_match.group(1) or dom_match.group(2)
            day = int(day_str)
            year = meeting_date.year
            month = meeting_date.month
            # Check if this day is valid in current month
            last_day = calendar.monthrange(year, month)[1]
            if 1 <= day <= last_day:
                target = date(year, month, day)
                # If target day is before meeting_date, it means next month
                if target < meeting_date:
                    if month == 12:
                        target = date(year + 1, 1, day)
                    else:
                        target = date(year, month + 1, day)
                return target.isoformat()
        except ValueError:
            return None

    # Parsing failed: never guess
    return None
