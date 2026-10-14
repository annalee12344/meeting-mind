import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { IssueNotes } from '../components/meeting/issue-notes';
import { SectionErrorBoundary } from '../components/meeting/section-error-boundary';
import { mergeMeetingView, createEmptyOverlay, applyIssueNote } from '../lib/overlay';
import type { IssueNote, MeetingOutput, ViewIssue } from '../lib/types.generated';

describe('IssueNotes & Issues Tab Robustness', () => {
  const dummyIssueId = 'issue-vnpay-timeout';

  it('renders without throwing when notes prop is undefined (regression test for line 36 crash)', () => {
    // Calling IssueNotes with undefined notes must not trigger TypeError: Cannot read properties of undefined (reading 'filter')
    expect(() => {
      render(
        <IssueNotes
          issueId={dummyIssueId}
          notes={undefined as unknown as IssueNote[]}
          onAddNote={vi.fn()}
          onEditNote={vi.fn()}
          onDeleteNote={vi.fn()}
        />
      );
    }).not.toThrow();

    expect(screen.getByText(/Ghi chú thảo luận \(0\)/)).toBeTruthy();
  });

  it('renders without throwing when notes prop is an empty array', () => {
    expect(() => {
      render(
        <IssueNotes
          issueId={dummyIssueId}
          notes={[]}
          onAddNote={vi.fn()}
          onEditNote={vi.fn()}
          onDeleteNote={vi.fn()}
        />
      );
    }).not.toThrow();

    expect(screen.getByText(/Ghi chú thảo luận \(0\)/)).toBeTruthy();
  });

  it('filters and displays notes belonging to the specific issueId', () => {
    const notes: IssueNote[] = [
      {
        id: 'n-1',
        issue_id: dummyIssueId,
        author_id: 'u-1',
        author_name: 'Bình',
        content: 'Đã gửi ticket sang đối tác VNPay để xin cấp lại key.',
        created_at: '2026-10-15T08:30:00Z',
        updated_at: '2026-10-15T08:30:00Z',
      },
      {
        id: 'n-2',
        issue_id: 'another-issue-id',
        author_id: 'u-2',
        author_name: 'Lan',
        content: 'Ghi chú cho vấn đề khác.',
        created_at: '2026-10-15T08:35:00Z',
        updated_at: '2026-10-15T08:35:00Z',
      },
    ];

    render(
      <IssueNotes
        issueId={dummyIssueId}
        notes={notes}
        onAddNote={vi.fn()}
        onEditNote={vi.fn()}
        onDeleteNote={vi.fn()}
      />
    );

    // Only note 1 should be displayed
    expect(screen.getByText(/Ghi chú thảo luận \(1\)/)).toBeTruthy();
    expect(screen.getByText('Đã gửi ticket sang đối tác VNPay để xin cấp lại key.')).toBeTruthy();
    expect(screen.queryByText('Ghi chú cho vấn đề khác.')).toBeNull();
  });

  it('exposes issue_notes on MeetingViewModel and preserves them across mergeMeetingView', () => {
    const aiOutput: MeetingOutput = {
      summary: 'Sprint meeting',
      participants: ['Bình', 'Minh'],
      decisions: [],
      tasks: [],
      unresolved: [],
      issues: [
        {
          id: dummyIssueId,
          content: 'Lỗi timeout khi gọi sandbox VNPay',
          owner: 'Bình',
          status: 'open',
          evidence: [],
          notes: [],
          needs_review: false,
        },
      ],
      meta: {
        schema_version: '2.0.0',
        prompt_version: '2.3.0',
        per_step_model: {},
        analyzed_at: '2026-10-15T08:00:00Z',
        transcript_hash: 'hash-abc',
        meeting_date: '2026-10-15',
        meeting_date_source: 'fallback_today',
      },
    };

    let overlay = createEmptyOverlay('m-test');
    expect(overlay.issue_notes).toEqual([]);

    // Add note via helper
    const added = applyIssueNote(overlay, dummyIssueId, {
      authorId: 'u-1',
      authorName: 'Minh',
      content: 'Cần whitelist IP staging trước 17h.',
    });
    overlay = added.overlay;

    const viewModel = mergeMeetingView(aiOutput, overlay);

    // 1. Top-level issue_notes is populated
    expect(viewModel.issue_notes).toHaveLength(1);
    expect(viewModel.issue_notes[0].content).toBe('Cần whitelist IP staging trước 17h.');

    // 2. Issue item itself has notes populated
    const issueInView = viewModel.issues.find((i) => i.id === dummyIssueId);
    expect(issueInView).toBeDefined();
    expect(issueInView?.notes).toHaveLength(1);
    expect(issueInView?.notes[0].author_name).toBe('Minh');
  });

  it('catches component error in SectionErrorBoundary without throwing and provides recovery', () => {
    function BuggyComponent(): React.JSX.Element {
      throw new Error('Simulated crash inside child section');
    }

    const onResetSpy = vi.fn();
    render(
      <SectionErrorBoundary
        fallbackTitle="Lỗi hiển thị vướng mắc"
        fallbackMessage="Không thể hiển thị phần này."
        onReset={onResetSpy}
      >
        <BuggyComponent />
      </SectionErrorBoundary>
    );

    // Error is caught, fallback is displayed
    expect(screen.getByText('Lỗi hiển thị vướng mắc')).toBeTruthy();
    expect(screen.getByText('Không thể hiển thị phần này.')).toBeTruthy();

    // Clicking retry button calls onReset
    const retryBtn = screen.getByRole('button', { name: /Thử lại/i });
    fireEvent.click(retryBtn);
    expect(onResetSpy).toHaveBeenCalledTimes(1);
  });
});
