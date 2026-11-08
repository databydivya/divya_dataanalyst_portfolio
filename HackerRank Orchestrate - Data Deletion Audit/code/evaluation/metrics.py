"""Scoring functions shared by the evaluation harness and the custom cases."""
from __future__ import annotations

import csv
import json
from collections import Counter

FIELDS = ["phase", "system_id", "resource_id", "operation", "state", "evidence_id"]


def step_key(s, fields=FIELDS):
    return tuple(s.get(f, "") for f in fields)


def score(gold: dict, pred: dict, verbose=False) -> dict:
    n = len(gold)
    status_ok = 0
    tp = fp = fn = 0
    seq_ok = 0
    field_hits = Counter()
    field_total = 0
    confusion = Counter()
    failures = []
    for cid, (gs, gsteps) in gold.items():
        ps, psteps = pred.get(cid, ("MISSING", []))
        confusion[(gs, ps)] += 1
        status_ok += gs == ps
        G = Counter(step_key(s) for s in gsteps)
        P = Counter(step_key(s) for s in psteps)
        t = sum((G & P).values())
        tp += t
        fp += sum(P.values()) - t
        fn += sum(G.values()) - t
        exact = [step_key(s) for s in gsteps] == [step_key(s) for s in psteps]
        seq_ok += exact
        # field-level: align by (resource_id, operation-phase) else by position
        for i, g in enumerate(gsteps):
            match = next((p for p in psteps if p["resource_id"] == g["resource_id"] and p["phase"] == g["phase"]), None)
            if match is None and i < len(psteps):
                match = psteps[i]
            for f in FIELDS + ["step_no"]:
                field_total += 1 if f == "phase" else 0
                if match is not None and match.get(f) == g.get(f):
                    field_hits[f] += 1
        if not exact or gs != ps:
            failures.append(cid)
            if verbose:
                print(f"--- {cid}: gold={gs} pred={ps}")
                for s in sorted(set(G) - set(P)):
                    print("   missing ", s)
                for s in sorted(set(P) - set(G)):
                    print("   extra   ", s)
    gold_steps = sum(len(v[1]) for v in gold.values())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {
        "cases": n,
        "status_accuracy": status_ok / n if n else 0,
        "step_precision": prec,
        "step_recall": rec,
        "step_f1": 2 * prec * rec / (prec + rec) if prec + rec else 0,
        "field_accuracy": {f: field_hits[f] / gold_steps for f in FIELDS + ["step_no"]} if gold_steps else {},
        "sequence_accuracy": seq_ok / n if n else 0,
        "confusion": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items())},
        "failures": failures,
    }


def load_gold(path):
    return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"]))
            for r in csv.DictReader(open(path, encoding="utf-8"))}


