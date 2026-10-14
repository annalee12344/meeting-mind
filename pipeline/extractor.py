"""
Step 1 — Utterance extraction using Google Gemini API.

Sends preprocessed transcript to Gemini to extract candidate utterances,
classifying each by type (decision, action_item, etc.) and role in discussion.
Validates LLM output against the ExtractionResult Pydantic schema with automatic retries.
"""
import json
import logging
from typing import Optional
import google.generativeai as genai
from pydantic import ValidationError

import config
from models.intermediate import ExtractionResult
from prompts.extraction_prompt import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_TEMPLATE

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
    ) -> None:
        """
        Initialize the Extractor and configure Google Gemini API client.

        Args:
            api_key: Gemini API key. Defaults to config.GEMINI_API_KEY.
            model_name: Gemini model name. Defaults to config.GEMINI_MODEL.
            temperature: Sampling temperature. Defaults to config.TEMPERATURE.
        """
        self.api_key = api_key or config.GEMINI_API_KEY
        if not self.api_key or self.api_key == "your_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is not configured! Please set your Gemini API key "
                "in the .env file or GEMINI_API_KEY environment variable. "
                "Get a free key at https://aistudio.google.com/apikey"
            )

        self.model_name = model_name or config.GEMINI_MODEL
        self.temperature = temperature if temperature is not None else config.TEMPERATURE

        # Configure Gemini SDK
        genai.configure(api_key=self.api_key)

        # Initialize GenerativeModel with system instruction and JSON output config
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=EXTRACTION_SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=self.temperature,
            ),
        )
        logger.debug(f"Extractor initialized with model '{self.model_name}' (temp={self.temperature})")

    @staticmethod
    def _clean_json_response(raw_text: str) -> str:
        """Clean markdown code block wrappers if returned by LLM."""
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

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

        user_content = EXTRACTION_USER_TEMPLATE.format(transcript=preprocessed_transcript)

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[Step 1] Calling Gemini API (attempt {attempt}/{max_retries})...")
                response = self.model.generate_content(user_content)

                if not response.text:
                    raise ValueError("Gemini returned an empty response.")

                cleaned_json = self._clean_json_response(response.text)
                parsed_data = json.loads(cleaned_json)

                # Validate with Pydantic model
                result = ExtractionResult.model_validate(parsed_data)
                logger.info(f"[Step 1] Extraction succeeded: {len(result.utterances)} utterances extracted.")
                return result

            except (json.JSONDecodeError, ValidationError, Exception) as err:
                last_error = err
                logger.warning(
                    f"[Step 1] Attempt {attempt}/{max_retries} failed: {type(err).__name__}: {err}"
                )
                if attempt == max_retries:
                    break

        raise RuntimeError(
            f"Step 1 Extraction failed after {max_retries} attempts. Last error: {last_error}"
        ) from last_error
