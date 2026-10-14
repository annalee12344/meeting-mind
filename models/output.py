"""
Output schema module for Meeting Mind.

Contains:
1. Internal models (ResolvedResult): 5-array structure produced by Step 2 Resolver
   and verified by Step 3 Validator (decisions, action_items, blockers, requests, unresolved_items).
2. Public models (MeetingOutput): 4-group structure produced by the deterministic mapper
   (decisions, tasks, unresolved, issues) plus metadata and UUIDs.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Literal, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# 1. Internal Enums and Shared Models (Used by Step 2 & Step 3)
# ─────────────────────────────────────────────────────────────────────────────

class ItemStatus(str, Enum):
    """Status of an information item in the internal Step 2 result."""
    CONFIRMED = "confirmed"          # Đã chốt, có hiệu lực
    SUPERSEDED = "superseded"        # Đã bị thay thế bởi quyết định khác
    UNRESOLVED = "unresolved"        # Chưa được giải quyết trong cuộc họp
    NEEDS_REVIEW = "needs_review"    # AI không đủ bằng chứng để xác định


_STATUS_NORM_MAP: dict[str, ItemStatus] = {
    "confirmed": ItemStatus.CONFIRMED,
    "chốt": ItemStatus.CONFIRMED,
    "done": ItemStatus.CONFIRMED,
    "resolved": ItemStatus.CONFIRMED,
    "superseded": ItemStatus.SUPERSEDED,
    "thay thế": ItemStatus.SUPERSEDED,
    "unresolved": ItemStatus.UNRESOLVED,
    "chưa chốt": ItemStatus.UNRESOLVED,
    "open": ItemStatus.UNRESOLVED,
    "pending": ItemStatus.UNRESOLVED,
    "needs_review": ItemStatus.NEEDS_REVIEW,
}


def _normalize_item_status(v: Any) -> ItemStatus:
    if isinstance(v, ItemStatus):
        return v
    if isinstance(v, str):
        clean = v.strip().lower()
        if clean in _STATUS_NORM_MAP:
            return _STATUS_NORM_MAP[clean]
        for member in ItemStatus:
            if member.value == clean:
                return member
    return ItemStatus.UNRESOLVED


def generate_uuid() -> str:
    """Generate a stable standard UUID4 string for items and evidence."""
    return str(uuid4())


class Evidence(BaseModel):
    """A piece of evidence linking back to the original transcript."""
    id: str = Field(default_factory=generate_uuid, description="Unique evidence UUID")
    speaker: str
    timestamp: Optional[str] = None
    quote: str = Field(description="Exact quote from transcript")
    utterance_id: Optional[str] = Field(
        default=None, description="Reference to extracted utterance ID from Step 1"
    )
    line_range: Optional[Tuple[int, int]] = Field(
        default=None, description="Start and end line numbers in transcript"
    )
    verified: bool = Field(
        default=False,
        description="Set to True after Python verification confirms quote exists in transcript",
    )
    speaker_matched: Optional[bool] = Field(
        default=None,
        description="True if cited utterance's speaker matches evidence speaker",
    )
    corrected_utterance_id: Optional[str] = Field(
        default=None,
        description="Populated if validator corrected a mismatched utterance_id",
    )


class HistoryEntry(BaseModel):
    """One step in the progression of a decision."""
    value: str = Field(description="The proposed/changed value at this step")
    status: ItemStatus
    evidence: list[Evidence] = Field(default_factory=list)
    role: Optional[str] = Field(
        default=None,
        description="Role of this history step: proposes, confirms, supersedes, etc.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> ItemStatus:
        return _normalize_item_status(v)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Internal Output Models (Step 2 Result)
# ─────────────────────────────────────────────────────────────────────────────

class Decision(BaseModel):
    """A decision made (or changed) during the meeting (Internal Step 2)."""
    item_id: str = Field(description="e.g. D001")
    topic: str
    final_value: str
    status: ItemStatus
    condition: Optional[str] = None
    history: list[HistoryEntry] = Field(default_factory=list)
    needs_review: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> ItemStatus:
        return _normalize_item_status(v)


class ActionItem(BaseModel):
    """A task assigned during the meeting (Internal Step 2)."""
    item_id: str = Field(description="e.g. A001")
    task: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False
    # Task acceptance fields (Section 3)
    assignee_confirmed: bool = Field(
        default=False,
        description="True if the assignee verbally confirmed or accepted taking the task",
    )
    confirmation_utterance_id: Optional[str] = Field(
        default=None,
        description="ID of the utterance where the assignee accepted/confirmed",
    )
    assigned_by: Optional[str] = Field(
        default=None,
        description="Speaker who assigned the task, if different from assignee",
    )


class Blocker(BaseModel):
    """An issue or blocker raised during the meeting (Internal Step 2)."""
    item_id: str = Field(description="e.g. B001")
    issue: str
    owner: Optional[str] = None
    status: ItemStatus = ItemStatus.UNRESOLVED
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> ItemStatus:
        return _normalize_item_status(v)


class Request(BaseModel):
    """A request or feedback item from the meeting (Internal Step 2)."""
    item_id: str = Field(description="e.g. R001")
    type: str = Field(description="'request' or 'feedback'")
    content: str
    from_person: Optional[str] = None
    to_person: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False


class UnresolvedItem(BaseModel):
    """An item discussed but not resolved in the meeting (Internal Step 2)."""
    item_id: str = Field(description="e.g. UR001")
    topic: str
    reason_unresolved: str
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False


class ResolvedResult(BaseModel):
    """Internal 5-array output generated by Step 2 Resolver and verified by Step 3."""
    meeting_summary: str = Field(description="2-3 sentence summary of the meeting")
    participants: list[str] = Field(description="List of identified participants")
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    requests: list[Request] = Field(default_factory=list)
    unresolved_items: list[UnresolvedItem] = Field(default_factory=list)


# Alias for backward compatibility with existing tests and scripts
InternalMeetingOutput = ResolvedResult


# ─────────────────────────────────────────────────────────────────────────────
# 3. Public Output Models (Section 1: 4 Target Groups + Metadata)
# ─────────────────────────────────────────────────────────────────────────────

class IssueNote(BaseModel):
    """A user note attached to an issue."""
    id: str = Field(default_factory=generate_uuid, description="Unique note UUID")
    issue_id: str = Field(description="Referenced issue UUID")
    author_id: str = Field(default="user_local", description="Author identifier")
    author_name: str = Field(default="You", description="Author display name")
    content: str = Field(description="Note content text")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 last update timestamp",
    )


class PublicDecision(BaseModel):
    """Confirmed decision in the public output."""
    id: str = Field(default_factory=generate_uuid, description="Unique item UUID")
    source_ref: Optional[str] = Field(default=None, description="Original LLM item ID, e.g. D001")
    topic: str
    content: str = Field(description="Final confirmed decision content")
    proposed_by: Optional[str] = Field(default=None, description="Speaker who proposed the idea")
    confirmed_by: Optional[str] = Field(default=None, description="Speaker who finalized/confirmed")
    evidence: list[Evidence] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list, description="Decision Trail")
    needs_review: bool = False


class PublicTask(BaseModel):
    """Confirmed task in the public output."""
    id: str = Field(default_factory=generate_uuid, description="Unique item UUID")
    source_ref: Optional[str] = Field(default=None, description="Original LLM item ID, e.g. A001")
    title: str
    assignee: Optional[str] = Field(default=None, description="Confirmed person responsible")
    assigned_by: Optional[str] = Field(default=None, description="Speaker who assigned this task")
    requested_by: Optional[str] = Field(default=None, description="Original requester if from request")
    deadline_raw: Optional[str] = Field(default=None, description="Original text deadline from transcript")
    deadline_iso: Optional[str] = Field(default=None, description="Normalized ISO 8601 date (YYYY-MM-DD)")
    source: Literal["ai", "from_unresolved", "manual"] = Field(
        default="ai", description="Origin of this task"
    )
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False


class PublicUnresolvedItem(BaseModel):
    """Unresolved topic or unconfirmed task in public output."""
    id: str = Field(default_factory=generate_uuid, description="Unique item UUID")
    source_ref: Optional[str] = Field(default=None, description="Original LLM item ID, e.g. UR001")
    kind: Literal["open_decision", "unconfirmed_task"] = Field(
        description="Whether this is an unmade decision or an unaccepted/unassigned task"
    )
    content: str
    reason_unresolved: Optional[str] = None
    suggested_assignee: Optional[str] = Field(
        default=None, description="Named person who was assigned but has not confirmed"
    )
    suggested_deadline_raw: Optional[str] = None
    suggested_deadline_iso: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False


class PublicIssue(BaseModel):
    """Issue / Blocker in public output."""
    id: str = Field(default_factory=generate_uuid, description="Unique item UUID")
    source_ref: Optional[str] = Field(default=None, description="Original LLM item ID, e.g. B001")
    content: str
    owner: Optional[str] = None
    status: Literal["open", "resolved"] = "open"
    evidence: list[Evidence] = Field(default_factory=list)
    notes: list[IssueNote] = Field(default_factory=list, description="User notes on this issue")
    needs_review: bool = False


class PublicMeta(BaseModel):
    """Metadata describing the analysis execution, schema version, and date resolution."""
    schema_version: str = "2.0.0"
    prompt_version: str = "2.0.0"
    per_step_model: dict[str, str] = Field(default_factory=dict)
    analyzed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    transcript_hash: str = ""
    meeting_date: Optional[str] = None
    meeting_date_source: Literal["user", "transcript", "fallback_today"] = "fallback_today"


class MeetingOutput(BaseModel):
    """
    Public output model for Meeting Mind.
    Organizes results into 4 groups: Decisions, Tasks, Unresolved, Issues, plus metadata.
    """
    model_config = ConfigDict(populate_by_name=True)

    summary: str = Field(
        description="2-3 sentence summary of the meeting",
        alias="meeting_summary",
    )
    participants: list[str] = Field(default_factory=list)
    decisions: list[PublicDecision] = Field(default_factory=list)
    tasks: list[PublicTask] = Field(default_factory=list)
    unresolved: list[PublicUnresolvedItem] = Field(default_factory=list)
    issues: list[PublicIssue] = Field(default_factory=list)
    meta: PublicMeta = Field(default_factory=PublicMeta)

    @property
    def meeting_summary(self) -> str:
        """Alias property for backward compatibility."""
        return self.summary
