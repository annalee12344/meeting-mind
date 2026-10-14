# Meeting Mind — Real Pipeline Audit & Root Cause Analysis

**Audit Date:** 2026-10-14  
**Author:** Senior Full-Stack Engineer  
**Scope:** Real execution path of Meeting Mind (`main.py`, `server.py`, `pipeline/`, and frontend polling) on new, un-cached transcripts.

---

## 1. Reproduction & Isolation (Section 1)

### a) Direct Pipeline Execution via CLI (`main.py`)
- **Input:** `temp_new_transcript.txt` (8 utterances, realistic Vietnamese meeting on FCM notification system, not in `tests/`).
- **Command:** `python main.py temp_new_transcript.txt`
- **Result:** **FAILS AT STEP 1 (Extractor)**.
- **Traceback:**
  ```text
  ERROR: [Step 1] Extraction failed: Unknown field for Schema: default
  RuntimeError: Step 1 Extraction failed after 3 attempts: Unknown field for Schema: default
  File ".../pipeline/extractor.py", line 97, in extract
      result = self.llm_client.generate_structured(...)
  File ".../pipeline/llm_client.py", line 277, in generate_structured
      model = self.genai.GenerativeModel(...)
  File ".../google/generativeai/types/generation_types.py", line 202, in _normalize_schema
      generation_config["response_schema"] = protos.Schema(response_schema)
  ValueError: Unknown field for Schema: default
  ```
- **Failing Layer:** Step 1 LLM Structured Output (`pipeline/llm_client.py`).

### b) API Execution via `POST /api/v1/analyze` and Job Poller (`scripts/reproduce_api.py`)
- **Command:** `python scripts/reproduce_api.py`
- **Status Transitions with Timestamps:**
  ```text
  [21:35:15.500] POST /api/v1/analyze -> HTTP 200: {'job_id': 'job_b4669ef7476b', 'status': 'pending'}
  [21:35:16.147] TRANSITION: status='processing', stage='extracting', progress=0.45
  [21:35:16.652] status='processing', stage='extracting', progress=0.45
  [21:35:17.158] status='processing', stage='extracting', progress=0.45
  [21:35:17.662] TRANSITION: status='failed', stage='failed', progress=1.0
  [21:35:17.662] Error: Step 1 Extraction failed after 3 attempts: Unknown field for Schema: default
  [21:35:17.662] Friendly error: Quá trình phân tích gặp sự cố: RuntimeError (Step 1 Extraction failed after 3 attempts: Unknown field for Schema: default)
  ```
- **Backend Job Lifecycle:** The backend background thread successfully transitions: `queued` -> `preprocessing` -> `extracting` -> `failed`. The failure is recorded in `JobStore`.

### c) Frontend Inspection & Failure to Terminate
- **Payload Sent by Frontend:**
  ```json
  {
    "transcript": "...",
    "meeting_name": "Sprint 24 · Planning",
    "meeting_date": "2026-10-14",
    "use_sample_cache": true
  }
  ```
- **Status Contract Mismatch:**
  - Backend emits: `status = "done"`, `progress = 1.0` (float), `stage_message = "..."`.
  - Frontend (`src/routes/index.tsx`) checks: `if (status.status === 'completed')`.
  - **Result:** `"done" !== "completed"`. Even if the analysis succeeds, the frontend polling loop never terminates.
- **Error Suppression in Frontend Poller:**
  - In `index.tsx`:
    ```typescript
    } catch (pollErr) {
      if (cancelledRef.current) break;
      if (pollErr instanceof Error && pollErr.message.includes('thất bại')) {
        throw pollErr;
      }
      console.warn('[Job Poller] Poll attempt failed, will retry:', pollErr);
    }
    ```
  - When backend fails with `status = "failed"`, `status.error` is `"Step 1 Extraction failed after 3 attempts: Unknown field for Schema: default"`.
  - Because the error string is in English and does not contain `"thất bại"`, the catch block treats it as a transient network error, suppresses it, and **polls indefinitely**.
  - The UI remains stuck in the scanning mascot modal forever.
- **Server Restart / Missing Job Handling (HTTP 404):**
  - If uvicorn reloads or the server restarts, `JobStore` in-memory state is wiped.
  - Poller receives HTTP 404: `Tác vụ phân tích 'job_...' không tồn tại hoặc đã hết hạn.`
  - This message also does not contain `"thất bại"`, so the frontend continues polling the non-existent job indefinitely without displaying a clear error or a Retry button.

