"""
LLM Client Interface, Safety Helpers, and Google Gemini Implementation.

Features:
1. LLMClient Protocol defining standard generation and structured extraction interface.
2. Typed error hierarchy (LLMTimeoutError, LLMRateLimitError, LLMSafetyError, LLMAuthError, LLMContextLengthError, LLMValidationError).
3. Anti-prompt injection via dynamic cryptographically random nonces (<<<TRANSCRIPT_DATA_{nonce}>>>)
   and transcript sanitization.
4. Early context length checks to prevent oversized payloads.
5. Structured generation with automatic retry, exponential backoff with jitter,
   fail-fast on non-retryable errors (auth, safety, invalid model), and validation error feedback.
6. Reliable JSON-mode structured output compatible with Pydantic v2 schemas.
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


class LLMAuthError(LLMError):
    """Raised when LLM API authentication fails (invalid API key, unauthorized, permission denied)."""
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


class LLMInvalidOutputError(LLMValidationError):
    """Alias for output validation error."""
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
        max_retries: int = 2,
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
            raise LLMAuthError(
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
        if isinstance(err, LLMError):
            raise err

        err_str = str(err).lower()
        err_type = type(err).__name__.lower()

        # Auth errors
        if (
            "api_key" in err_str
            or "api key" in err_str
            or "401" in err_str
            or "403" in err_str
            or "permissiondenied" in err_type
            or "permission_denied" in err_str
            or "unauthenticated" in err_str
        ):
            raise LLMAuthError(f"Google Gemini authentication failed: {err}") from err

        # Rate limit
        if "429" in err_str or "resourceexhausted" in err_type or "resource_exhausted" in err_str or "quota" in err_str:
            raise LLMRateLimitError(f"Rate limit exceeded (429): {err}") from err

        # Timeout
        if "deadline" in err_type or "timeout" in err_type or "timed out" in err_str:
            raise LLMTimeoutError(f"Request timed out after {self.timeout}s: {err}") from err

        # Safety
        if "safety" in err_str or "blocked" in err_str or "harm" in err_str:
            raise LLMSafetyError(f"Content blocked by safety filters: {err}") from err

        # Invalid model or argument
        if "not found" in err_str or "invalid argument" in err_str or "invalidargument" in err_type:
            raise LLMError(f"Gemini API invalid model/argument: {err}") from err

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
        max_retries: int = 2,
    ) -> T:
        """
        Generate structured output adhering to schema_cls.
        Implements:
        1. response_mime_type="application/json" mode without broken protobuf defaults.
        2. Exponential backoff with jitter on transient failures (bounded to <= 20s).
        3. Fail-fast on non-retryable errors (auth, safety, invalid model).
        4. Feedback loop injecting validation error details on retry.
        """
        check_context_length(prompt)

        temp = temperature if temperature is not None else self.temperature

        # Note: We pass response_mime_type="application/json" without passing
        # schema_cls directly to response_schema because Google's protobuf Schema
        # parser crashes on Pydantic v2 schemas with field defaults:
        # "ValueError: Protocol message Schema has no 'default' field".
        # The JSON output is strictly validated against schema_cls via model_validate.
        gen_config = self.genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=temp,
        )

        try:
            model = self.genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction,
                generation_config=gen_config,
            )
        except Exception as model_err:
            logger.error(f"[{self.model_name}] Failed to initialize GenerativeModel: {model_err}")
            self._classify_and_raise_error(model_err)
            raise

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

                if attempt >= max_retries:
                    break

                # Backoff before retrying (1.0s, 2.0s...)
                delay = 1.0 * attempt + random.uniform(0.1, 0.4)
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
                err_type = type(api_err).__name__.lower()

                # Fail fast on non-retryable errors
                is_auth = (
                    "api_key" in err_str
                    or "api key" in err_str
                    or "401" in err_str
                    or "403" in err_str
                    or "permissiondenied" in err_type
                    or "permission_denied" in err_str
                    or "unauthenticated" in err_str
                )
                is_safety = "safety" in err_str or "blocked" in err_str or "harm" in err_str
                is_invalid_model = "not found" in err_str or "invalid argument" in err_str

                if is_auth or is_safety or is_invalid_model:
                    self._classify_and_raise_error(api_err)

                is_rate_limit = (
                    "429" in err_str
                    or "resourceexhausted" in err_type
                    or "resource_exhausted" in err_str
                    or "quota" in err_str
                )

                if is_rate_limit and attempt < max_retries:
                    delay = 2.0 * attempt + random.uniform(0.5, 1.0)
                    logger.warning(f"Rate limited (429). Backing off for {delay:.2f}s before retry {attempt+1}...")
                    time.sleep(delay)
                    continue

                logger.warning(
                    f"[{self.model_name}] API call failed on attempt {attempt}: {api_err}"
                )
                if attempt >= max_retries:
                    self._classify_and_raise_error(api_err)

        if isinstance(last_error, (json.JSONDecodeError, ValidationError)):
            raise LLMInvalidOutputError(
                f"Failed to generate valid {schema_cls.__name__} after {max_retries} attempts. Last error: {last_error}"
            ) from last_error

        if last_error:
            self._classify_and_raise_error(last_error)

        raise LLMValidationError(
            f"Failed to generate valid {schema_cls.__name__} after {max_retries} attempts."
        )
