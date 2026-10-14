"""
Unit tests for models/output.py (Section 1).
Tests internal ResolvedResult, public MeetingOutput, UUID generation,
and schema validation.
"""
import unittest
from uuid import UUID

from models.output import (
    ResolvedResult,
    Decision,
    ActionItem,
    Blocker,
    Request,
    UnresolvedItem,
    Evidence,
    HistoryEntry,
    ItemStatus,
    MeetingOutput,
    PublicDecision,
    PublicTask,
    PublicUnresolvedItem,
    PublicIssue,
    PublicMeta,
)


class TestModelsOutput(unittest.TestCase):
    def test_internal_resolved_result_instantiation(self):
        ev = Evidence(speaker="Lan", quote="Tôi đề xuất PostgreSQL", utterance_id="U002", verified=True)
        h = HistoryEntry(value="PostgreSQL", status=ItemStatus.SUPERSEDED, evidence=[ev])
        d = Decision(item_id="D001", topic="Database", final_value="MongoDB", status=ItemStatus.CONFIRMED, history=[h])
        a = ActionItem(
            item_id="A001",
            task="Setup DB",
            assignee="Lan",
            deadline="Thứ Sáu",
            assignee_confirmed=True,
            confirmation_utterance_id="U006",
            assigned_by="Tuấn",
        )
        b = Blocker(item_id="B001", issue="Server lag", status=ItemStatus.CONFIRMED)
        r = Request(item_id="R001", type="request", content="Cần tài liệu", from_person="Nam", to_person="Lan")
        u = UnresolvedItem(item_id="UR001", topic="Ngân sách", reason_unresolved="Chưa rõ chi phí")

        res = ResolvedResult(
            meeting_summary="Cuộc họp sprint",
            participants=["Lan", "Tuấn", "Nam"],
            decisions=[d],
            action_items=[a],
            blockers=[b],
            requests=[r],
            unresolved_items=[u],
        )
        self.assertEqual(len(res.decisions), 1)
        self.assertEqual(len(res.action_items), 1)
        self.assertTrue(res.action_items[0].assignee_confirmed)
        self.assertEqual(res.action_items[0].assigned_by, "Tuấn")

    def test_public_meeting_output_instantiation_and_uuids(self):
        pub_d = PublicDecision(
            topic="Database",
            content="Use MongoDB",
            proposed_by="Lan",
            confirmed_by="Tuấn",
            source_ref="D001",
        )
        pub_t = PublicTask(
            title="Setup database",
            assignee="Lan",
            assigned_by="Tuấn",
            deadline_raw="Thứ Sáu",
            deadline_iso="2026-10-16",
            source="ai",
            source_ref="A001",
        )
        pub_u1 = PublicUnresolvedItem(
            kind="open_decision",
            content="Lựa chọn hosting",
            reason_unresolved="Chưa thống nhất ngân sách",
            source_ref="UR001",
        )
        pub_u2 = PublicUnresolvedItem(
            kind="unconfirmed_task",
            content="Viết tài liệu API",
            suggested_assignee="Minh",
            source_ref="A002",
        )
        pub_i = PublicIssue(
            content="Server staging quá chậm",
            owner="Nam",
            status="open",
            source_ref="B001",
        )
        meta = PublicMeta(
            schema_version="2.0.0",
            prompt_version="2.0.0",
            per_step_model={"step1": "gemini-flash-lite-latest", "step2": "gemini-flash-lite-latest"},
            meeting_date="2026-10-14",
            meeting_date_source="transcript",
        )

        out = MeetingOutput(
            summary="Cuộc họp hoàn thành mục tiêu.",
            participants=["Lan", "Tuấn", "Nam", "Minh"],
            decisions=[pub_d],
            tasks=[pub_t],
            unresolved=[pub_u1, pub_u2],
            issues=[pub_i],
            meta=meta,
        )

        # Check UUID validity
        UUID(pub_d.id)
        UUID(pub_t.id)
        UUID(pub_u1.id)
        UUID(pub_i.id)

        # Check properties and aliases
        self.assertEqual(out.summary, "Cuộc họp hoàn thành mục tiêu.")
        self.assertEqual(out.meeting_summary, "Cuộc họp hoàn thành mục tiêu.")
        self.assertEqual(len(out.decisions), 1)
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(len(out.unresolved), 2)
        self.assertEqual(len(out.issues), 1)
        self.assertEqual(out.meta.meeting_date_source, "transcript")


if __name__ == "__main__":
    unittest.main()
