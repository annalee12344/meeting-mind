import { z } from 'zod';
import type {
  ExportPackage,
  MeetingOutput,
  MeetingOverlay,
  ViewTask,
  ViewIssue,
  ViewUnresolvedItem,
} from './types.generated';
import { createEmptyOverlay } from './overlay';

export type {
  ExportPackage,
  MeetingOutput,
  MeetingOverlay,
  ViewTask,
  ViewIssue,
  ViewUnresolvedItem,
};

export interface Evidence {
  speaker: string;
  timestamp?: string | null;
  quote: string;
  utterance_id?: string | null;
  utterance_ids?: string[];
  line_range?: [number, number] | null;
  verified: boolean;
}

export interface HistoryEntry {
  value: string;
  status: string;
  speaker?: string | null;
  utterance_id?: string | null;
  evidence: Evidence[];
}

export interface Decision {
  id?: string;
  item_id?: string;
  source_ref?: string | null;
  topic: string;
  content?: string;
  final_value?: string;
  status: string;
  condition?: string | null;
  proposed_by?: string | null;
  confirmed_by?: string | null;
  history: HistoryEntry[];
  evidence?: Evidence[];
  needs_review: boolean;
}

export interface Action {
  id?: string;
  item_id?: string;
  source_ref?: string | null;
  task?: string;
  title?: string;
  assignee: string | null;
  assigned_by?: string | null;
  requested_by?: string | null;
  deadline?: string | null;
  deadline_raw?: string | null;
  deadline_iso?: string | null;
  dependencies?: string[];
  evidence?: Evidence[];
  needs_review: boolean;
}

export type ActionItem = Action;

export interface Issue {
  id?: string;
  item_id?: string;
  source_ref?: string | null;
  issue?: string;
  content?: string;
  topic?: string;
  owner?: string | null;
  status?: string;
  type?: string;
  from_person?: string | null;
  to_person?: string | null;
  reason_unresolved?: string;
  evidence?: Evidence[];
  needs_review?: boolean;
}

export interface MeetingResult {
  meeting_summary?: string;
  summary?: string;
  participants: string[];
  decisions: Decision[];
  action_items?: Action[];
  tasks?: Action[];
  blockers?: Issue[];
  requests?: Issue[];
  unresolved_items?: Issue[];
  unresolved?: Issue[];
  issues?: Issue[];
  meta?: unknown;
}

export function parseUtterances(text: string) {
  return text.split('\n').filter(line => line.trim()).map((line, index) => {
    const bracketMatch = line.match(/^(?:\[U\d+\]\s*)?\[([^\]]+)\]\s*([^:]+):\s*(.*)$/);
    if (bracketMatch) {
      return {
        id: String(index + 1),
        timestamp: bracketMatch[1] ?? '',
        speaker: bracketMatch[2]?.trim() ?? '',
        text: bracketMatch[3] ?? line,
      };
    }
    const simpleMatch = line.match(/^(?:\[U\d+\]\s*)?([^:]+):\s*(.*)$/);
    if (simpleMatch) {
      return {
        id: String(index + 1),
        timestamp: '',
        speaker: simpleMatch[1]?.trim() ?? '',
        text: simpleMatch[2] ?? line,
      };
    }
    return {
      id: String(index + 1),
      timestamp: '',
      speaker: '',
      text: line,
    };
  });
}

/**
 * Validate whether an unknown value matches MeetingResult (legacy or modern format).
 */
