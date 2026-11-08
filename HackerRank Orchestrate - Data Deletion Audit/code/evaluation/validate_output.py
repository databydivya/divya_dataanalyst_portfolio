"""Structural validation of output.csv against the submission contract."""
import csv, json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OPS = {"FINDING": {"REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
                   "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE"},
       "REMEDIATION": {"DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED", "DELETE_RECORD": "ABSENT",
                       "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED"},
       "VERIFICATION": {"VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT",
                        "VERIFY_RECORD_REDACTED": "REDACTED", "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
                        "VERIFY_DATA_FLOW_DISABLED": "DISABLED", "VERIFY_RESTORE_BLOCKED": "BLOCKED"}}
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "output.csv")
req = [r["case_id"] for r in csv.DictReader(open(os.path.join(ROOT, "dataset", "deletion_requests.csv")))]
rows = list(csv.DictReader(open(out)))
errs = []
assert list(rows[0].keys()) == ["case_id", "deletion_status", "steps_json"], "bad header"
if sorted(r["case_id"] for r in rows) != sorted(req): errs.append("case set mismatch")
nums = [int(re.sub(r"\D", "", r["case_id"])) for r in rows]
if nums != sorted(nums): errs.append("not sorted by case_id")
phase_rank = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
for r in rows:
    st, steps = r["deletion_status"], json.loads(r["steps_json"])
    if st == "NOT_APPLICABLE" and steps: errs.append(f"{r['case_id']} NA with steps")
    if st == "COMPLETE" and any(s["phase"] != "VERIFICATION" or not s["evidence_id"] for s in steps):
        errs.append(f"{r['case_id']} COMPLETE needs evidence-backed verification only")
    last = -1
    for i, s in enumerate(steps, 1):
        if s["step_no"] != i: errs.append(f"{r['case_id']} step_no")
        if OPS.get(s["phase"], {}).get(s["operation"]) != s["state"]: errs.append(f"{r['case_id']} bad op/state {s}")
        if phase_rank[s["phase"]] < last: errs.append(f"{r['case_id']} phase order")
        last = phase_rank[s["phase"]]
        if st == "INCOMPLETE" and s["phase"] != "FINDING" and s["evidence_id"]: errs.append(f"{r['case_id']} future step cites evidence")
print(f"{len(rows)} rows checked, {len(errs)} problems"); [print("  ", e) for e in errs[:20]]
sys.exit(1 if errs else 0)
