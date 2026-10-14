import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getAnalysisJob, startAnalysisJob } from '../lib/api';
import type { JobStatusResponse, AnalyzeJobResponse } from '../lib/types.generated';

describe('Job Poller & API Client Robustness', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('throws JOB_NOT_FOUND error when job returns HTTP 404', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Tác vụ phân tích 'job_123' không tồn tại." }),
    } as unknown as Response);

    await expect(getAnalysisJob('job_123')).rejects.toThrow(/JOB_NOT_FOUND/);
  });

  it('successfully returns JobStatusResponse for running and completed jobs', async () => {
    const mockStatus: JobStatusResponse = {
      job_id: 'job_456',
      status: 'done',
      stage: 'done',
      progress: 1.0,
      progress_percent: 100,
      stage_label: 'Phân tích hoàn tất thành công!',
      created_at: new Date().toISOString(),
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockStatus,
    } as unknown as Response);

    const res = await getAnalysisJob('job_456');
    expect(res.status).toBe('done');
    expect(res.progress_percent).toBe(100);
    expect(res.stage_label).toBe('Phân tích hoàn tất thành công!');
  });

  it('supports starting an analysis job and receiving job_id', async () => {
    const mockStartResponse: AnalyzeJobResponse = {
      job_id: 'job_789',
      status: 'pending',
      stage: 'queued',
      stage_label: 'Đang xếp hàng chờ xử lý...',
      progress_percent: 5,
      poll_url: '/api/v1/jobs/job_789',
      message: 'Tác vụ phân tích đã được khởi tạo thành công.',
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockStartResponse,
    } as unknown as Response);

    const res = await startAnalysisJob({ transcript: 'An: Họp sprint nhé' });
    expect(res.job_id).toBe('job_789');
    expect(res.status).toBe('pending');
    expect(res.stage).toBe('queued');
  });

  it('parses error details when startAnalysisJob fails with 400', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'Biên bản cuộc họp không hợp lệ: Nội dung biên bản cuộc họp trống.' }),
    } as unknown as Response);

    await expect(startAnalysisJob({ transcript: '   ' })).rejects.toThrow(
      'Biên bản cuộc họp không hợp lệ: Nội dung biên bản cuộc họp trống.'
    );
  });
});
