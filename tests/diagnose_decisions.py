"""
Diagnosis script for Meeting Mind - Decisions Group Analysis.
Runs the live pipeline on 4 new test transcripts and prints compact funnel tables.
DOES NOT log raw transcript text or sensitive content.
"""
import os
import sys
from pathlib import Path
from collections import Counter

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.preprocessor import preprocess
from pipeline.extractor import Extractor
from pipeline.resolver import Resolver
from pipeline.validator import Validator
from pipeline.mapper import map_to_public
import config


def diagnose_sample(transcript_path: Path):
    name = transcript_path.name
    raw_text = transcript_path.read_text(encoding="utf-8")
    
    # Preprocessing
    preprocessed = preprocess(raw_text)
    num_lines = len(preprocessed.splitlines())
    
    # Step 1: Extractor
    extractor = Extractor()
    step1_res = extractor.extract(preprocessed)
    step1_types = Counter([u.type.value for u in step1_res.utterances])
    step1_utterance_ids = [u.id for u in step1_res.utterances]
    unique_step1_ids = len(set(step1_utterance_ids))
    total_step1_items = len(step1_res.utterances)
    
    # Step 2: Resolver
    resolver = Resolver()
    step2_res = resolver.resolve(step1_res)
    step2_decisions = step2_res.decisions
    step2_dec_statuses = Counter([d.status.value if hasattr(d.status, "value") else str(d.status) for d in step2_decisions])
    
    # Step 3: Validator
    validator = Validator()
    validated_res = validator.validate(step2_res, raw_text)
    val_dec_reviews = []
    for d in validated_res.decisions:
        reasons = []
        tot_ev = sum(len(h.evidence) for h in d.history)
        ver_ev = sum(sum(1 for ev in h.evidence if ev.verified) for h in d.history)
        mismatch_ev = sum(sum(1 for ev in h.evidence if ev.speaker_matched is False) for h in d.history)
        if not d.topic.strip() or not d.final_value.strip():
            reasons.append("empty_topic_or_value")
        if tot_ev == 0:
            reasons.append("zero_evidence")
        if ver_ev < tot_ev:
            reasons.append(f"unverified_evidence({ver_ev}/{tot_ev})")
        if mismatch_ev > 0:
            reasons.append(f"speaker_mismatch({mismatch_ev})")
        val_dec_reviews.append({
            "id": d.item_id,
            "status": d.status.value if hasattr(d.status, "value") else str(d.status),
            "needs_review": d.needs_review,
            "reasons": reasons,
            "total_ev": tot_ev,
            "verified_ev": ver_ev,
        })
    
    # Step 4: Mapper
    public_res = map_to_public(validated_res, transcript=raw_text)
    
    # Check PublicDecision attributes
    pub_dec_status_present = all(hasattr(d, "status") for d in public_res.decisions)
    pub_dec_statuses = [getattr(d, "status", "<MISSING>") for d in public_res.decisions]
    
    # Unresolved breakdown
    unres_from_dec = [u for u in public_res.unresolved if getattr(u, "kind", None) == "open_decision"]
    
    return {
        "name": name,
        "lines": num_lines,
        "step1_total": total_step1_items,
        "step1_unique_ids": unique_step1_ids,
        "step1_types": dict(step1_types),
        "step2_decisions_count": len(step2_decisions),
        "step2_statuses": dict(step2_dec_statuses),
        "step2_action_items": len(step2_res.action_items),
        "step2_unresolved": len(step2_res.unresolved_items),
        "step2_blockers": len(step2_res.blockers),
        "step3_dec_reviews": val_dec_reviews,
        "mapper_decisions": len(public_res.decisions),
        "mapper_tasks": len(public_res.tasks),
        "mapper_unresolved": len(public_res.unresolved),
        "mapper_unresolved_from_dec": len(unres_from_dec),
        "mapper_issues": len(public_res.issues),
        "pub_dec_status_present": pub_dec_status_present,
        "pub_dec_statuses": pub_dec_statuses,
        "frontend_visible_decisions": sum(1 for d in public_res.decisions if getattr(d, "status", None) == "confirmed"),
    }


def main():
    decisions_dir = REPO_ROOT / "tests" / "transcripts_extra" / "decisions"
    samples = sorted(decisions_dir.glob("*.txt"))
    
    if not samples:
        print("No samples found in", decisions_dir)
        return
    
    print("=" * 80)
    print("MEETING MIND - DECISION EXTRACTION DIAGNOSIS (LIVE PIPELINE)")
    print("=" * 80)
    
    results = []
    for sample in samples:
        print(f"\nProcessing {sample.name}...")
        res = diagnose_sample(sample)
        results.append(res)
        
        print(f"\n--- Funnel Table for: {res['name']} ({res['lines']} utterances) ---")
        print(f"  Step 1 Candidates: Total={res['step1_total']}, Unique IDs={res['step1_unique_ids']}")
        print(f"    Types: {res['step1_types']}")
        print(f"  Step 2 Internal Output:")
        print(f"    Decisions: {res['step2_decisions_count']} -> Statuses: {res['step2_statuses']}")
        print(f"    Action items: {res['step2_action_items']}, Blockers: {res['step2_blockers']}, Unresolved: {res['step2_unresolved']}")
        print(f"  Step 3 Validator:")
        for r in res['step3_dec_reviews']:
            print(f"    Decision {r['id']} (status={r['status']}, needs_review={r['needs_review']}): reasons={r['reasons']}")
        print(f"  Step 4 Mapper Output:")
        print(f"    Decisions={res['mapper_decisions']}, Tasks={res['mapper_tasks']}, Unresolved={res['mapper_unresolved']} (from decisions: {res['mapper_unresolved_from_dec']}), Issues={res['mapper_issues']}")
        print(f"  Final / Frontend Layer:")
        print(f"    PublicDecision has 'status' field: {res['pub_dec_status_present']}")
        print(f"    PublicDecision status values: {res['pub_dec_statuses']}")
        print(f"    Frontend visible count (d.status === 'confirmed'): {res['frontend_visible_decisions']}")
        
    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON TABLE")
    print("=" * 80)
    header = f"{'Sample':<18} | {'Step1 Dec':<9} | {'Step2 Dec':<9} | {'Val Rev':<7} | {'Map Dec':<7} | {'Map Unres(Dec)':<14} | {'FE Visible':<10}"
    print(header)
    print("-" * len(header))
    for r in results:
        step1_dec = r['step1_types'].get('decision', 0)
        step2_dec = r['step2_decisions_count']
        val_rev = sum(1 for d in r['step3_dec_reviews'] if d['needs_review'])
        map_dec = r['mapper_decisions']
        map_unres_dec = r['mapper_unresolved_from_dec']
        fe_vis = r['frontend_visible_decisions']
        print(f"{r['name']:<18} | {step1_dec:<9} | {step2_dec:<9} | {val_rev:<7} | {map_dec:<7} | {map_unres_dec:<14} | {fe_vis:<10}")


if __name__ == "__main__":
    main()
