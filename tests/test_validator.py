"""
Unit tests for the hardened Step 3 Validator (pipeline/validator.py).

Tests:
1. Unicode NFC vs NFD normalization.
2. Short quote handling: exact verbatim matches pass; partial matches fail.
3. Utterance ID anchoring and neighbor/global fallback (populating corrected_utterance_id).
4. Speaker verification: matching, honorific stripping, and mismatch detection.
5. End-to-end validate() updating item needs_review flag.
"""
import unittest
import unicodedata

from models.output import (
    ActionItem,
    Decision,
    Evidence,
    HistoryEntry,
    ItemStatus,
    ResolvedResult,
)
from pipeline.validator import (
    Validator,
    check_speaker_match,
    is_short_quote,
    match_quote_in_text,
    normalize_uid,
    parse_transcript_utterances,
)


SAMPLE_TRANSCRIPT = """
[U001] [09:00] Minh: Chào cả nhà, hôm nay team mình họp sprint planning cho Sprint 24 nhé.
[U002] [09:02] Lan: Chào anh Minh và mọi người. Về phía dev, em đã review sơ qua backlog rồi.
[U003] [09:05] Tuấn: Em đồng ý triển khai tích hợp thanh toán QR code qua VNPay.
[U004] [09:07] Minh: Nhất trí, vậy chốt scope là VNPay và nâng cấp UI giỏ hàng nhé.
[U005] [09:10] Hương: Về phía QA em sẽ test kỹ luồng thanh toán và các case timeout.
[U006] [09:12] Lan: Em sẽ nhận task tích hợp SDK và webhook VNPay, cam kết trước ngày 22/10.
"""


class TestValidatorNFC(unittest.TestCase):
    """Test Unicode NFC vs NFD normalization in quote matching."""

    def setUp(self):
        self.validator = Validator(threshold=80)

    def test_nfd_quote_matches_nfc_transcript(self):
        # Create quote with explicit NFD (decomposed) characters
        nfc_text = "Chào cả nhà, hôm nay team mình họp sprint planning"
        nfd_quote = unicodedata.normalize("NFD", nfc_text)

        self.assertNotEqual(nfc_text, nfd_quote)  # verify they have different byte representations
        matched, score = match_quote_in_text(nfd_quote, SAMPLE_TRANSCRIPT)
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 80.0)

    def test_nfd_transcript_matches_nfc_quote(self):
        nfc_quote = "Chào cả nhà, hôm nay team mình họp sprint planning"
        nfd_transcript = unicodedata.normalize("NFD", SAMPLE_TRANSCRIPT)

        matched, score = match_quote_in_text(nfc_quote, nfd_transcript)
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 80.0)


class TestValidatorShortQuotes(unittest.TestCase):
    """Test short quote handling (< 6 words or < 20 chars)."""

    def setUp(self):
        self.validator = Validator(threshold=80)

    def test_is_short_quote_identification(self):
        self.assertTrue(is_short_quote("OK anh"))
        self.assertTrue(is_short_quote("Đồng ý"))
        self.assertTrue(is_short_quote("Em làm phần này"))
        # 6 words and >= 20 chars
        self.assertFalse(is_short_quote("Em sẽ nhận task tích hợp SDK VNPay"))

    def test_short_quote_exact_match_passes(self):
        target = "Tuấn: Em đồng ý triển khai tích hợp thanh toán QR code qua VNPay."
        # Short quote present verbatim
        matched, score = match_quote_in_text("Em đồng ý", target)
        self.assertTrue(matched)
        self.assertEqual(score, 100.0)

    def test_short_quote_fuzzy_match_fails(self):
        target = "Tuấn: Em không đồng ý triển khai phương án này."
        # "Em đồng ý" is NOT an exact substring of "Em không đồng ý" as a word phrase
        # But if we test a slightly altered phrase like "Em hoàn toàn đồng ý", which does not exist in target:
        matched, score = match_quote_in_text("Em hoàn toàn đồng ý", target)
        # Even though RapidFuzz partial_ratio would score ~75-85%, short quote MUST fail
        self.assertFalse(matched)
        self.assertEqual(score, 0.0)


