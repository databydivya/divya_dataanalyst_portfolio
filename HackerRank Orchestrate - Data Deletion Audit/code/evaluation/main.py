"""Evaluation harness: score predictions against sample_output.csv (and custom cases).

Metrics
  * case-level status accuracy
  * step-level precision / recall / F1 (a step = phase, system, resource, operation, state, evidence)
  * field-level accuracy over aligned steps (per field)
  * sequence accuracy (exact ordered match of the whole steps array)
Usage:  python3 code/evaluation/main.py [--custom] [--verbose]
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit.pipeline import read_requests, run_cases  # noqa: E402
from audit.util import DATASET_DIR  # noqa: E402

from metrics import FIELDS, load_gold, score  # noqa: E402


def main():
    verbose = "--verbose" in sys.argv
    use_llm = "--no-llm" not in sys.argv
    sample_req = read_requests(os.path.join(DATASET_DIR, "sample_deletion_requests.csv"))
    all_req = sample_req + read_requests(os.path.join(DATASET_DIR, "deletion_requests.csv"))
    results = run_cases(sample_req, use_llm=use_llm, context_cases=all_req)
    pred = {r.case_id: (r.status, r.steps) for r in results}
    gold = load_gold(os.path.join(DATASET_DIR, "sample_output.csv"))
    m = score(gold, pred, verbose=verbose)
    print(json.dumps({k: v for k, v in m.items()}, indent=2))
    if "--custom" in sys.argv:
        from custom_cases import run_custom  # noqa
        run_custom(verbose=verbose)


if __name__ == "__main__":
    main()