### d) Startup Verification
- `GEMINI_API_KEY`: Present in `.env` (valid 53-character key).
- `STEP1_MODEL` (`gemini-flash-lite-latest`): Valid model name. Verified with probe call (`Response: OK`).
- `STEP2_MODEL` (`gemini-flash-lite-latest`): Valid model name. Verified with probe call.

---

## 2. Examination of Potential Root Causes (Section 2)

| Potential Cause | Status | Evidence & Findings |
| :--- | :---: | :--- |
| **1. Job stays `pending` / never reaches terminal state** | **CONFIRMED (Partially)** | The background thread *does* start and reaches `status="failed"`. However, there was no overall pipeline job timeout (if an external API or validator stalled, the job stayed `processing` forever). |
| **2. In-memory JobStore lost on server restart / uvicorn reload** | **CONFIRMED** | `InMemoryJobStore` loses jobs on reload. When frontend polls a missing job, the 404 error was swallowed as transient and polled forever without informing the user. |
| **3. Frontend polling bugs (status names, 404/500, no overall timeout)** | **CONFIRMED** | (a) Frontend checked `status === 'completed'` instead of `'done'`.<br>(b) Frontend expected `status.progress_percent` and `status.stage_label` while backend sent `progress` (0.0-1.0) and `stage_message`.<br>(c) Catch block required substring `'thất bại'` to stop polling, swallowing all English errors and HTTP 404/500s.<br>(d) No frontend polling timeout. |
| **4. Gemini failures: `response_schema` rejected by SDK** | **CONFIRMED (PRIMARY)** | `protos.Schema(schema_cls)` inside `google.generativeai.GenerativeModel` throws `ValueError: Unknown field for Schema: default` because Pydantic v2 includes `default` attributes that protobuf rejects.<br>Because `GenerativeModel` was instantiated outside the `try/except` fallback in `llm_client.py`, the fallback to `application/json` was bypassed. |
| **5. Preprocessor fails on non-standard transcript formats** | **CONFIRMED** | `preprocessor.py` lacked support for `Name - text`, `Name (09:00): text`, UTF-8 BOM (`\ufeff`), and Unicode decomposed characters (NFD). Empty or unparseable input returned 0 utterances without raising an HTTP 400 error. |
| **6. Mapper / Validator / Deadline parser crashing on real data** | **RULED OUT** | Tested independently with real LLM output. RapidFuzz, mapper, and date math handled Vietnamese names, missing deadlines, and None fields cleanly. |
| **7. Cache key bug returning failed/pending state** | **RULED OUT** | `pipeline/cache.py` only caches completed `MeetingOutput` objects. Failed or pending jobs are never written to analysis cache. |
| **8. Request body shape mismatch / CORS / Encoding** | **RULED OUT** | Backend `AnalyzeRequest` correctly accepts `transcript`, `meeting_name`, `meeting_date`, `use_sample_cache`. CORS headers allow all local origins. |

---

## 3. Planned Fixes & Hardening Strategy (Section 3)

1. **`pipeline/llm_client.py`:**
   - Enforce robust `response_mime_type="application/json"` with schema instruction in prompt.
   - Wrap `GenerativeModel` instantiation and generation in schema fallback.
   - Fail fast on non-retryable errors (auth, invalid model, safety blocks) without wasted retry delays.
2. **`pipeline/preprocessor.py`:**
   - Strip UTF-8 BOM (`\ufeff`), normalize CRLF, normalize Unicode to NFC.
   - Add regex patterns for `Speaker - text`, `Speaker (HH:MM): text`, `Speaker [HH:MM] - text`.
   - Fallback to clean line utterances if no speaker pattern is matched.
   - If 0 utterances are produced, raise `PreprocessError` to return HTTP 400.
3. **`pipeline/job_store.py` & `server.py`:**
   - Add overall job timeout (default: 120s, configurable via `PIPELINE_TIMEOUT_SECONDS`).
   - Categorize errors into typed error codes: `llm_auth`, `llm_rate_limit`, `llm_timeout`, `llm_safety`, `llm_invalid_output`, `preprocess_failed`, `internal_error`.
   - Log per-stage timings and item counts for every run (support `DEBUG_PIPELINE=true`).
   - Standardize `JobStatusResponse` fields: provide both `status: "done" | "completed"`, `progress` (float), `progress_percent` (int), `stage_message`, and `stage_label`.
4. **`meeting-muse-56/src/routes/index.tsx`:**
   - Accept either `'done'` or `'completed'` as terminal success state.
   - Terminate polling immediately on `'failed'` or `'cancelled'`.
   - Handle 404 / server restart with explicit error message and **"Thử lại" (Retry)** button.
   - Enforce maximum polling timeout (150s).