class TestValidatorUtteranceAnchoring(unittest.TestCase):
    """Test utterance anchoring, neighbor search, and global search fallback."""

    def setUp(self):
        self.validator = Validator(threshold=80)
        self.utterances = parse_transcript_utterances(SAMPLE_TRANSCRIPT)

    def test_normalize_uid(self):
        self.assertEqual(normalize_uid("U001"), "U001")
        self.assertEqual(normalize_uid("u1"), "U001")
        self.assertEqual(normalize_uid("[U005]"), "U005")
        self.assertEqual(normalize_uid("U024:"), "U024")
        self.assertIsNone(normalize_uid(None))
        self.assertIsNone(normalize_uid(""))

    def test_exact_cited_utterance_match(self):
        ev = Evidence(
            speaker="Tuấn",
            quote="Em đồng ý triển khai tích hợp thanh toán QR code qua VNPay.",
            utterance_id="U003",
        )
        self.validator.verify_evidence(ev, self.utterances)
        self.assertTrue(ev.verified)
        self.assertIsNone(ev.corrected_utterance_id)
        self.assertTrue(ev.speaker_matched)

    def test_neighbor_utterance_relocation(self):
        # Quote is at U003, but LLM cited U004 (distance 1 neighbor)
        ev = Evidence(
            speaker="Tuấn",
            quote="Em đồng ý triển khai tích hợp thanh toán QR code qua VNPay.",
            utterance_id="U004",
        )
        self.validator.verify_evidence(ev, self.utterances)
        self.assertTrue(ev.verified)
        self.assertEqual(ev.corrected_utterance_id, "U003")
        self.assertTrue(ev.speaker_matched)

    def test_global_search_fallback(self):
        # Quote is at U006, but LLM cited U001 (far distance)
        ev = Evidence(
            speaker="Lan",
            quote="Em sẽ nhận task tích hợp SDK và webhook VNPay, cam kết trước ngày 22/10.",
            utterance_id="U001",
        )
        self.validator.verify_evidence(ev, self.utterances)
        self.assertTrue(ev.verified)
        self.assertEqual(ev.corrected_utterance_id, "U006")
        self.assertTrue(ev.speaker_matched)

    def test_unprovided_utterance_id_finds_match(self):
        # Utterance ID is None (legacy result format)
        ev = Evidence(
            speaker="Hương",
            quote="Về phía QA em sẽ test kỹ luồng thanh toán và các case timeout.",
            utterance_id=None,
        )
        self.validator.verify_evidence(ev, self.utterances)
        self.assertTrue(ev.verified)
        self.assertEqual(ev.utterance_id, "U005")
        self.assertTrue(ev.speaker_matched)

    def test_hallucinated_quote_fails_completely(self):
        ev = Evidence(
            speaker="Lan",
            quote="Chúng ta sẽ dùng Kubernetes và Kafka cho toàn bộ hệ thống payment.",
            utterance_id="U002",
        )
        self.validator.verify_evidence(ev, self.utterances)
        self.assertFalse(ev.verified)
        self.assertFalse(ev.speaker_matched)


class TestValidatorSpeakerMatching(unittest.TestCase):
    """Test speaker verification logic."""

    def test_exact_and_case_insensitive_match(self):
        self.assertTrue(check_speaker_match("Minh", "Minh"))
        self.assertTrue(check_speaker_match("minh", "MINH"))

    def test_honorific_stripping(self):
        self.assertTrue(check_speaker_match("Minh", "Anh Minh"))
        self.assertTrue(check_speaker_match("Chị Lan", "Lan"))
        self.assertTrue(check_speaker_match("em Tuấn", "Tuấn"))
        self.assertTrue(check_speaker_match("Mr. John", "John"))

    def test_speaker_mismatch(self):
        self.assertFalse(check_speaker_match("Lan", "Minh"))
        self.assertFalse(check_speaker_match("Tuấn", "Hương"))

    def test_speaker_mismatch_sets_needs_review(self):
        validator = Validator(threshold=80)
        utterances = parse_transcript_utterances(SAMPLE_TRANSCRIPT)

        # Quote at U006 was spoken by Lan, but evidence claims it was spoken by Minh
        ev = Evidence(
            speaker="Minh",
            quote="Em sẽ nhận task tích hợp SDK và webhook VNPay, cam kết trước ngày 22/10.",
            utterance_id="U006",
        )
        validator.verify_evidence(ev, utterances)
        self.assertTrue(ev.verified)  # Text exists
        self.assertFalse(ev.speaker_matched)  # Speaker does NOT match!


class TestValidatorEndToEnd(unittest.TestCase):
    """Test full validate() flow on ResolvedResult."""

    def setUp(self):
        self.validator = Validator(threshold=80)

    def test_validate_flags_unverified_items(self):
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=["Minh", "Lan"],
            action_items=[
                ActionItem(
                    item_id="A001",
                    task="Tích hợp SDK VNPay",
                    assignee="Lan",
                    deadline="22/10",
                    evidence=[
                        Evidence(
                            speaker="Lan",
                            quote="Em sẽ nhận task tích hợp SDK và webhook VNPay, cam kết trước ngày 22/10.",
                            utterance_id="U006",
                        )
                    ],
                ),
                ActionItem(
                    item_id="A002",
                    task="Viết tài liệu DevOps",
                    assignee="Minh",
                    deadline="25/10",
                    evidence=[
                        Evidence(
                            speaker="Minh",
                            quote="Tôi đã dựng cụm cluster Kubernetes trên AWS rồi nhé.",  # Fabricated!
                            utterance_id="U001",
                        )
                    ],
                ),
            ],
        )

        validated = self.validator.validate(res, SAMPLE_TRANSCRIPT)

        # A001 verified -> needs_review is False
        self.assertTrue(validated.action_items[0].evidence[0].verified)
        self.assertFalse(validated.action_items[0].needs_review)

        # A002 unverified -> needs_review is True
        self.assertFalse(validated.action_items[1].evidence[0].verified)
        self.assertTrue(validated.action_items[1].needs_review)

    def test_validate_flags_speaker_mismatch_item(self):
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=["Minh", "Tuấn"],
            action_items=[
                ActionItem(
                    item_id="A001",
                    task="Triển khai VNPay QR",
                    assignee="Tuấn",
                    evidence=[
                        Evidence(
                            speaker="Minh",  # Speaker mismatch! Spoken by Tuấn at U003
                            quote="Em đồng ý triển khai tích hợp thanh toán QR code qua VNPay.",
                            utterance_id="U003",
                        )
                    ],
                )
            ],
        )

        validated = self.validator.validate(res, SAMPLE_TRANSCRIPT)
        self.assertTrue(validated.action_items[0].evidence[0].verified)
        self.assertFalse(validated.action_items[0].evidence[0].speaker_matched)
        self.assertTrue(validated.action_items[0].needs_review)


if __name__ == "__main__":
    unittest.main()
