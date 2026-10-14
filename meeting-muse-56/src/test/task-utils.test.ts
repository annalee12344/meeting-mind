import { describe, it, expect } from 'vitest';
import { cleanTaskFields, formatDeadlineToDisplay, parseDateAndTime } from '../lib/task-utils';

describe('task-utils', () => {
  it('cleans title and separates assignee and deadline for user sample', () => {
    const raw =
      'Nhờ team DevOps mở whitelist IP và cấu hình mở port cho webhook domain staging trước 10:00 ngày 21/10';
    const result = cleanTaskFields(raw, null, null, null, '2026-10-20');

    expect(result.title).toBe(
      'Mở whitelist IP và cấu hình mở port cho webhook domain staging'
    );
    expect(result.assignee).toBe('Team DevOps');
    expect(result.datePart).toBe('2026-10-21');
    expect(result.timePart).toBe('10:00');
    expect(result.deadline_iso).toBe('2026-10-21T10:00:00');
    expect(result.deadline_raw).toContain('10:00');
  });

  it('keeps clean title when already clean', () => {
    const raw = 'Cập nhật tài liệu API staging';
    const result = cleanTaskFields(raw, 'Tuấn', '15:00 ngày 22/10/2026', '2026-10-22T15:00:00');

    expect(result.title).toBe('Cập nhật tài liệu API staging');
    expect(result.assignee).toBe('Tuấn');
    expect(result.datePart).toBe('2026-10-22');
    expect(result.timePart).toBe('15:00');
    expect(result.deadline_iso).toBe('2026-10-22T15:00:00');
  });

  it('strips prefix when assignee is already given', () => {
    const raw = 'Giao Lan viết test case cho auth module trước 17:00 25/10';
    const result = cleanTaskFields(raw, 'Lan', null, null, '2026-10-20');

    expect(result.title).toBe('Viết test case cho auth module');
    expect(result.assignee).toBe('Lan');
    expect(result.timePart).toBe('17:00');
    expect(result.datePart).toBe('2026-10-25');
  });

  it('formats date and time properly to display', () => {
    expect(formatDeadlineToDisplay('2026-10-21', '10:00')).toBe('10:00 ngày 21/10/2026');
    expect(formatDeadlineToDisplay('2026-10-21', '')).toBe('ngày 21/10/2026');
    expect(formatDeadlineToDisplay('', '10:00')).toBe('10:00');
  });

  it('parses date and time from various formats', () => {
    const p1 = parseDateAndTime('10:00 ngày 21/10', null, 2026);
    expect(p1.datePart).toBe('2026-10-21');
    expect(p1.timePart).toBe('10:00');
    expect(p1.iso).toBe('2026-10-21T10:00:00');

    const p2 = parseDateAndTime(null, '2026-10-21T14:30:00', 2026);
    expect(p2.datePart).toBe('2026-10-21');
    expect(p2.timePart).toBe('14:30');
  });
});
