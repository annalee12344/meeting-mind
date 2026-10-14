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
from typing import Optional

import config
from models.intermediate import ExtractionResult
from models.output import ResolvedResult
from pipeline.llm_client import GeminiLLMClient, LLMClient, clean_json_markdown
from prompts.resolution_prompt import (
    RESOLUTION_SYSTEM_PROMPT,
    RESOLUTION_USER_TEMPLATE,
    build_resolution_user_prompt,
)

logger = logging.getLogger(__name__)


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
            logger.info(
                f"[Step 2] Resolution succeeded: "
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
