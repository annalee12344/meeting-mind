"""
Unit tests for pipeline/mapper.py (Section 2 & Section 3).
Tests:
- Deterministic mapping rules for decisions, action items, requests, blockers, unresolved items.
- Downgrade path for unconfirmed tasks.
- Name normalization and honorific stripping.
- Legacy JSON upgrade via upgrade_legacy_result().
"""
import unittest

from models.output import (
    ActionItem,
    Blocker,
    Decision,
    Evidence,
    HistoryEntry,
    ItemStatus,
    Request,
    ResolvedResult,
    UnresolvedItem,
)
from pipeline.mapper import (
    is_generic_assignee,
    map_to_public,
    normalize_person_name,
    upgrade_legacy_result,
)


class TestMapper(unittest.TestCase):
    def setUp(self):
        self.participants = ["Tuấn", "Lan", "Hương", "Minh"]

    def test_normalize_person_name(self):
        # Honorific stripping
        self.assertEqual(normalize_person_name("anh Tuấn", self.participants), "Tuấn")
        self.assertEqual(normalize_person_name("Chị Lan", self.participants), "Lan")
        self.assertEqual(normalize_person_name("em Hương", self.participants), "Hương")
        self.assertEqual(normalize_person_name("Mr. Minh", self.participants), "Minh")
        self.assertEqual(normalize_person_name("bạn Tuấn", self.participants), "Tuấn")

        # Diacritic-insensitive match against participants
        self.assertEqual(normalize_person_name("Tuan", self.participants), "Tuấn")
        self.assertEqual(normalize_person_name("Huong", self.participants), "Hương")

        # Unknown name
        self.assertEqual(normalize_person_name("anh Dũng", self.participants), "Dũng")
        self.assertEqual(normalize_person_name("", self.participants), "")
        self.assertEqual(normalize_person_name(None, self.participants), "")

    def test_is_generic_assignee(self):
        self.assertTrue(is_generic_assignee(None))
        self.assertTrue(is_generic_assignee(""))
        self.assertTrue(is_generic_assignee("unknown"))
        self.assertTrue(is_generic_assignee("chưa rõ"))
        self.assertTrue(is_generic_assignee("chưa phân công"))
        self.assertTrue(is_generic_assignee("ai đó"))
        self.assertTrue(is_generic_assignee("team"))
        self.assertFalse(is_generic_assignee("Lan"))
        self.assertFalse(is_generic_assignee("Tuấn"))

    def test_map_decisions_rules(self):
        ev1 = Evidence(speaker="Lan", quote="Dùng Postgres", utterance_id="U002")
        ev2 = Evidence(speaker="Tuấn", quote="Chốt MongoDB", utterance_id="U006")

        h1 = HistoryEntry(value="Postgres", status=ItemStatus.SUPERSEDED, role="proposes", evidence=[ev1])
        h2 = HistoryEntry(value="MongoDB", status=ItemStatus.CONFIRMED, role="confirms", evidence=[ev2])

        # 1. Confirmed decision
        d_confirmed = Decision(
            item_id="D001",
            topic="Database",
            final_value="MongoDB",
            status=ItemStatus.CONFIRMED,
            history=[h1, h2],
        )

        # 2. Unresolved decision
        d_unresolved = Decision(
            item_id="D002",
            topic="Ngân sách",
            final_value="Chưa chốt",
            status=ItemStatus.UNRESOLVED,
            history=[],
        )

        # 3. Needs review decision
        d_review = Decision(
            item_id="D003",
            topic="Cloud provider",
            final_value="AWS hay GCP",
            status=ItemStatus.NEEDS_REVIEW,
            needs_review=True,
            history=[],
        )

        # 4. Superseded decision
        d_superseded = Decision(
            item_id="D004",
            topic="Old architecture",
            final_value="Monolith",
            status=ItemStatus.SUPERSEDED,
            history=[],
        )

        resolved = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            decisions=[d_confirmed, d_unresolved, d_review, d_superseded],
        )

        public_out = map_to_public(resolved)

        # Only confirmed goes to public decisions
        self.assertEqual(len(public_out.decisions), 1)
        self.assertEqual(public_out.decisions[0].content, "MongoDB")
        self.assertEqual(public_out.decisions[0].proposed_by, "Lan")
        self.assertEqual(public_out.decisions[0].confirmed_by, "Tuấn")

        # Unresolved and needs_review go to public unresolved (open_decision)
        unres_open = [u for u in public_out.unresolved if u.kind == "open_decision"]
        self.assertEqual(len(unres_open), 2)
        review_item = next(u for u in unres_open if u.source_ref == "D003")
        self.assertTrue(review_item.needs_review)

        # Superseded is omitted from top-level
        self.assertNotIn("D004", [d.source_ref for d in public_out.decisions])

    def test_map_action_items_confirmed_vs_downgrade(self):
        transcript = "[U005] Tuấn: Lan làm database nhé\n[U006] Lan: Vâng, em nhận việc này"

        # Item 1: Confirmed by assignee
        a1 = ActionItem(
            item_id="A001",
            task="Setup MongoDB",
            assignee="Lan",
            assigned_by="Tuấn",
            deadline="Thứ Sáu",
            assignee_confirmed=True,
            confirmation_utterance_id="U006",
            evidence=[Evidence(speaker="Lan", quote="em nhận việc này", utterance_id="U006")],
        )

        # Item 2: Unconfirmed (no confirmation utterance)
        a2 = ActionItem(
            item_id="A002",
            task="Design UI",
            assignee="Hương",
            deadline="Thứ Ba",
            assignee_confirmed=False,
            evidence=[],
        )

        # Item 3: Generic assignee
        a3 = ActionItem(
            item_id="A003",
            task="Review code",
            assignee="ai đó",
            evidence=[],
        )

        # Item 4: Speaker mismatch (U005 was Tuấn, but assignee is Hương)
        a4 = ActionItem(
            item_id="A004",
            task="Test staging",
            assignee="Hương",
            assignee_confirmed=True,
            confirmation_utterance_id="U005",  # Spoken by Tuấn, not Hương
            evidence=[],
        )

        resolved = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a1, a2, a3, a4],
        )

        public_out = map_to_public(resolved, transcript=transcript)

        # Only a1 should become a confirmed Task
        self.assertEqual(len(public_out.tasks), 1)
        self.assertEqual(public_out.tasks[0].title, "Setup MongoDB")
        self.assertEqual(public_out.tasks[0].assignee, "Lan")

        # a2, a3, a4 should be downgraded to unresolved (unconfirmed_task)
        unconfirmed = [u for u in public_out.unresolved if u.kind == "unconfirmed_task"]
        self.assertEqual(len(unconfirmed), 3)

        # a2 suggested_assignee is Hương
        u_a2 = next(u for u in unconfirmed if u.source_ref == "A002")
        self.assertEqual(u_a2.suggested_assignee, "Hương")

        # a3 suggested_assignee should be None (generic)
        u_a3 = next(u for u in unconfirmed if u.source_ref == "A003")
        self.assertIsNone(u_a3.suggested_assignee)

        # a4 suggested_assignee is Hương
        u_a4 = next(u for u in unconfirmed if u.source_ref == "A004")
        self.assertEqual(u_a4.suggested_assignee, "Hương")

    def test_map_requests_and_blockers(self):
        # Request with clear assignee -> Tasks
        r1 = Request(
            item_id="R001",
            type="request",
            content="Gửi tài liệu API",
            from_person="Tuấn",
            to_person="Lan",
        )
        # Request without assignee -> Unresolved
        r2 = Request(
            item_id="R002",
            type="request",
            content="Cần server test",
            from_person="Lan",
            to_person=None,
        )
        # Blocker -> Issues
        b1 = Blocker(
            item_id="B001",
            issue="Database connection timeout",
            owner="Minh",
            status=ItemStatus.UNRESOLVED,
        )

        resolved = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            requests=[r1, r2],
            blockers=[b1],
        )

        public_out = map_to_public(resolved)

        # r1 mapped to Task
        t_r1 = next((t for t in public_out.tasks if t.source_ref == "R001"), None)
        self.assertIsNotNone(t_r1)
        self.assertEqual(t_r1.title, "Gửi tài liệu API")
        self.assertEqual(t_r1.assignee, "Lan")
        self.assertEqual(t_r1.requested_by, "Tuấn")

        # r2 mapped to Unresolved
        u_r2 = next((u for u in public_out.unresolved if u.source_ref == "R002"), None)
        self.assertIsNotNone(u_r2)
        self.assertEqual(u_r2.kind, "unconfirmed_task")

        # b1 mapped to Issue
        self.assertEqual(len(public_out.issues), 1)
        self.assertEqual(public_out.issues[0].content, "Database connection timeout")
        self.assertEqual(public_out.issues[0].owner, "Minh")
        self.assertEqual(public_out.issues[0].status, "open")

    def test_upgrade_legacy_result(self):
        legacy_dict = {
            "meeting_summary": "Legacy meeting",
            "participants": ["Tuấn", "Lan"],
            "decisions": [
                {
                    "item_id": "D001",
                    "topic": "DB",
                    "final_value": "MongoDB",
                    "status": "confirmed",
                    "history": [],
                }
            ],
            "action_items": [
                {
                    "item_id": "A001",
                    "task": "Setup",
                    "assignee": "Lan",
                    "deadline": "Thứ Sáu",
                    "assignee_confirmed": True,
                    "confirmation_utterance_id": "U002",
                    "evidence": [{"speaker": "Lan", "quote": "em làm", "utterance_id": "U002"}],
                }
            ],
            "blockers": [
                {"item_id": "B001", "issue": "Staging bug", "status": "unresolved"}
            ],
            "requests": [],
            "unresolved_items": [],
        }

        upgraded = upgrade_legacy_result(legacy_dict)
        self.assertEqual(upgraded.meta.schema_version, "2.0.0")
        self.assertEqual(len(upgraded.decisions), 1)
        self.assertEqual(upgraded.decisions[0].content, "MongoDB")
        self.assertEqual(len(upgraded.tasks), 1)
        self.assertEqual(len(upgraded.issues), 1)


if __name__ == "__main__":
    unittest.main()
