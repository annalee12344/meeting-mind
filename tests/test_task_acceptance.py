"""
Unit tests for Section 3: Task acceptance (assignee_confirmed) & prompts.
"""
import unittest

from models.intermediate import UtteranceRole, ExtractedUtterance
from models.output import ActionItem, ResolvedResult
from pipeline.mapper import map_to_public, normalize_person_name
from prompts import PROMPT_VERSION
from prompts.extraction_prompt import EXTRACTION_SYSTEM_PROMPT
from prompts.resolution_prompt import RESOLUTION_SYSTEM_PROMPT


class TestTaskAcceptance(unittest.TestCase):
    def test_utterance_roles_and_normalization(self):
        self.assertEqual(UtteranceRole.ACCEPTS.value, "accepts")
        self.assertEqual(UtteranceRole.DECLINES.value, "declines")

        # Test normalization in ExtractedUtterance
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
        self.assertEqual(PROMPT_VERSION, "2.1.0")

        # Verify extraction prompt contains accepts and declines
        self.assertIn('"accepts"', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"declines"', EXTRACTION_SYSTEM_PROMPT)

        # Verify resolution prompt contains task acceptance rules and examples
        self.assertIn("TASK ACCEPTANCE & ASSIGNEE_CONFIRMED", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("Lan, setup the database by Friday", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("Ok anh, em làm", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("Mình sẽ làm phần đó", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("assignee_confirmed", RESOLUTION_SYSTEM_PROMPT)
        self.assertIn("confirmation_utterance_id", RESOLUTION_SYSTEM_PROMPT)

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

        # Case 2: Silence / No confirmation
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
        self.assertEqual(len(out2.tasks), 0)
        self.assertEqual(len(out2.unresolved), 1)
        self.assertEqual(out2.unresolved[0].kind, "unconfirmed_task")
        self.assertEqual(out2.unresolved[0].suggested_assignee, "Lan")

        # Case 3: Third person agrees instead of assignee (Tuấn assigned Lan, but Tuấn spoke U001)
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
        self.assertEqual(len(out3.tasks), 0)
        self.assertEqual(len(out3.unresolved), 1)
        self.assertEqual(out3.unresolved[0].kind, "unconfirmed_task")
        self.assertEqual(out3.unresolved[0].suggested_assignee, "Lan")


if __name__ == "__main__":
    unittest.main()
