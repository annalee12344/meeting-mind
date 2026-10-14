"""
Step 3 — Evidence validation via hardened fuzzy string matching and utterance anchoring.

Verifies that all quotes extracted by the LLM genuinely exist within the
original meeting transcript:
1. Normalizes all strings to Unicode NFC (handling precomposed vs combining characters).
2. Anchors quote verification to cited utterance_id (+/- 1-2 neighbor utterances).
   Falls back to global search across the transcript only if neighbor search fails,
   recording the corrected utterance ID.
3. Enforces strict verbatim/exact matching for short quotes (< 6 words or < 20 chars)
   to eliminate fuzzy partial_ratio false positives on common words.
4. Verifies evidence speaker against the speaker of the matching utterance,
   flagging speaker mismatches.
5. Sets evidence.verified = True/False, evidence.speaker_matched = True/False,
   and marks parent items with needs_review = True if evidence is missing, unverified,
   or speaker-mismatched.
"""
from dataclasses import dataclass
import logging
import re
from typing import List, Optional, Set, Tuple
import unicodedata

from rapidfuzz import fuzz

import config
from models.output import Evidence, ResolvedResult
from pipeline.preprocessor import parse_line

logger = logging.getLogger(__name__)

# Minimum length requirements for fuzzy matching
MIN_FUZZY_WORDS = 6
MIN_FUZZY_CHARS = 20

# Honorific prefixes in Vietnamese & English for speaker normalization
HONORIFIC_REGEX = re.compile(
    r"^(?:anh|chị|chi|em|bạn|ban|cô|co|chú|chu|bác|bac|thầy|thay|ông|ong|bà|ba|mr\.?|ms\.?|mrs\.?)\s+",
    re.IGNORECASE,
)

RE_UID_PREFIX = re.compile(r"^\[?(U\d+)\]?\s*[:\-]?", re.IGNORECASE)


@dataclass
class UtteranceEntry:
    """Indexed utterance parsed from the transcript."""
    uid: str                 # Standardized "U001", "U002"...
    speaker: str             # Speaker name from transcript line
    text: str                # Utterance content text
    raw_line: str            # Full original line
    index: int               # 1-based line sequence index


