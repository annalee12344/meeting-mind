"""
Deterministic Mapper Module for Meeting Mind.

Pure functions that map internal Step 2 results (ResolvedResult) into the public
4-group output (MeetingOutput: Decisions, Tasks, Unresolved, Issues).

Enforces strict business rules:
- decisions: confirmed -> Decisions; unresolved/needs_review -> Unresolved (open_decision); superseded -> history only.
- unresolved_items -> Unresolved (open_decision).
- action_items: -> Tasks only if assignee is non-empty & non-generic AND confirmed by assignee.
  Otherwise -> Unresolved (unconfirmed_task).
- requests: clear assignee -> Tasks; otherwise -> Unresolved (unconfirmed_task).
- blockers -> Issues (status 'open').
- feedback/information -> hidden internal context.
"""
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import unicodedata

from models.output import (
    ActionItem,
    Decision,
    ItemStatus,
    MeetingOutput,
    PublicDecision,
    PublicIssue,
    PublicMeta,
    PublicTask,
    PublicUnresolvedItem,
    ResolvedResult,
)
from pipeline.deadlines import convert_deadline_to_iso, resolve_meeting_date

logger = logging.getLogger(__name__)

# List of honorific prefixes in Vietnamese & English to strip when normalizing person names
HONORIFIC_REGEX = re.compile(
    r"^(?:anh|chị|chi|em|bạn|ban|cô|co|chú|chu|bác|bac|thầy|thay|ông|ong|bà|ba|mr\.?|ms\.?|mrs\.?)\s+",
    re.IGNORECASE,
)

GENERIC_ASSIGNEES = {
    "unknown",
    "chưa rõ",
    "chưa có",
    "chưa phân công",
    "chưa giao",
    "ai đó",
    "team",
    "cả team",
    "mọi người",
    "tất cả",
    "all",
    "nobody",
    "none",
    "null",
}


