"""
Step 2 — Progression resolution using Google Gemini API.

Receives extracted candidate utterances from Step 1 (ExtractionResult),
sends them to Gemini with the resolution prompt to group by topic,
track progression over time (handling changes like A -> B), and determine
final conclusions (confirmed/superseded/unresolved).
Validates output against the MeetingOutput Pydantic schema with automatic retries.
"""
import json
import logging
from typing import Optional
import google.generativeai as genai
from pydantic import ValidationError

import config
from models.intermediate import ExtractionResult
from models.output import ResolvedResult
from prompts.resolution_prompt import RESOLUTION_SYSTEM_PROMPT, RESOLUTION_USER_TEMPLATE

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
    ) -> None:
        """
        Initialize the Resolver and configure Google Gemini API client.

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
            system_instruction=RESOLUTION_SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=self.temperature,
            ),
        )
        logger.debug(f"Resolver initialized with model '{self.model_name}' (temp={self.temperature})")

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
        user_content = RESOLUTION_USER_TEMPLATE.format(extraction_json=extraction_json)

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[Step 2] Calling Gemini API (attempt {attempt}/{max_retries})...")
                response = self.model.generate_content(user_content)

                if not response.text:
                    raise ValueError("Gemini returned an empty response.")

                cleaned_json = self._clean_json_response(response.text)
                parsed_data = json.loads(cleaned_json)

                # Validate with Pydantic model
                output = ResolvedResult.model_validate(parsed_data)
                logger.info(
                    f"[Step 2] Resolution succeeded: "
                    f"{len(output.decisions)} decisions, "
                    f"{len(output.action_items)} action items, "
                    f"{len(output.blockers)} blockers, "
                    f"{len(output.requests)} requests, "
                    f"{len(output.unresolved_items)} unresolved."
                )
                return output

            except (json.JSONDecodeError, ValidationError, Exception) as err:
                last_error = err
                logger.warning(
                    f"[Step 2] Attempt {attempt}/{max_retries} failed: {type(err).__name__}: {err}"
                )
                if attempt == max_retries:
                    break

        raise RuntimeError(
            f"Step 2 Resolution failed after {max_retries} attempts. Last error: {last_error}"
        ) from last_error
