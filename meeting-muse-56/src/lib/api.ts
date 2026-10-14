import type {
  AnalyzeJobResponse,
  HealthResponse,
  JobStatusResponse,
  MeetingOutput,
  SampleDetail,
  SampleSummary,
} from './types.generated';

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.VITE_API_URL as string | undefined) ||
  'http://localhost:8000';

export type { HealthResponse, SampleSummary, SampleDetail, JobStatusResponse, AnalyzeJobResponse };

export interface AnalyzePayload {
  transcript: string;
  meeting_name?: string;
  meeting_date?: string;
  sample_id?: string;
  use_sample_cache?: boolean;
  language?: string;
  threshold?: number;
}

/**
 * Check if the backend API server is online and report configuration status.
 */
export async function checkApiHealth(): Promise<HealthResponse> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/health`);
    if (!res.ok) {
      // Fallback to legacy path if v1 not present
      const fallbackRes = await fetch(`${API_BASE_URL}/api/health`);
      if (!fallbackRes.ok) {
        throw new Error(`API health check returned status ${fallbackRes.status}`);
      }
      return await fallbackRes.json();
    }
    return await res.json();
  } catch (err) {
    throw new Error(
      `Cannot connect to Meeting Mind API server at ${API_BASE_URL}. Ensure the Python backend is running.`
    );
  }
}

/**
 * Fetch available sample transcripts from the backend.
 */
export async function fetchSamples(): Promise<SampleSummary[]> {
  try {
    let res = await fetch(`${API_BASE_URL}/api/v1/samples`);
    if (!res.ok) {
      res = await fetch(`${API_BASE_URL}/api/samples`);
    }
    if (!res.ok) {
      throw new Error(`Failed to fetch samples list (status ${res.status})`);
    }
    return await res.json();
  } catch (err) {
    console.warn('API samples endpoint unavailable:', err);
    throw err;
  }
}

/**
 * Fetch a specific sample transcript by its id or filename.
 */
export async function fetchSample(sampleId: string): Promise<SampleDetail> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/samples/${encodeURIComponent(sampleId)}`);
    if (!res.ok) {
      res = await fetch(`${API_BASE_URL}/api/samples/${encodeURIComponent(sampleId)}`);
    }
  } catch (err) {
    throw new Error(
      `Cannot connect to Meeting Mind API server at ${API_BASE_URL}. Ensure the Python backend is running.`
    );
  }

  if (!res.ok) {
    let msg = `Failed to load sample transcript (${res.status})`;
    try {
      const errJson = await res.json();
      if (errJson.detail) msg = errJson.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return await res.json();
}

/**
 * Fetch precomputed verified benchmark results for a sample (0 API calls, instant response).
 */
export async function fetchSampleResult(sampleId: string, threshold?: number): Promise<MeetingOutput> {
  let res: Response;
  const url = threshold
    ? `${API_BASE_URL}/api/v1/samples/${encodeURIComponent(sampleId)}/result?threshold=${threshold}`
    : `${API_BASE_URL}/api/v1/samples/${encodeURIComponent(sampleId)}/result`;

  try {
    res = await fetch(url);
    if (!res.ok) {
      const legacyUrl = threshold
        ? `${API_BASE_URL}/api/samples/${encodeURIComponent(sampleId)}/result?threshold=${threshold}`
        : `${API_BASE_URL}/api/samples/${encodeURIComponent(sampleId)}/result`;
      res = await fetch(legacyUrl);
    }
  } catch (err) {
    throw new Error(
      `Cannot connect to Meeting Mind API server at ${API_BASE_URL}. Ensure the Python backend is running.`
    );
  }

  if (!res.ok) {
    let msg = `Failed to load sample results (${res.status})`;
    try {
      const errJson = await res.json();
      if (errJson.detail) msg = errJson.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return (await res.json()) as MeetingOutput;
}

/**
 * Start asynchronous analysis job (API v1).
 * Returns job_id and stage immediately without blocking.
 */
export async function startAnalysisJob(payload: AnalyzePayload): Promise<AnalyzeJobResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    throw new Error(
      `Cannot connect to Meeting Mind API at ${API_BASE_URL}. Please ensure the Python backend is running.`
    );
  }

  if (!res.ok) {
    let errorDetail = `Failed to start analysis job (status ${res.status})`;
    try {
      const errorJson = await res.json();
      if (errorJson.detail) errorDetail = errorJson.detail;
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }

  return (await res.json()) as AnalyzeJobResponse;
}

/**
 * Poll progress and stage of an asynchronous analysis job.
 */
export async function getAnalysisJob(jobId: string): Promise<JobStatusResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/jobs/${encodeURIComponent(jobId)}`);
  } catch (err) {
    throw new Error(`Cannot reach server to poll job ${jobId}.`);
  }

  if (!res.ok) {
    if (res.status === 404) {
      throw new Error(
        'JOB_NOT_FOUND: Tác vụ phân tích không tồn tại trên máy chủ (máy chủ có thể đã khởi động lại). Vui lòng thử lại.'
      );
    }
    let msg = `Job status check failed (${res.status})`;
    try {
      const errJson = await res.json();
      if (errJson.detail) msg = errJson.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }

  return (await res.json()) as JobStatusResponse;
}

/**
 * Request cancellation of a running analysis job.
 */
export async function cancelAnalysisJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Failed to cancel job ${jobId}: status ${res.status}`);
  }
  return (await res.json()) as JobStatusResponse;
}

/**
 * Upgrade legacy 5-array export format to modern MeetingOutput schema.
 */
export async function upgradeLegacyResult(legacyData: unknown, meetingDate?: string): Promise<MeetingOutput> {
  const url = meetingDate
    ? `${API_BASE_URL}/api/v1/legacy/upgrade?meeting_date=${encodeURIComponent(meetingDate)}`
    : `${API_BASE_URL}/api/v1/legacy/upgrade`;

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(legacyData),
  });

  if (!res.ok) {
    let msg = `Nâng cấp định dạng biên bản thất bại (${res.status})`;
    try {
      const errJson = await res.json();
      if (errJson.detail) msg = errJson.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }

  return (await res.json()) as MeetingOutput;
}

/**
 * Legacy synchronous analysis fallback.
 */
export async function analyzeTranscript(payload: AnalyzePayload): Promise<MeetingOutput> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    throw new Error(
      `Cannot connect to Meeting Mind API at ${API_BASE_URL}. Please ensure the Python backend is running.`
    );
  }

  if (!res.ok) {
    let errorDetail = `Analysis failed (status ${res.status})`;
    try {
      const errorJson = await res.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }

  const data = await res.json();
  return data as MeetingOutput;
}

/**
 * Clear in-memory analysis cache.
 */
export async function clearCache(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cache/clear`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Failed to clear cache: status ${res.status}`);
  }
  return await res.json();
}