def strip_accents(text: str) -> str:
    """Strip Vietnamese diacritics for insensitive comparison."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def normalize_person_name(name: Optional[str], participants: Optional[List[str]] = None) -> str:
    """
    Normalize person name:
    1. Strip honorifics (anh, chị, em, bạn, cô, chú, Mr, Ms...).
    2. Normalize Unicode NFC.
    3. Match against participants list (exact, diacritic-insensitive, or substring).
    """
    if not name or not name.strip():
        return ""

    clean = unicodedata.normalize("NFC", name.strip())
    # Strip honorific prefix
    clean = HONORIFIC_REGEX.sub("", clean).strip()

    if not participants:
        return clean

    clean_lower = clean.lower()
    clean_no_accents = strip_accents(clean)

    # 1. Exact case-insensitive match
    for p in participants:
        p_nfc = unicodedata.normalize("NFC", p.strip())
        if p_nfc.lower() == clean_lower:
            return p_nfc

    # 2. Diacritic-insensitive match
    for p in participants:
        p_nfc = unicodedata.normalize("NFC", p.strip())
        if strip_accents(p_nfc) == clean_no_accents:
            return p_nfc

    # 3. Substring match (e.g. "Lan" in "Nguyễn Thị Lan")
    for p in participants:
        p_nfc = unicodedata.normalize("NFC", p.strip())
        p_parts = p_nfc.split()
        if clean in p_parts or clean_no_accents in [strip_accents(part) for part in p_parts]:
            return p_nfc

    return clean


def is_generic_assignee(name: Optional[str]) -> bool:
    """Return True if assignee is missing or a generic placeholder."""
    if not name or not name.strip():
        return True
    cleaned = unicodedata.normalize("NFC", name.strip().lower())
    return cleaned in GENERIC_ASSIGNEES


def build_utterance_speaker_map(
    resolved_result: ResolvedResult,
    transcript: Optional[str] = None,
) -> Dict[str, str]:
    """Build a mapping of utterance_id (e.g. 'U001') -> speaker name."""
    speaker_map: Dict[str, str] = {}

    # 1. Parse from transcript if available
    if transcript:
        for line in transcript.splitlines():
            # Line format: [U001] [09:00] Tuấn: Text or [U001] Tuấn: Text
            m = re.match(r"^\[(?P<uid>U\d{3,})\]\s*(?:\[[^\]]+\])?\s*(?P<speaker>[^:]+):", line.strip())
            if m:
                uid = m.group("uid").strip()
                speaker = m.group("speaker").strip()
                speaker_map[uid] = speaker

    # 2. Parse from all evidence in resolved_result
    def collect_evidence_speakers(ev_list):
        for ev in ev_list:
            if ev.utterance_id and ev.speaker:
                speaker_map[ev.utterance_id] = ev.speaker

    for d in resolved_result.decisions:
        for h in d.history:
            collect_evidence_speakers(h.evidence)
    for a in resolved_result.action_items:
        collect_evidence_speakers(a.evidence)
    for b in resolved_result.blockers:
        collect_evidence_speakers(b.evidence)
    for r in resolved_result.requests:
        collect_evidence_speakers(r.evidence)
    for u in resolved_result.unresolved_items:
        collect_evidence_speakers(u.evidence)

    return speaker_map


def derive_decision_actors(
    decision: Decision,
    utterance_speaker_map: Dict[str, str],
    participants: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Derive proposed_by and confirmed_by from history entries and utterance IDs.
    Returns (proposed_by, confirmed_by).
    """
    proposed_by: Optional[str] = None
    confirmed_by: Optional[str] = None

    for entry in decision.history:
        entry_role = (entry.role or "").lower()
        speaker = None

        if entry.evidence:
            first_ev = entry.evidence[0]
            if first_ev.utterance_id and first_ev.utterance_id in utterance_speaker_map:
                speaker = utterance_speaker_map[first_ev.utterance_id]
            else:
                speaker = first_ev.speaker

        if speaker:
            speaker = normalize_person_name(speaker, participants)

        if "propose" in entry_role or entry.status == ItemStatus.SUPERSEDED:
            if not proposed_by and speaker:
                proposed_by = speaker

        if "confirm" in entry_role or entry.status == ItemStatus.CONFIRMED:
            if speaker:
                confirmed_by = speaker

    # Fallbacks if history roles were missing
    if not proposed_by and decision.history and decision.history[0].evidence:
        spk = decision.history[0].evidence[0].speaker
        if spk:
            proposed_by = normalize_person_name(spk, participants)

    if not confirmed_by and decision.status == ItemStatus.CONFIRMED:
        # Check last history entry
        if decision.history and decision.history[-1].evidence:
            spk = decision.history[-1].evidence[-1].speaker
            if spk:
                confirmed_by = normalize_person_name(spk, participants)

    return proposed_by, confirmed_by