def strip_accents(text: str) -> str:
    """Strip Vietnamese combining diacritics for insensitive comparison."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def normalize_uid(uid: Optional[str]) -> Optional[str]:
    """
    Standardize utterance ID into 'Uxxx' format.
    Handles 'u1', 'U01', '[U001]', 'U0001'.
    """
    if not uid:
        return None
    cleaned = uid.strip().upper()
    m = re.search(r"\d+", cleaned)
    if m:
        return f"U{int(m.group(0)):03d}"
    return None


def parse_transcript_utterances(transcript_text: str) -> List[UtteranceEntry]:
    """
    Parse a raw or preprocessed transcript into a list of UtteranceEntry objects.
    Ensures every line is NFC normalized and assigned a standardized Uxxx ID.
    """
    if not transcript_text or not transcript_text.strip():
        return []

    entries: List[UtteranceEntry] = []
    lines = [
        unicodedata.normalize("NFC", l.strip())
        for l in transcript_text.splitlines()
        if l.strip()
    ]

    for idx, line in enumerate(lines, 1):
        m = RE_UID_PREFIX.match(line)
        if m:
            raw_uid = m.group(1).upper()
            num_match = re.search(r"\d+", raw_uid)
            uid = f"U{int(num_match.group(0)):03d}" if num_match else f"U{idx:03d}"
        else:
            uid = f"U{idx:03d}"

        parsed = parse_line(line)
        entries.append(
            UtteranceEntry(
                uid=uid,
                speaker=unicodedata.normalize("NFC", parsed.speaker.strip()),
                text=unicodedata.normalize("NFC", parsed.text.strip()),
                raw_line=line,
                index=idx,
            )
        )

    return entries


def check_speaker_match(ev_speaker: Optional[str], utt_speaker: Optional[str]) -> Optional[bool]:
    """
    Check if evidence speaker matches utterance speaker.
    Returns:
        True: if speakers match (accounting for NFC, case, honorifics, diacritics).
        False: if both speakers are known and definitely do not match.
        None: if either speaker is unknown / unprovided.
    """
    if not ev_speaker or not utt_speaker:
        return None

    s1 = unicodedata.normalize("NFC", ev_speaker.strip())
    s2 = unicodedata.normalize("NFC", utt_speaker.strip())

    unknown_tokens = {"unknown", "chưa rõ", "none", "không rõ"}
    if s1.lower() in unknown_tokens or s2.lower() in unknown_tokens:
        return None

    if s1.lower() == s2.lower():
        return True

    h1 = HONORIFIC_REGEX.sub("", s1).strip().lower()
    h2 = HONORIFIC_REGEX.sub("", s2).strip().lower()
    if h1 == h2 or (h1 and h2 and (h1 in h2 or h2 in h1)):
        return True

    if strip_accents(h1) == strip_accents(h2):
        return True

    return False


def is_short_quote(quote: str) -> bool:
    """Return True if quote is considered short (< 6 words or < 20 characters)."""
    words = quote.split()
    return len(words) < MIN_FUZZY_WORDS or len(quote) < MIN_FUZZY_CHARS


def match_quote_in_text(
    quote: str,
    target_text: str,
    threshold: int = 80,
    force_short: Optional[bool] = None,
) -> Tuple[bool, float]:
    """
    Match a quote against a target text.
    - If quote is short (< 6 words or < 20 chars):
      Requires exact/verbatim substring match (case-insensitive, whitespace-normalized).
      No loose partial_ratio allowed!
    - If quote is long:
      Checks exact match first (score=100.0), otherwise fuzzy partial_ratio.
    """
    q_norm = unicodedata.normalize("NFC", quote.strip())
    t_norm = unicodedata.normalize("NFC", target_text.strip())
    if not q_norm or not t_norm:
        return False, 0.0

    # Normalize whitespace
    q_clean = " ".join(q_norm.split())
    t_clean = " ".join(t_norm.split())

    # Check stripped exact substring match (stripping quotation marks/punctuation)
    q_sub = q_clean.strip("\"'“”….,;:!? ").lower()
    if q_sub and q_sub in t_clean.lower():
        return True, 100.0

    short = is_short_quote(q_clean) if force_short is None else force_short
    if short:
        # Short quotes MUST match verbatim/exact
        return False, 0.0

    # Long quotes: use RapidFuzz partial_ratio
    score_raw = fuzz.partial_ratio(q_clean, t_clean)
    score_lower = fuzz.partial_ratio(q_clean.lower(), t_clean.lower())
    best_score = float(max(score_raw, score_lower))

    return (best_score >= threshold), best_score


class Validator:
    """
    Step 3 Validator: Validates evidence quotes and schema integrity
    with utterance anchoring, NFC normalization, and speaker verification.
    """

    def __init__(self, threshold: Optional[int] = None) -> None:
        """
        Initialize the Validator.

        Args:
            threshold: Fuzzy matching similarity threshold (0-100).
                       Defaults to config.FUZZY_MATCH_THRESHOLD.
        """
        self.threshold: int = (
            threshold if threshold is not None else config.FUZZY_MATCH_THRESHOLD
        )
        logger.debug(f"Validator initialized with fuzzy match threshold={self.threshold}")

    def verify_quote(self, quote: str, original_transcript: str) -> bool:
        """
        Check if a quote exists in the original transcript using NFC normalization
        and length-aware matching (verbatim for short quotes, fuzzy for long quotes).
        """
        if not quote or not quote.strip() or not original_transcript:
            return False

        utterances = parse_transcript_utterances(original_transcript)
        if not utterances:
            # Fallback to single text match
            matched, _ = match_quote_in_text(quote, original_transcript, self.threshold)
            return matched

        for u in utterances:
            matched_txt, _ = match_quote_in_text(quote, u.text, self.threshold)
            if matched_txt:
                return True
            matched_raw, _ = match_quote_in_text(quote, u.raw_line, self.threshold)
            if matched_raw:
                return True

        # Check full concatenated text as last resort for long quotes
        if not is_short_quote(quote):
            matched_full, _ = match_quote_in_text(quote, original_transcript, self.threshold)
            return matched_full

        return False

    def verify_evidence(
        self,
        ev: Evidence,
        utterances: List[UtteranceEntry],
    ) -> None:
        """
        Verify a single Evidence object:
        1. NFC normalize quote.
        2. If cited utterance_id is provided:
           a. Check cited utterance.
           b. Check neighbor utterances (+/- 1-2 neighbors).
           c. If found in neighbor, set ev.corrected_utterance_id = neighbor.uid.
        3. If not found in cited/neighbor window (or utterance_id not provided):
           Fall back to global search across all transcript utterances.
           If found globally, set ev.corrected_utterance_id = global_match.uid.
        4. If matched, verify speaker against matched utterance:
           Set ev.speaker_matched = True/False/None.
        5. If not found anywhere:
           ev.verified = False, ev.speaker_matched = False.
        """
        if not ev.quote or not ev.quote.strip() or not utterances:
            ev.verified = False
            ev.speaker_matched = False
            return

        ev.quote = unicodedata.normalize("NFC", ev.quote.strip())
        if ev.speaker:
            ev.speaker = unicodedata.normalize("NFC", ev.speaker.strip())

        cited_uid = normalize_uid(ev.utterance_id)
        matched_entry: Optional[UtteranceEntry] = None
        match_score = 0.0
        corrected_id: Optional[str] = None

        uid_map = {u.uid: u for u in utterances}
        idx_map = {u.index: u for u in utterances}

        # ── 1. If utterance_id cited, check cited utterance and neighbor window (+/- 2) ──
        if cited_uid and cited_uid in uid_map:
            cited_entry = uid_map[cited_uid]
            # Check cited utterance directly
            ok, score = match_quote_in_text(ev.quote, cited_entry.text, self.threshold)
            if not ok:
                ok, score = match_quote_in_text(ev.quote, cited_entry.raw_line, self.threshold)

            if ok:
                matched_entry = cited_entry
                match_score = score
                logger.debug(
                    f"[Validator] Evidence quote matched at cited {cited_uid} "
                    f"(score={score:.1f}, speaker='{cited_entry.speaker}')"
                )
            else:
                # Check neighbors at distance 1, then distance 2
                neighbor_indices = [
                    cited_entry.index - 1,
                    cited_entry.index + 1,
                    cited_entry.index - 2,
                    cited_entry.index + 2,
                ]
                for n_idx in neighbor_indices:
                    if n_idx in idx_map:
                        n_entry = idx_map[n_idx]
                        ok_n, score_n = match_quote_in_text(ev.quote, n_entry.text, self.threshold)
                        if not ok_n:
                            ok_n, score_n = match_quote_in_text(ev.quote, n_entry.raw_line, self.threshold)
                        if ok_n:
                            matched_entry = n_entry
                            match_score = score_n
                            corrected_id = n_entry.uid
                            logger.info(
                                f"[Validator] Evidence quote relocated from cited {cited_uid} "
                                f"to neighbor {n_entry.uid} (score={score_n:.1f})"
                            )
                            break

        # ── 2. Fallback to global transcript search across all utterances ──
        if not matched_entry:
            best_entry: Optional[UtteranceEntry] = None
            best_score = 0.0

            for u in utterances:
                ok_u, score_u = match_quote_in_text(ev.quote, u.text, self.threshold)
                if not ok_u:
                    ok_u, score_u = match_quote_in_text(ev.quote, u.raw_line, self.threshold)
                if ok_u and score_u > best_score:
                    best_score = score_u
                    best_entry = u
                    # Exact matches can terminate immediately
                    if score_u >= 100.0:
                        break

            if best_entry:
                matched_entry = best_entry
                match_score = best_score
                if cited_uid and best_entry.uid != cited_uid:
                    corrected_id = best_entry.uid
                    logger.info(
                        f"[Validator] Evidence quote relocated via global search from "
                        f"cited {cited_uid} to {best_entry.uid} (score={best_score:.1f})"
                    )
                elif not cited_uid:
                    # Populate newly discovered utterance_id if none was originally cited
                    ev.utterance_id = best_entry.uid

        # ── 3. Check concatenated text for long quotes spanning utterances ──
        if not matched_entry and not is_short_quote(ev.quote):
            full_text = "\n".join(u.raw_line for u in utterances)
            ok_full, score_full = match_quote_in_text(ev.quote, full_text, self.threshold)
            if ok_full:
                ev.verified = True
                ev.corrected_utterance_id = corrected_id
                # Check if evidence speaker matches any speaker in transcript
                spk_match = any(
                    check_speaker_match(ev.speaker, u.speaker) is True
                    for u in utterances
                )
                ev.speaker_matched = spk_match if spk_match else None
                logger.debug(f"[Validator] Long quote matched across multi-line text (score={score_full:.1f})")
                return

        # ── 4. Finalize verification result ──
        if matched_entry:
            ev.verified = True
            ev.corrected_utterance_id = corrected_id
            spk_matched = check_speaker_match(ev.speaker, matched_entry.speaker)
            ev.speaker_matched = spk_matched

            if spk_matched is False:
                logger.warning(
                    f"[Validator] Speaker mismatch for quote '{ev.quote[:35]}...': "
                    f"cited speaker='{ev.speaker}', but utterance {matched_entry.uid} "
                    f"speaker is '{matched_entry.speaker}'"
                )
        else:
            ev.verified = False
            ev.speaker_matched = False
            logger.debug(
                f"[Validator] Evidence quote verification failed completely: '{ev.quote[:50]}...'"
            )

    def validate(
        self,
        output: ResolvedResult,
        original_transcript: str,
    ) -> ResolvedResult:
        """
        Validate all evidence in ResolvedResult against the original transcript.

        Performs:
        1. Parse transcript into structured utterances.
        2. Verify every Evidence quote with utterance anchoring & speaker verification.
        3. Flag parent items with needs_review = True if:
           - An item has 0 evidence quotes, OR
           - Any evidence quote failed verification (verified = False), OR
           - Any evidence quote has an explicit speaker mismatch (speaker_matched = False).
        4. Validates that item_ids are unique across all categories.
        5. Validates that required fields are non-empty.
        """
        seen_ids: Set[str] = set()
        total_evidence = 0
        verified_evidence = 0
        mismatched_speakers = 0

        utterances = parse_transcript_utterances(original_transcript)

        def validate_evidence_list(ev_list: List[Evidence]) -> Tuple[int, int, bool]:
            nonlocal total_evidence, verified_evidence, mismatched_speakers
            item_total = len(ev_list)
            item_verified = 0
            has_mismatch = False

            for ev in ev_list:
                total_evidence += 1
                self.verify_evidence(ev, utterances)
                if ev.verified:
                    verified_evidence += 1
                    item_verified += 1
                if ev.speaker_matched is False:
                    mismatched_speakers += 1
                    has_mismatch = True

            return item_total, item_verified, has_mismatch

        def check_id_uniqueness(item_id: str, item_type: str) -> bool:
            if not item_id or not item_id.strip():
                logger.warning(f"Empty item_id in {item_type}")
                return False
            if item_id in seen_ids:
                logger.warning(f"Duplicate item_id '{item_id}' detected in {item_type}")
                return False
            seen_ids.add(item_id)
            return True

        # 1. Validate Decisions
        for decision in output.decisions:
            id_ok = check_id_uniqueness(decision.item_id, "Decision")
            if not id_ok or not decision.topic.strip() or not decision.final_value.strip():
                decision.needs_review = True

            dec_total_ev = 0
            dec_verified_ev = 0
            dec_has_mismatch = False

            for entry in decision.history:
                tot, ver, mismatch = validate_evidence_list(entry.evidence)
                dec_total_ev += tot
                dec_verified_ev += ver
                if mismatch:
                    dec_has_mismatch = True

            # Mark needs_review if no evidence, any unverified, or speaker mismatch
            if dec_total_ev == 0 or dec_verified_ev < dec_total_ev or dec_has_mismatch:
                decision.needs_review = True

        # 2. Validate Action Items
        for ai in output.action_items:
            id_ok = check_id_uniqueness(ai.item_id, "ActionItem")
            if not id_ok or not ai.task.strip():
                ai.needs_review = True

            # If assignee is missing or generic, flag for human review
            if not ai.assignee or not ai.assignee.strip() or ai.assignee.strip().lower() in (
                "unknown", "chưa rõ", "chưa phân công", "chưa giao", "ai đó"
            ):
                ai.needs_review = True

            tot, ver, mismatch = validate_evidence_list(ai.evidence)
            if tot == 0 or ver < tot or mismatch:
                ai.needs_review = True

        # 3. Validate Blockers
        for blocker in output.blockers:
            id_ok = check_id_uniqueness(blocker.item_id, "Blocker")
            if not id_ok or not blocker.issue.strip():
                blocker.needs_review = True

            tot, ver, mismatch = validate_evidence_list(blocker.evidence)
            if tot == 0 or ver < tot or mismatch:
                blocker.needs_review = True

        # 4. Validate Requests
        for req in output.requests:
            id_ok = check_id_uniqueness(req.item_id, "Request")
            if not id_ok or not req.content.strip():
                req.needs_review = True

            tot, ver, mismatch = validate_evidence_list(req.evidence)
            if tot == 0 or ver < tot or mismatch:
                req.needs_review = True

        # 5. Validate Unresolved Items
        for ui in output.unresolved_items:
            id_ok = check_id_uniqueness(ui.item_id, "UnresolvedItem")
            if not id_ok or not ui.topic.strip() or not ui.reason_unresolved.strip():
                ui.needs_review = True

            tot, ver, mismatch = validate_evidence_list(ui.evidence)
            if tot == 0 or ver < tot or mismatch:
                ui.needs_review = True

        logger.info(
            f"[Step 3] Validation complete: {verified_evidence}/{total_evidence} "
            f"evidence quotes verified ({self.threshold}% fuzzy threshold). "
            f"Speaker mismatches: {mismatched_speakers}."
        )

        return output
