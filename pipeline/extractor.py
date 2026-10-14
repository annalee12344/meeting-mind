"""
Step 1 — Utterance extraction using Google Gemini API.

Sends preprocessed transcript to Gemini to extract candidate utterances,
classifying each by type (decision, action_item, etc.) and role in discussion.
Validates LLM output against the ExtractionResult Pydantic schema with automatic retries,
exponential backoff, and prompt injection safety nonces.
"""
import logging
from typing import Optional

import config
from models.intermediate import ExtractionResult
from pipeline.llm_client import GeminiLLMClient, LLMClient, clean_json_markdown
from prompts.extraction_prompt import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEMPLATE,
    build_extraction_user_prompt,
)

logger = logging.getLogger(__name__)


class Extractor:
    """
    Step 1 Extractor: Identifies meaningful utterances from a meeting transcript.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        """
        Initialize the Extractor.

        Args:
            api_key: Gemini API key. Defaults to config.GEMINI_API_KEY.
            model_name: Model name. Defaults to config.STEP1_MODEL (or config.GEMINI_MODEL).
            temperature: Sampling temperature. Defaults to config.TEMPERATURE.
            llm_client: Custom LLMClient instance (useful for mocking/testing).
        """
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model_name = model_name or config.STEP1_MODEL
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

        logger.debug(f"Extractor initialized with model '{self.model_name}' (temp={self.temperature})")

    @staticmethod
    def _clean_json_response(raw_text: str) -> str:
        """Clean markdown code block wrappers if returned by LLM."""
        return clean_json_markdown(raw_text)

    def extract(
        self,
        preprocessed_transcript: str,
        max_retries: int = 3,
    ) -> ExtractionResult:
        """
        Extract candidate utterances from preprocessed transcript.

        Args:
            preprocessed_transcript: Transcript text formatted with [U001], [U002] IDs.
            max_retries: Maximum number of retry attempts upon JSON or validation errors.

        Returns:
            ExtractionResult containing all extracted utterances.

        Raises:
            RuntimeError: If extraction fails after all retry attempts.
        """
        if not preprocessed_transcript.strip():
            logger.warning("Empty transcript provided to extractor. Returning empty ExtractionResult.")
            return ExtractionResult(utterances=[])

        user_content = build_extraction_user_prompt(preprocessed_transcript)

        try:
            logger.info(f"[Step 1] Calling Gemini API (model={self.model_name})...")
            result = self.llm_client.generate_structured(
                prompt=user_content,
                schema_cls=ExtractionResult,
                system_instruction=EXTRACTION_SYSTEM_PROMPT,
                temperature=self.temperature,
                max_retries=max_retries,
            )
            logger.info(f"[Step 1] Extraction succeeded: {len(result.utterances)} utterances extracted.")
            return result

        except Exception as err:
            logger.error(f"[Step 1] Extraction failed: {err}")
            raise RuntimeError(
                f"Step 1 Extraction failed after {max_retries} attempts: {err}"
            ) from err
