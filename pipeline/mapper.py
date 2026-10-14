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


EXTERNAL_KEYWORDS = (
    "đối tác", "doi tac", "partner", "khách hàng", "khach hang", "customer",
    "client", "vendor", "bên thứ ba", "ben thu ba", "third party", "vnpay",
    "account manager", "bên ngoài"
)

REVIEWER_KEYWORDS = (
    "duyệt", "duyet", "review", "approve", "kiểm tra", "kiem tra", "check"
)

COLLABORATOR_KEYWORDS = (
    "phối hợp", "phoi hop", "cùng", "cung", "team", "nhóm", "nhom"
)


def parse_assignee_and_roles(
    raw_assignee: Optional[str],
    participants: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Parse a potentially compound or multi-role assignee string.
    Returns: (assignee, external_dependency, reviewer, collaborator)

    Distinguishes internal performer from external dependencies, reviewers, and collaborators.
    Examples:
    - "Bình / Đối tác" -> ("Bình", "Đối tác", None, None)
    - "Bình / Đối tác VNPay" -> ("Bình", "Đối tác VNPay", None, None)
    - "Bình và đối tác" -> ("Bình", "đối tác", None, None)
    - "Tuấn / Mai duyệt" -> ("Tuấn", None, "Mai", None)
    - "Tuấn (Mai duyệt)" -> ("Tuấn", None, "Mai", None)
    - "Mai phối hợp với team sản phẩm" -> ("Mai", None, None, "team sản phẩm")
    - "Đối tác" (not in participants) -> (None, "Đối tác", None, None)
    """
    if not raw_assignee or not raw_assignee.strip():
        return None, None, None, None

    clean = raw_assignee.strip()

    reviewer: Optional[str] = None
    collaborator: Optional[str] = None
    external_dep: Optional[str] = None
    assignee: Optional[str] = None

    # 1. Check parenthesized note, e.g. "Tuấn (Mai duyệt)" or "Bình (đối tác)"
    paren_match = re.match(r"^(.*?)\s*\((.*?)\)$", clean)
    if paren_match:
        clean = paren_match.group(1).strip()
        extra = paren_match.group(2).strip()
        extra_lower = extra.lower()
        if any(kw in extra_lower for kw in REVIEWER_KEYWORDS):
            rev_name = re.sub(r"^(?:review|duyệt|kiểm tra|approve|check)\s*:?\s*", "", extra, flags=re.IGNORECASE).strip()
            rev_name = re.sub(r"\s+(?:review|duyệt|kiểm tra|approve|check)$", "", rev_name, flags=re.IGNORECASE).strip()
            reviewer = normalize_person_name(rev_name, participants)
        elif any(kw in extra_lower for kw in COLLABORATOR_KEYWORDS):
            collaborator = extra
        elif any(kw in extra_lower for kw in EXTERNAL_KEYWORDS):
            external_dep = extra
        else:
            external_dep = extra

    # 2. Check for explicit delimiters: '/', ' và ', ' & ', ' kèm ', ','
    delimiters = [r"\s*/\s*", r"\s+và\s+", r"\s*&\s*", r"\s+kèm\s+", r",\s*"]
    split_parts: List[str] = []
    for delim in delimiters:
        parts = [p.strip() for p in re.split(delim, clean) if p.strip()]
        if len(parts) > 1:
            split_parts = parts
            break

    if split_parts:
        matched_assignee = None
        remaining_parts = []
        for part in split_parts:
            norm_p = normalize_person_name(part, participants)
            if participants and norm_p in participants and matched_assignee is None:
                matched_assignee = norm_p
            else:
                remaining_parts.append(part)

        if matched_assignee:
            assignee = matched_assignee
        else:
            assignee = split_parts[0]
            remaining_parts = split_parts[1:]

        for rem in remaining_parts:
            rem_lower = rem.lower()
            if any(kw in rem_lower for kw in REVIEWER_KEYWORDS) and not reviewer:
                rev_name = re.sub(r"^(?:review|duyệt|kiểm tra|approve|check)\s*:?\s*", "", rem, flags=re.IGNORECASE).strip()
                rev_name = re.sub(r"\s+(?:review|duyệt|kiểm tra|approve|check)$", "", rev_name, flags=re.IGNORECASE).strip()
                reviewer = normalize_person_name(rev_name, participants) if rev_name else rem
            elif any(kw in rem_lower for kw in COLLABORATOR_KEYWORDS) and not collaborator:
                collaborator = rem
            elif not external_dep:
                external_dep = rem

        return assignee, external_dep, reviewer, collaborator

    # 3. Check inline phrases:
    rev_match = re.search(r"^(.*?)\s+(?:gửi|cho|để)\s+(.*?)\s+(?:duyệt|review|kiểm tra)$", clean, re.IGNORECASE)
    if rev_match:
        assignee = normalize_person_name(rev_match.group(1).strip(), participants)
        reviewer = normalize_person_name(rev_match.group(2).strip(), participants)
        return assignee, external_dep, reviewer, collaborator

    collab_match = re.search(r"^(.*?)\s+phối hợp\s+(?:với|cùng)?\s+(.+)$", clean, re.IGNORECASE)
    if collab_match:
        assignee = normalize_person_name(collab_match.group(1).strip(), participants)
        collaborator = collab_match.group(2).strip()
        return assignee, external_dep, reviewer, collaborator

    # 4. Check if standalone name is purely an external entity (e.g. "Đối tác", "Đối tác VNPay")
    clean_lower = clean.lower()
    norm_single = normalize_person_name(clean, participants)
    is_in_participants = participants and (norm_single in participants)
    if not is_in_participants and any(kw in clean_lower for kw in EXTERNAL_KEYWORDS):
        return None, clean, reviewer, collaborator

    # 5. Single assignee
    return clean, external_dep, reviewer, collaborator


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
    # 3. Map Action Items (Ownership & Role Separation)
    # ─────────────────────────────────────────────────────────────────────────
    for a in resolved_result.action_items:
        deadline_raw = a.deadline
        is_rel_allowed = (date_source != "fallback_today")
        deadline_iso = convert_deadline_to_iso(
            deadline_raw, meeting_date_obj, is_relative_allowed=is_rel_allowed
        )

        # Parse compound assignee strings (e.g. "Bình / Đối tác", "Tuấn / Mai duyệt")
        parsed_assignee, parsed_ext_dep, parsed_rev, parsed_collab = parse_assignee_and_roles(
            a.assignee, participants
        )

        ext_dep = getattr(a, "external_dependency", None) or parsed_ext_dep
        collab = getattr(a, "collaborator", None) or parsed_collab
        rev = getattr(a, "reviewer", None) or parsed_rev
        escalation = getattr(a, "escalation", None)

        norm_assignee = normalize_person_name(parsed_assignee, participants) if parsed_assignee else None
        is_generic = is_generic_assignee(norm_assignee)

        if norm_assignee and not is_generic:
            # Explicitly named responsible person -> Confirmed PublicTask.
            # Explicit verbal acceptance is NOT required for task ownership.
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
                    external_dependency=ext_dep,
                    collaborator=collab,
                    reviewer=rev,
                    escalation=escalation,
                )
            )
        else:
            # Truly unassigned: no responsible person identified or generic placeholder (ai đó, chưa rõ, cả team)
            downgrade_count += 1
            reason = "Chưa có người nhận trách nhiệm cụ thể."
            logger.info(
                f"[Mapper] Action item '{a.item_id}' ({a.task}) mapped to unconfirmed_task (assignee={norm_assignee})"
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
        logger.info(f"[Mapper Summary] Mapped {downgrade_count} unassigned item(s) to unconfirmed_task.")

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
