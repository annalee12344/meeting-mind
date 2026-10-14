"""
Step 1 output schema — Extracted utterances from transcript.

Each utterance represents one meaningful piece of information identified
by the LLM during the first pass. The LLM classifies each utterance by
its type (decision, action_item, etc.) and its role in the discussion
flow (proposes, supports, rejects, confirms, etc.).

This intermediate representation is fed into Step 2 (resolution) where
utterances on the same topic are grouped and their progression is resolved.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from enum import Enum


class UtteranceRole(str, Enum):
    """Role of the utterance in the meeting discussion flow."""
    PROPOSES = "proposes"        # Đề xuất ý kiến / phương án mới
    SUPPORTS = "supports"        # Đồng ý / ủng hộ ý kiến trước đó
    REJECTS = "rejects"          # Phản đối / bác bỏ
    SUPERSEDES = "supersedes"    # Thay thế / đề xuất phương án khác thay cho cái cũ
    CONFIRMS = "confirms"        # Chốt / xác nhận quyết định cuối cùng
    CONDITIONS = "conditions"    # Đặt điều kiện cho quyết định
    INFORMS = "informs"          # Cung cấp thông tin / tri thức
    REQUESTS = "requests"        # Yêu cầu ai đó thực hiện điều gì
    ASSIGNS = "assigns"          # Giao việc cụ thể cho ai đó
    QUESTIONS = "questions"      # Đặt câu hỏi / nêu vấn đề
    REPORTS = "reports"          # Báo cáo tiến độ / tình trạng


class UtteranceType(str, Enum):
    """Type of information contained in the utterance."""
    DECISION = "decision"
    ACTION_ITEM = "action_item"
    BLOCKER = "blocker"
    REQUEST = "request"
    FEEDBACK = "feedback"
    INFORMATION = "information"
    UNRESOLVED = "unresolved"


# Fallback & normalization mappings when LLM mixes up type and role
_TYPE_NORM_MAP: dict[str, UtteranceType] = {
    "decision": UtteranceType.DECISION,
    "action_item": UtteranceType.ACTION_ITEM,
    "action": UtteranceType.ACTION_ITEM,
    "task": UtteranceType.ACTION_ITEM,
    "blocker": UtteranceType.BLOCKER,
    "risk": UtteranceType.BLOCKER,
    "issue": UtteranceType.BLOCKER,
    "request": UtteranceType.REQUEST,
    "feedback": UtteranceType.FEEDBACK,
    "information": UtteranceType.INFORMATION,
    "info": UtteranceType.INFORMATION,
    "unresolved": UtteranceType.UNRESOLVED,
    # Roles mistakenly returned as types:
    "proposes": UtteranceType.DECISION,
    "supports": UtteranceType.DECISION,
    "rejects": UtteranceType.DECISION,
    "supersedes": UtteranceType.DECISION,
    "confirms": UtteranceType.DECISION,
    "conditions": UtteranceType.DECISION,
    "assigns": UtteranceType.ACTION_ITEM,
    "reports": UtteranceType.INFORMATION,
    "informs": UtteranceType.INFORMATION,
    "questions": UtteranceType.UNRESOLVED,
    "requests": UtteranceType.REQUEST,
}

_ROLE_NORM_MAP: dict[str, UtteranceRole] = {
    "proposes": UtteranceRole.PROPOSES,
    "supports": UtteranceRole.SUPPORTS,
    "rejects": UtteranceRole.REJECTS,
    "supersedes": UtteranceRole.SUPERSEDES,
    "confirms": UtteranceRole.CONFIRMS,
    "conditions": UtteranceRole.CONDITIONS,
    "informs": UtteranceRole.INFORMS,
    "requests": UtteranceRole.REQUESTS,
    "assigns": UtteranceRole.ASSIGNS,
    "questions": UtteranceRole.QUESTIONS,
    "reports": UtteranceRole.REPORTS,
    # Types mistakenly returned as roles:
    "decision": UtteranceRole.CONFIRMS,
    "action_item": UtteranceRole.ASSIGNS,
    "action": UtteranceRole.ASSIGNS,
    "blocker": UtteranceRole.REPORTS,
    "information": UtteranceRole.INFORMS,
    "request": UtteranceRole.REQUESTS,
    "feedback": UtteranceRole.SUPPORTS,
    "unresolved": UtteranceRole.QUESTIONS,
}


class ExtractedUtterance(BaseModel):
    """A single meaningful utterance extracted from the transcript."""
    id: str = Field(description="Utterance ID, e.g. U001, U002")
    speaker: str = Field(description="Name of the speaker")
    timestamp: Optional[str] = Field(
        default=None, description="Timestamp if available, e.g. '09:10'"
    )
    quote: str = Field(
        description="Exact quote from transcript — must be verbatim, not paraphrased"
    )
    topic: str = Field(
        description="Short topic label this utterance relates to"
    )
    type: UtteranceType = Field(description="What type of information this is")
    role: UtteranceRole = Field(description="Role in the discussion flow")
    references: list[str] = Field(
        default_factory=list,
        description="IDs of other utterances this one responds to or relates to",
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v: Any) -> UtteranceType:
        if isinstance(v, UtteranceType):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in _TYPE_NORM_MAP:
                return _TYPE_NORM_MAP[clean]
            for member in UtteranceType:
                if member.value == clean:
                    return member
        return UtteranceType.INFORMATION

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: Any) -> UtteranceRole:
        if isinstance(v, UtteranceRole):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in _ROLE_NORM_MAP:
                return _ROLE_NORM_MAP[clean]
            for member in UtteranceRole:
                if member.value == clean:
                    return member
        return UtteranceRole.INFORMS


class ExtractionResult(BaseModel):
    """Complete output of Step 1 — all extracted utterances from a transcript."""
    utterances: list[ExtractedUtterance] = Field(
        description="All meaningful utterances extracted from the transcript"
    )
