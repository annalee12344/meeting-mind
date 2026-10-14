# Meeting Mind — Real Analysis Pipeline Smoke Test Report

**Execution Timestamp:** 2026-10-14  
**Pipeline Execution Mode:** Real Gemini LLM API (`gemini-flash-lite-latest`)  
**Fuzzy Match Validator Threshold:** 80  
**Overall Status:** PASSED (4/4 transcripts completed with 0 errors)

---

## 1. Summary Results Table

| Transcript Name | Language | Format Characteristics | Length (chars / lines) | Total Time | Decisions | Tasks | Unresolved | Issues | Needs Review Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `transcript_a_en_short.txt` | English | Sprint sync with timestamps | 1,636 chars / 19 lines | **11.23s** | 1 | 5 | 1 | 1 | 0/8 (0.0%) |
| `transcript_b_vi_notimestamp.txt` | Vietnamese | Conversational debate (`Speaker: text`) | 3,250 chars / 36 lines | **13.41s** | 1 | 4 | 1 | 1 | 0/7 (0.0%) |
| `transcript_c_mixed_deadlines.txt` | Mixed (Vi/En) | Relative deadlines (`trước 17h thứ Sáu`, `next Monday`) | 2,667 chars / 25 lines | **13.33s** | 1 | 5 | 1 | 1 | 0/8 (0.0%) |
| `transcript_d_long.txt` | Vietnamese | Comprehensive quarterly planning stress test | 10,672 chars / 81 lines | **28.46s** | 5 | 11 | 2 | 7 | 0/25 (0.0%) |

---

## 2. Per-Stage Latency Breakdown

```
transcript_a_en_short.txt (19 utterances):
  - Step 0 (Preprocessor):       0.00s
  - Step 1 (Extractor LLM):      6.46s  (17 raw items extracted)
  - Step 2 (Resolver LLM):       4.77s  (6 items resolved)
  - Step 3 (Validator RapidFuzz): 0.00s
  - Step 4 (Deterministic Map):  0.00s
  - Total: 11.23s

transcript_b_vi_notimestamp.txt (36 utterances):
  - Step 0 (Preprocessor):       0.00s
  - Step 1 (Extractor LLM):      8.26s  (28 raw items extracted)
  - Step 2 (Resolver LLM):       5.16s  (6 items resolved)
  - Step 3 (Validator RapidFuzz): 0.00s
  - Step 4 (Deterministic Map):  0.00s
  - Total: 13.41s

transcript_c_mixed_deadlines.txt (25 utterances):
  - Step 0 (Preprocessor):       0.00s
  - Step 1 (Extractor LLM):      6.55s  (21 raw items extracted)
  - Step 2 (Resolver LLM):       6.79s  (7 items resolved)
  - Step 3 (Validator RapidFuzz): 0.00s
  - Step 4 (Deterministic Map):  0.00s
  - Total: 13.33s

transcript_d_long.txt (81 utterances, 10,672 chars):
  - Step 0 (Preprocessor):       0.00s
  - Step 1 (Extractor LLM):     14.27s  (49 raw items extracted)
  - Step 2 (Resolver LLM):      14.19s  (24 items resolved)
  - Step 3 (Validator RapidFuzz): 0.00s
  - Step 4 (Deterministic Map):  0.00s
  - Total: 28.46s
```

---

## 3. Key Observations & Hardening Verification

1. **Pydantic v2 Protobuf Schema Issue Completely Solved:**
   - Both Step 1 (`ExtractionResult`) and Step 2 (`ResolvedResult`) executed without any `ValueError: Protocol message Schema has no 'default' field` exceptions.
   - Structured JSON mode (`response_mime_type="application/json"`) validated cleanly on every run.
2. **Preprocessor Robustness:**
   - Successfully parsed English timestamps, Vietnamese conversational lines without timestamps, mixed brackets, and relative deadlines without losing any utterances.
   - BOM, CRLF, and NFC normalization passed cleanly.
3. **No Unbounded Retries or Freezing:**
   - Longest run was 28.46s (stress test on 10.6KB transcript), well below the 120s timeout limit.
   - Zero transcript text leaked into console or log streams.
4. **Evidence Integrity:**
   - RapidFuzz validated all evidence quotes with 100% verification across all 4 sample transcripts (0 items required manual review fallback).
