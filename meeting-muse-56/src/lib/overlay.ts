/**
 * Pure Merge Function and Overlay Mutators for Meeting Mind.
 * 
 * Merges the immutable AI analysis layer (MeetingOutput) with the mutable User Overlay (MeetingOverlay)
 * into a unified View Model (MeetingViewModel) consumed by UI components and export tools.
 * 
 * Rules:
 * 1. Re-analysis idempotence: AI results can be recomputed, upgraded, or re-run without wiping
 *    user modifications, notes, or manual items.
 * 2. Deleted items (tasks, unresolved, issues) marked in overlay are omitted from view.
 * 3. Converted unconfirmed tasks (status="converted") are moved from Unresolved into Tasks.
 * 4. Manually added user tasks (source="manual") are appended to Tasks.
 * 5. Task status changes (done/open), edits (title, assignee, deadline) are overlaid on AI tasks.
 * 6. Issue status changes (open/resolved) and user notes (IssueNote) are overlaid on Issues.
 */

import type {
  Evidence,
  IssueNote,
  MeetingOutput,
  MeetingOverlay,
  MeetingViewModel,
  PublicDecision,
  PublicTask,
  PublicUnresolvedItem,
  PublicIssue,
  TaskOverlay,
  UnresolvedOverlay,
  IssueOverlay,
  ViewIssue,
  ViewTask,
  ViewUnresolvedItem,
} from './types.generated';

export function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Creates an empty default MeetingOverlay.
 */
export function createEmptyOverlay(meetingId: string, transcriptHash?: string | null): MeetingOverlay {
  return {
    schema_version: '2.0.0',
    meeting_id: meetingId,
    transcript_hash: transcriptHash || null,
    tasks: {},
    manual_tasks: [],
    deleted_task_ids: [],
    unresolved: {},
    deleted_unresolved_ids: [],
    issues: {},
    issue_notes: [],
    deleted_issue_ids: [],
    updated_at: new Date().toISOString(),
  };
}

function tokenizeWords(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .normalize('NFC')
      .replace(/[^\p{L}\p{N}\s]/gu, ' ')
      .split(/\s+/)
      .filter((w) => w.length > 0)
  );
}

/**
 * Check if two ViewTasks refer to the same commitment/deliverable by the same person.
 */
export function areViewTasksDuplicate(t1: ViewTask, t2: ViewTask): boolean {
  // 1. Assignee matching
  const a1 = (t1.assignee || '').trim().toLowerCase();
  const a2 = (t2.assignee || '').trim().toLowerCase();
  if (a1 && a2 && a1 !== a2) {
    return false;
  }

  // 2. Exact normalized title match
  const clean1 = t1.title.trim().toLowerCase().normalize('NFC');
  const clean2 = t2.title.trim().toLowerCase().normalize('NFC');
  if (clean1 === clean2) return true;

  // 3. Token overlap matching
  const set1 = tokenizeWords(clean1);
  const set2 = tokenizeWords(clean2);
  if (set1.size === 0 || set2.size === 0) return false;

  let intersection = 0;
  for (const w of set1) {
    if (set2.has(w)) intersection++;
  }
  const minSize = Math.min(set1.size, set2.size);
  const union = new Set([...set1, ...set2]).size;

  const overlapMin = intersection / minSize;
  const jaccard = intersection / union;

  return (overlapMin >= 0.75 && jaccard >= 0.4) || jaccard >= 0.6;
}

/**
 * Merge two duplicate ViewTask objects, preserving canonical deadline and combining evidence.
 */
