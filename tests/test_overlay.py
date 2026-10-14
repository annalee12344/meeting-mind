"""
Unit tests for the Pure Merge Function (pipeline/overlay.py).

Tests:
1. Task editing: title, assignee, deadline, and marking done.
2. Task deletion: removing tasks via deleted_task_ids.
3. Manual tasks: appending user-created tasks.
4. Unresolved conversion: converting unconfirmed task into a task.
5. Issue status and notes: attaching user notes and resolving issues.
6. Re-analysis idempotence: updating the AI layer does not erase overlay edits.
"""
import unittest

from models.output import (
    Evidence,
    IssueNote,
    MeetingOutput,
    PublicDecision,
    PublicIssue,
    PublicMeta,
    PublicTask,
    PublicUnresolvedItem,
)
from models.overlay import (
    IssueOverlay,
    MeetingOverlay,
    TaskOverlay,
    UnresolvedOverlay,
    ViewTask,
)
from pipeline.overlay import merge_meeting_view


def build_sample_ai_output() -> MeetingOutput:
    d = PublicDecision(
        id="dec-1",
        topic="Database Choice",
        content="Use PostgreSQL for primary store",
        proposed_by="Minh",
        confirmed_by="Minh",
    )
    t1 = PublicTask(
        id="task-1",
        title="Setup database schema",
        assignee="Lan",
        deadline_raw="thứ Sáu",
        deadline_iso="2026-10-18",
        source="ai",
    )
    t2 = PublicTask(
        id="task-2",
        title="Write API documentation",
        assignee="Tuấn",
        deadline_raw="thứ Hai",
        deadline_iso="2026-10-21",
        source="ai",
    )
    u = PublicUnresolvedItem(
        id="unres-1",
        kind="unconfirmed_task",
        content="Setup Redis cache cluster",
        suggested_assignee="Hương",
    )
    iss = PublicIssue(
        id="issue-1",
        content="VPN access blocked for remote developers",
        status="open",
    )
    return MeetingOutput(
        meeting_summary="Cuộc họp sprint planning mẫu.",
        participants=["Minh", "Lan", "Tuấn", "Hương"],
        decisions=[d],
        tasks=[t1, t2],
        unresolved=[u],
        issues=[iss],
        meta=PublicMeta(
            meeting_date="2026-10-14",
            transcript_hash="hash_12345",
        ),
    )


