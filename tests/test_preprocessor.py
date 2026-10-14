"""
Unit tests for Step 0 Preprocessor (pipeline/preprocessor.py).

Tests:
1. All timestamp and speaker line formats.
2. Markdown bullets disambiguation from speaker hyphen.
3. BOM, CRLF, and Unicode NFC normalization.
4. Sequential utterance ID assignment.
5. Strict and non-strict mode validation.
"""
import unittest
import unicodedata

from pipeline.preprocessor import (
    ParsedLine,
    PreprocessError,
    parse_line,
    preprocess,
)


class TestPreprocessor(unittest.TestCase):
    """Exhaustive tests for transcript preprocessing."""

    def test_parse_line_all_formats(self):
        # Format 1: [09:00] Speaker: text
        p1 = parse_line("[09:00] An: Chào mọi người")
        self.assertEqual(p1.timestamp, "09:00")
        self.assertEqual(p1.speaker, "An")
        self.assertEqual(p1.text, "Chào mọi người")

        # Format 1b: [09:00:15] Speaker: text
        p1b = parse_line("[09:00:15] Bình: Tôi đây")
        self.assertEqual(p1b.timestamp, "09:00:15")
        self.assertEqual(p1b.speaker, "Bình")
        self.assertEqual(p1b.text, "Tôi đây")

        # Format 2: [09:00] text (no speaker)
        p2 = parse_line("[09:00] Cuộc họp bắt đầu lúc chín giờ")
        self.assertEqual(p2.timestamp, "09:00")
        self.assertEqual(p2.speaker, "Unknown")
        self.assertEqual(p2.text, "Cuộc họp bắt đầu lúc chín giờ")

        # Format 3: Speaker (09:00): text
        p3 = parse_line("Cường (09:05): Báo cáo tiến độ")
        self.assertEqual(p3.timestamp, "09:05")
        self.assertEqual(p3.speaker, "Cường")
        self.assertEqual(p3.text, "Báo cáo tiến độ")

        # Format 4: Speaker [09:00]: text and Speaker [09:00] - text
        p4 = parse_line("Dũng [09:10]: Đã hoàn thành API")
        self.assertEqual(p4.timestamp, "09:10")
        self.assertEqual(p4.speaker, "Dũng")
        self.assertEqual(p4.text, "Đã hoàn thành API")

        p4b = parse_line("Dũng [09:11] - Đã viết unit test")
        self.assertEqual(p4b.timestamp, "09:11")
        self.assertEqual(p4b.speaker, "Dũng")
        self.assertEqual(p4b.text, "Đã viết unit test")

        # Format 5: 09:00 - Speaker: text
        p5 = parse_line("09:15 - Em: Đang kiểm tra hệ thống")
        self.assertEqual(p5.timestamp, "09:15")
        self.assertEqual(p5.speaker, "Em")
        self.assertEqual(p5.text, "Đang kiểm tra hệ thống")

        # Format 6: 09:00 text (no speaker)
        p6 = parse_line("09:20 Tạm nghỉ giải lao")
        self.assertEqual(p6.timestamp, "09:20")
        self.assertEqual(p6.speaker, "Unknown")
        self.assertEqual(p6.text, "Tạm nghỉ giải lao")

        # Format 7: Speaker: text
        p7 = parse_line("Giang: Tôi đồng ý với đề xuất này")
        self.assertIsNone(p7.timestamp)
        self.assertEqual(p7.speaker, "Giang")
        self.assertEqual(p7.text, "Tôi đồng ý với đề xuất này")

        # Format 8: Speaker - text
        p8 = parse_line("Hải - Chúng ta sẽ chốt phương án B")
        self.assertIsNone(p8.timestamp)
        self.assertEqual(p8.speaker, "Hải")
        self.assertEqual(p8.text, "Chúng ta sẽ chốt phương án B")

        # Plain line
        plain = parse_line("Mọi người đều gật đầu tán thành.")
        self.assertIsNone(plain.timestamp)
        self.assertEqual(plain.speaker, "Unknown")
        self.assertEqual(plain.text, "Mọi người đều gật đầu tán thành.")

    def test_markdown_bullets_not_speaker(self):
        # Markdown bullets with hyphen should not be treated as speaker name '-'
        p1 = parse_line("- Nhiệm vụ 1: hoàn thành tài liệu")
        self.assertEqual(p1.speaker, "Unknown")
        self.assertIn("Nhiệm vụ 1", p1.text)

        p2 = parse_line("* Nhiệm vụ 2: kiểm thử API")
        self.assertEqual(p2.speaker, "Unknown")

    def test_bom_and_crlf_normalization(self):
        # Transcript with BOM and Windows CRLF
        raw = "\ufeff[09:00] An: Chào mọi người\r\n[09:01] Bình: Chào An\r\n"
        out = preprocess(raw, strict=True)
        self.assertNotIn("\ufeff", out)
        self.assertNotIn("\r", out)
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("[U001]"))
        self.assertTrue(lines[1].startswith("[U002]"))

    def test_unicode_nfc_normalization(self):
        # Decomposed NFD Vietnamese string: 'H' + 'o' + combining hook above
        nfd_text = unicodedata.normalize("NFD", "Hỏi đáp tiến độ")
        raw = f"An: {nfd_text}"
        out = preprocess(raw, strict=True)
        # Should be converted to NFC
        self.assertEqual(out, "[U001] An: Hỏi đáp tiến độ")
        self.assertEqual(unicodedata.normalize("NFC", out), out)

    def test_strip_existing_utterance_ids(self):
        raw = "[U005] [09:00] An: Đã có ID cũ\n[U009] Bình: Cũng có ID"
        out = preprocess(raw, strict=True)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("[U001] [09:00] An:"))
        self.assertTrue(lines[1].startswith("[U002] Bình:"))

    def test_strict_mode_errors(self):
        with self.assertRaises(PreprocessError):
            preprocess("", strict=True)

        with self.assertRaises(PreprocessError):
            preprocess("   \r\n\t  \n", strict=True)

    def test_non_strict_mode_empty(self):
        self.assertEqual(preprocess(""), "")
        self.assertEqual(preprocess("   \n\t "), "")


if __name__ == "__main__":
    unittest.main()
