"""
Step 2 — Progression resolution using Google Gemini API.

Receives extracted candidate utterances from Step 1 (ExtractionResult),
sends them to Gemini with the resolution prompt to group by topic,
track progression over time (handling changes like A -> B), and determine
final conclusions (confirmed/superseded/unresolved).
Validates output against the ResolvedResult Pydantic schema with automatic retries,
exponential backoff, and validation error feedback.
"""
import logging
from typing import List, Optional
import unicodedata

from rapidfuzz import fuzz

import config
from models.intermediate import ExtractionResult
from models.output import ActionItem, Evidence, ResolvedResult
from pipeline.llm_client import GeminiLLMClient, LLMClient, clean_json_markdown
from prompts.resolution_prompt import (
    RESOLUTION_SYSTEM_PROMPT,
    RESOLUTION_USER_TEMPLATE,
    build_resolution_user_prompt,
)

logger = logging.getLogger(__name__)


def are_action_items_duplicate(a1: ActionItem, a2: ActionItem) -> bool:
    """Check if two ActionItems refer to the same deliverable/commitment by the same person."""
    # 1. Assignee match
    asg1 = (a1.assignee or "").strip().lower()
    asg2 = (a2.assignee or "").strip().lower()
    if asg1 and asg2 and asg1 != asg2:
        return False

    # 2. Exact normalized title match
    clean1 = " ".join(unicodedata.normalize("NFC", a1.task).lower().split())
    clean2 = " ".join(unicodedata.normalize("NFC", a2.task).lower().split())
    if clean1 == clean2:
        return True

    # 3. Fuzzy similarity
    set_ratio = fuzz.token_set_ratio(clean1, clean2)
    sort_ratio = fuzz.token_sort_ratio(clean1, clean2)

    # If both have evidence with shared utterance IDs
    uids1 = {ev.utterance_id for ev in (a1.evidence or []) if ev.utterance_id}
    uids2 = {ev.utterance_id for ev in (a2.evidence or []) if ev.utterance_id}
    has_shared_utterance = bool(uids1 and uids2 and (uids1 & uids2))
    if has_shared_utterance and set_ratio >= 75.0:
        return True

    return (set_ratio >= 85.0 and sort_ratio >= 50.0) or (set_ratio >= 80.0 and sort_ratio >= 55.0)


def merge_two_action_items(a1: ActionItem, a2: ActionItem) -> ActionItem:
    """Merge two duplicate ActionItems into a single canonical ActionItem."""
    # 1. Task description: select the more descriptive/detailed one
    w1 = len(a1.task.split())
    w2 = len(a2.task.split())
    chosen_task = a1.task if w1 >= w2 else a2.task

    # 2. Assignee
    chosen_assignee = a1.assignee or a2.assignee

    # 3. Deadline: prefer non-null / more specific
    chosen_deadline = a1.deadline or a2.deadline
    if a1.deadline and a2.deadline:
        chosen_deadline = a1.deadline if len(a1.deadline) >= len(a2.deadline) else a2.deadline

    # 4. Evidence: union without duplicates
    seen_ev = set()
    merged_ev = []
    for ev in (a1.evidence or []) + (a2.evidence or []):
        key = (ev.quote.strip() if ev.quote else "", ev.utterance_id, ev.speaker)
        if key not in seen_ev:
            seen_ev.add(key)
            merged_ev.append(ev)

    # 5. Metadata / Roles
    assignee_confirmed = bool(a1.assignee_confirmed or a2.assignee_confirmed)
    confirm_uid = a1.confirmation_utterance_id or a2.confirmation_utterance_id
    assigned_by = a1.assigned_by or a2.assigned_by
    external_dep = a1.external_dependency or a2.external_dependency
    collab = a1.collaborator or a2.collaborator
    rev = a1.reviewer or a2.reviewer
    esc = a1.escalation or a2.escalation
    needs_review = bool(a1.needs_review and a2.needs_review)
    deps = list(dict.fromkeys(a1.dependencies + a2.dependencies))

    return ActionItem(
        item_id=a1.item_id,
        task=chosen_task,
        assignee=chosen_assignee,
        deadline=chosen_deadline,
        dependencies=deps,
        evidence=merged_ev,
        needs_review=needs_review,
        assignee_confirmed=assignee_confirmed,
        confirmation_utterance_id=confirm_uid,
        assigned_by=assigned_by,
        external_dependency=external_dep,
        collaborator=collab,
        reviewer=rev,
        escalation=esc,
    )


