# Section 1: Homepage Samples Inspection & Deduplication Trace

## 1. Inspection of the 5 Homepage Samples

### Sample 1: Standard Sprint Planning (`test_01_happy_path`)
- **Transcript File**: `tests/transcripts/test_01_happy_path.txt`
- **Expected JSON**: `tests/expected/test_01_expected.json`
- **Ground Truth Counts**: 3 action items (`A001` Tuấn, `A002` Lan, `A003` Hương), 1 request (`R001` to Team DevOps).
- **API `/api/v1/samples/test_01_happy_path/result`**: Returns 4 public tasks (3 action items + 1 from request R001).
- **Duplication Status**: No duplicates present in expected JSON, sample cache, or public mapping.

### Sample 2: Product Launch Timing (`test_02_decision_change`)
- **Transcript File**: `tests/transcripts/test_02_decision_change.txt`
  - Utterance [14:33] Quân assigns task: *"Đạt chuẩn bị tài liệu kiến trúc kỹ thuật và lập bảng so sánh chi phí các đối tác cổng thanh toán, hoàn thành trước ngày 10 tháng 5 nhé."*
  - Utterance [14:34] Đạt accepts task: *"Vâng, em nhận task làm spec kiến trúc và so sánh đối tác thanh toán, deadline 10/5."*
- **Expected JSON**: `tests/expected/test_02_expected.json`
- **Ground Truth Counts**: Exactly 2 action items (`A001` Đạt, deadline `"10/05"`; `A002` Mai, deadline `"12/05"`).
- **API `/api/v1/samples/test_02_decision_change/result`**: Returns 2 public tasks:
  1. `A001`: Lập tài liệu kiến trúc kỹ thuật... — Đạt — raw: `10/05`, iso: `2027-05-10`
  2. `A002`: Cập nhật lại timeline... — Mai — raw: `12/05`, iso: `2027-05-12`
- **Frontend / Overlay Behavior**:
  - In `Workspace`, `cleanTaskFields` reformats ISO `2027-05-10` into `ngày 10/05/2027` for display.
  - If a user previously converted unresolved items, added manual tasks, or re-merged tasks, `mergeMeetingView` in `overlay.ts` appends `overlay.manual_tasks` without deduplicating against `aiOutput.tasks`.
  - When `overlay.manual_tasks` contains tasks loaded from `localStorage` under `meetingId`, the view model displays both the canonical AI tasks (`ngày 10/05/2027`) and duplicate manual tasks (`10/05`).
  - Furthermore, in the live Gemini pipeline, if Step 1 extracts both [14:33] and [14:34] as separate items and Step 2 doesn't merge them, multiple tasks for the same deliverable by Đạt are emitted.

### Sample 3: Chaotic Team Sync (`test_03_chaotic`)
- **Transcript File**: `tests/transcripts/test_03_chaotic.txt`
- **Expected JSON**: `tests/expected/test_03_expected.json`
- **Ground Truth Counts**: 1 action item (`A001` Khoa).
- **API `/api/v1/samples/test_03_chaotic/result`**: Returns 1 public task.
- **Duplication Status**: No duplicates present.

### Sample 4: Implicit Consensus Discussion (`test_04_implicit`)
- **Transcript File**: `tests/transcripts/test_04_implicit.txt`
- **Expected JSON**: `tests/expected/test_04_expected.json`
- **Ground Truth Counts**: 2 action items (`A001` Bình, `A002` Nga).
- **API `/api/v1/samples/test_04_implicit/result`**: Returns 2 public tasks.
- **Duplication Status**: No duplicates present.

### Sample 5: Adversarial Discussion (`test_05_sarcasm_fail`)
- **Transcript File**: `tests/transcripts/test_05_sarcasm_fail.txt`
- **Expected JSON**: `tests/expected/test_05_expected.json`
- **Ground Truth Counts**: 1 action item (`A001` Phúc).
- **API `/api/v1/samples/test_05_sarcasm_fail/result`**: Returns 1 public task.
- **Duplication Status**: No duplicates present.

---

## 2. Layer-by-Layer Root Cause Analysis

| Layer | Duplication Present? | Analysis / Mechanism |
| :--- | :---: | :--- |
| **a) Expected JSON** | **NO** | All 5 benchmark expected JSON files contain canonical, non-duplicated action items (Sample 1: 3, Sample 2: 2, Sample 3: 1, Sample 4: 2, Sample 5: 1). |
| **b) Sample Output Fixture / Cache** | **NO** | `get_sample_result` loads expected JSON directly and returns canonical tasks. |
| **c) Live Pipeline (Step 1 & Step 2)** | **YES** | Multi-turn task conversations (e.g. Quân assigns at [14:33], Đạt accepts at [14:34]) can be extracted as separate items in Step 1. If Step 2 Resolver does not enforce single-task consolidation across turns, duplicate action items with varying phrasing are emitted. |
| **d) Mapping Layer (`pipeline/mapper.py`)** | **YES** | `map_to_public` lacked a deterministic deduplication pass before returning `public_tasks`. If both an action item and a request represent the same deliverable, or if resolver produced duplicates, they both passed into `public_tasks`. |
| **e) Frontend Store / Merge Function (`overlay.ts`)** | **YES** | `mergeMeetingView` previously concatenated `aiOutput.tasks` and `overlay.manual_tasks` without checking for duplicates. Re-converting unresolved items or loading accumulated manual tasks from localStorage caused duplicate tasks to render with raw deadlines (`10/05`) alongside ISO-formatted AI tasks (`ngày 10/05/2027`). |
