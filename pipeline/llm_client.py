"""
LLM Client Interface, Safety Helpers, and Google Gemini Implementation.

Features:
1. LLMClient Protocol defining standard generation and structured extraction interface.
2. Typed error hierarchy (LLMTimeoutError, LLMRateLimitError, LLMSafetyError, LLMContextLengthError).
3. Anti-prompt injection via dynamic cryptographically random nonces (<<<TRANSCRIPT_DATA_{nonce}>>>)
   and transcript sanitization.
4. Early context length checks to prevent oversized payloads.
5. Structured generation with automatic retry, exponential backoff with jitter,
   and validation error feedback into subsequent attempts.
6. Support for response_schema with graceful fallback to JSON mime-type.
"""
from abc import abstractmethod
import json
import logging
import random
import re
import secrets
import time
from typing import Any, Dict, Optional, Protocol, Type, TypeVar
import unicodedata

from pydantic import BaseModel, ValidationError

import config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Typed Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class LLMError(Exception):
    """Base exception for all LLM errors."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM API request times out."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when an LLM API request is throttled / rate-limited (HTTP 429 / ResourceExhausted)."""
    pass


class LLMSafetyError(LLMError):
    """Raised when an LLM request or response is blocked by safety filters."""
    pass


class LLMContextLengthError(LLMError):
    """Raised when input text exceeds maximum configured context length."""
    pass


class LLMValidationError(LLMError):
    """Raised when LLM output repeatedly fails JSON or Pydantic validation."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# 2. Safety and Prompt Sanitization Helpers
# ─────────────────────────────────────────────────────────────────────────────

RE_DELIMITER_STRIP = re.compile(r"<{2,3}/?TRANSCRIPT_DATA.*?/{0,3}>{2,3}", re.IGNORECASE)


def sanitize_transcript_text(text: str) -> str:
    """
    Sanitize untrusted transcript text by stripping artificial delimiter sequences
    to prevent escaping prompt boundaries.
    """
    if not text:
        return ""
    # Strip any attempt to forge transcript delimiter tags
    sanitized = RE_DELIMITER_STRIP.sub("[FILTERED_TAG]", text)
    return sanitized


def wrap_untrusted_transcript(transcript: str, nonce: Optional[str] = None) -> tuple[str, str]:
    """
    Wrap untrusted transcript in dynamic cryptographically secure nonce tags:
    <<<TRANSCRIPT_DATA_{nonce}>>>
    ...transcript...
    <<</TRANSCRIPT_DATA_{nonce}>>>

    Returns:
        tuple of (wrapped_content, nonce)
    """
    if not nonce:
        nonce = secrets.token_hex(8)

    sanitized = sanitize_transcript_text(transcript)
    # Also ensure nonce itself is not present in the body
    sanitized = sanitized.replace(nonce, "[NONCE_MASK]")

    open_tag = f"<<<TRANSCRIPT_DATA_{nonce}>>>"
    close_tag = f"<<</TRANSCRIPT_DATA_{nonce}>>>"

    wrapped = f"{open_tag}\n{sanitized}\n{close_tag}"
    return wrapped, nonce


def check_context_length(text: str, max_chars: Optional[int] = None) -> None:
    """
    Early check to prevent oversized inputs exceeding token limits.
    """
    limit = max_chars if max_chars is not None else config.MAX_CONTEXT_CHARS
    if len(text) > limit:
        raise LLMContextLengthError(
            f"Input text length ({len(text)} chars) exceeds maximum allowed context ({limit} chars)."
        )


def clean_json_markdown(raw_text: str) -> str:
    """Strip markdown code fence blocks if returned by LLM."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