class TestOverlayMergeFunction(unittest.TestCase):
    """Test merge_meeting_view pure function."""

    def test_default_merge_without_overlay(self):
        ai = build_sample_ai_output()
        view = merge_meeting_view(ai)

        self.assertEqual(len(view.decisions), 1)
        self.assertEqual(len(view.tasks), 2)
        self.assertEqual(len(view.unresolved), 1)
        self.assertEqual(len(view.issues), 1)
        self.assertEqual(view.tasks[0].status, "open")
        self.assertEqual(view.tasks[0].title, "Setup database schema")

    def test_task_edit_and_mark_done(self):
        ai = build_sample_ai_output()
        overlay = MeetingOverlay(
            meeting_id="meeting-abc",
            tasks={
                "task-1": TaskOverlay(
                    assignee="Hương (Lead QA)",
                    deadline_raw="thứ Bảy",
                    deadline_iso="2026-10-19",
                    status="done",
                    completed_at="2026-10-15T10:00:00Z",
                )
            },
        )
        view = merge_meeting_view(ai, overlay)

        t1 = next(t for t in view.tasks if t.id == "task-1")
        self.assertEqual(t1.assignee, "Hương (Lead QA)")
        self.assertEqual(t1.deadline_iso, "2026-10-19")
        self.assertEqual(t1.status, "done")
        self.assertEqual(t1.completed_at, "2026-10-15T10:00:00Z")

        # task-2 unchanged
        t2 = next(t for t in view.tasks if t.id == "task-2")
        self.assertEqual(t2.assignee, "Tuấn")
        self.assertEqual(t2.status, "open")

    def test_task_deletion(self):
        ai = build_sample_ai_output()
        overlay = MeetingOverlay(
            meeting_id="meeting-abc",
            deleted_task_ids=["task-1"],
        )
        view = merge_meeting_view(ai, overlay)

        task_ids = [t.id for t in view.tasks]
        self.assertNotIn("task-1", task_ids)
        self.assertIn("task-2", task_ids)

    def test_manual_task_addition(self):
        ai = build_sample_ai_output()
        manual_task = ViewTask(
            id="manual-task-99",
            meeting_id="meeting-abc",
            title="Tạo Jira ticket cho Sprint 24",
            assignee="Minh",
            source="manual",
            status="open",
        )
        overlay = MeetingOverlay(
            meeting_id="meeting-abc",
            manual_tasks=[manual_task],
        )
        view = merge_meeting_view(ai, overlay)

        self.assertEqual(len(view.tasks), 3)
        self.assertTrue(any(t.id == "manual-task-99" and t.source == "manual" for t in view.tasks))

    def test_unresolved_conversion_to_task(self):
        ai = build_sample_ai_output()
        # Converting unres-1 into a task
        converted_task = ViewTask(
            id="converted-task-1",
            meeting_id="meeting-abc",
            source_ref="unres-1",
            title="Setup Redis cache cluster",
            assignee="Hương",
            source="from_unresolved",
            status="open",
        )
        overlay = MeetingOverlay(
            meeting_id="meeting-abc",
            unresolved={
                "unres-1": UnresolvedOverlay(
                    status="converted",
                    converted_to_task_id="converted-task-1",
                )
            },
            manual_tasks=[converted_task],
        )
        view = merge_meeting_view(ai, overlay)

        # Unresolved item unres-1 must be omitted from Unresolved list
        self.assertEqual(len(view.unresolved), 0)
        # And appears in Tasks as source='from_unresolved'
        self.assertTrue(any(t.id == "converted-task-1" and t.source == "from_unresolved" for t in view.tasks))

    def test_issue_status_and_notes(self):
        ai = build_sample_ai_output()
        note = IssueNote(
            id="note-1",
            issue_id="issue-1",
            author_id="user_minh",
            author_name="Minh",
            content="Đã gửi ticket cho bên hạ tầng mạng xử lý.",
        )
        overlay = MeetingOverlay(
            meeting_id="meeting-abc",
            issues={"issue-1": IssueOverlay(status="resolved")},
            issue_notes=[note],
        )
        view = merge_meeting_view(ai, overlay)

        iss = view.issues[0]
        self.assertEqual(iss.status, "resolved")
        self.assertEqual(len(iss.notes), 1)
        self.assertEqual(iss.notes[0].content, "Đã gửi ticket cho bên hạ tầng mạng xử lý.")

    def test_reanalysis_idempotence(self):
        """Re-analysis generates updated AI output, but existing overlay is preserved."""
        original_ai = build_sample_ai_output()
        overlay = MeetingOverlay(
            meeting_id="meeting-abc",
            tasks={
                "task-1": TaskOverlay(
                    assignee="Lan (Lead Dev)",
                    status="done",
                )
            },
            deleted_task_ids=["task-2"],
        )

        view_1 = merge_meeting_view(original_ai, overlay)
        self.assertEqual(len(view_1.tasks), 1)
        self.assertEqual(view_1.tasks[0].assignee, "Lan (Lead Dev)")
        self.assertEqual(view_1.tasks[0].status, "done")

        # Simulate re-analysis with upgraded prompt / new summary / new decisions
        reanalyzed_ai = original_ai.model_copy(
            update={
                "summary": "Tóm tắt cuộc họp được AI cập nhật tốt hơn nhiều.",
            }
        )

        view_2 = merge_meeting_view(reanalyzed_ai, overlay)
        # Summary updated by AI
        self.assertEqual(view_2.summary, "Tóm tắt cuộc họp được AI cập nhật tốt hơn nhiều.")
        # User overlay edits remain intact!
        self.assertEqual(len(view_2.tasks), 1)
        self.assertEqual(view_2.tasks[0].id, "task-1")
        self.assertEqual(view_2.tasks[0].assignee, "Lan (Lead Dev)")
        self.assertEqual(view_2.tasks[0].status, "done")


if __name__ == "__main__":
    unittest.main()
