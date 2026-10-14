import { describe, it, expect } from 'vitest';
import {
  areViewTasksDuplicate,
  mergeTwoViewTasks,
  deduplicateViewTasks,
  mergeMeetingView,
  createEmptyOverlay,
} from '../lib/overlay';
import type { MeetingOutput, ViewTask } from '../lib/types.generated';

describe('Frontend ViewTask Deduplication & Overlay Merging', () => {
  it('deduplicates identical tasks with different deadline formats', () => {
    const t1: ViewTask = {
      id: 'task-1',
      title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
      assignee: 'Đạt',
      deadline_raw: '10/05',
      deadline_iso: null,
      status: 'open',
      source: 'ai',
      evidence: [{ speaker: 'Đạt', quote: 'deadline 10/5', verified: true }],
      needs_review: false,
    };
    const t2: ViewTask = {
      id: 'task-2',
      title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
      assignee: 'Đạt',
      deadline_raw: 'ngày 10/05/2027',
      deadline_iso: '2027-05-10',
      status: 'open',
      source: 'ai',
      evidence: [{ speaker: 'Quân', quote: 'hoàn thành trước ngày 10 tháng 5', verified: true }],
      needs_review: false,
    };

    expect(areViewTasksDuplicate(t1, t2)).toBe(true);
    const deduped = deduplicateViewTasks([t1, t2]);
    expect(deduped.length).toBe(1);
    expect(deduped[0].deadline_iso).toBe('2027-05-10');
    expect(deduped[0].deadline_raw).toBe('ngày 10/05/2027');
    expect(deduped[0].evidence.length).toBe(2);
  });

  it('deduplicates tasks with slightly different phrasing for the same deliverable', () => {
    const t1: ViewTask = {
      id: 'task-1',
      title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
      assignee: 'Đạt',
      deadline_raw: '10 tháng 5',
      status: 'open',
      source: 'ai',
      evidence: [],
      needs_review: false,
    };
    const t2: ViewTask = {
      id: 'task-2',
      title: 'làm spec kiến trúc và so sánh đối tác thanh toán',
      assignee: 'Đạt',
      deadline_raw: '10/5',
      status: 'open',
      source: 'ai',
      evidence: [],
      needs_review: false,
    };

    expect(areViewTasksDuplicate(t1, t2)).toBe(true);
    const deduped = deduplicateViewTasks([t1, t2]);
    expect(deduped.length).toBe(1);
    expect(deduped[0].title).toBe('Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán');
  });

  it('does NOT merge distinct tasks by the same assignee', () => {
    const t1: ViewTask = {
      id: 'task-1',
      title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
      assignee: 'Đạt',
      deadline_raw: '10/05',
      status: 'open',
      source: 'ai',
      evidence: [],
      needs_review: false,
    };
    const t2: ViewTask = {
      id: 'task-2',
      title: 'Gửi tài liệu cho đối tác review',
      assignee: 'Đạt',
      deadline_raw: '12/05',
      status: 'open',
      source: 'ai',
      evidence: [],
      needs_review: false,
    };

    expect(areViewTasksDuplicate(t1, t2)).toBe(false);
    const deduped = deduplicateViewTasks([t1, t2]);
    expect(deduped.length).toBe(2);
  });

  it('does NOT merge similar deliverable tasks for different assignees', () => {
    const t1: ViewTask = {
      id: 'task-1',
      title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
      assignee: 'Đạt',
      deadline_raw: '10/05',
      status: 'open',
      source: 'ai',
      evidence: [],
      needs_review: false,
    };
    const t2: ViewTask = {
      id: 'task-2',
      title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
      assignee: 'Mai',
      deadline_raw: '10/05',
      status: 'open',
      source: 'ai',
      evidence: [],
      needs_review: false,
    };

    expect(areViewTasksDuplicate(t1, t2)).toBe(false);
    const deduped = deduplicateViewTasks([t1, t2]);
    expect(deduped.length).toBe(2);
  });

  it('merges manual tasks in overlay with existing AI tasks cleanly without duplicates', () => {
    const aiOutput: MeetingOutput = {
      summary: 'Summary',
      participants: ['Đạt', 'Mai', 'Quân'],
      decisions: [],
      tasks: [
        {
          id: 'ai-task-1',
          title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
          assignee: 'Đạt',
          deadline_raw: 'ngày 10/05/2027',
          deadline_iso: '2027-05-10',
          source: 'ai',
          evidence: [],
          needs_review: false,
        },
      ],
      unresolved: [],
      issues: [],
    };

    const overlay = createEmptyOverlay('m-123');
    overlay.manual_tasks = [
      {
        id: 'manual-task-1',
        title: 'Lập tài liệu kiến trúc kỹ thuật và so sánh chi phí các đối tác cổng thanh toán',
        assignee: 'Đạt',
        deadline_raw: '10/05',
        deadline_iso: null,
        status: 'open',
        source: 'manual',
        evidence: [],
        needs_review: false,
      },
    ];

    const view = mergeMeetingView(aiOutput, overlay);
    expect(view.tasks.length).toBe(1);
    expect(view.tasks[0].assignee).toBe('Đạt');
    expect(view.tasks[0].deadline_iso).toBe('2027-05-10');
    expect(view.tasks[0].deadline_raw).toBe('ngày 10/05/2027');
  });
});
