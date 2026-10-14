"""
Pure Merge Function for Meeting Mind Data Layers.

Merges the immutable AI analysis layer (MeetingOutput) with the mutable User Overlay (MeetingOverlay)
into a unified View Model (MeetingViewModel) consumed by UI components and export tools.

Rules:
1. Re-analysis idempotence: AI results can be recomputed, upgraded, or re-run without wiping
   user modifications, notes, or manual items.
2. Deleted items (tasks, unresolved, issues) marked in overlay are omitted from view.
3. Converted unconfirmed tasks (status="converted") are moved from Unresolved into Tasks.
4. Manually added user tasks (source="manual") are appended to Tasks.
5. Task status changes (done/open), edits (title, assignee, deadline) are overlaid on AI tasks.
6. Issue status changes (open/resolved) and user notes (IssueNote) are overlaid on Issues.
"""
from typing import Optional

from models.output import MeetingOutput, generate_uuid
from models.overlay import (
    MeetingOverlay,
    MeetingViewModel,
    ViewIssue,
    ViewTask,
    ViewUnresolvedItem,
)


def merge_meeting_view(
    ai_output: MeetingOutput,
    overlay: Optional[MeetingOverlay] = None,
) -> MeetingViewModel:
    """
    Pure merge function combining AI layer + User overlay -> MeetingViewModel.

    Args:
        ai_output: Immutable analysis output from pipeline or sample cache.
        overlay: Optional user overlay containing edits, deletions, manual tasks, and notes.

    Returns:
        MeetingViewModel with all user modifications applied over AI results.
    """
    meeting_id = (
        (overlay.meeting_id if overlay and overlay.meeting_id else None)
        or ai_output.meta.transcript_hash
        or (ai_output.decisions[0].id if ai_output.decisions else None)
        or generate_uuid()
    )

    effective_overlay = overlay or MeetingOverlay(meeting_id=meeting_id)
    if not effective_overlay.meeting_id:
        effective_overlay.meeting_id = meeting_id

    # Sets for fast O(1) deletion checks
    deleted_tasks = set(effective_overlay.deleted_task_ids)
    deleted_unresolved = set(effective_overlay.deleted_unresolved_ids)
    deleted_issues = set(effective_overlay.deleted_issue_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Merge Decisions (AI layer is canonical, decisions are read-only)
    # ─────────────────────────────────────────────────────────────────────────
    decisions = list(ai_output.decisions)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Merge Tasks
    # ─────────────────────────────────────────────────────────────────────────
    merged_tasks: list[ViewTask] = []

    # Process AI-extracted tasks
    for ai_task in ai_output.tasks:
        if ai_task.id in deleted_tasks:
            continue

        task_overlay = effective_overlay.tasks.get(ai_task.id)

        title = task_overlay.title if (task_overlay and task_overlay.title is not None) else ai_task.title
        assignee = task_overlay.assignee if (task_overlay and task_overlay.assignee is not None) else ai_task.assignee
        deadline_raw = (
            task_overlay.deadline_raw
            if (task_overlay and task_overlay.deadline_raw is not None)
            else ai_task.deadline_raw
        )
        deadline_iso = (
            task_overlay.deadline_iso
            if (task_overlay and task_overlay.deadline_iso is not None)
            else ai_task.deadline_iso
        )
        status = task_overlay.status if (task_overlay and task_overlay.status is not None) else "open"
        completed_at = task_overlay.completed_at if task_overlay else None

        merged_tasks.append(
            ViewTask(
                id=ai_task.id,
                meeting_id=meeting_id,
                source_ref=ai_task.source_ref,
                title=title,
                assignee=assignee,
                assigned_by=ai_task.assigned_by,
                requested_by=ai_task.requested_by,
                deadline_raw=deadline_raw,
                deadline_iso=deadline_iso,
                status=status,
                source=ai_task.source,
                evidence=ai_task.evidence,
                needs_review=ai_task.needs_review,
                completed_at=completed_at,
            )
        )

    # Append manual and converted tasks from overlay
    for manual_task in effective_overlay.manual_tasks:
        if manual_task.id in deleted_tasks:
            continue

        # Check if manual task itself has an overlay edit
        task_overlay = effective_overlay.tasks.get(manual_task.id)
        if task_overlay:
            title = task_overlay.title or manual_task.title
            assignee = task_overlay.assignee if task_overlay.assignee is not None else manual_task.assignee
            deadline_raw = (
                task_overlay.deadline_raw if task_overlay.deadline_raw is not None else manual_task.deadline_raw
            )
            deadline_iso = (
                task_overlay.deadline_iso if task_overlay.deadline_iso is not None else manual_task.deadline_iso
            )
            status = task_overlay.status or manual_task.status
            completed_at = task_overlay.completed_at or manual_task.completed_at
            merged_tasks.append(
                manual_task.model_copy(
                    update={
                        "title": title,
                        "assignee": assignee,
                        "deadline_raw": deadline_raw,
                        "deadline_iso": deadline_iso,
                        "status": status,
                        "completed_at": completed_at,
                    }
                )
            )
        else:
            merged_tasks.append(manual_task)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Merge Unresolved Items
    # ─────────────────────────────────────────────────────────────────────────
    merged_unresolved: list[ViewUnresolvedItem] = []

    for ai_unresolved in ai_output.unresolved:
        if ai_unresolved.id in deleted_unresolved:
            continue

        u_overlay = effective_overlay.unresolved.get(ai_unresolved.id)

        # If converted to task, do not display in Unresolved
        if u_overlay and u_overlay.status == "converted":
            continue

        suggested_assignee = (
            u_overlay.suggested_assignee
            if (u_overlay and u_overlay.suggested_assignee is not None)
            else ai_unresolved.suggested_assignee
        )
        suggested_deadline_raw = (
            u_overlay.suggested_deadline_raw
            if (u_overlay and u_overlay.suggested_deadline_raw is not None)
            else ai_unresolved.suggested_deadline_raw
        )
        suggested_deadline_iso = (
            u_overlay.suggested_deadline_iso
            if (u_overlay and u_overlay.suggested_deadline_iso is not None)
            else ai_unresolved.suggested_deadline_iso
        )

        merged_unresolved.append(
            ViewUnresolvedItem(
                id=ai_unresolved.id,
                meeting_id=meeting_id,
                source_ref=ai_unresolved.source_ref,
                kind=ai_unresolved.kind,
                content=ai_unresolved.content,
                reason_unresolved=ai_unresolved.reason_unresolved,
                suggested_assignee=suggested_assignee,
                suggested_deadline_raw=suggested_deadline_raw,
                suggested_deadline_iso=suggested_deadline_iso,
                status="open",
                evidence=ai_unresolved.evidence,
                needs_review=ai_unresolved.needs_review,
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Merge Issues and Notes
    # ─────────────────────────────────────────────────────────────────────────
    merged_issues: list[ViewIssue] = []

    for ai_issue in ai_output.issues:
        if ai_issue.id in deleted_issues:
            continue

        i_overlay = effective_overlay.issues.get(ai_issue.id)
        issue_status = i_overlay.status if (i_overlay and i_overlay.status is not None) else ai_issue.status

        # Collect notes for this issue
        issue_notes = [note for note in effective_overlay.issue_notes if note.issue_id == ai_issue.id]

        merged_issues.append(
            ViewIssue(
                id=ai_issue.id,
                meeting_id=meeting_id,
                source_ref=ai_issue.source_ref,
                content=ai_issue.content,
                owner=ai_issue.owner,
                status=issue_status,
                evidence=ai_issue.evidence,
                notes=issue_notes,
                needs_review=ai_issue.needs_review,
            )
        )

    return MeetingViewModel(
        meeting_id=meeting_id,
        summary=ai_output.summary,
        participants=ai_output.participants,
        decisions=decisions,
        tasks=merged_tasks,
        unresolved=merged_unresolved,
        issues=merged_issues,
        meta=ai_output.meta,
        overlay=effective_overlay,
    )
