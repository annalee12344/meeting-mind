"""
Generate TypeScript types from FastAPI OpenAPI schema and Pydantic models.

Outputs to: meeting-muse-56/src/lib/types.generated.ts
Ensures frontend and backend types remain strictly in sync without drift.
"""
from pathlib import Path
import sys

# Add root directory to python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import app
from models.output import (
    Evidence,
    HistoryEntry,
    PublicDecision,
    PublicTask,
    PublicUnresolvedItem,
    PublicIssue,
    IssueNote,
    PublicMeta,
    MeetingOutput,
)
from models.overlay import (
    TaskOverlay,
    UnresolvedOverlay,
    IssueOverlay,
    MeetingOverlay,
    ViewTask,
    ViewUnresolvedItem,
    ViewIssue,
    MeetingViewModel,
    ExportPackage,
)
from models.jobs import (
    JobStage,
    JobStatus,
    JobStatusResponse,
    AnalyzeJobResponse,
)

TARGET_FILE = Path(__file__).parent.parent / "meeting-muse-56" / "src" / "lib" / "types.generated.ts"

TS_HEADER = """/**
 * AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY.
 * Generated from backend FastAPI OpenAPI / Pydantic models via scripts/generate_types.py.
 * Run `python scripts/generate_types.py` to regenerate.
 */

"""

