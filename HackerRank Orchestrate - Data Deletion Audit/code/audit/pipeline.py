"""End-to-end pipeline used by main.py and the evaluation harness."""
from __future__ import annotations

import csv
import json
import os

from . import llm
from .engine import Auditor, CaseResult, load_activity, load_rules
from .extract import load_evidence
from .identity import IdentityIndex
from .intent import classify_all
from .util import DATASET_DIR, parse_ts


def read_requests(path: str) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


def run_cases(cases: list[dict], dataset_dir: str = DATASET_DIR, use_llm: bool = True,
              context_cases: list[dict] | None = None, verbose: bool = False) -> list[CaseResult]:
    """Audit `cases`.  `context_cases` (default: cases) are used for activity attribution,
    because several requests can share the same deletion-workflow window."""
    use_llm = use_llm and llm.available() or (use_llm and _cache_has_entries())
    store = load_evidence(dataset_dir, use_llm=use_llm)
    idx = IdentityIndex(dataset_dir)
    acts = load_activity(dataset_dir)
    rules = load_rules(dataset_dir)
    auditor = Auditor(store, idx, acts, rules)

    ctx = context_cases or cases
    intents = classify_all([q["request_text"] for q in ctx], use_llm=use_llm)
    identities = {}
    for q in ctx:
        if intents.get(q["request_text"]) != "DELETE":
            continue
        idn = idx.resolve(q["email"])
        if idn:
            identities[q["case_id"]] = idn
    auditor.assign_windows([q for q in ctx if q["case_id"] in identities], identities)

    out = []
    for q in cases:
        if intents.get(q["request_text"]) != "DELETE":
            out.append(CaseResult(q["case_id"], "NOT_APPLICABLE", [], ["request does not authorise deletion"]))
            continue
        idn = identities.get(q["case_id"])
        if not idn:
            out.append(CaseResult(q["case_id"], "INCOMPLETE", [], ["identity not resolved"]))
            continue
        audit = parse_ts(q["audit_at"])
        res = auditor.discover(q, idn, audit)
        status, steps = auditor.plan(q, idn, res, audit)
        notes = [f"{rid}: {r.category} state={r.state} pii={r.pii} via={sorted(r.linked_by)}"
                 for rid, r in sorted(res.items())]
        out.append(CaseResult(q["case_id"], status, steps, notes, idn.user_id))
        if verbose:
            print(q["case_id"], status, notes)
    return out


def _cache_has_entries() -> bool:
    from .util import CACHE_DIR
    d = os.path.join(CACHE_DIR, "llm")
    return os.path.isdir(d) and bool(os.listdir(d))


def write_output(results: list[CaseResult], path: str):
    results = sorted(results, key=lambda r: _num(r.case_id))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for r in results:
            w.writerow([r.case_id, r.status, json.dumps(r.steps, separators=(",", ":"), ensure_ascii=False)])


def _num(cid):
    import re
    m = re.search(r"(\d+)$", cid)
    return int(m.group(1)) if m else 0
