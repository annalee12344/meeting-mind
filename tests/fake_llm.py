"""
Fake LLM Client for Deterministic and Offline Testing.

Simulates Gemini API responses, errors, retries, and schema validation
without making actual network calls.
"""
from typing import Any, Dict, List, Optional, Type, TypeVar
import json

from pydantic import BaseModel

from pipeline.llm_client import (
    LLMAuthError,
    LLMClient,
    LLMError,
    LLMInvalidOutputError,
    LLMRateLimitError,
    LLMSafetyError,
    LLMTimeoutError,
    LLMValidationError,
)
from models.intermediate import ExtractionResult, ExtractedUtterance, UtteranceRole, UtteranceType
from models.output import (
    ActionItem,
    Blocker,
    Decision,
    Evidence,
    HistoryEntry,
    ItemStatus,
    Request,
    ResolvedResult,
    UnresolvedItem,
)

T = TypeVar("T", bound=BaseModel)


def create_minimal_extraction_result() -> ExtractionResult:
    """Create a minimal valid ExtractionResult for test pipelines."""
    return ExtractionResult(
        utterances=[
            ExtractedUtterance(
                id="U001",
                speaker="An",
                timestamp="09:00",
                topic="Kế hoạch phát hành",
                type=UtteranceType.DECISION,
                role=UtteranceRole.CONFIRMS,
                quote="Chốt ngày phát hành là 25/12/2026.",
                references=[],
            ),
            ExtractedUtterance(
                id="U002",
                speaker="Bình",
                timestamp="09:02",
                topic="Kiểm thử hệ thống",
                type=UtteranceType.ACTION_ITEM,
                role=UtteranceRole.ACCEPTS,
                quote="Kiểm thử tải hệ thống hoàn thành trước thứ Sáu.",
                references=[],
            ),
            ExtractedUtterance(
                id="U003",
                speaker="Cường",
                timestamp="09:04",
                topic="Hạ tầng máy chủ",
                type=UtteranceType.BLOCKER,
                role=UtteranceRole.REPORTS,
                quote="Chưa được cấp quyền truy cập máy chủ production.",
                references=[],
            ),
            ExtractedUtterance(
                id="U004",
                speaker="An",
                timestamp="09:06",
                topic="Ngân sách quảng cáo",
                type=UtteranceType.UNRESOLVED,
                role=UtteranceRole.QUESTIONS,
                quote="Chưa thống nhất ngân sách cho chiến dịch.",
                references=[],
            ),
        ]
    )


def create_minimal_resolved_result() -> ResolvedResult:
    """Create a minimal valid ResolvedResult for test pipelines."""
    return ResolvedResult(
        meeting_summary="Cuộc họp thảo luận về kế hoạch phát hành, kiểm thử và ngân sách.",
        participants=["An", "Bình", "Cường"],
        decisions=[
            Decision(
                item_id="D001",
                topic="Kế hoạch phát hành",
                final_value="Chốt ngày phát hành là 25/12/2026.",
                status=ItemStatus.CONFIRMED,
                history=[
                    HistoryEntry(
                        value="Chốt ngày phát hành là 25/12/2026.",
                        status=ItemStatus.CONFIRMED,
                        role="confirms",
                        evidence=[
                            Evidence(
                                speaker="An",
                                timestamp="09:00",
                                quote="Chốt ngày phát hành là 25/12/2026.",
                                utterance_id="U001",
                                verified=True,
                            )
                        ],
                    )
                ],
            )
        ],
        action_items=[
            ActionItem(
                item_id="A001",
                task="Kiểm thử tải hệ thống hoàn thành trước thứ Sáu.",
                assignee="Bình",
                deadline="thứ Sáu",
                assignee_confirmed=True,
                confirmation_utterance_id="U002",
                evidence=[
                    Evidence(
                        speaker="Bình",
                        timestamp="09:02",
                        quote="Kiểm thử tải hệ thống hoàn thành trước thứ Sáu.",
                        utterance_id="U002",
                        verified=True,
                    )
                ],
            )
        ],
        blockers=[
            Blocker(
                item_id="B001",
                issue="Chưa được cấp quyền truy cập máy chủ production.",
                status=ItemStatus.UNRESOLVED,
                evidence=[
                    Evidence(
                        speaker="Cường",
                        timestamp="09:04",
                        quote="Chưa được cấp quyền truy cập máy chủ production.",
                        utterance_id="U003",
                        verified=True,
                    )
                ],
            )
        ],
        requests=[],
        unresolved_items=[
            UnresolvedItem(
                item_id="UR001",
                topic="Ngân sách quảng cáo",
                reason_unresolved="Chưa thống nhất ngân sách cho chiến dịch.",
                evidence=[
                    Evidence(
                        speaker="An",
                        timestamp="09:06",
                        quote="Chưa thống nhất ngân sách cho chiến dịch.",
                        utterance_id="U004",
                        verified=True,
                    )
                ],
            )
        ],
    )


class FakeLLMClient:
    """Configurable Fake LLM Client satisfying the LLMClient protocol."""

    def __init__(
        self,
        default_extraction: Optional[ExtractionResult] = None,
        default_resolution: Optional[ResolvedResult] = None,
    ) -> None:
        self.default_extraction = default_extraction or create_minimal_extraction_result()
        self.default_resolution = default_resolution or create_minimal_resolved_result()
        self.simulated_exception: Optional[Exception] = None
        self.call_history: List[Dict[str, Any]] = []

    def set_exception(self, exc: Optional[Exception]) -> None:
        """Configure an exception to be raised on the next call."""
        self.simulated_exception = exc

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        self.call_history.append({
            "method": "generate",
            "prompt_length": len(prompt),
            "system_instruction": system_instruction,
            "temperature": temperature,
        })
        if self.simulated_exception:
            exc = self.simulated_exception
            self.simulated_exception = None
            raise exc

        return '{"status": "ok"}'

    def generate_structured(
        self,
        prompt: str,
        schema_cls: Type[T],
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_retries: int = 2,
    ) -> T:
        self.call_history.append({
            "method": "generate_structured",
            "schema": schema_cls.__name__,
            "prompt_length": len(prompt),
            "temperature": temperature,
        })

        if self.simulated_exception:
            exc = self.simulated_exception
            self.simulated_exception = None
            raise exc

        if schema_cls is ExtractionResult or schema_cls.__name__ == "ExtractionResult":
            return self.default_extraction  # type: ignore

        if schema_cls is ResolvedResult or schema_cls.__name__ == "ResolvedResult":
            return self.default_resolution  # type: ignore

        # Fallback to model defaults
        try:
            return schema_cls()  # type: ignore
        except Exception:
            raise LLMValidationError(f"Cannot instantiate fake schema {schema_cls.__name__}")
