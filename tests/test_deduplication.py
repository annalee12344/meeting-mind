"""
Regression tests for Action Item Deduplication (Section 4).

Covers all 8 required scenarios:
1. Deduplication of identical tasks with different deadline formats.
2. Deduplication of tasks with slightly different phrasing for the same deliverable.
3. Tasks assigned then confirmed by the assignee in a later turn (single task produced, multi-turn evidence).
4. Distinct tasks by the same assignee that must NOT be merged.
5. Tasks by different assignees with similar deliverable descriptions that must NOT be merged.
6. Tasks with no deadline merged with a later mention that includes a deadline.
7. Verification that all five homepage samples produce zero duplicate action items.
8. Verification that total action item counts match ground truth for each sample.
"""
import json
from pathlib import Path
import unittest

import config
from models.output import (
    ActionItem,
    Evidence,
    PublicTask,
    ResolvedResult,
)
from pipeline.mapper import (
    are_public_tasks_duplicate,
    deduplicate_public_tasks,
    map_to_public,
    merge_two_public_tasks,
)
from pipeline.resolver import (
    are_action_items_duplicate,
    deduplicate_action_items,
    merge_two_action_items,
)
from server import SAMPLE_CATALOG, load_sample_expected


class TestTaskDeduplicationRegression(unittest.TestCase):
    def setUp(self):
        self.participants = ["Quân", "Đạt", "Mai", "Thảo", "Tuấn", "Lan", "Hương"]

    def test_01_identical_tasks_different_deadline_formats(self):
        """
        Scenario 1: Deduplication of identical tasks with different deadline formats.
        Preserves canonical parsed deadline (ISO & formatted raw) while merging.
        """
        t1 = PublicTask(
            id="task-1",
            source_ref="A001",
            title="Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
            assignee="Đạt",
            deadline_raw="10/05",
            deadline_iso=None,
            evidence=[Evidence(speaker="Đạt", quote="deadline 10/5", utterance_id="U002")],
        )
        t2 = PublicTask(
            id="task-2",
            source_ref="A001",
            title="Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
            assignee="Đạt",
            deadline_raw="ngày 10/05/2027",
            deadline_iso="2027-05-10",
            evidence=[Evidence(speaker="Quân", quote="hoàn thành trước ngày 10 tháng 5", utterance_id="U001")],
        )

        self.assertTrue(are_public_tasks_duplicate(t1, t2))
        deduped = deduplicate_public_tasks([t1, t2])
        self.assertEqual(len(deduped), 1)
        merged = deduped[0]
        self.assertEqual(merged.assignee, "Đạt")
        self.assertEqual(merged.deadline_iso, "2027-05-10")
        self.assertEqual(merged.deadline_raw, "ngày 10/05/2027")
        self.assertEqual(len(merged.evidence), 2)

    def test_02_paraphrased_same_deliverable(self):
        """
        Scenario 2: Deduplication of tasks with slightly different phrasing for the same deliverable.
        Example: 'Lập tài liệu kiến trúc kỹ thuật...' vs 'làm spec kiến trúc và so sánh đối tác thanh toán'.
        """
        t1 = PublicTask(
            id="task-1",
            source_ref="A001",
            title="Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
            assignee="Đạt",
            deadline_raw="10 tháng 5",
            evidence=[Evidence(speaker="Quân", quote="Đạt chuẩn bị tài liệu kiến trúc...", utterance_id="U001")],
        )
        t2 = PublicTask(
            id="task-2",
            source_ref="A002",
            title="làm spec kiến trúc và so sánh đối tác thanh toán",
            assignee="Đạt",
            deadline_raw="10/5",
            evidence=[Evidence(speaker="Đạt", quote="em nhận task làm spec kiến trúc...", utterance_id="U002")],
        )

        self.assertTrue(are_public_tasks_duplicate(t1, t2))
        deduped = deduplicate_public_tasks([t1, t2])
        self.assertEqual(len(deduped), 1)
        # Should retain the more descriptive title
        self.assertEqual(
            deduped[0].title,
            "Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
        )
        self.assertEqual(len(deduped[0].evidence), 2)

    def test_03_assigned_then_confirmed_multiturn(self):
        """
        Scenario 3: Tasks assigned then confirmed by the assignee in a later turn.
        Produces a single ActionItem combining multi-turn evidence.
        """
        a1 = ActionItem(
            item_id="A001",
            task="Chuẩn bị tài liệu kiến trúc kỹ thuật và lập bảng so sánh chi phí các đối tác cổng thanh toán",
            assignee="Đạt",
            assigned_by="Quân",
            deadline="10 tháng 5",
            assignee_confirmed=False,
            evidence=[
                Evidence(
                    speaker="Quân",
                    quote="Đạt chuẩn bị tài liệu kiến trúc kỹ thuật và lập bảng so sánh chi phí các đối tác cổng thanh toán, hoàn thành trước ngày 10 tháng 5 nhé.",
                    utterance_id="U033",
                )
            ],
        )
        a2 = ActionItem(
            item_id="A002",
            task="Làm spec kiến trúc và so sánh đối tác thanh toán",
            assignee="Đạt",
            deadline="10/5",
            assignee_confirmed=True,
            confirmation_utterance_id="U034",
            evidence=[
                Evidence(
                    speaker="Đạt",
                    quote="Vâng, em nhận task làm spec kiến trúc và so sánh đối tác thanh toán, deadline 10/5.",
                    utterance_id="U034",
                )
            ],
        )

        self.assertTrue(are_action_items_duplicate(a1, a2))
        deduped_actions = deduplicate_action_items([a1, a2])
        self.assertEqual(len(deduped_actions), 1)
        merged = deduped_actions[0]
        self.assertEqual(merged.assignee, "Đạt")
        self.assertEqual(merged.assigned_by, "Quân")
        self.assertTrue(merged.assignee_confirmed)
        self.assertEqual(merged.confirmation_utterance_id, "U034")
        self.assertEqual(len(merged.evidence), 2)
        uids = {ev.utterance_id for ev in merged.evidence}
        self.assertEqual(uids, {"U033", "U034"})

    def test_04_distinct_tasks_same_assignee_not_merged(self):
        """
        Scenario 4: Distinct tasks by the same assignee that must NOT be merged.
        Example: 'Lập tài liệu kiến trúc kỹ thuật' and 'Gửi tài liệu cho đối tác review'.
        """
        t1 = PublicTask(
            id="task-1",
            title="Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
            assignee="Đạt",
            deadline_raw="10/05",
            deadline_iso="2027-05-10",
        )
        t2 = PublicTask(
            id="task-2",
            title="Gửi tài liệu cho đối tác review",
            assignee="Đạt",
            deadline_raw="12/05",
            deadline_iso="2027-05-12",
        )

        self.assertFalse(are_public_tasks_duplicate(t1, t2))
        deduped = deduplicate_public_tasks([t1, t2])
        self.assertEqual(len(deduped), 2)

    def test_05_different_assignees_similar_deliverables_not_merged(self):
        """
        Scenario 5: Tasks by different assignees with similar deliverable descriptions must NOT be merged.
        Example: Đạt vs Mai assigned the same deliverable template.
        """
        t1 = PublicTask(
            id="task-1",
            title="Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
            assignee="Đạt",
            deadline_raw="10/05",
            deadline_iso="2027-05-10",
        )
        t2 = PublicTask(
            id="task-2",
            title="Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán",
            assignee="Mai",
            deadline_raw="10/05",
            deadline_iso="2027-05-10",
        )

        self.assertFalse(are_public_tasks_duplicate(t1, t2))
        deduped = deduplicate_public_tasks([t1, t2])
        self.assertEqual(len(deduped), 2)
        assignees = {t.assignee for t in deduped}
        self.assertEqual(assignees, {"Đạt", "Mai"})

    def test_06_no_deadline_merged_with_deadline(self):
        """
        Scenario 6: Tasks with no deadline merged with a later mention that includes a deadline.
        The merged task preserves the specific deadline.
        """
        t1 = PublicTask(
            id="task-1",
            title="Cập nhật lại timeline kế hoạch truyền thông marketing cho ngày ra mắt 15 tháng 7",
            assignee="Mai",
            deadline_raw=None,
            deadline_iso=None,
            evidence=[Evidence(speaker="Quân", quote="Mai cập nhật timeline", utterance_id="U005")],
        )
        t2 = PublicTask(
            id="task-2",
            title="Cập nhật lại timeline kế hoạch truyền thông marketing cho ngày ra mắt 15 tháng 7",
            assignee="Mai",
            deadline_raw="12/05",
            deadline_iso="2027-05-12",
            evidence=[Evidence(speaker="Mai", quote="hạn chót 12/5 em gửi anh", utterance_id="U006")],
        )

        self.assertTrue(are_public_tasks_duplicate(t1, t2))
        deduped = deduplicate_public_tasks([t1, t2])
        self.assertEqual(len(deduped), 1)
        merged = deduped[0]
        self.assertEqual(merged.deadline_raw, "12/05")
        self.assertEqual(merged.deadline_iso, "2027-05-12")
        self.assertEqual(len(merged.evidence), 2)

    def test_07_all_five_homepage_samples_zero_duplicates(self):
        """
        Scenario 7: Verification that all five homepage samples produce zero duplicate action items.
        """
        for sample in SAMPLE_CATALOG:
            with self.subTest(sample=sample["id"]):
                resolved = load_sample_expected(sample)
                tx_path = config.TRANSCRIPTS_DIR / sample["filename"]
                tx_text = tx_path.read_text(encoding="utf-8") if tx_path.exists() else None

                public_out = map_to_public(resolved, transcript=tx_text)
                tasks = public_out.tasks

                # Check pairwise: no two tasks should be duplicates
                for i in range(len(tasks)):
                    for j in range(i + 1, len(tasks)):
                        is_dup = are_public_tasks_duplicate(tasks[i], tasks[j])
                        self.assertFalse(
                            is_dup,
                            f"Sample '{sample['id']}' produced duplicate tasks: '{tasks[i].title}' and '{tasks[j].title}'",
                        )

    def test_08_total_action_item_counts_match_ground_truth(self):
        """
        Scenario 8: Verification that total action item counts match ground truth for each sample.
        Ground truth action_items count from expected JSON:
        - test_01_happy_path: 3
        - test_02_decision_change: 2
        - test_03_chaotic: 1
        - test_04_implicit: 2
        - test_05_sarcasm_fail: 1
        """
        expected_counts = {
            "test_01_happy_path": 3,
            "test_02_decision_change": 2,
            "test_03_chaotic": 1,
            "test_04_implicit": 2,
            "test_05_sarcasm_fail": 1,
        }

        for sample_id, expected_count in expected_counts.items():
            with self.subTest(sample_id=sample_id):
                exp_file = config.EXPECTED_DIR / f"{sample_id.split('_')[0]}_{sample_id.split('_')[1]}_expected.json"
                if not exp_file.exists():
                    matches = list(config.EXPECTED_DIR.glob(f"{sample_id[:7]}*.json"))
                    self.assertTrue(matches, f"Missing expected file for {sample_id}")
                    exp_file = matches[0]

                data = json.loads(exp_file.read_text(encoding="utf-8"))
                actual_action_items = data.get("action_items", [])
                self.assertEqual(
                    len(actual_action_items),
                    expected_count,
                    f"Sample '{sample_id}' action_items ground truth count mismatch: {len(actual_action_items)} != {expected_count}",
                )


if __name__ == "__main__":
    unittest.main()
