"""
Pipeline runner module for Meeting Mind.

Provides reusable entry points for running the full analysis pipeline:
Step 0 (Preprocessor) -> Step 1 (Extractor) -> Step 2 (Resolver) -> Step 3 (Validator).
Supports result caching via pipeline.cache.
"""
import logging
from typing import Optional

import config
from models.output import ResolvedResult
from pipeline.cache import compute_analysis_cache_key, get_analysis_cache
from pipeline.extractor import Extractor
from pipeline.preprocessor import preprocess
from pipeline.resolver import Resolver
from pipeline.validator import Validator

logger = logging.getLogger(__name__)


def run_pipeline(
    raw_transcript: str,
    threshold: Optional[int] = None,
    use_cache: bool = True,
) -> ResolvedResult:
    """
    Execute full Meeting Mind 2-pass pipeline on transcript string.

    Args:
        raw_transcript: Raw meeting transcript text.
        threshold: Optional fuzzy matching threshold (0-100).
        use_cache: Whether to use caching for the pipeline run.

    Returns:
        ResolvedResult containing structured, verified meeting results.

    Raises:
        ValueError: If transcript is empty.
        RuntimeError: If extraction, resolution or validation fails.
    """
    if not raw_transcript or not raw_transcript.strip():
        raise ValueError("Transcript cannot be empty.")

    cache = get_analysis_cache()
    cache_key = None

    if use_cache and config.CACHE_ENABLED:
        cache_key = f"pipeline::{compute_analysis_cache_key(raw_transcript)}::t={threshold}"
        cached = cache.get(cache_key)
        if cached:
            logger.info(f"[Pipeline] Cache hit for pipeline key '{cache_key[:16]}...'. Reusing verified result.")
            return cached

    # Step 0: Preprocessing
    logger.info("Executing Step 0: Preprocessing transcript...")
    preprocessed_transcript = preprocess(raw_transcript)

    # Step 1: Extraction (Pass 1)
    logger.info("Executing Step 1: Utterance extraction...")
    extractor = Extractor()
    extraction_result = extractor.extract(preprocessed_transcript)

    # Step 2: Resolution (Pass 2)
    logger.info("Executing Step 2: Progression resolution...")
    resolver = Resolver()
    resolved_output = resolver.resolve(extraction_result)

    # Step 3: Evidence Validation
    logger.info("Executing Step 3: Evidence validation...")
    validator = Validator(threshold=threshold)
    validated_output = validator.validate(resolved_output, raw_transcript)

    if use_cache and config.CACHE_ENABLED and cache_key:
        cache.set(cache_key, validated_output)

    return validated_output
