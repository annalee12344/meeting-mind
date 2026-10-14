import { describe, it, expect, beforeEach } from 'vitest';
import {
  mergeMeetingView,
  createEmptyOverlay,
  applyTaskEdit,
  applyTaskStatus,
  applyTaskDelete,
  applyManualTask,
  applyConvertUnresolved,
  applyIssueStatus,
  applyIssueNote,
  applyEditIssueNote,
  applyDeleteIssueNote,
} from '../lib/overlay';
import { LocalStorageAdapter } from '../lib/storage';
import type { MeetingOutput } from '../lib/types.generated';

function buildMockAiOutput(): MeetingOutput {
  return {
    summary: 'Sprint 24 Planning Summary',
    participants: ['Tuấn', 'Lan', 'Hương', 'Minh'],
    decisions: [
      {
        id: 'dec-1',
        topic: 'Payment Gateway',
        content: 'Chốt dùng PayOS',
        status: 'confirmed',
        history: [],
        evidence: [],
        needs_review: false,
      },
    ],
    tasks: [
      {
        id: 'task-1',
        title: 'Hoàn thiện Figma design tokens',
        assignee: 'Tuấn',
        deadline_raw: 'thứ Sáu',
        deadline_iso: '2026-10-18',
        source: 'ai',
        evidence: [],
        needs_review: false,
      },
      {
        id: 'task-2',
        title: 'Tích hợp VNPay SDK',
        assignee: 'Lan',
        deadline_raw: 'thứ Hai tuần sau',
        deadline_iso: '2026-10-21',
        source: 'ai',
        evidence: [],
        needs_review: false,
      },
    ],
    unresolved: [
      {
        id: 'unres-1',
        kind: 'unconfirmed_task',
        content: 'Xây dựng test matrix QR',
        suggested_assignee: 'Hương',
        suggested_deadline_raw: 'thứ Tư',
        suggested_deadline_iso: '2026-10-16',
        evidence: [],
        needs_review: false,
      },
    ],
    issues: [
      {
        id: 'issue-1',
        content: 'Staging environment timeout lỗi 504',
        owner: 'Lan',
        status: 'open',
        evidence: [],
        notes: [],
        needs_review: false,
      },
    ],
    meta: {
      schema_version: '2.0.0',
      prompt_version: '2.0.0',
      extractor_model: 'gemini-flash-lite-latest',
      resolver_model: 'gemini-flash-lite-latest',
      analyzed_at: '2026-10-14T09:00:00Z',
      transcript_hash: 'hash-abc-123',
      meeting_date: '2026-10-14',
      meeting_date_source: 'user',
    },
  };
}