export function isMeetingResult(value: unknown): value is MeetingResult {
  if (!value || typeof value !== 'object') return false;

  const candidate = value as Record<string, unknown>;

  // Case A: ExportPackage wrapper ({ schema_version, result, overlay })
  if (candidate.result && typeof candidate.result === 'object') {
    return isMeetingResult(candidate.result);
  }

  // Case B: Modern MeetingOutput ({ summary, decisions, tasks, unresolved, issues })
  if ('tasks' in candidate && 'decisions' in candidate && Array.isArray(candidate.tasks)) {
    const modernDecision = z.object({
      id: z.string().optional(),
      item_id: z.string().optional(),
      topic: z.string(),
      content: z.string().optional(),
      final_value: z.string().optional(),
      status: z.string(),
    });
    const modernTask = z.object({
      id: z.string().optional(),
      item_id: z.string().optional(),
      title: z.string().optional(),
      task: z.string().optional(),
    });

    const parsed = z
      .object({
        summary: z.string().optional(),
        meeting_summary: z.string().optional(),
        participants: z.array(z.string()),
        decisions: z.array(modernDecision),
        tasks: z.array(modernTask),
      })
      .safeParse(candidate);

    if (parsed.success) return true;
  }

  // Case C: Legacy 5-array format ({ decisions, action_items, blockers, requests, unresolved_items })
  const evidenceSchema = z.object({
    speaker: z.string(),
    timestamp: z.string().nullable().optional(),
    quote: z.string(),
    utterance_id: z.string().nullable().optional(),
    verified: z.boolean().default(false),
  });

  const issueSchema = z.object({
    item_id: z.string().optional(),
    id: z.string().optional(),
    issue: z.string().optional(),
    content: z.string().optional(),
    topic: z.string().optional(),
    owner: z.string().nullable().optional(),
    status: z.string().optional(),
    type: z.string().optional(),
    from_person: z.string().nullable().optional(),
    to_person: z.string().nullable().optional(),
    reason_unresolved: z.string().optional(),
    evidence: z.array(evidenceSchema).optional(),
    needs_review: z.boolean().optional(),
  });

  const legacySchema = z.object({
    meeting_summary: z.string(),
    participants: z.array(z.string()),
    decisions: z.array(
      z.object({
        item_id: z.string().optional(),
        id: z.string().optional(),
        topic: z.string(),
        final_value: z.string().optional(),
        content: z.string().optional(),
        status: z.string(),
        condition: z.string().nullable().optional(),
        needs_review: z.boolean().default(false),
        history: z
          .array(
            z.object({
              value: z.string(),
              status: z.string(),
              evidence: z.array(evidenceSchema).default([]),
            })
          )
          .default([]),
      })
    ),
    action_items: z.array(
      z.object({
        item_id: z.string().optional(),
        id: z.string().optional(),
        task: z.string().optional(),
        title: z.string().optional(),
        assignee: z.string().nullable().optional(),
        deadline: z.string().nullable().optional(),
        dependencies: z.array(z.string()).default([]),
        evidence: z.array(evidenceSchema).default([]),
        needs_review: z.boolean().default(false),
      })
    ),
    blockers: z.array(issueSchema).default([]),
    requests: z.array(issueSchema).default([]),
    unresolved_items: z.array(issueSchema).default([]),
  });

  return legacySchema.safeParse(candidate).success;
}

/**
 * Checks if value is an ExportPackage containing AI result + user overlay.
 */
export function isExportPackage(value: unknown): value is ExportPackage {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.schema_version !== undefined &&
    candidate.result !== undefined &&
    typeof candidate.result === 'object' &&
    candidate.overlay !== undefined &&
    typeof candidate.overlay === 'object'
  );
}

/**
 * Checks if value is the legacy 5-array format that needs upgrading.
 */
export function isLegacyMeetingFormat(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return (
    'action_items' in candidate &&
    ('blockers' in candidate || 'requests' in candidate || 'unresolved_items' in candidate)
  );
}

/**
 * Standard Export function: saves JSON bundling immutable AI result + mutable user overlay.
 * Fixes export bug where user-edited tasks/status/notes were lost.
 */
export function exportMeeting(
  result: MeetingResult | MeetingOutput,
  name: string,
  overlay?: MeetingOverlay | null,
  transcript?: string | null
) {
  // Normalize result to MeetingOutput-compatible structure
  const meetingId =
    overlay?.meeting_id ||
    (result as MeetingOutput).meta?.transcript_hash ||
    (result.decisions && result.decisions[0]?.id) ||
    'meeting-mind';

  const effectiveOverlay: MeetingOverlay = overlay || createEmptyOverlay(meetingId);

  const exportPackage: ExportPackage = {
    schema_version: '2.0.0',
    exported_at: new Date().toISOString(),
    meeting_name: name || 'Meeting Mind Analysis',
    transcript: transcript || null,
    result: result as MeetingOutput,
    overlay: effectiveOverlay,
  };

  const url = URL.createObjectURL(
    new Blob([JSON.stringify(exportPackage, null, 2)], { type: 'application/json' })
  );
  const link = document.createElement('a');
  link.href = url;
  const safeName = name.trim().replace(/[^\p{L}\p{N}-]+/gu, '-') || 'meeting-mind';
  link.download = `${safeName}.json`;
  link.click();
  URL.revokeObjectURL(url);
}