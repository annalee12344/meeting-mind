"""
Final output schema — Structured meeting data.

This is the ultimate output of the pipeline after progression resolution.
Each item links back to evidence (verbatim quotes from the transcript)
and decisions include their full progression history showing how opinions
changed during the meeting.

Schema design principles (from user's architecture):
- decisions contain the FINAL conclusion, not every proposal as if all valid
- history preserves the progression with evidence for each step
- status is NOT automatically 'confirmed' just because something was said last;
  if the meeting didn't conclude, status must be 'unresolved'
- unresolved_items distinguish between "not concluded in meeting" and
  "AI lacks evidence to classify" via needs_review flag
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from enum import Enum


class ItemStatus(str, Enum):
    """Status of an information item after progression resolution."""
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


class Evidence(BaseModel):
    """A piece of evidence linking back to the original transcript."""
    speaker: str
    timestamp: Optional[str] = None
    quote: str = Field(description="Exact quote from transcript")
    utterance_id: Optional[str] = Field(
        default=None, description="Reference to extracted utterance ID from Step 1"
    )
    verified: bool = Field(
        default=False,
        description="Set to True after Python verification confirms quote exists in transcript",
    )


class HistoryEntry(BaseModel):
    """One step in the progression of a decision."""
    value: str = Field(description="The proposed/changed value at this step")
    status: ItemStatus
    evidence: list[Evidence]

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> ItemStatus:
        return _normalize_item_status(v)


class Decision(BaseModel):
    """A decision made (or changed) during the meeting."""
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
    """A task assigned to someone during the meeting."""
    item_id: str = Field(description="e.g. A001")
    task: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    evidence: list[Evidence]
    needs_review: bool = False


class Blocker(BaseModel):
    """An issue or blocker raised during the meeting."""
    item_id: str = Field(description="e.g. B001")
    issue: str
    owner: Optional[str] = None
    status: ItemStatus
    evidence: list[Evidence]
    needs_review: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> ItemStatus:
        return _normalize_item_status(v)


class Request(BaseModel):
    """A request or feedback item from the meeting."""
    item_id: str = Field(description="e.g. R001")
    type: str = Field(description="'request' or 'feedback'")
    content: str
    from_person: Optional[str] = None
    to_person: Optional[str] = None
    evidence: list[Evidence]
    needs_review: bool = False


class UnresolvedItem(BaseModel):
    """An item discussed but not resolved in the meeting."""
    item_id: str = Field(description="e.g. UR001")
    topic: str
    reason_unresolved: str
    evidence: list[Evidence]
    needs_review: bool = False


class MeetingOutput(BaseModel):
    """Complete structured output of the meeting analysis pipeline."""
    meeting_summary: str = Field(description="2-3 sentence summary of the meeting")
    participants: list[str] = Field(description="List of identified participants")
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    requests: list[Request] = Field(default_factory=list)
    unresolved_items: list[UnresolvedItem] = Field(default_factory=list)
