"""
Meeting Mind — Test Runner & Evaluation Suite.

Executes meeting analysis pipeline against benchmark transcripts,
compares generated outputs against expected ground truth using RapidFuzz,
computes Precision, Recall, and F1 metrics (with dedicated semantic decision matching
and separate status evaluation), displays formatted Rich tables,
and saves evaluation results to output/test_results.json.

Usage:
    python -m tests.test_runner --test 1
    python -m tests.test_runner --all
    python -m tests.test_runner --all --mock
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

import config
from models.output import ResolvedResult
from pipeline.preprocessor import preprocess
from pipeline.extractor import Extractor
from pipeline.resolver import Resolver
from pipeline.validator import Validator
from pipeline.mapper import map_to_public

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()

SIMILARITY_THRESHOLD = 70.0

TEST_CASES = [
    {
        "id": 1,
        "name": "test_01_happy_path",
        "transcript_file": "test_01_happy_path.txt",
        "expected_file": "test_01_expected.json",
        "description": "Sprint planning (happy path: 2 decisions, 3 actions, 1 blocker, 1 request)",
    },
    {
        "id": 2,
        "name": "test_02_decision_change",
        "transcript_file": "test_02_decision_change.txt",
        "expected_file": "test_02_expected.json",
        "description": "Product launch timing (A->B changes: 2 decisions with history, 2 actions, 1 unresolved)",
    },
    {
        "id": 3,
        "name": "test_03_chaotic",
        "transcript_file": "test_03_chaotic.txt",
        "expected_file": "test_03_expected.json",
        "description": "Chaotic meeting (interruptions, casual speech, sarcasm, unresolved conflict)",
    },
    {
        "id": 4,
        "name": "test_04_implicit",
        "transcript_file": "test_04_implicit.txt",
        "expected_file": "test_04_expected.json",
        "description": "Implicit context (implicit pronouns, silence consensus, no deadlines)",
    },
    {
        "id": 5,
        "name": "test_05_sarcasm_fail",
        "transcript_file": "test_05_sarcasm_fail.txt",
        "expected_file": "test_05_expected.json",
        "description": "Adversarial test (sarcasm rejection, joke proposals, unresolved disputes)",
    },
    {
        "id": 6,
        "name": "test_06_explicit_decision",
        "transcript_file": "test_06_explicit_decision.txt",
        "expected_file": "test_06_expected.json",
        "description": "Explicit decision (proposal accepted with 'chốt': MongoDB log DB, 4 tasks, 1 blocker)",
    },
    {
        "id": 7,
        "name": "test_07_implicit_agreement",
        "transcript_file": "test_07_implicit_agreement.txt",
        "expected_file": "test_07_expected.json",
        "description": "Implicit agreement without 'chốt' (accepted using 'ok', 'được', 'nhất trí': Tailwind UI, 3 tasks)",
    },
    {
        "id": 8,
        "name": "test_08_mixed_utterance",
        "transcript_file": "test_08_mixed_utterance.txt",
        "expected_file": "test_08_expected.json",
        "description": "Mixed utterance (decision and task in single utterance: GCP staging migration, 5 tasks)",
    },
    {
        "id": 9,
        "name": "test_09_negative_control",
        "transcript_file": "test_09_negative_control.txt",
        "expected_file": "test_09_expected.json",
        "description": "Negative control (discussion and tasks but 0 decisions accepted: deferred notifications, 4 tasks)",
    },
]


def match_items(
    expected_list: List[str],
    actual_list: List[str],
    threshold: float = SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """
    Perform greedy 1-to-1 maximum similarity matching between expected and actual item texts.

    Args:
        expected_list: Texts representing ground truth items.
        actual_list: Texts representing extracted items.
        threshold: Minimum RapidFuzz token_set_ratio score to consider a match.

    Returns:
        Dict with count, matched, precision, recall, f1, and detailed matches.
    """
    exp_len = len(expected_list)
    act_len = len(actual_list)

    if exp_len == 0 and act_len == 0:
        return {
            "expected_count": 0,
            "actual_count": 0,
            "matched_count": 0,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "matches": [],
            "unmatched_expected": [],
            "unmatched_actual": [],
        }

    # Generate pairwise candidate matches
    candidates: List[Tuple[float, int, int]] = []
    for i, exp in enumerate(expected_list):
        for j, act in enumerate(actual_list):
            score = fuzz.token_set_ratio(exp, act)
            if score >= threshold:
                candidates.append((score, i, j))

    # Sort descending by similarity score
    candidates.sort(key=lambda x: x[0], reverse=True)

    matched_exp: set[int] = set()
    matched_act: set[int] = set()
    matches: List[Dict[str, Any]] = []

    for score, i, j in candidates:
        if i not in matched_exp and j not in matched_act:
            matched_exp.add(i)
            matched_act.add(j)
            matches.append(
                {
                    "expected": expected_list[i],
                    "actual": actual_list[j],
                    "score": round(score, 1),
                }
            )

    matched_count = len(matches)
    precision = (matched_count / act_len) if act_len > 0 else (1.0 if exp_len == 0 else 0.0)
    recall = (matched_count / exp_len) if exp_len > 0 else (1.0 if act_len == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    unmatched_exp = [expected_list[i] for i in range(exp_len) if i not in matched_exp]
    unmatched_act = [actual_list[j] for j in range(act_len) if j not in matched_act]

    return {
        "expected_count": exp_len,
        "actual_count": act_len,
        "matched_count": matched_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matches": matches,
        "unmatched_expected": unmatched_exp,
        "unmatched_actual": unmatched_act,
    }


def match_decisions(
    expected_decisions: List[Any],
    actual_decisions: List[Any],
    threshold: float = SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """
    Match decisions by semantic content and the settled choice (topic + final_value),
    evaluating status separately so a wrong status cannot be hidden by a content match.
    Uses greedy 1-to-1 matching to avoid double-counting duplicate predictions.
    """
    exp_len = len(expected_decisions)
    act_len = len(actual_decisions)

    if exp_len == 0 and act_len == 0:
        return {
            "expected_count": 0,
            "actual_count": 0,
            "matched_count": 0,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "matches": [],
            "unmatched_expected": [],
            "unmatched_actual": [],
            "status_mismatches": [],
        }

    # Generate pairwise candidate matches
    candidates: List[Tuple[float, int, int]] = []
    status_mismatches: List[Dict[str, Any]] = []

    for i, exp in enumerate(expected_decisions):
        exp_text = f"{exp.topic}: {exp.final_value}"
        exp_status = exp.status.value if hasattr(exp.status, "value") else str(exp.status)
        for j, act in enumerate(actual_decisions):
            act_text = f"{act.topic}: {act.final_value}"
            act_status = act.status.value if hasattr(act.status, "value") else str(act.status)

            score = fuzz.token_set_ratio(exp_text, act_text)
            if score >= threshold:
                if exp_status.lower() == act_status.lower():
                    candidates.append((score, i, j))
                else:
                    status_mismatches.append(
                        {
                            "expected": exp_text,
                            "expected_status": exp_status,
                            "actual": act_text,
                            "actual_status": act_status,
                            "score": round(score, 1),
                        }
                    )

    # Sort descending by similarity score
    candidates.sort(key=lambda x: x[0], reverse=True)

    matched_exp: set[int] = set()
    matched_act: set[int] = set()
    matches: List[Dict[str, Any]] = []

    for score, i, j in candidates:
        if i not in matched_exp and j not in matched_act:
            matched_exp.add(i)
            matched_act.add(j)
            matches.append(
                {
                    "expected": f"{expected_decisions[i].topic}: {expected_decisions[i].final_value} [{expected_decisions[i].status}]",
                    "actual": f"{actual_decisions[j].topic}: {actual_decisions[j].final_value} [{actual_decisions[j].status}]",
                    "score": round(score, 1),
                }
            )

    matched_count = len(matches)
    precision = (matched_count / act_len) if act_len > 0 else (1.0 if exp_len == 0 else 0.0)
    recall = (matched_count / exp_len) if exp_len > 0 else (1.0 if act_len == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    unmatched_exp = [
        f"{expected_decisions[i].topic}: {expected_decisions[i].final_value}"
        for i in range(exp_len)
        if i not in matched_exp
    ]
    unmatched_act = [
        f"{actual_decisions[j].topic}: {actual_decisions[j].final_value}"
        for j in range(act_len)
        if j not in matched_act
    ]

    return {
        "expected_count": exp_len,
        "actual_count": act_len,
        "matched_count": matched_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matches": matches,
        "unmatched_expected": unmatched_exp,
        "unmatched_actual": unmatched_act,
        "status_mismatches": status_mismatches,
    }


def compare_meeting_outputs(
    expected: ResolvedResult, actual: ResolvedResult
) -> Dict[str, Any]:
    """
    Compare expected ResolvedResult with pipeline actual ResolvedResult across all categories,
    using semantic decision matching with separate status verification.
    """
    # 1. Decisions (by semantic topic + settled choice and separate status evaluation)
    dec_res = match_decisions(expected.decisions, actual.decisions)

    # 2. Action items (by task similarity)
    exp_actions = [a.task for a in expected.action_items]
    act_actions = [a.task for a in actual.action_items]
    act_res = match_items(exp_actions, act_actions)

    # 3. Blockers (by issue similarity)
    exp_blockers = [b.issue for b in expected.blockers]
    act_blockers = [b.issue for b in actual.blockers]
    blk_res = match_items(exp_blockers, act_blockers)

    # 4. Requests (by content similarity)
    exp_requests = [r.content for r in expected.requests]
    act_requests = [r.content for r in actual.requests]
    req_res = match_items(exp_requests, act_requests)

    # 5. Unresolved items (by topic similarity)
    exp_unresolved = [u.topic for u in expected.unresolved_items]
    act_unresolved = [u.topic for u in actual.unresolved_items]
    unres_res = match_items(exp_unresolved, act_unresolved)

    total_expected = (
        dec_res["expected_count"]
        + act_res["expected_count"]
        + blk_res["expected_count"]
        + req_res["expected_count"]
        + unres_res["expected_count"]
    )
    total_actual = (
        dec_res["actual_count"]
        + act_res["actual_count"]
        + blk_res["actual_count"]
        + req_res["actual_count"]
        + unres_res["actual_count"]
    )
    total_matched = (
        dec_res["matched_count"]
        + act_res["matched_count"]
        + blk_res["matched_count"]
        + req_res["matched_count"]
        + unres_res["matched_count"]
    )

    total_precision = (
        (total_matched / total_actual)
        if total_actual > 0
        else (1.0 if total_expected == 0 else 0.0)
    )
    total_recall = (
        (total_matched / total_expected)
        if total_expected > 0
        else (1.0 if total_actual == 0 else 0.0)
    )
    total_f1 = (
        (2 * total_precision * total_recall / (total_precision + total_recall))
        if (total_precision + total_recall) > 0
        else 0.0
    )

    # Mapped public 4-group output counts (Decisions, Tasks, Unresolved, Issues)
    try:
        pub_actual = map_to_public(actual)
        public_counts = {
            "decisions": len(pub_actual.decisions),
            "tasks": len(pub_actual.tasks),
            "unresolved": len(pub_actual.unresolved),
            "issues": len(pub_actual.issues),
        }
    except Exception:
        public_counts = {
            "decisions": len(actual.decisions),
            "tasks": len(actual.action_items),
            "unresolved": len(actual.unresolved_items),
            "issues": len(actual.blockers),
        }

    return {
        "categories": {
            "Decisions": dec_res,
            "Action Items": act_res,
            "Blockers": blk_res,
            "Requests": req_res,
            "Unresolved Items": unres_res,
        },
        "totals": {
            "expected_count": total_expected,
            "actual_count": total_actual,
            "matched_count": total_matched,
            "precision": round(total_precision, 4),
            "recall": round(total_recall, 4),
            "f1": round(total_f1, 4),
        },
        "public_counts": public_counts,
    }


def run_pipeline(transcript_path: Path) -> ResolvedResult:
    """
    Execute full pipeline from raw text:
    Preprocess -> Extract -> Resolve -> Validate.
    """
    with open(transcript_path, "r", encoding="utf-8") as f:
        raw_transcript = f.read()

    # Step 0: Preprocessing
    preprocessed_text = preprocess(raw_transcript)

    # Step 1: Extraction
    extractor = Extractor()
    extraction_result = extractor.extract(preprocessed_text)

    # Step 2: Progression Resolution
    resolver = Resolver()
    resolved_output = resolver.resolve(extraction_result)

    # Step 3: Evidence Validation
    validator = Validator()
    validated_output = validator.validate(resolved_output, raw_transcript)

    return validated_output


def format_percent(val: float) -> str:
    """Format float into percentage string with color styling."""
    pct = val * 100
    if pct >= 80.0:
        return f"[green]{pct:.1f}%[/green]"
    if pct >= 50.0:
        return f"[yellow]{pct:.1f}%[/yellow]"
    return f"[red]{pct:.1f}%[/red]"


def print_test_results_table(test_meta: Dict[str, Any], evaluation: Dict[str, Any]) -> None:
    """Print Rich table formatted per test evaluation."""
    title = f"Test: {test_meta['name']} (ID: {test_meta['id']})"
    table = Table(
        title=title,
        box=box.ROUNDED,
        header_style="bold cyan",
        show_footer=True,
    )
    table.add_column("Category", style="bold white", footer="Total")
    table.add_column("Expected", justify="center", footer=str(evaluation["totals"]["expected_count"]))
    table.add_column("Actual", justify="center", footer=str(evaluation["totals"]["actual_count"]))
    table.add_column("Matched", justify="center", footer=str(evaluation["totals"]["matched_count"]))
    table.add_column("Precision", justify="center", footer=format_percent(evaluation["totals"]["precision"]))
    table.add_column("Recall", justify="center", footer=format_percent(evaluation["totals"]["recall"]))
    table.add_column("F1-Score", justify="center", footer=format_percent(evaluation["totals"]["f1"]))

    for cat_name, cat_data in evaluation["categories"].items():
        table.add_row(
            cat_name,
            str(cat_data["expected_count"]),
            str(cat_data["actual_count"]),
            str(cat_data["matched_count"]),
            format_percent(cat_data["precision"]),
            format_percent(cat_data["recall"]),
            format_percent(cat_data["f1"]),
        )

    console.print(table)
    
    # Print 4-group mapped counts
    pub = evaluation.get("public_counts", {})
    console.print(
        f"[dim]Public 4-Group Mapped Output Counts: "
        f"Decisions={pub.get('decisions', 0)}, Tasks={pub.get('tasks', 0)}, "
        f"Unresolved={pub.get('unresolved', 0)}, Issues={pub.get('issues', 0)}[/dim]"
    )
    console.print()


def resolve_transcript_path(filename: str) -> Path:
    """Resolve transcript file from transcripts or transcripts_extra dirs."""
    tfile = Path(filename)
    if tfile.is_absolute() and tfile.exists():
        return tfile
    if (config.TRANSCRIPTS_DIR / tfile).exists():
        return config.TRANSCRIPTS_DIR / tfile
    if (config.TESTS_DIR / "transcripts_extra" / "decisions" / tfile).exists():
        return config.TESTS_DIR / "transcripts_extra" / "decisions" / tfile
    if (config.TESTS_DIR / tfile).exists():
        return config.TESTS_DIR / tfile
    if (config.PROJECT_ROOT / tfile).exists():
        return config.PROJECT_ROOT / tfile
    return config.TRANSCRIPTS_DIR / tfile


def run_single_test(test_meta: Dict[str, Any], mock: bool = False) -> Dict[str, Any]:
    """Execute evaluation for a single test case."""
    transcript_path = resolve_transcript_path(test_meta["transcript_file"])
    expected_path = config.EXPECTED_DIR / test_meta["expected_file"]

    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
    if not expected_path.exists():
        raise FileNotFoundError(f"Expected output file not found: {expected_path}")

    with open(expected_path, "r", encoding="utf-8") as f:
        expected_output = ResolvedResult.model_validate_json(f.read())

    console.print(f"[bold blue]Running {test_meta['name']}[/bold blue]: {test_meta['description']}")

    if mock:
        console.print("[dim italic](Running in mock mode — using ground truth as pipeline output)[/dim italic]")
        actual_output = expected_output
    else:
        actual_output = run_pipeline(transcript_path)

    evaluation = compare_meeting_outputs(expected_output, actual_output)
    print_test_results_table(test_meta, evaluation)

    return {
        "test_id": test_meta["id"],
        "name": test_meta["name"],
        "description": test_meta["description"],
        "status": "passed",
        "categories": evaluation["categories"],
        "totals": evaluation["totals"],
        "public_counts": evaluation.get("public_counts", {}),
    }


def print_overall_summary(test_results: List[Dict[str, Any]]) -> None:
    """Print overall summary table across all executed tests and Decisions breakdown."""
    table = Table(
        title="[bold green]Overall Evaluation Summary (All Categories)[/bold green]",
        box=box.DOUBLE_EDGE,
        header_style="bold magenta",
        show_footer=True,
    )

    tot_exp = sum(t["totals"]["expected_count"] for t in test_results)
    tot_act = sum(t["totals"]["actual_count"] for t in test_results)
    tot_mat = sum(t["totals"]["matched_count"] for t in test_results)
    overall_p = (tot_mat / tot_act) if tot_act > 0 else (1.0 if tot_exp == 0 else 0.0)
    overall_r = (tot_mat / tot_exp) if tot_exp > 0 else (1.0 if tot_act == 0 else 0.0)
    overall_f1 = (2 * overall_p * overall_r / (overall_p + overall_r)) if (overall_p + overall_r) > 0 else 0.0

    table.add_column("Test Name", style="bold white", footer="Overall", overflow="fold")
    table.add_column("Expected", justify="center", footer=str(tot_exp))
    table.add_column("Actual", justify="center", footer=str(tot_act))
    table.add_column("Matched", justify="center", footer=str(tot_mat))
    table.add_column("Precision", justify="center", footer=format_percent(overall_p))
    table.add_column("Recall", justify="center", footer=format_percent(overall_r))
    table.add_column("F1-Score", justify="center", footer=format_percent(overall_f1))

    for t in test_results:
        totals = t["totals"]
        table.add_row(
            t["name"],
            str(totals["expected_count"]),
            str(totals["actual_count"]),
            str(totals["matched_count"]),
            format_percent(totals["precision"]),
            format_percent(totals["recall"]),
            format_percent(totals["f1"]),
        )

    console.print(table)
    console.print()

    # Dedicated Decisions breakdown table
    dec_table = Table(
        title="[bold cyan]Decisions Group Performance Breakdown (Semantic Match + Status)[/bold cyan]",
        box=box.DOUBLE_EDGE,
        header_style="bold blue",
        show_footer=True,
    )
    dec_table.add_column("Test Name", style="bold white", footer="Overall Decisions")
    dec_table.add_column("Expected", justify="center")
    dec_table.add_column("Actual", justify="center")
    dec_table.add_column("Matched", justify="center")
    dec_table.add_column("Precision", justify="center")
    dec_table.add_column("Recall", justify="center")
    dec_table.add_column("F1-Score", justify="center")
    dec_table.add_column("Mapped (D, T, U, I)", justify="center")

    dec_tot_exp = sum(t["categories"].get("Decisions", {}).get("expected_count", 0) for t in test_results)
    dec_tot_act = sum(t["categories"].get("Decisions", {}).get("actual_count", 0) for t in test_results)
    dec_tot_mat = sum(t["categories"].get("Decisions", {}).get("matched_count", 0) for t in test_results)
    dec_overall_p = (dec_tot_mat / dec_tot_act) if dec_tot_act > 0 else (1.0 if dec_tot_exp == 0 else 0.0)
    dec_overall_r = (dec_tot_mat / dec_tot_exp) if dec_tot_exp > 0 else (1.0 if dec_tot_act == 0 else 0.0)
    dec_overall_f1 = (2 * dec_overall_p * dec_overall_r / (dec_overall_p + dec_overall_r)) if (dec_overall_p + dec_overall_r) > 0 else 0.0

    dec_table.columns[1].footer = str(dec_tot_exp)
    dec_table.columns[2].footer = str(dec_tot_act)
    dec_table.columns[3].footer = str(dec_tot_mat)
    dec_table.columns[4].footer = format_percent(dec_overall_p)
    dec_table.columns[5].footer = format_percent(dec_overall_r)
    dec_table.columns[6].footer = format_percent(dec_overall_f1)
    dec_table.columns[7].footer = "-"

    for t in test_results:
        d = t["categories"].get("Decisions", {})
        pub = t.get("public_counts", {})
        pub_str = f"({pub.get('decisions', 0)}, {pub.get('tasks', 0)}, {pub.get('unresolved', 0)}, {pub.get('issues', 0)})"
        dec_table.add_row(
            t["name"],
            str(d.get("expected_count", 0)),
            str(d.get("actual_count", 0)),
            str(d.get("matched_count", 0)),
            format_percent(d.get("precision", 0.0)),
            format_percent(d.get("recall", 0.0)),
            format_percent(d.get("f1", 0.0)),
            pub_str,
        )

    console.print(dec_table)


def save_results_to_file(test_results: List[Dict[str, Any]]) -> Path:
    """Save detailed evaluation results to output/test_results.json."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = config.OUTPUT_DIR / "test_results.json"

    tot_exp = sum(t["totals"]["expected_count"] for t in test_results)
    tot_act = sum(t["totals"]["actual_count"] for t in test_results)
    tot_mat = sum(t["totals"]["matched_count"] for t in test_results)
    overall_p = (tot_mat / tot_act) if tot_act > 0 else (1.0 if tot_exp == 0 else 0.0)
    overall_r = (tot_mat / tot_exp) if tot_exp > 0 else (1.0 if tot_act == 0 else 0.0)
    overall_f1 = (2 * overall_p * overall_r / (overall_p + overall_r)) if (overall_p + overall_r) > 0 else 0.0

    dec_tot_exp = sum(t["categories"].get("Decisions", {}).get("expected_count", 0) for t in test_results)
    dec_tot_act = sum(t["categories"].get("Decisions", {}).get("actual_count", 0) for t in test_results)
    dec_tot_mat = sum(t["categories"].get("Decisions", {}).get("matched_count", 0) for t in test_results)
    dec_overall_p = (dec_tot_mat / dec_tot_act) if dec_tot_act > 0 else (1.0 if dec_tot_exp == 0 else 0.0)
    dec_overall_r = (dec_tot_mat / dec_tot_exp) if dec_tot_exp > 0 else (1.0 if dec_tot_act == 0 else 0.0)
    dec_overall_f1 = (2 * dec_overall_p * dec_overall_r / (dec_overall_p + dec_overall_r)) if (dec_overall_p + dec_overall_r) > 0 else 0.0

    payload = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": len(test_results),
        "overall_summary": {
            "expected_count": tot_exp,
            "actual_count": tot_act,
            "matched_count": tot_mat,
            "precision": round(overall_p, 4),
            "recall": round(overall_r, 4),
            "f1": round(overall_f1, 4),
        },
        "decisions_summary": {
            "expected_count": dec_tot_exp,
            "actual_count": dec_tot_act,
            "matched_count": dec_tot_mat,
            "precision": round(dec_overall_p, 4),
            "recall": round(dec_overall_r, 4),
            "f1": round(dec_overall_f1, 4),
        },
        "tests": test_results,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    console.print(f"[bold green]Saved detailed test results to:[/bold green] {out_file}")
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Meeting Mind Test Runner — Evaluates Vietnamese meeting extraction against ground truth."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--test",
        type=int,
        choices=list(range(1, len(TEST_CASES) + 1)),
        help=f"Run a specific test case by ID (1 to {len(TEST_CASES)}).",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help=f"Run all {len(TEST_CASES)} test cases.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode (uses expected ground truth as pipeline output without calling Gemini API).",
    )

    args = parser.parse_args()

    tests_to_run = (
        TEST_CASES
        if args.all
        else [t for t in TEST_CASES if t["id"] == args.test]
    )

    results: List[Dict[str, Any]] = []

    for test_meta in tests_to_run:
        try:
            res = run_single_test(test_meta, mock=args.mock)
            results.append(res)
        except Exception as e:
            console.print(f"[bold red]Test {test_meta['name']} failed with error:[/bold red] {e}")
            results.append(
                {
                    "test_id": test_meta["id"],
                    "name": test_meta["name"],
                    "description": test_meta["description"],
                    "status": "error",
                    "error": str(e),
                    "totals": {
                        "expected_count": 0,
                        "actual_count": 0,
                        "matched_count": 0,
                        "precision": 0.0,
                        "recall": 0.0,
                        "f1": 0.0,
                    },
                    "categories": {},
                }
            )

    if len(results) > 1:
        print_overall_summary(results)

    save_results_to_file(results)


if __name__ == "__main__":
    main()
