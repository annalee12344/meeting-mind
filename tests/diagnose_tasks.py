"""
Diagnosis script for Meeting Mind - Task Assignee & Unassigned Classification.
Traces the prompt's diagnosis transcript through every pipeline stage.
DOES NOT log sensitive transcript content.
"""
import sys
from pathlib import Path
from pprint import pprint

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.preprocessor import preprocess
from pipeline.extractor import Extractor
from pipeline.resolver import Resolver
from pipeline.validator import Validator
from pipeline.mapper import map_to_public
import config

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DIAGNOSIS_TRANSCRIPT = """10:21 — Lan: Em cần tài khoản sandbox và API secret key mới nhất của VNPay. Tài khoản hiện tại của em đăng nhập được nhưng không tạo được giao dịch thử.

10:22 — Bình: Em đã gửi yêu cầu cho đối tác từ hôm qua nhưng chưa nhận được phản hồi. Nếu đến thứ Tư vẫn chưa có tài khoản thì tiến độ tích hợp có thể bị chậm.

10:23 — Minh: Đây là blocker của sprint. Bình tiếp tục liên hệ đối tác và cập nhật tình hình trong nhóm trước 15:00 ngày mai. Nếu chưa có phản hồi, báo lại anh để escalte với bên phụ trách hợp đồng.
"""

def main():
    print("=" * 60)
    print("MEETING MIND - TASK ASSIGNEE & CLASSIFICATION DIAGNOSIS")
    print("=" * 60)
    
    # 0. Preprocessing
    preprocessed = preprocess(DIAGNOSIS_TRANSCRIPT)
    print("\n[Step 0] Preprocessed Utterance Count:", len(preprocessed.splitlines()))
    
    # 1. Extraction (Step 1)
    extractor = Extractor()
    try:
        step1_res = extractor.extract(preprocessed)
        print(f"\n[Step 1] Extraction Result: {len(step1_res.utterances)} utterances")
        for u in step1_res.utterances:
            print(f"  - {u.id} | speaker: {u.speaker} | type: {u.type} | role: {u.role}")
    except Exception as e:
        print(f"\n[Step 1] Extraction Error: {type(e).__name__}: {e}")
        return

    # 2. Resolution (Step 2)
    resolver = Resolver()
    try:
        step2_res = resolver.resolve(step1_res)
        print(f"\n[Step 2] Resolution Result:")
        print(f"  - Participants: {step2_res.participants}")
        print(f"  - Action Items: {len(step2_res.action_items)}")
        for a in step2_res.action_items:
            print(f"    * ID: {a.item_id}")
            print(f"      Task: {a.task}")
            print(f"      Assignee: {a.assignee!r}")
            print(f"      Assigned By: {a.assigned_by!r}")
            print(f"      Assignee Confirmed: {a.assignee_confirmed}")
            print(f"      Conf Utterance ID: {a.confirmation_utterance_id!r}")
            print(f"      Deadline: {a.deadline!r}")
        print(f"  - Blockers: {len(step2_res.blockers)}")
        for b in step2_res.blockers:
            print(f"    * ID: {b.item_id} | Issue: {b.issue} | Owner: {b.owner!r} | Status: {b.status}")
        print(f"  - Unresolved: {len(step2_res.unresolved_items)}")
    except Exception as e:
        print(f"\n[Step 2] Resolution Error: {type(e).__name__}: {e}")
        return

    # 3. Validation (Step 3)
    validator = Validator()
    validated_res = validator.validate(step2_res, DIAGNOSIS_TRANSCRIPT)
    print(f"\n[Step 3] Validation complete.")

    # 4. Mapper (Step 4)
    public_out = map_to_public(validated_res, transcript=DIAGNOSIS_TRANSCRIPT)
    print(f"\n[Step 4] Mapped Public Output:")
    print(f"  - Tasks Count: {len(public_out.tasks)}")
    for t in public_out.tasks:
        print(f"    * Title: {t.title}")
        print(f"      Assignee: {t.assignee!r}")
        print(f"      Assigned By: {t.assigned_by!r}")
        print(f"      Deadline Raw: {t.deadline_raw!r}")
        print(f"      Deadline ISO: {t.deadline_iso!r}")
    print(f"  - Unresolved Count: {len(public_out.unresolved)}")
    for u in public_out.unresolved:
        print(f"    * Kind: {u.kind}")
        print(f"      Content: {u.content}")
        print(f"      Suggested Assignee: {u.suggested_assignee!r}")
        print(f"      Reason: {u.reason_unresolved}")
    print(f"  - Issues Count: {len(public_out.issues)}")
    for i in public_out.issues:
        print(f"    * Content: {i.content} | Owner: {i.owner!r}")

if __name__ == "__main__":
    main()
