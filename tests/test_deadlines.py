"""
Unit tests for pipeline/deadlines.py (Section 4).
Tests:
- Relative and informal deadline parsing in Vietnamese and English.
- Absolute date parsing.
- Failure cases returning None (no guessing).
- Meeting date resolution priority (user input -> transcript preamble -> fallback today).
"""
from datetime import date
import unittest

from pipeline.deadlines import (
    convert_deadline_to_iso,
    parse_transcript_preamble_date,
    resolve_meeting_date,
)


class TestDeadlines(unittest.TestCase):
    def setUp(self):
        # Base meeting date: Wednesday, 2026-10-14
        self.meeting_date = date(2026, 10, 14)
        self.assertEqual(self.meeting_date.weekday(), 2)  # Wednesday

    def test_immediate_and_relative_days(self):
        # Today
        self.assertEqual(convert_deadline_to_iso("hôm nay", self.meeting_date), "2026-10-14")
        self.assertEqual(convert_deadline_to_iso("today", self.meeting_date), "2026-10-14")
        self.assertEqual(convert_deadline_to_iso("trong ngày", self.meeting_date), "2026-10-14")

        # Tomorrow
        self.assertEqual(convert_deadline_to_iso("mai", self.meeting_date), "2026-10-15")
        self.assertEqual(convert_deadline_to_iso("ngày mai", self.meeting_date), "2026-10-15")
        self.assertEqual(convert_deadline_to_iso("tomorrow", self.meeting_date), "2026-10-15")

        # Day after tomorrow
        self.assertEqual(convert_deadline_to_iso("ngày kia", self.meeting_date), "2026-10-16")
        self.assertEqual(convert_deadline_to_iso("mốt", self.meeting_date), "2026-10-16")
        self.assertEqual(convert_deadline_to_iso("ngày mốt", self.meeting_date), "2026-10-16")

    def test_days_of_week_vietnamese_and_english(self):
        # Meeting date is Wednesday 2026-10-14
        # "thứ Sáu" -> Friday of current week: 2026-10-16
        self.assertEqual(convert_deadline_to_iso("thứ Sáu", self.meeting_date), "2026-10-16")
        self.assertEqual(convert_deadline_to_iso("thứ 6", self.meeting_date), "2026-10-16")
        self.assertEqual(convert_deadline_to_iso("Friday", self.meeting_date), "2026-10-16")

        # "thứ Sáu tuần sau" / "next Friday" -> 2026-10-23
        self.assertEqual(convert_deadline_to_iso("thứ Sáu tuần sau", self.meeting_date), "2026-10-23")
        self.assertEqual(convert_deadline_to_iso("next Friday", self.meeting_date), "2026-10-23")

        # "trước thứ Ba" -> since Tuesday already passed in current week, next Tuesday is 2026-10-20
        self.assertEqual(convert_deadline_to_iso("trước thứ Ba", self.meeting_date), "2026-10-20")

    def test_end_of_week_and_month(self):
        # Weekend -> Saturday of current week (2026-10-17)
        self.assertEqual(convert_deadline_to_iso("cuối tuần", self.meeting_date), "2026-10-17")
        self.assertEqual(convert_deadline_to_iso("weekend", self.meeting_date), "2026-10-17")

        # End of month -> 2026-10-31
        self.assertEqual(convert_deadline_to_iso("cuối tháng", self.meeting_date), "2026-10-31")
        self.assertEqual(convert_deadline_to_iso("end of month", self.meeting_date), "2026-10-31")

    def test_day_of_month_and_explicit_dates(self):
        # "trước ngày 20" -> 2026-10-20
        self.assertEqual(convert_deadline_to_iso("trước ngày 20", self.meeting_date), "2026-10-20")
        self.assertEqual(convert_deadline_to_iso("by the 20th", self.meeting_date), "2026-10-20")
        self.assertEqual(convert_deadline_to_iso("20th", self.meeting_date), "2026-10-20")

        # "20/10" -> 2026-10-20
        self.assertEqual(convert_deadline_to_iso("20/10", self.meeting_date), "2026-10-20")
        # Full date
        self.assertEqual(convert_deadline_to_iso("2026-11-15", self.meeting_date), "2026-11-15")
        self.assertEqual(convert_deadline_to_iso("15/11/2026", self.meeting_date), "2026-11-15")

    def test_unparseable_fails_to_none_never_guesses(self):
        self.assertIsNone(convert_deadline_to_iso("sớm nhất có thể", self.meeting_date))
        self.assertIsNone(convert_deadline_to_iso("khi nào xong thì gửi", self.meeting_date))
        self.assertIsNone(convert_deadline_to_iso("sau cuộc họp", self.meeting_date))
        self.assertIsNone(convert_deadline_to_iso("asap", self.meeting_date))
        self.assertIsNone(convert_deadline_to_iso("", self.meeting_date))
        self.assertIsNone(convert_deadline_to_iso(None, self.meeting_date))

    def test_meeting_date_resolution_priority(self):
        # Priority 1: User input
        d, src = resolve_meeting_date(user_input_date="2026-06-15", transcript="Ngày 20/10/2026")
        self.assertEqual(d, date(2026, 6, 15))
        self.assertEqual(src, "user")

        # User input in DD/MM/YYYY
        d, src = resolve_meeting_date(user_input_date="15/06/2026")
        self.assertEqual(d, date(2026, 6, 15))
        self.assertEqual(src, "user")

        # Priority 2: Transcript preamble
        sample_transcript = "Biên bản cuộc họp Sprint 24\nNgày 15/06/2026\n[09:00] Tuấn: Bắt đầu họp"
        d, src = resolve_meeting_date(user_input_date=None, transcript=sample_transcript)
        self.assertEqual(d, date(2026, 6, 15))
        self.assertEqual(src, "transcript")

        # Priority 3: Fallback today
        d, src = resolve_meeting_date(user_input_date=None, transcript="[09:00] Tuấn: Bắt đầu họp")
        self.assertEqual(d, date.today())
        self.assertEqual(src, "fallback_today")


if __name__ == "__main__":
    unittest.main()