def deduplicate_action_items(action_items: List[ActionItem]) -> List[ActionItem]:
    """Deduplicate action items while preserving single deliverable and combining evidence."""
    if not action_items or len(action_items) <= 1:
        return action_items

    merged: List[ActionItem] = []
    for item in action_items:
        match_idx = None
        for i, existing in enumerate(merged):
            if are_action_items_duplicate(existing, item):
                match_idx = i
                break

        if match_idx is not None:
            merged[match_idx] = merge_two_action_items(merged[match_idx], item)
        else:
            merged.append(item)

    return merged



class Resolver:
    """
    Step 2 Resolver: Resolves discussion progression and final meeting outcomes.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        """
        Initialize the Resolver.

        Args:
            api_key: Gemini API key. Defaults to config.GEMINI_API_KEY.
            model_name: Model name. Defaults to config.STEP2_MODEL (or config.GEMINI_MODEL).
            temperature: Sampling temperature. Defaults to config.TEMPERATURE.
            llm_client: Custom LLMClient instance (useful for mocking/testing).
        """
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model_name = model_name or config.STEP2_MODEL
        self.temperature = temperature if temperature is not None else config.TEMPERATURE

        if llm_client:
            self.llm_client = llm_client
        else:
            if not self.api_key or self.api_key == "your_api_key_here":
                raise ValueError(
                    "GEMINI_API_KEY is not configured! Please set your Gemini API key "
                    "in the .env file or GEMINI_API_KEY environment variable. "
                    "Get a free key at https://aistudio.google.com/apikey"
                )
            self.llm_client = GeminiLLMClient(
                api_key=self.api_key,
                model_name=self.model_name,
                temperature=self.temperature,
            )

        logger.debug(f"Resolver initialized with model '{self.model_name}' (temp={self.temperature})")

    @staticmethod
    def _clean_json_response(raw_text: str) -> str:
        """Clean markdown code block wrappers if returned by LLM."""
        return clean_json_markdown(raw_text)

    def resolve(
        self,
        extraction_result: ExtractionResult,
        max_retries: int = 3,
    ) -> ResolvedResult:
        """
        Resolve discussion progression from Step 1 utterances.

        Args:
            extraction_result: Step 1 output containing all candidate utterances.
            max_retries: Maximum number of retry attempts upon JSON or validation errors.

        Returns:
            ResolvedResult containing structured decisions, action items, blockers, etc.

        Raises:
            RuntimeError: If resolution fails after all retry attempts.
        """
        if not extraction_result.utterances:
            logger.warning("Empty utterances provided to resolver. Returning empty ResolvedResult.")
            return ResolvedResult(
                meeting_summary="Cuộc họp không có nội dung trích xuất đáng kể.",
                participants=[],
            )

        extraction_json = extraction_result.model_dump_json(indent=2)
        user_content = build_resolution_user_prompt(extraction_json)

        try:
            logger.info(f"[Step 2] Calling Gemini API (model={self.model_name})...")
            output = self.llm_client.generate_structured(
                prompt=user_content,
                schema_cls=ResolvedResult,
                system_instruction=RESOLUTION_SYSTEM_PROMPT,
                temperature=self.temperature,
                max_retries=max_retries,
            )
            output.action_items = deduplicate_action_items(output.action_items)
            logger.info(
                f"[Step 2] Resolution succeeded (after deduplication): "
                f"{len(output.decisions)} decisions, "
                f"{len(output.action_items)} action items, "
                f"{len(output.blockers)} blockers, "
                f"{len(output.requests)} requests, "
                f"{len(output.unresolved_items)} unresolved."
            )
            return output

        except Exception as err:
            logger.error(f"[Step 2] Resolution failed: {err}")
            raise RuntimeError(
                f"Step 2 Resolution failed after {max_retries} attempts: {err}"
            ) from err
