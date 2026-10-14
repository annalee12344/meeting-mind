"""
Pipeline runner module for Meeting Mind.

Provides reusable entry points for running the full analysis pipeline:
Step 0 (Preprocessor) -> Step 1 (Extractor) -> Step 2 (Resolver) -> Step 3 (Validator).
"""
import logging
from typing import Optional

from models.output import MeetingOutput
from pipeline.preprocessor import preprocess
from pipeline.extractor import Extractor
from pipeline.resolver import Resolver
from pipeline.validator import Validator

logger = logging.getLogger(__name__)


def run_pipeline(
    raw_transcript: str,
    threshold: Optional[int] = None,
) -> MeetingOutput:
    """
    Execute full Meeting Mind 2-pass pipeline on transcript string.

    Args:
        raw_transcript: Raw meeting transcript text.
        threshold: Optional fuzzy matching threshold (0-100).

    Returns:
        MeetingOutput containing structured, verified meeting results.

    Raises:
        ValueError: If transcript is empty.
        RuntimeError: If extraction, resolution or validation fails.
    """
    if not raw_transcript or not raw_transcript.strip():
        raise ValueError("Transcript cannot be empty.")

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

    return validated_output
