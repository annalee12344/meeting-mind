import urllib.request
import json
import time
import datetime

def main():
    with open("temp_new_transcript.txt", "r", encoding="utf-8") as f:
        transcript = f.read()

    print(f"[API REPRO] Calling POST http://127.0.0.1:8000/api/v1/analyze with NEW transcript ({len(transcript)} chars)...")
    payload = json.dumps({
        "transcript": transcript,
        "meeting_title": "Test Real Analysis",
        "use_sample_cache": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/analyze",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"[API REPRO] POST response ({resp.status}):", data)
        job_id = data["job_id"]

    print(f"[API REPRO] Polling job {job_id} every 500ms:")
    last_status = None
    last_stage = None
    start_time = time.time()
    while time.time() - start_time < 30:
        now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        poll_url = f"http://127.0.0.1:8000/api/v1/jobs/{job_id}"
        with urllib.request.urlopen(poll_url) as poll_resp:
            job_data = json.loads(poll_resp.read().decode("utf-8"))
            status = job_data.get("status")
            stage = job_data.get("stage")
            progress = job_data.get("progress")
            
            # Print transition
            if status != last_status or stage != last_stage:
                print(f"[{now}] TRANSITION: status='{status}', stage='{stage}', progress={progress}")
                last_status = status
                last_stage = stage
            else:
                print(f"[{now}] status='{status}', stage='{stage}', progress={progress}")

            if status in ("done", "failed", "cancelled"):
                print(f"[{now}] Terminal state reached: status={status}, stage={stage}")
                print(f"[{now}] Error: {job_data.get('error')}")
                print(f"[{now}] Friendly error: {job_data.get('friendly_error')}")
                break
        time.sleep(0.5)

if __name__ == "__main__":
    main()
