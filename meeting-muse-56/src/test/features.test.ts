import { describe, it, expect, beforeEach } from 'vitest';
import { canEditNote, canDeleteNote, saveStoredIdentity, getStoredIdentity } from '../lib/identity';
import { getDeadlineWarning, NEAR_DUE_HOURS_THRESHOLD } from '../lib/deadlines';
import { createEmptyOverlay, applyConvertUnresolved, mergeMeetingView } from '../lib/overlay';
import type { MeetingOutput, ViewUnresolvedItem } from '../lib/types.generated';

describe('1. Permission Helper (Identity & Note Permissions)', () => {
  it('allows editing and deleting only when authorId matches currentUserId', () => {
    const authorA = 'user-uuid-111';
    const authorB = 'user-uuid-222';

    // Same author
    expect(canEditNote(authorA, authorA)).toBe(true);
    expect(canDeleteNote(authorA, authorA)).toBe(true);

    // Different author
    expect(canEditNote(authorA, authorB)).toBe(false);
    expect(canDeleteNote(authorA, authorB)).toBe(false);

    // Edge cases: missing/null IDs
    expect(canEditNote(null, authorA)).toBe(false);
    expect(canEditNote(authorA, null)).toBe(false);
    expect(canEditNote(undefined, undefined)).toBe(false);
    expect(canEditNote('', 'user-uuid-111')).toBe(false);
  });

  it('manages local anonymous identity storage', () => {
    window.localStorage.clear();
    expect(getStoredIdentity()).toBeNull();

    const identity = saveStoredIdentity('Nguyễn Văn A');
    expect(identity.displayName).toBe('Nguyễn Văn A');
    expect(identity.clientId).toBeTruthy();

    const loaded = getStoredIdentity();
    expect(loaded?.displayName).toBe('Nguyễn Văn A');
    expect(loaded?.clientId).toBe(identity.clientId);
  });
});

describe('2. Overdue Warning Logic (Date Math on deadline_iso)', () => {
  const baseTime = new Date('2026-10-15T10:00:00Z');

  it('returns null if task is already completed (isDone = true)', () => {
    // Even if deadline is far in the past, no warning for done task
    const warning = getDeadlineWarning('2026-10-10T10:00:00Z', true, baseTime);
    expect(warning).toBeNull();
  });

  it('returns null if deadline_iso is null, undefined, or empty (no guessing)', () => {
    expect(getDeadlineWarning(null, false, baseTime)).toBeNull();
    expect(getDeadlineWarning(undefined, false, baseTime)).toBeNull();
    expect(getDeadlineWarning('', false, baseTime)).toBeNull();
    expect(getDeadlineWarning('invalid-date', false, baseTime)).toBeNull();
  });

  it('detects overdue deadlines (past deadline)', () => {
    // 2 days ago
    const twoDaysAgo = '2026-10-13T10:00:00Z';
    const warning = getDeadlineWarning(twoDaysAgo, false, baseTime);

    expect(warning).not.toBeNull();
    expect(warning?.isWarning).toBe(true);
    expect(warning?.isOverdue).toBe(true);
    expect(warning?.isDueSoon).toBe(false);
    expect(warning?.severity).toBe('overdue');
    expect(warning?.label).toContain('Quá hạn');
  });

  it('detects near-due deadlines within 48h threshold', () => {
    // 24 hours in the future
    const in24h = '2026-10-16T10:00:00Z';
    const warning = getDeadlineWarning(in24h, false, baseTime);

    expect(warning).not.toBeNull();
    expect(warning?.isWarning).toBe(true);
    expect(warning?.isOverdue).toBe(false);
    expect(warning?.isDueSoon).toBe(true);
    expect(warning?.severity).toBe('due_soon');
    expect(warning?.label).toContain('Còn');
  });

  it('marks deadlines beyond 48h as normal without warning flag', () => {
    // 5 days in the future
    const in5Days = '2026-10-20T10:00:00Z';
    const warning = getDeadlineWarning(in5Days, false, baseTime);

    expect(warning).not.toBeNull();
    expect(warning?.isWarning).toBe(false);
    expect(warning?.isOverdue).toBe(false);
    expect(warning?.isDueSoon).toBe(false);
    expect(warning?.severity).toBe('normal');
  });
});

describe('3. Convert-to-Task Flow', () => {
  it('converts an unresolved unconfirmed_task into an assigned task preserving evidence', () => {
    const mockAi: MeetingOutput = {
      summary: 'Họp kỹ thuật',
      participants: ['Tuấn', 'Lan'],
      decisions: [],
      tasks: [],
      unresolved: [
        {
          id: 'unres-item-1',
          kind: 'unconfirmed_task',
          content: 'Nghiên cứu tích hợp Apple Pay SDK',
          reason_unresolved: 'Chưa chốt ai nhận',
          suggested_assignee: 'Tuấn',
          suggested_deadline_raw: 'thứ Sáu',
          evidence: [
            {
              speaker: 'Minh',
              quote: 'Ai làm Apple Pay nhé?',
              verified: true,
            },
          ],
          needs_review: false,
        },
      ],
      issues: [],
      meta: {
        schema_version: '2.0.0',
        prompt_version: '2.0.0',
        extractor_model: 'test',
        resolver_model: 'test',
        analyzed_at: '2026-10-14T00:00:00Z',
        transcript_hash: 'hash-test',
        meeting_date: '2026-10-14',
        meeting_date_source: 'user',
      },
    };

    let overlay = createEmptyOverlay('meeting-conv-test');
    const unresolvedItem: ViewUnresolvedItem = {
      ...mockAi.unresolved[0],
      meeting_id: 'meeting-conv-test',
      status: 'open',
    };

    // Act: Convert to task
    const { overlay: updatedOverlay, task } = applyConvertUnresolved(
      overlay,
      unresolvedItem,
      'Tuấn (Senior iOS)',
      '18/10',
      '2026-10-18'
    );

    // Verify task properties
    expect(task.source).toBe('from_unresolved');
    expect(task.assignee).toBe('Tuấn (Senior iOS)');
    expect(task.deadline_raw).toBe('18/10');
    expect(task.deadline_iso).toBe('2026-10-18');
    expect(task.evidence.length).toBe(1);
    expect(task.evidence[0].quote).toBe('Ai làm Apple Pay nhé?');

    // Verify merge view model
    const viewModel = mergeMeetingView(mockAi, updatedOverlay);

    // Unresolved list now empty
    expect(viewModel.unresolved.length).toBe(0);

    // Tasks list contains the converted task
    expect(viewModel.tasks.length).toBe(1);
    const convertedInView = viewModel.tasks[0];
    expect(convertedInView.id).toBe(task.id);
    expect(convertedInView.source).toBe('from_unresolved');
    expect(convertedInView.assignee).toBe('Tuấn (Senior iOS)');
    expect(convertedInView.evidence[0].quote).toBe('Ai làm Apple Pay nhé?');
  });
});