def pydantic_to_ts():
    lines = [TS_HEADER]

    # Job stages & statuses
    lines.append("// ─────────────────────────────────────────────────────────────────────────────")
    lines.append("// Job Status & Stages")
    lines.append("// ─────────────────────────────────────────────────────────────────────────────\n")

    lines.append("export type JobStage = 'queued' | 'preprocessing' | 'extracting' | 'resolving' | 'validating' | 'mapping' | 'done' | 'failed' | 'cancelled';\n")
    lines.append("export type JobStatus = 'pending' | 'processing' | 'done' | 'completed' | 'failed' | 'cancelled';\n")

    lines.append("""export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  stage: JobStage;
  progress?: number;
  progress_percent: number;
  stage_message?: string;
  stage_label: string;
  detail_message?: string | null;
  error_code?: string | null;
  error?: string | null;
  friendly_error?: string | null;
  created_at: string;
  updated_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  result?: MeetingOutput | null;
}

export interface AnalyzeJobResponse {
  job_id: string;
  status: JobStatus;
  stage?: JobStage;
  stage_label?: string;
  progress_percent?: number;
  poll_url?: string;
  message: string;
}
""")

    # Evidence and core AI Output models
    lines.append("// ─────────────────────────────────────────────────────────────────────────────")
    lines.append("// Immutable AI Pipeline Output Layer (MeetingOutput)")
    lines.append("// ─────────────────────────────────────────────────────────────────────────────\n")

    lines.append("""export interface Evidence {
  id?: string;
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

export interface PublicDecision {
  id: string;
  source_ref?: string | null;
  topic: string;
  content: string;
  proposed_by?: string | null;
  confirmed_by?: string | null;
  status: string;
  condition?: string | null;
  history: HistoryEntry[];
  evidence: Evidence[];
  needs_review: boolean;
}

export interface PublicTask {
  id: string;
  source_ref?: string | null;
  title: string;
  assignee?: string | null;
  assigned_by?: string | null;
  requested_by?: string | null;
  deadline_raw?: string | null;
  deadline_iso?: string | null;
  source: 'ai' | 'manual' | 'from_unresolved';
  evidence: Evidence[];
  needs_review: boolean;
  external_dependency?: string | null;
  collaborator?: string | null;
  reviewer?: string | null;
  escalation?: string | null;
}

export interface PublicUnresolvedItem {
  id: string;
  source_ref?: string | null;
  kind: 'open_decision' | 'unconfirmed_task';
  content: string;
  reason_unresolved?: string | null;
  suggested_assignee?: string | null;
  suggested_deadline_raw?: string | null;
  suggested_deadline_iso?: string | null;
  evidence: Evidence[];
  needs_review: boolean;
}

export interface IssueNote {
  id: string;
  issue_id: string;
  author_id: string;
  author_name: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface PublicIssue {
  id: string;
  source_ref?: string | null;
  content: string;
  owner?: string | null;
  status: 'open' | 'resolved';
  evidence: Evidence[];
  notes: IssueNote[];
  needs_review: boolean;
}

export interface PublicMeta {
  schema_version: string;
  prompt_version: string;
  extractor_model: string;
  resolver_model: string;
  analyzed_at: string;
  transcript_hash: string;
  meeting_date: string;
  meeting_date_source: 'user' | 'transcript' | 'fallback_today';
}

export interface MeetingOutput {
  summary: string;
  participants: string[];
  decisions: PublicDecision[];
  tasks: PublicTask[];
  unresolved: PublicUnresolvedItem[];
  issues: PublicIssue[];
  meta: PublicMeta;
}
""")

    # User Overlay models
    lines.append("// ─────────────────────────────────────────────────────────────────────────────")
    lines.append("// Mutable User Overlay Layer (MeetingOverlay)")
    lines.append("// ─────────────────────────────────────────────────────────────────────────────\n")

    lines.append("""export interface TaskOverlay {
  title?: string | null;
  assignee?: string | null;
  deadline_raw?: string | null;
  deadline_iso?: string | null;
  status?: 'open' | 'done' | null;
  completed_at?: string | null;
  updated_at: string;
}

export interface UnresolvedOverlay {
  status?: 'open' | 'converted' | null;
  suggested_assignee?: string | null;
  suggested_deadline_raw?: string | null;
  suggested_deadline_iso?: string | null;
  converted_to_task_id?: string | null;
  updated_at: string;
}

export interface IssueOverlay {
  status?: 'open' | 'resolved' | null;
  updated_at: string;
}

export interface MeetingOverlay {
  schema_version: string;
  meeting_id: string;
  transcript_hash?: string | null;
  tasks: Record<string, TaskOverlay>;
  manual_tasks: ViewTask[];
  deleted_task_ids: string[];
  unresolved: Record<string, UnresolvedOverlay>;
  deleted_unresolved_ids: string[];
  issues: Record<string, IssueOverlay>;
  issue_notes: IssueNote[];
  deleted_issue_ids: string[];
  updated_at: string;
}
""")

    # View Models (Merged layer consumed by UI)
    lines.append("// ─────────────────────────────────────────────────────────────────────────────")
    lines.append("// Unified View Models (Merged AI Layer + Overlay)")
    lines.append("// ─────────────────────────────────────────────────────────────────────────────\n")

    lines.append("""export interface ViewTask {
  id: string;
  meeting_id?: string;
  source_ref?: string | null;
  title: string;
  assignee?: string | null;
  assigned_by?: string | null;
  requested_by?: string | null;
  deadline_raw?: string | null;
  deadline_iso?: string | null;
  status: 'open' | 'done';
  source: 'ai' | 'manual' | 'from_unresolved';
  evidence: Evidence[];
  needs_review: boolean;
  external_dependency?: string | null;
  collaborator?: string | null;
  reviewer?: string | null;
  escalation?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface ViewUnresolvedItem {
  id: string;
  meeting_id?: string;
  source_ref?: string | null;
  kind: 'open_decision' | 'unconfirmed_task';
  content: string;
  reason_unresolved?: string | null;
  suggested_assignee?: string | null;
  suggested_deadline_raw?: string | null;
  suggested_deadline_iso?: string | null;
  status: 'open' | 'converted';
  evidence: Evidence[];
  needs_review: boolean;
}

export interface ViewIssue {
  id: string;
  meeting_id?: string;
  source_ref?: string | null;
  content: string;
  owner?: string | null;
  status: 'open' | 'resolved';
  evidence: Evidence[];
  notes: IssueNote[];
  needs_review: boolean;
}

export interface MeetingViewModel {
  meeting_id: string;
  summary: string;
  participants: string[];
  decisions: PublicDecision[];
  tasks: ViewTask[];
  unresolved: ViewUnresolvedItem[];
  issues: ViewIssue[];
  meta: PublicMeta;
  overlay: MeetingOverlay;
}

export interface ExportPackage {
  schema_version: string;
  exported_at: string;
  meeting_name: string;
  transcript?: string | null;
  result: MeetingOutput;
  overlay: MeetingOverlay;
}
""")

    # Catalog & API response models
    lines.append("// ─────────────────────────────────────────────────────────────────────────────")
    lines.append("// Server Catalog & Health Responses")
    lines.append("// ─────────────────────────────────────────────────────────────────────────────\n")

    lines.append("""export interface HealthResponse {
  status: string;
  model: string;
  gemini_configured: boolean;
}

export interface SampleSummary {
  id: string;
  alt_id?: string;
  title: string;
  name: string;
  filename: string;
  description: string;
}

export interface SampleDetail extends SampleSummary {
  transcript: string;
}
""")

    content = "\n".join(lines)
    TARGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    TARGET_FILE.write_text(content, encoding="utf-8")
    print(f"Generated TypeScript types at: {TARGET_FILE}")


if __name__ == "__main__":
    pydantic_to_ts()
