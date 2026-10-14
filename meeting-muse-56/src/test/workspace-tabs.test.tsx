import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { Workspace } from '../components/meeting/workspace';
import type { MeetingOutput } from '../lib/types.generated';

describe('Workspace Tab Switching & Regression for Issues Tab Crash', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  const sample1Modern: MeetingOutput = {
    summary: 'Cuộc họp Sprint Planning cho Sprint 24.',
    participants: ['Minh', 'Lan', 'Tuấn', 'Hương'],
    decisions: [
      {
        id: 'd-1',
        topic: 'Phạm vi Sprint 24',
        content: 'Triển khai tích hợp thanh toán QR code qua cổng VNPay.',
        status: 'confirmed',
        evidence: [],
        history: [],
        needs_review: false,
      },
    ],
    tasks: [
      {
        id: 't-1',
        title: 'Hoàn thiện Figma design specs chi tiết',
        assignee: 'Tuấn',
        deadline_raw: '12:00 ngày 18/10',
        deadline_iso: '2026-10-18',
        source: 'ai',
        evidence: [],
        needs_review: false,
      },
    ],
    unresolved: [],
    issues: [
      {
        id: 'iss-1',
        content: 'Chưa nhận được tài khoản sandbox và API key mới từ phía cổng thanh toán VNPay.',
        owner: 'Bình',
        status: 'open',
        evidence: [
          {
            speaker: 'Lan',
            quote: 'Em cần tài khoản sandbox và API secret key mới nhất của VNPay.',
            verified: true,
          },
        ],
        notes: [],
        needs_review: false,
      },
    ],
    meta: {
      schema_version: '2.0.0',
      prompt_version: '2.3.0',
      per_step_model: {},
      analyzed_at: '2026-10-15T00:00:00Z',
      transcript_hash: 'sample1-hash',
      meeting_date: '2026-10-15',
      meeting_date_source: 'fallback_today',
    },
  };

  const sample2ZeroIssues: MeetingOutput = {
    summary: 'Cuộc họp Product Launch Timing.',
    participants: ['Quân', 'Đạt', 'Mai'],
    decisions: [
      {
        id: 'd-2',
        topic: 'Thời điểm ra mắt sản phẩm',
        content: 'Chốt lùi ngày ra mắt chính thức sang 15 tháng 7.',
        status: 'confirmed',
        evidence: [],
        history: [],
        needs_review: false,
      },
    ],
    tasks: [
      {
        id: 't-2',
        title: 'Lập tài liệu kiến trúc kỹ thuật',
        assignee: 'Đạt',
        deadline_raw: '10/05',
        deadline_iso: '2027-05-10',
        source: 'ai',
        evidence: [],
        needs_review: false,
      },
    ],
    unresolved: [],
    issues: [], // Zero issues
    meta: {
      schema_version: '2.0.0',
      prompt_version: '2.3.0',
      per_step_model: {},
      analyzed_at: '2026-10-15T00:00:00Z',
      transcript_hash: 'sample2-hash',
      meeting_date: '2027-05-02',
      meeting_date_source: 'fallback_today',
    },
  };

  const legacySampleBlocker = {
    meeting_summary: 'Legacy sprint planning meeting with blockers.',
    participants: ['Khoa', 'Tuấn'],
    decisions: [],
    action_items: [
      {
        item_id: 'A001',
        task: 'Kiểm tra log crash server',
        assignee: 'Khoa',
        deadline: 'Đầu giờ chiều',
        dependencies: [],
        evidence: [],
        needs_review: false,
      },
    ],
    unresolved_items: [],
    blockers: [
      {
        item_id: 'B001',
        issue: 'Server staging bị tràn bộ nhớ khi chạy batch job',
        owner: 'Khoa',
        evidence: [],
        status: 'unresolved',
        needs_review: false,
      },
    ],
  };

  it('clicking Vướng mắc (Issues) tab on sample with 1 issue renders issue content and notes without crashing', () => {
    render(
      <Workspace
        result={sample1Modern}
        transcript="[09:00] Lan: Em cần tài khoản sandbox VNPay..."
        onBack={vi.fn()}
      />
    );

    // Initial render shows Dashboard
    expect(screen.getByText('Biên bản cuộc họp')).toBeTruthy();

    // Click on the Issues section button
    const issuesButton = screen.getAllByRole('button', { name: /Vướng mắc/i })[0];
    fireEvent.click(issuesButton);

    // Verifies the issue content appears without throwing
    expect(
      screen.getByText(
        'Chưa nhận được tài khoản sandbox và API key mới từ phía cổng thanh toán VNPay.'
      )
    ).toBeTruthy();

    // Verifies IssueNotes is rendered inside the issue item
    expect(screen.getByText(/Ghi chú thảo luận \(0\)/)).toBeTruthy();
  });

  it('clicking Vướng mắc (Issues) tab on sample with 0 issues displays empty state cleanly', () => {
    render(
      <Workspace
        result={sample2ZeroIssues}
        transcript="[09:00] Quân: Chốt lùi ngày ra mắt..."
        onBack={vi.fn()}
      />
    );

    const issuesButton = screen.getAllByRole('button', { name: /Vướng mắc/i })[0];
    fireEvent.click(issuesButton);

    expect(screen.getByText('Không có vướng mắc nào đang tồn đọng!')).toBeTruthy();
  });

  it('renders legacy blocker format into issues and allows tab switching back and forth', () => {
    render(
      <Workspace
        result={legacySampleBlocker as any}
        transcript="[10:00] Khoa: Server staging bị tràn bộ nhớ..."
        onBack={vi.fn()}
      />
    );

    // Switch to Issues
    const issuesButton = screen.getAllByRole('button', { name: /Vướng mắc/i })[0];
    fireEvent.click(issuesButton);
    expect(screen.getByText('Server staging bị tràn bộ nhớ khi chạy batch job')).toBeTruthy();

    // Switch to Tasks
    const tasksButton = screen.getAllByRole('button', { name: /Việc cần làm/i })[0];
    fireEvent.click(tasksButton);
    expect(screen.getByText('Kiểm tra log crash server')).toBeTruthy();

    // Switch to Decisions
    const decisionsButton = screen.getAllByRole('button', { name: /Quyết định/i })[0];
    fireEvent.click(decisionsButton);
    expect(screen.getByText('Không có quyết định nào được xác lập trong cuộc họp.')).toBeTruthy();

    // Switch back to Issues
    fireEvent.click(issuesButton);
    expect(screen.getByText('Server staging bị tràn bộ nhớ khi chạy batch job')).toBeTruthy();
  });

  it('allows adding a new note to an issue inside the workspace without crashing', () => {
    render(
      <Workspace
        result={sample1Modern}
        transcript="[09:00] Lan: Em cần tài khoản sandbox VNPay..."
        onBack={vi.fn()}
      />
    );

    const issuesButton = screen.getAllByRole('button', { name: /Vướng mắc/i })[0];
    fireEvent.click(issuesButton);

    // Find note input box
    const noteInput = screen.getByPlaceholderText(/Nhập ghi chú ý kiến cho vấn đề này/i);
    fireEvent.change(noteInput, { target: { value: 'Đã báo lên CTO.' } });

    const submitBtn = screen.getByRole('button', { name: /Gửi/i });
    fireEvent.click(submitBtn);

    // Should prompt for user name if not identified
    expect(screen.getByText(/Tên hiển thị của bạn:/i)).toBeTruthy();
    const nameInput = screen.getByPlaceholderText(/VD: Tuấn \(Backend\)/i);
    fireEvent.change(nameInput, { target: { value: 'Minh PM' } });

    const saveNameBtn = screen.getByRole('button', { name: /Lưu tên/i });
    fireEvent.click(saveNameBtn);

    // Note should now appear under the issue!
    expect(screen.getByText('Đã báo lên CTO.')).toBeTruthy();
    expect(screen.getByText(/Ghi chú thảo luận \(1\)/)).toBeTruthy();
  });
});
