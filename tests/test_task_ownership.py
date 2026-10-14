"""
Regression tests for task ownership, role separation, and unassigned classification (Section 5).

Covers all 9 required regression scenarios:
1. A named assignee without explicit acceptance wording.
2. An internal assignee plus an external partner dependency.
3. A task performer different from the reviewer or approver.
4. A task with no identifiable assignee.
5. A named assignee with no deadline.
6. A blocker and its related follow-up task in the same conversation.
7. A task with a conditional escalation.
8. Relative deadlines when the meeting date is unknown.
9. A person mentioned in a transcript without being responsible for the task.
"""
from datetime import date
import unittest

from models.intermediate import UtteranceRole, ExtractedUtterance
from models.output import (
    ActionItem,
    Blocker,
    Evidence,
    ItemStatus,
    PublicTask,
    PublicUnresolvedItem,
    ResolvedResult,
)
from pipeline.mapper import map_to_public, parse_assignee_and_roles
from prompts import PROMPT_VERSION
from prompts.extraction_prompt import EXTRACTION_SYSTEM_PROMPT
from prompts.resolution_prompt import RESOLUTION_SYSTEM_PROMPT


class TestTaskOwnershipRegression(unittest.TestCase):
    def setUp(self):
        self.participants = ["Minh", "Lan", "Bình", "Tuấn", "Hương", "Mai"]

    def test_01_named_assignee_without_explicit_acceptance(self):
        """
        Scenario 1: Explicitly assigned person who never explicitly says 'Tôi nhận việc'
        must be recorded as assignee and NOT classified as unassigned.
        """
        a = ActionItem(
            item_id="A001",
            task="Tối ưu hoá database",
            assignee="Bình",
            assigned_by="Minh",
            assignee_confirmed=False,
            confirmation_utterance_id=None,
            deadline="Thứ Sáu",
            evidence=[Evidence(speaker="Minh", quote="Bình phụ trách tối ưu hoá database trước thứ Sáu.")],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a],
        )
        out = map_to_public(res)
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(out.tasks[0].assignee, "Bình")
        self.assertEqual(out.tasks[0].assigned_by, "Minh")
        self.assertEqual(len(out.unresolved), 0)

    def test_02_internal_assignee_plus_external_partner_dependency(self):
        """
        Scenario 2: Internal assignee + external partner dependency.
        The external partner must not be joined into assignee (e.g. 'Bình / Đối tác').
        """
        # Case 2A: Compound string from LLM
        a1 = ActionItem(
            item_id="A001",
            task="Tiếp tục liên hệ đối tác lấy tài khoản sandbox VNPay",
            assignee="Bình / Đối tác VNPay",
            assigned_by="Minh",
            evidence=[Evidence(speaker="Minh", quote="Bình tiếp tục liên hệ đối tác lấy tài khoản sandbox VNPay.")],
        )
        res1 = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a1],
        )
        out1 = map_to_public(res1)
        self.assertEqual(len(out1.tasks), 1)
        self.assertEqual(out1.tasks[0].assignee, "Bình")
        self.assertEqual(out1.tasks[0].external_dependency, "Đối tác VNPay")

        # Case 2B: Structured fields
        a2 = ActionItem(
            item_id="A002",
            task="Liên hệ đối tác lấy sandbox credentials",
            assignee="Bình",
            external_dependency="Đối tác VNPay",
            assigned_by="Minh",
            evidence=[],
        )
        res2 = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a2],
        )
        out2 = map_to_public(res2)
        self.assertEqual(len(out2.tasks), 1)
        self.assertEqual(out2.tasks[0].assignee, "Bình")
        self.assertEqual(out2.tasks[0].external_dependency, "Đối tác VNPay")

    def test_03_task_performer_different_from_reviewer_or_approver(self):
        """
        Scenario 3: Task performer different from reviewer or approver.
        'Tuấn gửi bản thiết kế QR để Mai duyệt' -> Assignee: Tuấn, Reviewer: Mai.
        """
        # Case 3A: Compound assignee
        a1 = ActionItem(
            item_id="A001",
            task="Hoàn thiện bản thiết kế QR để Mai duyệt",
            assignee="Tuấn / Mai duyệt",
            assigned_by="Minh",
            evidence=[],
        )
        res1 = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a1],
        )
        out1 = map_to_public(res1)
        self.assertEqual(len(out1.tasks), 1)
        self.assertEqual(out1.tasks[0].assignee, "Tuấn")
        self.assertEqual(out1.tasks[0].reviewer, "Mai")

        # Case 3B: Structured reviewer field
        a2 = ActionItem(
            item_id="A002",
            task="Hoàn thiện bản thiết kế QR",
            assignee="Tuấn",
            reviewer="Mai",
            evidence=[],
        )
        res2 = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a2],
        )
        out2 = map_to_public(res2)
        self.assertEqual(len(out2.tasks), 1)
        self.assertEqual(out2.tasks[0].assignee, "Tuấn")
        self.assertEqual(out2.tasks[0].reviewer, "Mai")

    def test_04_task_with_no_identifiable_assignee(self):
        """
        Scenario 4: Task with no identifiable assignee.
        Classified as unassigned (unconfirmed_task) with suggested_assignee = None.
        """
        a = ActionItem(
            item_id="A001",
            task="Cần liên hệ đối tác để hỏi tài khoản sandbox",
            assignee=None,
            assigned_by="Minh",
            evidence=[Evidence(speaker="Minh", quote="Cần liên hệ đối tác để hỏi tài khoản sandbox.")],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a],
        )
        out = map_to_public(res)
        self.assertEqual(len(out.tasks), 0)
        self.assertEqual(len(out.unresolved), 1)
        self.assertEqual(out.unresolved[0].kind, "unconfirmed_task")
        self.assertIsNone(out.unresolved[0].suggested_assignee)

    def test_05_named_assignee_with_no_deadline(self):
        """
        Scenario 5: Named assignee with no deadline.
        Must remain a confirmed task, NOT downgraded to unassigned.
        """
        a = ActionItem(
            item_id="A001",
            task="Cập nhật tài liệu API integration guide",
            assignee="Hương",
            deadline=None,
            evidence=[Evidence(speaker="Minh", quote="Hương cập nhật tài liệu API nhé.")],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a],
        )
        out = map_to_public(res)
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(out.tasks[0].assignee, "Hương")
        self.assertIsNone(out.tasks[0].deadline_raw)
        self.assertIsNone(out.tasks[0].deadline_iso)
        self.assertEqual(len(out.unresolved), 0)

    def test_06_blocker_and_followup_task_in_same_conversation(self):
        """
        Scenario 6: Blocker and its related follow-up task in the same conversation.
        Kept as distinct items (Issue vs Task) and not merged or duplicated.
        """
        b = Blocker(
            item_id="B001",
            issue="Đối tác VNPay chưa cấp tài khoản sandbox và API secret key",
            owner="Bình",
            status=ItemStatus.CONFIRMED,
            evidence=[Evidence(speaker="Lan", quote="Em cần tài khoản sandbox và API secret key mới nhất của VNPay.")],
        )
        a = ActionItem(
            item_id="A001",
            task="Tiếp tục liên hệ đối tác lấy tài khoản sandbox và cập nhật nhóm",
            assignee="Bình",
            assigned_by="Minh",
            dependencies=["B001"],
            evidence=[Evidence(speaker="Minh", quote="Bình tiếp tục liên hệ đối tác và cập nhật tình hình trong nhóm.")],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            blockers=[b],
            action_items=[a],
        )
        out = map_to_public(res)
        # Issues has the blocker
        self.assertEqual(len(out.issues), 1)
        self.assertEqual(out.issues[0].owner, "Bình")
        self.assertIn("chưa cấp tài khoản sandbox", out.issues[0].content)

        # Tasks has the follow-up action
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(out.tasks[0].assignee, "Bình")
        self.assertIn("Tiếp tục liên hệ đối tác", out.tasks[0].title)

    def test_07_task_with_conditional_escalation(self):
        """
        Scenario 7: Task with conditional escalation.
        Preserves escalation recipient (Minh) and condition context.
        """
        a = ActionItem(
            item_id="A001",
            task="Liên hệ đối tác lấy sandbox credentials",
            assignee="Bình",
            assigned_by="Minh",
            escalation="Minh",
            external_dependency="Đối tác VNPay",
            evidence=[Evidence(speaker="Minh", quote="Nếu chưa có phản hồi, báo lại anh để escalate.")],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a],
        )
        out = map_to_public(res)
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(out.tasks[0].assignee, "Bình")
        self.assertEqual(out.tasks[0].escalation, "Minh")
        self.assertEqual(out.tasks[0].external_dependency, "Đối tác VNPay")

    def test_08_relative_deadlines_when_meeting_date_unknown(self):
        """
        Scenario 8: Relative deadlines when meeting date is unknown (fallback_today).
        Raw text 'trước 15:00 ngày mai' is preserved in deadline_raw,
        while deadline_iso is None to avoid inventing an arbitrary calendar date.
        """
        a = ActionItem(
            item_id="A001",
            task="Cập nhật tình hình nhóm",
            assignee="Bình",
            deadline="trước 15:00 ngày mai",
            evidence=[],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a],
        )
        # Without explicit meeting date input or transcript date preamble
        out = map_to_public(res, meeting_date_input=None, transcript="[09:00] Minh: Bắt đầu họp")
        self.assertEqual(out.meta.meeting_date_source, "fallback_today")
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(out.tasks[0].deadline_raw, "trước 15:00 ngày mai")
        self.assertIsNone(out.tasks[0].deadline_iso)

        # Contrast with known meeting date
        out_known = map_to_public(res, meeting_date_input="2026-10-14")
        self.assertEqual(out_known.meta.meeting_date_source, "user")
        self.assertEqual(out_known.tasks[0].deadline_iso, "2026-10-15")

    def test_09_person_mentioned_without_being_responsible(self):
        """
        Scenario 9: A person mentioned in a transcript without being responsible.
        'Mai nhắc Tuấn gửi báo cáo cho Lan kiểm tra' -> Tuấn is assignee, not Mai or Lan.
        """
        raw = "Tuấn gửi Lan kiểm tra"
        assignee, ext, rev, collab = parse_assignee_and_roles(raw, self.participants)
        self.assertEqual(assignee, "Tuấn")
        self.assertEqual(rev, "Lan")

        # ActionItem where assigned_by is Mai, reviewer is Lan, assignee is Tuấn
        a = ActionItem(
            item_id="A001",
            task="Gửi báo cáo cho Lan kiểm tra",
            assignee="Tuấn",
            assigned_by="Mai",
            reviewer="Lan",
            evidence=[Evidence(speaker="Mai", quote="Tuấn nhớ gửi báo cáo cho Lan kiểm tra nhé.")],
        )
        res = ResolvedResult(
            meeting_summary="Summary",
            participants=self.participants,
            action_items=[a],
        )
        out = map_to_public(res)
        self.assertEqual(len(out.tasks), 1)
        self.assertEqual(out.tasks[0].assignee, "Tuấn")
        self.assertEqual(out.tasks[0].assigned_by, "Mai")
        self.assertEqual(out.tasks[0].reviewer, "Lan")

    def test_utterance_roles_and_normalization(self):
        self.assertEqual(UtteranceRole.ACCEPTS.value, "accepts")
        self.assertEqual(UtteranceRole.DECLINES.value, "declines")

        u1 = ExtractedUtterance(
            id="U001",
            speaker="Lan",
            quote="Ok anh, em làm",
            topic="Setup DB",
            type="action_item",
            role="accepts",
        )
        self.assertEqual(u1.role, UtteranceRole.ACCEPTS)

    def test_prompt_version_and_acceptance_guidelines(self):
        self.assertEqual(PROMPT_VERSION, "2.3.0")

        self.assertIn('"accepts"', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"declines"', EXTRACTION_SYSTEM_PROMPT)

        self.assertIn("TASK OWNERSHIP & ROLE SEPARATION", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("assignee_confirmed", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("external_dependency", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("reviewer", RESOLUTION_SYSTEM_PROMPT)

    def test_task_acceptance_guard_in_mapper(self):
        participants = ["Tuấn", "Lan", "Hương"]
        transcript = "[U001] [09:00] Tuấn: Lan làm database trước thứ 6 nhé.\n[U002] [09:01] Lan: Ok anh, em làm."

        # Case 1: Valid confirmation
        a1 = ActionItem(
            item_id="A001",
            task="Setup database",
            assignee="Lan",
            assigned_by="Tuấn",
            assignee_confirmed=True,
            confirmation_utterance_id="U002",
        )
        res1 = ResolvedResult(
            meeting_summary="Summary",
            participants=participants,
            action_items=[a1],
        )
        out1 = map_to_public(res1, transcript=transcript)
        self.assertEqual(len(out1.tasks), 1)
        self.assertEqual(out1.tasks[0].assignee, "Lan")
        self.assertEqual(out1.tasks[0].assigned_by, "Tuấn")
        self.assertEqual(len(out1.unresolved), 0)

        # Case 2: Named assignee without verbal confirmation (remains assigned task)
        a2 = ActionItem(
            item_id="A002",
            task="Setup database",
            assignee="Lan",
            assigned_by="Tuấn",
            assignee_confirmed=False,
            confirmation_utterance_id=None,
        )
        res2 = ResolvedResult(
            meeting_summary="Summary",
            participants=participants,
            action_items=[a2],
        )
        out2 = map_to_public(res2, transcript=transcript)
        self.assertEqual(len(out2.tasks), 1)
        self.assertEqual(out2.tasks[0].assignee, "Lan")
        self.assertEqual(len(out2.unresolved), 0)

        # Case 3: Third person agrees instead of assignee (remains assigned to Lan)
        a3 = ActionItem(
            item_id="A003",
            task="Setup database",
            assignee="Lan",
            assigned_by="Tuấn",
            assignee_confirmed=True,
            confirmation_utterance_id="U001",  # Spoken by Tuấn, not Lan!
        )
        res3 = ResolvedResult(
            meeting_summary="Summary",
            participants=participants,
            action_items=[a3],
        )
        out3 = map_to_public(res3, transcript=transcript)
        self.assertEqual(len(out3.tasks), 1)
        self.assertEqual(out3.tasks[0].assignee, "Lan")
        self.assertEqual(len(out3.unresolved), 0)

        # Case 4: No identifiable assignee -> Unresolved (unconfirmed_task)
        a4 = ActionItem(
            item_id="A004",
            task="Cần liên hệ đối tác kiểm tra sandbox",
            assignee=None,
            assigned_by="Tuấn",
        )
        res4 = ResolvedResult(
            meeting_summary="Summary",
            participants=participants,
            action_items=[a4],
        )
        out4 = map_to_public(res4, transcript=transcript)
        self.assertEqual(len(out4.tasks), 0)
        self.assertEqual(len(out4.unresolved), 1)
        self.assertEqual(out4.unresolved[0].kind, "unconfirmed_task")


if __name__ == "__main__":
    unittest.main()