# ─────────────────────────────────────────────────────────────────────────────
# 3. LLM Client Protocol
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient(Protocol):
    """Protocol for LLM clients."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Generate raw text response from the model."""
        ...

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        schema_cls: Type[T],
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_retries: int = 3,
    ) -> T:
        """Generate and validate a structured Pydantic object with retry & feedback."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# 4. Google Gemini Implementation
# ─────────────────────────────────────────────────────────────────────────────

class GeminiLLMClient:
    """
    Robust Google Gemini client with retry, timeout, error typing,
    and schema validation feedback.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.api_key = api_key or config.GEMINI_API_KEY
        if not self.api_key or self.api_key == "your_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is not configured! Please set GEMINI_API_KEY in .env."
            )

        self.model_name = model_name or config.GEMINI_MODEL
        self.temperature = temperature if temperature is not None else config.TEMPERATURE
        self.timeout = timeout if timeout is not None else config.LLM_REQUEST_TIMEOUT

        # Import google.generativeai here
        import google.generativeai as genai
        self.genai = genai
        self.genai.configure(api_key=self.api_key)

    def _classify_and_raise_error(self, err: Exception) -> None:
        """Map SDK errors to typed LLM exceptions."""
        err_str = str(err).lower()
        err_type = type(err).__name__.lower()

        if "429" in err_str or "resourceexhausted" in err_type or "resource_exhausted" in err_str or "quota" in err_str:
            raise LLMRateLimitError(f"Rate limit exceeded (429): {err}") from err

        if "deadline" in err_type or "timeout" in err_type or "timed out" in err_str:
            raise LLMTimeoutError(f"Request timed out after {self.timeout}s: {err}") from err

        if "safety" in err_str or "blocked" in err_str or "harm" in err_str:
            raise LLMSafetyError(f"Content blocked by safety filters: {err}") from err

        raise LLMError(f"Gemini API error ({type(err).__name__}): {err}") from err

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Generate text response from Gemini model."""
        check_context_length(prompt)

        temp = temperature if temperature is not None else self.temperature
        model = self.genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_instruction,
            generation_config=self.genai.GenerationConfig(
                temperature=temp,
            ),
        )

        try:
            # request_options supports timeout in google-generativeai
            request_options = {"timeout": self.timeout} if self.timeout else None
            response = model.generate_content(prompt, request_options=request_options)

            if not response.text:
                raise LLMError("Gemini returned empty response text.")

            return response.text

        except Exception as err:
            self._classify_and_raise_error(err)
            raise

    def generate_structured(
        self,
        prompt: str,
        schema_cls: Type[T],
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_retries: int = 3,
    ) -> T:
        """
        Generate structured output adhering to schema_cls.
        Implements:
        1. response_schema config if supported (with fallback).
        2. Exponential backoff with jitter on transient failures.
        3. Feedback loop injecting validation error details on retry.
        """
        check_context_length(prompt)

        temp = temperature if temperature is not None else self.temperature

        # Attempt to configure response_schema, fallback gracefully if unsupported
        generation_config_args: Dict[str, Any] = {
            "response_mime_type": "application/json",
            "temperature": temp,
        }
        try:
            # Some versions of google-generativeai support response_schema
            generation_config_args["response_schema"] = schema_cls
            gen_config = self.genai.GenerationConfig(**generation_config_args)
        except Exception as schema_err:
            logger.debug(f"Gemini response_schema configuration fallback: {schema_err}")
            generation_config_args.pop("response_schema", None)
            gen_config = self.genai.GenerationConfig(**generation_config_args)

        model = self.genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_instruction,
            generation_config=gen_config,
        )

        last_error: Optional[Exception] = None
        current_prompt = prompt

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"[{self.model_name}] Calling LLM (attempt {attempt}/{max_retries})..."
                )
                request_options = {"timeout": self.timeout} if self.timeout else None
                response = model.generate_content(current_prompt, request_options=request_options)

                if not response.text:
                    raise LLMError("Model returned an empty response.")

                cleaned_json = clean_json_markdown(response.text)
                parsed_data = json.loads(cleaned_json)
                result = schema_cls.model_validate(parsed_data)
                logger.info(f"[{self.model_name}] Structured generation succeeded on attempt {attempt}.")
                return result

            except (json.JSONDecodeError, ValidationError) as parse_err:
                last_error = parse_err
                logger.warning(
                    f"[{self.model_name}] Output validation failed on attempt {attempt}: {parse_err}"
                )

                if attempt == max_retries:
                    break

                # Backoff before retrying
                delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0.1, 0.4)
                time.sleep(delay)

                # Feed back error details into prompt for the next attempt
                error_summary = str(parse_err)
                if len(error_summary) > 500:
                    error_summary = error_summary[:500] + "... (truncated)"
                current_prompt = (
                    f"{prompt}\n\n"
                    f"[LỖI TỪ LẦN THỬ TRƯỚC {attempt}]: Output của bạn không khớp schema hoặc sai JSON cú pháp:\n"
                    f"{error_summary}\n"
                    "Hãy sửa lỗi trên và chỉ trả về chuỗi JSON hợp lệ khớp chính xác với cấu trúc yêu cầu."
                )

            except Exception as api_err:
                last_error = api_err
                err_str = str(api_err).lower()
                is_rate_limit = "429" in err_str or "resourceexhausted" in type(api_err).__name__.lower() or "quota" in err_str

                if is_rate_limit and attempt < max_retries:
                    delay = 2.0 * (2 ** (attempt - 1)) + random.uniform(0.5, 1.5)
                    logger.warning(f"Rate limited (429). Backing off for {delay:.2f}s before retry {attempt+1}...")
                    time.sleep(delay)
                    continue

                logger.warning(
                    f"[{self.model_name}] API call failed on attempt {attempt}: {api_err}"
                )
                if attempt == max_retries:
                    self._classify_and_raise_error(api_err)

        raise LLMValidationError(
            f"Failed to generate valid {schema_cls.__name__} after {max_retries} attempts. Last error: {last_error}"
        ) from last_error