export function mergeTwoViewTasks(t1: ViewTask, t2: ViewTask): ViewTask {
  // 1. Best title: longer / more detailed
  const w1 = t1.title.trim().split(/\s+/).length;
  const w2 = t2.title.trim().split(/\s+/).length;
  const chosenTitle = w1 >= w2 ? t1.title : t2.title;

  // 2. Assignee: prefer non-null
  const chosenAssignee = t1.assignee || t2.assignee;

  // 3. Deadlines: prefer valid ISO and canonical display format
  const chosenIso = t1.deadline_iso || t2.deadline_iso;
  let chosenRaw = t1.deadline_raw || t2.deadline_raw;

  if (t1.deadline_raw && t2.deadline_raw) {
    const t1Canonical =
      t1.deadline_raw.includes('ngày ') || Boolean(chosenIso && t1.deadline_raw.includes(chosenIso));
    const t2Canonical =
      t2.deadline_raw.includes('ngày ') || Boolean(chosenIso && t2.deadline_raw.includes(chosenIso));
    if (t1Canonical && !t2Canonical) {
      chosenRaw = t1.deadline_raw;
    } else if (t2Canonical && !t1Canonical) {
      chosenRaw = t2.deadline_raw;
    } else {
      chosenRaw =
        t1.deadline_raw.length >= t2.deadline_raw.length ? t1.deadline_raw : t2.deadline_raw;
    }
  }

  // 4. Evidence: union without duplicates
  const seenQuotes = new Set<string>();
  const mergedEv: Evidence[] = [];
  for (const ev of [...(t1.evidence || []), ...(t2.evidence || [])]) {
    const k = `${(ev.quote || '').trim()}::${ev.utterance_id || ''}::${ev.speaker || ''}`;
    if (!seenQuotes.has(k)) {
      seenQuotes.add(k);
      mergedEv.push(ev);
    }
  }

  // 5. Status: if either is 'done', keep 'done'
  const chosenStatus: 'open' | 'done' =
    t1.status === 'done' || t2.status === 'done' ? 'done' : 'open';
  const completedAt = t1.completed_at || t2.completed_at;

  return {
    ...t1,
    title: chosenTitle,
    assignee: chosenAssignee,
    assigned_by: t1.assigned_by || t2.assigned_by,
    requested_by: t1.requested_by || t2.requested_by,
    deadline_raw: chosenRaw,
    deadline_iso: chosenIso,
    status: chosenStatus,
    completed_at: completedAt,
    evidence: mergedEv,
    needs_review: Boolean(t1.needs_review && t2.needs_review),
    external_dependency: t1.external_dependency || t2.external_dependency,
    collaborator: t1.collaborator || t2.collaborator,
    reviewer: t1.reviewer || t2.reviewer,
    escalation: t1.escalation || t2.escalation,
  };
}

/**
 * Deduplicate ViewTask items preserving canonical deadlines and evidence.
 */
export function deduplicateViewTasks(tasks: ViewTask[]): ViewTask[] {
  if (!tasks || tasks.length <= 1) return tasks;

  const merged: ViewTask[] = [];
  for (const task of tasks) {
    const matchIdx = merged.findIndex((existing) => areViewTasksDuplicate(existing, task));
    if (matchIdx !== -1) {
      merged[matchIdx] = mergeTwoViewTasks(merged[matchIdx], task);
    } else {
      merged.push(task);
    }
  }
  return merged;
}

/**
 * Pure merge function combining AI layer + User overlay -> MeetingViewModel.
 *
 * @param aiOutput Immutable analysis output from pipeline or sample cache.
 * @param overlay Optional user overlay containing edits, deletions, manual tasks, and notes.
 * @returns MeetingViewModel with all user modifications applied over AI results.
 */
