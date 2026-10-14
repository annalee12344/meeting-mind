"""
Meeting Mind — Pipeline Smoke Test Runner.

Executes the real pipeline or fake pipeline against given transcripts,
measuring per-stage execution durations, item counts, needs_review rates,
and confirming end-to-end reliability.

IMPORTANT RULE: Never logs raw transcript text content.
"""
import argparse
from pathlib import Path
import sys
import time
from typing import Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from models.output import MeetingOutput
from pipeline.deadlines import resolve_meeting_date
from pipeline.extractor import Extractor
from pipeline.mapper import map_to_public
from pipeline.preprocessor import preprocess
from pipeline.resolver import Resolver
from pipeline.validator import Validator


def run_smoke_analysis(
    transcript_text: str,
    name: str = "Smoke Test",
    meeting_date: Optional[str] = None,
    threshold: int = 80,
) -> MeetingOutput:
    """Run real pipeline stages on transcript text, recording durations and counts."""
    clean_text = transcript_text.strip()
    total_chars = len(clean_text)
    total_lines = len(clean_text.splitlines())
    print(f"\n[{name}] Starting smoke analysis (length: {total_chars} chars, {total_lines} lines)...")

    overall_start = time.time()

    # Step 0: Preprocessor
    t0 = time.time()
    preprocessed = preprocess(clean_text, strict=True)
    d0 = time.time() - t0
    utterance_count = len(preprocessed.splitlines())
    print(f"  ✓ Step 0 (Preprocessor): {d0:.2f}s -> {utterance_count} utterances")

    # Step 1: Extractor (LLM)
    t1 = time.time()
    extractor = Extractor()
    extracted = extractor.extract(preprocessed)
    d1 = time.time() - t1
    extracted_count = len(extracted.utterances) if hasattr(extracted, "utterances") else 0
    print(f"  ✓ Step 1 (Extractor LLM): {d1:.2f}s -> {extracted_count} raw utterances extracted")

    # Step 2: Resolver (LLM)
    t2 = time.time()
    resolver = Resolver()
    resolved = resolver.resolve(extracted)
    d2 = time.time() - t2
    resolved_count = (
        len(resolved.decisions)
        + len(resolved.action_items)
        + len(resolved.blockers)
        + len(resolved.unresolved_items)
    )
    print(f"  ✓ Step 2 (Resolver LLM): {d2:.2f}s -> {resolved_count} internal items resolved")

    # Step 3: Validator (RapidFuzz)
    t3 = time.time()
    validator = Validator(threshold=threshold)
    validated = validator.validate(resolved, clean_text)
    d3 = time.time() - t3
    print(f"  ✓ Step 3 (Validator RapidFuzz): {d3:.2f}s")

    # Step 4: Mapper (Deterministic)
    t4 = time.time()
    public_output = map_to_public(
        validated,
        transcript=clean_text,
        meeting_date_input=meeting_date,
    )
    d4 = time.time() - t4
    overall_duration = time.time() - overall_start

    # Metrics calculation
    all_items = (
        list(public_output.decisions)
        + list(public_output.tasks)
        + list(public_output.unresolved)
        + list(public_output.issues)
    )
    total_items = len(all_items)
    needs_review_items = sum(1 for item in all_items if getattr(item, "needs_review", False))
    review_pct = (needs_review_items / total_items * 100) if total_items > 0 else 0.0

    print(f"  ✓ Step 4 (Deterministic Mapping): {d4:.2f}s")
    print(f"  ══ TOTAL TIME: {overall_duration:.2f}s ══")
    print(
        f"  ══ COUNTS: Decisions: {len(public_output.decisions)} | "
        f"Tasks: {len(public_output.tasks)} | "
        f"Unresolved: {len(public_output.unresolved)} | "
        f"Issues: {len(public_output.issues)} ══"
    )
    print(
        f"  ══ REVIEW RATE: {needs_review_items}/{total_items} items flagged needs_review ({review_pct:.1f}%) ══\n"
    )

    return public_output


def main():
    parser = argparse.ArgumentParser(description="Meeting Mind Smoke Test Runner")
    parser.add_argument("file", nargs="?", help="Path to transcript .txt file")
    parser.add_argument("--date", help="Optional ISO meeting date (YYYY-MM-DD)")
    parser.add_argument("--threshold", type=int, default=80, help="Fuzzy match threshold")
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: File not found: {path}")
            sys.exit(1)
        text = path.read_text(encoding="utf-8")
        run_smoke_analysis(text, name=path.name, meeting_date=args.date, threshold=args.threshold)
    else:
        # Default run on built-in test transcript
        default_file = config.TRANSCRIPTS_DIR / "test_01_happy_path.txt"
        if default_file.exists():
            text = default_file.read_text(encoding="utf-8")
            run_smoke_analysis(text, name="Built-in Sample 1", threshold=args.threshold)
        else:
            print("No file specified and default sample not found.")


if __name__ == "__main__":
    main()