describe('Frontend Overlay & Pure Merge Function', () => {
  it('merges default AI output when overlay is empty', () => {
    const ai = buildMockAiOutput();
    const view = mergeMeetingView(ai);

    expect(view.decisions.length).toBe(1);
    expect(view.tasks.length).toBe(2);
    expect(view.unresolved.length).toBe(1);
    expect(view.issues.length).toBe(1);
    expect(view.tasks[0].status).toBe('open');
    expect(view.tasks[0].title).toBe('Hoàn thiện Figma design tokens');
  });

  it('applies task status change (done / open)', () => {
    const ai = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');

    overlay = applyTaskStatus(overlay, 'task-1', 'done');
    const view = mergeMeetingView(ai, overlay);

    const t1 = view.tasks.find((t) => t.id === 'task-1');
    expect(t1?.status).toBe('done');
    expect(t1?.completed_at).toBeTruthy();

    const t2 = view.tasks.find((t) => t.id === 'task-2');
    expect(t2?.status).toBe('open');
  });

  it('applies task edit (title, assignee, deadline)', () => {
    const ai = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');

    overlay = applyTaskEdit(overlay, 'task-1', {
      title: 'Thiết kế Design System V2',
      assignee: 'Tuấn & Minh',
      deadline_raw: 'Chủ Nhật',
      deadline_iso: '2026-10-20',
    });

    const view = mergeMeetingView(ai, overlay);
    const t1 = view.tasks.find((t) => t.id === 'task-1');
    expect(t1?.title).toBe('Thiết kế Design System V2');
    expect(t1?.assignee).toBe('Tuấn & Minh');
    expect(t1?.deadline_iso).toBe('2026-10-20');
  });

  it('deletes tasks without modifying immutable AI output', () => {
    const ai = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');

    overlay = applyTaskDelete(overlay, 'task-1');
    const view = mergeMeetingView(ai, overlay);

    expect(view.tasks.map((t) => t.id)).toEqual(['task-2']);
    // AI layer still intact
    expect(ai.tasks.length).toBe(2);
  });

  it('supports adding manual user tasks', () => {
    const ai = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');

    const { overlay: updatedOverlay, task } = applyManualTask(overlay, {
      title: 'Tạo tài liệu onboarding mới',
      assignee: 'Minh',
      deadline_raw: 'Cuối tuần',
      deadline_iso: '2026-10-18',
    });

    const view = mergeMeetingView(ai, updatedOverlay);
    expect(view.tasks.length).toBe(3);
    expect(view.tasks.some((t) => t.id === task.id && t.source === 'manual')).toBe(true);
  });

  it('converts unresolved item to task and removes from unresolved view', () => {
    const ai = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');

    const unresolvedItem = ai.unresolved[0];
    const { overlay: updatedOverlay, task } = applyConvertUnresolved(
      overlay,
      { ...unresolvedItem, status: 'open' },
      'Hương (QA Lead)',
      'Thứ Hai',
      '2026-10-21'
    );

    const view = mergeMeetingView(ai, updatedOverlay);
    expect(view.unresolved.length).toBe(0); // removed from unresolved
    expect(view.tasks.length).toBe(3); // added to tasks
    const converted = view.tasks.find((t) => t.id === task.id);
    expect(converted?.source).toBe('from_unresolved');
    expect(converted?.assignee).toBe('Hương (QA Lead)');
  });

  it('handles issue status toggle and author notes', () => {
    const ai = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');

    overlay = applyIssueStatus(overlay, 'issue-1', 'resolved');
    const { overlay: overlayWithNote, note } = applyIssueNote(overlay, 'issue-1', {
      authorId: 'user-lan',
      authorName: 'Lan',
      content: 'Đã reboot worker và tăng timeout lên 60s.',
    });

    let view = mergeMeetingView(ai, overlayWithNote);
    const iss = view.issues.find((i) => i.id === 'issue-1');
    expect(iss?.status).toBe('resolved');
    expect(iss?.notes.length).toBe(1);
    expect(iss?.notes[0].content).toBe('Đã reboot worker và tăng timeout lên 60s.');

    // Edit note
    const editedOverlay = applyEditIssueNote(overlayWithNote, note.id, 'Sửa: Đã nâng timeout lên 120s.');
    view = mergeMeetingView(ai, editedOverlay);
    expect(view.issues[0].notes[0].content).toBe('Sửa: Đã nâng timeout lên 120s.');

    // Delete note
    const deletedOverlay = applyDeleteIssueNote(editedOverlay, note.id);
    view = mergeMeetingView(ai, deletedOverlay);
    expect(view.issues[0].notes.length).toBe(0);
  });

  it('is idempotent across AI re-analysis', () => {
    const aiV1 = buildMockAiOutput();
    let overlay = createEmptyOverlay('meeting-1');
    overlay = applyTaskStatus(overlay, 'task-1', 'done');

    // Simulate re-analysis with upgraded prompt
    const aiV2: MeetingOutput = {
      ...aiV1,
      meta: { ...aiV1.meta, prompt_version: '2.1.0' },
      tasks: [
        ...aiV1.tasks,
        {
          id: 'task-3-new',
          title: 'Viết test cases tích hợp',
          assignee: 'Tuấn',
          source: 'ai',
          evidence: [],
          needs_review: false,
        },
      ],
    };

    const view = mergeMeetingView(aiV2, overlay);
    // User done status on task-1 is preserved!
    expect(view.tasks.find((t) => t.id === 'task-1')?.status).toBe('done');
    // New task-3 is included!
    expect(view.tasks.find((t) => t.id === 'task-3-new')).toBeTruthy();
  });
});

describe('LocalStorageAdapter', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('saves, loads, and deletes overlays', async () => {
    const adapter = new LocalStorageAdapter('test_mm_');
    const overlay = createEmptyOverlay('m-42');
    overlay.deleted_task_ids = ['task-99'];

    await adapter.saveOverlay(overlay);
    const loaded = await adapter.loadOverlay('m-42');

    expect(loaded).toBeTruthy();
    expect(loaded?.meeting_id).toBe('m-42');
    expect(loaded?.deleted_task_ids).toEqual(['task-99']);

    const list = await adapter.listOverlays();
    expect(list.some((item) => item.meetingId === 'm-42')).toBe(true);

    await adapter.deleteOverlay('m-42');
    const afterDelete = await adapter.loadOverlay('m-42');
    expect(afterDelete).toBeNull();
  });
});