export function mergeMeetingView(
  aiOutput: MeetingOutput,
  overlay?: MeetingOverlay | null
): MeetingViewModel {
  const meetingId =
    overlay?.meeting_id ||
    aiOutput.meta?.transcript_hash ||
    aiOutput.decisions?.[0]?.id ||
    generateUUID();

  const effectiveOverlay: MeetingOverlay = overlay
    ? { ...overlay, meeting_id: overlay.meeting_id || meetingId }
    : createEmptyOverlay(meetingId, aiOutput.meta?.transcript_hash);

  const deletedTasks = new Set(effectiveOverlay.deleted_task_ids || []);
  const deletedUnresolved = new Set(effectiveOverlay.deleted_unresolved_ids || []);
  const deletedIssues = new Set(effectiveOverlay.deleted_issue_ids || []);

  // 1. Decisions (AI layer is canonical)
  const decisions: PublicDecision[] = [...(aiOutput.decisions || [])];

  // 2. Tasks
  const mergedTasks: ViewTask[] = [];

  // Process AI tasks
  for (const aiTask of aiOutput.tasks || []) {
    if (deletedTasks.has(aiTask.id)) {
      continue;
    }

    const taskOverlay = effectiveOverlay.tasks?.[aiTask.id];
    const title = taskOverlay?.title !== undefined && taskOverlay.title !== null ? taskOverlay.title : aiTask.title;
    const assignee =
      taskOverlay?.assignee !== undefined && taskOverlay.assignee !== null ? taskOverlay.assignee : aiTask.assignee;
    const deadlineRaw =
      taskOverlay?.deadline_raw !== undefined && taskOverlay.deadline_raw !== null
        ? taskOverlay.deadline_raw
        : aiTask.deadline_raw;
    const deadlineIso =
      taskOverlay?.deadline_iso !== undefined && taskOverlay.deadline_iso !== null
        ? taskOverlay.deadline_iso
        : aiTask.deadline_iso;
    const status: 'open' | 'done' = taskOverlay?.status ? taskOverlay.status : 'open';
    const completedAt = taskOverlay?.completed_at || null;

    mergedTasks.push({
      id: aiTask.id,
      meeting_id: meetingId,
      source_ref: aiTask.source_ref,
      title,
      assignee,
      assigned_by: aiTask.assigned_by,
      requested_by: aiTask.requested_by,
      deadline_raw: deadlineRaw,
      deadline_iso: deadlineIso,
      status,
      source: aiTask.source || 'ai',
      evidence: aiTask.evidence || [],
      needs_review: aiTask.needs_review || false,
      external_dependency: aiTask.external_dependency,
      collaborator: aiTask.collaborator,
      reviewer: aiTask.reviewer,
      escalation: aiTask.escalation,
      created_at: new Date().toISOString(),
      completed_at: completedAt,
    });
  }

  // Append manual and converted tasks from overlay
  for (const manualTask of effectiveOverlay.manual_tasks || []) {
    if (deletedTasks.has(manualTask.id)) {
      continue;
    }

    const taskOverlay = effectiveOverlay.tasks?.[manualTask.id];
    if (taskOverlay) {
      mergedTasks.push({
        ...manualTask,
        title: taskOverlay.title !== undefined && taskOverlay.title !== null ? taskOverlay.title : manualTask.title,
        assignee:
          taskOverlay.assignee !== undefined && taskOverlay.assignee !== null
            ? taskOverlay.assignee
            : manualTask.assignee,
        deadline_raw:
          taskOverlay.deadline_raw !== undefined && taskOverlay.deadline_raw !== null
            ? taskOverlay.deadline_raw
            : manualTask.deadline_raw,
        deadline_iso:
          taskOverlay.deadline_iso !== undefined && taskOverlay.deadline_iso !== null
            ? taskOverlay.deadline_iso
            : manualTask.deadline_iso,
        status: taskOverlay.status || manualTask.status,
        completed_at: taskOverlay.completed_at || manualTask.completed_at,
      });
    } else {
      mergedTasks.push(manualTask);
    }
  }

  // 3. Unresolved Items
  const mergedUnresolved: ViewUnresolvedItem[] = [];

  for (const aiUnresolved of aiOutput.unresolved || []) {
    if (deletedUnresolved.has(aiUnresolved.id)) {
      continue;
    }

    const uOverlay = effectiveOverlay.unresolved?.[aiUnresolved.id];
    // If converted to task, do not display in Unresolved
    if (uOverlay?.status === 'converted') {
      continue;
    }

    const suggestedAssignee =
      uOverlay?.suggested_assignee !== undefined && uOverlay.suggested_assignee !== null
        ? uOverlay.suggested_assignee
        : aiUnresolved.suggested_assignee;
    const suggestedDeadlineRaw =
      uOverlay?.suggested_deadline_raw !== undefined && uOverlay.suggested_deadline_raw !== null
        ? uOverlay.suggested_deadline_raw
        : aiUnresolved.suggested_deadline_raw;
    const suggestedDeadlineIso =
      uOverlay?.suggested_deadline_iso !== undefined && uOverlay.suggested_deadline_iso !== null
        ? uOverlay.suggested_deadline_iso
        : aiUnresolved.suggested_deadline_iso;

    mergedUnresolved.push({
      id: aiUnresolved.id,
      meeting_id: meetingId,
      source_ref: aiUnresolved.source_ref,
      kind: aiUnresolved.kind,
      content: aiUnresolved.content,
      reason_unresolved: aiUnresolved.reason_unresolved,
      suggested_assignee: suggestedAssignee,
      suggested_deadline_raw: suggestedDeadlineRaw,
      suggested_deadline_iso: suggestedDeadlineIso,
      status: 'open',
      evidence: aiUnresolved.evidence || [],
      needs_review: aiUnresolved.needs_review || false,
    });
  }

  // 4. Issues & Notes
  const mergedIssues: ViewIssue[] = [];

  for (const aiIssue of aiOutput.issues || []) {
    if (deletedIssues.has(aiIssue.id)) {
      continue;
    }

    const iOverlay = effectiveOverlay.issues?.[aiIssue.id];
    const issueStatus: 'open' | 'resolved' = iOverlay?.status ? iOverlay.status : (aiIssue.status || 'open');

    const issueNotes = (effectiveOverlay.issue_notes || []).filter((note) => note.issue_id === aiIssue.id);

    mergedIssues.push({
      id: aiIssue.id,
      meeting_id: meetingId,
      source_ref: aiIssue.source_ref,
      content: aiIssue.content,
      owner: aiIssue.owner,
      status: issueStatus,
      evidence: aiIssue.evidence || [],
      notes: issueNotes,
      needs_review: aiIssue.needs_review || false,
    });
  }

  // Deduplicate tasks (combining multi-turn / overlay duplicates, preserving canonical deadlines)
  const finalTasks = deduplicateViewTasks(mergedTasks);

  return {
    meeting_id: meetingId,
    summary: aiOutput.summary || '',
    participants: aiOutput.participants || [],
    decisions,
    tasks: finalTasks,
    unresolved: mergedUnresolved,
    issues: mergedIssues,
    issue_notes: effectiveOverlay.issue_notes || [],
    meta: aiOutput.meta,
    overlay: effectiveOverlay,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Overlay Mutation Helpers (Pure functions returning updated MeetingOverlay)
// ─────────────────────────────────────────────────────────────────────────────

export function applyTaskEdit(
  overlay: MeetingOverlay,
  taskId: string,
  fields: Partial<TaskOverlay>
): MeetingOverlay {
  const existing = overlay.tasks[taskId] || {};
  return {
    ...overlay,
    tasks: {
      ...overlay.tasks,
      [taskId]: {
        ...existing,
        ...fields,
        updated_at: new Date().toISOString(),
      },
    },
    updated_at: new Date().toISOString(),
  };
}

export function applyTaskStatus(
  overlay: MeetingOverlay,
  taskId: string,
  status: 'open' | 'done'
): MeetingOverlay {
  return applyTaskEdit(overlay, taskId, {
    status,
    completed_at: status === 'done' ? new Date().toISOString() : null,
  });
}

export function applyTaskDelete(
  overlay: MeetingOverlay,
  taskIdOrIds: string | string[]
): MeetingOverlay {
  const toDelete = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds];
  const currentSet = new Set(overlay.deleted_task_ids || []);
  toDelete.forEach((id) => currentSet.add(id));

  return {
    ...overlay,
    deleted_task_ids: Array.from(currentSet),
    updated_at: new Date().toISOString(),
  };
}

export function applyManualTask(
  overlay: MeetingOverlay,
  taskInput: {
    title: string;
    assignee?: string | null;
    deadline_raw?: string | null;
    deadline_iso?: string | null;
    evidence?: Evidence[];
    source?: 'manual' | 'from_unresolved';
  }
): { overlay: MeetingOverlay; task: ViewTask } {
  const taskId = generateUUID();
  const newTask: ViewTask = {
    id: taskId,
    meeting_id: overlay.meeting_id,
    title: taskInput.title,
    assignee: taskInput.assignee || null,
    deadline_raw: taskInput.deadline_raw || null,
    deadline_iso: taskInput.deadline_iso || null,
    status: 'open',
    source: taskInput.source || 'manual',
    evidence: taskInput.evidence || [],
    needs_review: false,
    created_at: new Date().toISOString(),
  };

  const updatedOverlay: MeetingOverlay = {
    ...overlay,
    manual_tasks: [...(overlay.manual_tasks || []), newTask],
    updated_at: new Date().toISOString(),
  };

  return { overlay: updatedOverlay, task: newTask };
}

export function applyConvertUnresolved(
  overlay: MeetingOverlay,
  unresolvedItem: ViewUnresolvedItem,
  assignee?: string | null,
  deadlineRaw?: string | null,
  deadlineIso?: string | null
): { overlay: MeetingOverlay; task: ViewTask } {
  const safeAssignee =
    (typeof assignee === 'string' ? assignee.trim() : '') ||
    unresolvedItem.suggested_assignee ||
    null;

  const { overlay: overlayWithTask, task } = applyManualTask(overlay, {
    title: unresolvedItem.content,
    assignee: safeAssignee,
    deadline_raw: deadlineRaw || null,
    deadline_iso: deadlineIso || null,
    evidence: unresolvedItem.evidence || [],
    source: 'from_unresolved',
  });

  const updatedOverlay: MeetingOverlay = {
    ...overlayWithTask,
    unresolved: {
      ...overlayWithTask.unresolved,
      [unresolvedItem.id]: {
        status: 'converted',
        suggested_assignee: safeAssignee,
        suggested_deadline_raw: deadlineRaw || null,
        suggested_deadline_iso: deadlineIso || null,
        converted_to_task_id: task.id,
        updated_at: new Date().toISOString(),
      },
    },
    updated_at: new Date().toISOString(),
  };

  return { overlay: updatedOverlay, task };
}

export function applyIssueStatus(
  overlay: MeetingOverlay,
  issueId: string,
  status: 'open' | 'resolved'
): MeetingOverlay {
  return {
    ...overlay,
    issues: {
      ...overlay.issues,
      [issueId]: {
        status,
        updated_at: new Date().toISOString(),
      },
    },
    updated_at: new Date().toISOString(),
  };
}

export function applyIssueNote(
  overlay: MeetingOverlay,
  issueId: string,
  noteInput: {
    authorId: string;
    authorName: string;
    content: string;
  }
): { overlay: MeetingOverlay; note: IssueNote } {
  const noteId = generateUUID();
  const now = new Date().toISOString();
  const note: IssueNote = {
    id: noteId,
    issue_id: issueId,
    author_id: noteInput.authorId,
    author_name: noteInput.authorName,
    content: noteInput.content,
    created_at: now,
    updated_at: now,
  };

  const updatedOverlay: MeetingOverlay = {
    ...overlay,
    issue_notes: [...(overlay.issue_notes || []), note],
    updated_at: now,
  };

  return { overlay: updatedOverlay, note };
}

export function applyEditIssueNote(
  overlay: MeetingOverlay,
  noteId: string,
  newContent: string
): MeetingOverlay {
  const now = new Date().toISOString();
  return {
    ...overlay,
    issue_notes: (overlay.issue_notes || []).map((n) =>
      n.id === noteId ? { ...n, content: newContent, updated_at: now } : n
    ),
    updated_at: now,
  };
}

export function applyDeleteIssueNote(
  overlay: MeetingOverlay,
  noteId: string
): MeetingOverlay {
  return {
    ...overlay,
    issue_notes: (overlay.issue_notes || []).filter((n) => n.id !== noteId),
    updated_at: new Date().toISOString(),
  };
}
