"""Ghost Data Still Exists - deletion audit agent.

Usage (from the repository root):
    python3 code/main.py                       # audit dataset/deletion_requests.csv -> ./output.csv
    python3 code/main.py --input dataset/sample_deletion_requests.csv --output /tmp/sample_out.csv
    python3 code/main.py --no-llm              # deterministic fallback (rules + local OCR only)
    python3 code/main.py --explain case_36     # print the reasoning trace for one case

Environment:
    ANTHROPIC_API_KEY   enables Claude for request-intent classification and screenshot reading
    AUDIT_TEXT_MODEL / AUDIT_VISION_MODEL override the default models
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit import llm  # noqa: E402
from audit.pipeline import read_requests, run_cases, write_output  # noqa: E402
from audit.util import DATASET_DIR, REPO_ROOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=os.path.join(DATASET_DIR, "deletion_requests.csv"))
    ap.add_argument("--output", default=os.path.join(REPO_ROOT, "output.csv"))
    ap.add_argument("--no-llm", action="store_true", help="disable model calls (rules + OCR only)")
    ap.add_argument("--explain", default="", help="comma-separated case ids to explain")
    ap.add_argument("--usage-json", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "evaluation", "last_run_usage.json"))
    args = ap.parse_args()

    t0 = time.time()
    cases = read_requests(args.input)
    # all known requests give context for attributing shared deletion-workflow activity
    context = list(cases)
    for extra in ("sample_deletion_requests.csv", "deletion_requests.csv"):
        p = os.path.join(DATASET_DIR, extra)
        if os.path.abspath(p) != os.path.abspath(args.input) and os.path.exists(p):
            context += read_requests(p)
    results = run_cases(cases, use_llm=not args.no_llm, context_cases=context)
    write_output(results, args.output)

    explain = {c.strip() for c in args.explain.split(",") if c.strip()}
    for r in results:
        if r.case_id in explain:
            print(f"== {r.case_id} user={r.user_id} status={r.status}")
            for n in r.notes:
                print("   ", n)
            for s in r.steps:
                print("   ", json.dumps(s))

    usage = llm.usage_summary()
    usage.update(requests=len(cases), seconds=round(time.time() - t0, 1),
                 llm_enabled=(not args.no_llm) and llm.available(),
                 models={"text": llm.MODEL_TEXT, "vision": llm.MODEL_VISION})
    os.makedirs(os.path.dirname(args.usage_json), exist_ok=True)
    json.dump(usage, open(args.usage_json, "w"), indent=2)
    if os.path.abspath(args.input) == os.path.abspath(os.path.join(DATASET_DIR, "deletion_requests.csv")):
        from audit.report import write_usage_report
        write_usage_report(os.path.join(os.path.dirname(args.usage_json), "usage_report.md"), usage,
                           len(cases), usage["seconds"], usage["llm_enabled"])
    from collections import Counter
    print(f"wrote {len(results)} rows to {args.output}  "
          f"{dict(Counter(r.status for r in results))}  in {usage['seconds']}s")
    print("model usage:", json.dumps(usage["total"]))


if __name__ == "__main__":
    main()