def map_to_public(
    resolved_result: ResolvedResult,
    transcript: Optional[str] = None,
    meeting_date_input: Optional[str] = None,
    models_used: Optional[Dict[str, str]] = None,
    prompt_version: str = "2.0.0",
) -> MeetingOutput:
    """
    Map internal ResolvedResult into public MeetingOutput (4 groups + Meta).
    """
    # Resolve meeting date
    meeting_date_obj, date_source = resolve_meeting_date(
        user_input_date=meeting_date_input,
        transcript=transcript,
    )
    meeting_date_str = meeting_date_obj.isoformat()

    # Build speaker map
    speaker_map = build_utterance_speaker_map(resolved_result, transcript=transcript)
    participants = resolved_result.participants or []

    public_decisions: List[PublicDecision] = []
    public_tasks: List[PublicTask] = []
    public_unresolved: List[PublicUnresolvedItem] = []
    public_issues: List[PublicIssue] = []

    downgrade_count = 0
    needs_review_decision_count = 0

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Map Decisions
    # ─────────────────────────────────────────────────────────────────────────
    for d in resolved_result.decisions:
        prop_by, conf_by = derive_decision_actors(d, speaker_map, participants)

        # Collect all evidence from history entries
        all_ev = []
        for h in d.history:
            all_ev.extend(h.evidence)

        if d.status in (ItemStatus.CONFIRMED, ItemStatus.NEEDS_REVIEW):
            # A decision with status confirmed (or quality flag needs_review) must remain in Decisions
            is_review = bool(d.needs_review or (d.status == ItemStatus.NEEDS_REVIEW))
            public_decisions.append(
                PublicDecision(
                    source_ref=d.item_id,
                    topic=d.topic,
                    content=d.final_value,
                    proposed_by=prop_by,
                    confirmed_by=conf_by,
                    status="confirmed",
                    condition=getattr(d, "condition", None),
                    evidence=all_ev,
                    history=d.history,
                    needs_review=is_review,
                )
            )
        elif d.status == ItemStatus.UNRESOLVED:
            public_unresolved.append(
                PublicUnresolvedItem(
                    source_ref=d.item_id,
                    kind="open_decision",
                    content=d.final_value or d.topic,
                    reason_unresolved="Chưa thống nhất trong cuộc họp.",
                    evidence=all_ev,
                    needs_review=d.needs_review,
                )
            )
        elif d.status == ItemStatus.SUPERSEDED:
            # Preserve superseded decisions in decision history if matching confirmed decision exists
            matching_decision = next(
                (cd for cd in public_decisions if cd.topic.strip().lower() == d.topic.strip().lower()),
                None
            )
            if matching_decision:
                if not any(h.value == d.final_value for h in matching_decision.history):
                    matching_decision.history.insert(
                        0,
                        HistoryEntry(
                            value=d.final_value,
                            status=ItemStatus.SUPERSEDED,
                            speaker=prop_by or conf_by,
                            evidence=all_ev,
                        )
                    )
            logger.debug(f"[Mapper] Decision '{d.item_id}' is superseded. Omitting from top-level decisions.")

    if needs_review_decision_count > 0:
        logger.info(f"[Mapper Summary] {needs_review_decision_count} decision(s) routed to Unresolved due to needs_review.")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Map Unresolved Items from ResolvedResult
    # ─────────────────────────────────────────────────────────────────────────
    for u in resolved_result.unresolved_items:
        public_unresolved.append(
            PublicUnresolvedItem(
                source_ref=u.item_id,
                kind="open_decision",
                content=u.topic,
                reason_unresolved=u.reason_unresolved,
                evidence=u.evidence,
                needs_review=u.needs_review,
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Map Action Items (with Task Acceptance Guard)
    # ─────────────────────────────────────────────────────────────────────────
    for a in resolved_result.action_items:
        deadline_raw = a.deadline
        deadline_iso = convert_deadline_to_iso(deadline_raw, meeting_date_obj)

        raw_assignee = a.assignee
        norm_assignee = normalize_person_name(raw_assignee, participants) if raw_assignee else None
        is_generic = is_generic_assignee(norm_assignee)

        # Check confirmation
        confirmation_valid = False
        if not is_generic and a.assignee_confirmed and a.confirmation_utterance_id:
            conf_speaker = speaker_map.get(a.confirmation_utterance_id)
            if conf_speaker:
                norm_conf_speaker = normalize_person_name(conf_speaker, participants)
                if norm_conf_speaker == norm_assignee:
                    confirmation_valid = True

        if not is_generic and a.assignee_confirmed and confirmation_valid:
            # Passes all criteria -> Confirmed Task
            public_tasks.append(
                PublicTask(
                    source_ref=a.item_id,
                    title=a.task,
                    assignee=norm_assignee,
                    assigned_by=normalize_person_name(a.assigned_by, participants) if a.assigned_by else None,
                    requested_by=None,
                    deadline_raw=deadline_raw,
                    deadline_iso=deadline_iso,
                    source="ai",
                    evidence=a.evidence,
                    needs_review=a.needs_review,
                )
            )
        else:
            # Downgrade to Unresolved (unconfirmed_task)
            downgrade_count += 1
            reason = "Chưa có người nhận trách nhiệm hoặc người nhận chưa xác nhận đồng ý."
            logger.info(
                f"[Mapper] Action item '{a.item_id}' ({a.task}) downgraded to unconfirmed_task "
                f"(assignee={norm_assignee}, confirmed={a.assignee_confirmed}, conf_valid={confirmation_valid})"
            )
            public_unresolved.append(
                PublicUnresolvedItem(
                    source_ref=a.item_id,
                    kind="unconfirmed_task",
                    content=a.task,
                    reason_unresolved=reason,
                    suggested_assignee=norm_assignee if not is_generic else None,
                    suggested_deadline_raw=deadline_raw,
                    suggested_deadline_iso=deadline_iso,
                    evidence=a.evidence,
                    needs_review=True if is_generic or a.needs_review else False,
                )
            )

    if downgrade_count > 0:
        logger.info(f"[Mapper Summary] Downgraded {downgrade_count} action item(s) to unconfirmed_task.")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Map Requests
    # ─────────────────────────────────────────────────────────────────────────
    for r in resolved_result.requests:
        norm_to = normalize_person_name(r.to_person, participants) if r.to_person else None
        norm_from = normalize_person_name(r.from_person, participants) if r.from_person else None

        if norm_to and not is_generic_assignee(norm_to):
            # Clear non-generic assignee -> Task
            public_tasks.append(
                PublicTask(
                    source_ref=r.item_id,
                    title=r.content,
                    assignee=norm_to,
                    assigned_by=norm_from,
                    requested_by=norm_from,
                    deadline_raw=None,
                    deadline_iso=None,
                    source="ai",
                    evidence=r.evidence,
                    needs_review=r.needs_review,
                )
            )
        else:
            # Otherwise -> Unresolved (unconfirmed_task)
            public_unresolved.append(
                PublicUnresolvedItem(
                    source_ref=r.item_id,
                    kind="unconfirmed_task",
                    content=r.content,
                    reason_unresolved=f"Yêu cầu từ {norm_from or 'thành viên'} chưa phân công người thực hiện.",
                    suggested_assignee=norm_to if norm_to and not is_generic_assignee(norm_to) else None,
                    evidence=r.evidence,
                    needs_review=r.needs_review,
                )
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Map Blockers -> Issues (Status: open)
    # ─────────────────────────────────────────────────────────────────────────
    resolved_benchmark_blocker_count = 0
    for b in resolved_result.blockers:
        if b.status in (ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED):
            resolved_benchmark_blocker_count += 1

        norm_owner = normalize_person_name(b.owner, participants) if b.owner else None
        public_issues.append(
            PublicIssue(
                source_ref=b.item_id,
                content=b.issue,
                owner=norm_owner,
                status="open",
                evidence=b.evidence,
                needs_review=b.needs_review,
            )
        )

    if resolved_benchmark_blocker_count > 0:
        logger.info(
            f"[Mapper Summary] {resolved_benchmark_blocker_count} blocker(s) had resolved/superseded status."
        )

    # Calculate transcript hash
    tx_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16] if transcript else ""

    meta = PublicMeta(
        schema_version="2.0.0",
        prompt_version=prompt_version,
        per_step_model=models_used or {},
        transcript_hash=tx_hash,
        meeting_date=meeting_date_str,
        meeting_date_source=date_source,
    )

    return MeetingOutput(
        summary=resolved_result.meeting_summary,
        participants=participants,
        decisions=public_decisions,
        tasks=public_tasks,
        unresolved=public_unresolved,
        issues=public_issues,
        meta=meta,
    )


def upgrade_legacy_result(
    legacy_data: Union[dict, str, ResolvedResult],
    meeting_date_input: Optional[str] = None,
) -> MeetingOutput:
    """
    Convert an old exported 5-array JSON (no schema_version) into the new 4-group MeetingOutput.
    """
    if isinstance(legacy_data, str):
        parsed = json.loads(legacy_data)
    elif isinstance(legacy_data, dict):
        parsed = legacy_data
    elif isinstance(legacy_data, ResolvedResult):
        return map_to_public(legacy_data, meeting_date_input=meeting_date_input)
    else:
        raise ValueError(f"Unsupported input type for upgrade_legacy_result: {type(legacy_data)}")

    # Check if already upgraded
    if "schema_version" in parsed or ("tasks" in parsed and "unresolved" in parsed and "issues" in parsed):
        return MeetingOutput.model_validate(parsed)

    # Parse as internal ResolvedResult
    resolved = ResolvedResult.model_validate(parsed)
    return map_to_public(resolved, meeting_date_input=meeting_date_input)
