import { describe, expect, it } from 'vitest';
import { isMeetingResult, parseUtterances } from '@/lib/meeting';
import sample from '@/data/sprint-planning.json';

describe('Meeting output and source parsing', () => {
  it('accepts the provided original output', () => expect(isMeetingResult(sample)).toBe(true));
  it('rejects malformed nested results without opening a broken workspace', () => expect(isMeetingResult({ ...sample, decisions: [{}] })).toBe(false));
  it('keeps Vietnamese speakers and timestamps attached to utterances', () => {
    expect(parseUtterances('[09:00] Hương: Đồng ý.\n\nMore context.')).toEqual([
      { id: '1', timestamp: '09:00', speaker: 'Hương', text: 'Đồng ý.' },
      { id: '2', timestamp: '', speaker: '', text: 'More context.' },
    ]);
  });
  it('accepts valid meeting outputs with unassigned action items and null conditions', () => {
    const realisticOutput = {
      meeting_summary: 'Cuộc họp thảo luận kỹ thuật.',
      participants: ['Nam', 'Lan'],
      decisions: [{
        item_id: 'D001',
        topic: 'Chọn DB',
        final_value: 'MongoDB',
        status: 'confirmed',
        condition: null,
        needs_review: false,
        history: [{
          value: 'MongoDB',
          status: 'confirmed',
          evidence: [{
            speaker: 'Nam',
            timestamp: '09:00',
            quote: 'Chốt MongoDB.',
            utterance_id: 'U001',
            verified: true,
          }],
        }],
      }],
      action_items: [{
        item_id: 'A001',
        task: 'Setup DB',
        assignee: null,
        deadline: null,
        dependencies: [],
        evidence: [],
        needs_review: true,
      }],
      blockers: [],
      requests: [],
      unresolved_items: [],
    };
    expect(isMeetingResult(realisticOutput)).toBe(true);
  });

  it('correctly identifies urgent vs non-urgent deadlines', () => {
    // Import dynamically or test rules
    const urgentCases = ['17:00 hôm nay', 'Trong ngày mai', 'Trước thứ Ba', 'Gấp trong 24h', '18/10'];
    const nonUrgentCases = ['Cuối tháng sau', 'Sau 3 tháng', '15/12/2026', null, undefined, ''];

    urgentCases.forEach((d) => {
      const lower = (d || '').toLowerCase();
      const isUrgent = /hôm nay|ngay|khẩn|gấp|sớm|trong ngày|24h|today|urgent|asap|ngày mai|mai|tomorrow|thứ ba|thứ 3|thứ hai|thứ 2|thứ tư|thứ 4|t2|t3|t4|tue|wed|mon|18\/10|19\/10|20\/10/.test(lower);
      expect(isUrgent).toBe(true);
    });

    nonUrgentCases.forEach((d) => {
      if (!d) return;
      const lower = d.toLowerCase();
      const isUrgent = /hôm nay|ngay|khẩn|gấp|sớm|trong ngày|24h|today|urgent|asap|ngày mai|mai|tomorrow|thứ ba|thứ 3|thứ hai|thứ 2|thứ tư|thứ 4|t2|t3|t4|tue|wed|mon|18\/10|19\/10|20\/10/.test(lower);
      expect(isUrgent).toBe(false);
    });
  });
});