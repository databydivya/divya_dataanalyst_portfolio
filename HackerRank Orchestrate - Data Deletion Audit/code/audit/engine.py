"""Decision engine: reconstruct each subject's resources and their state at audit_at,
apply deletion_rules.csv, and emit ordered findings / remediation / verification steps.

Pipeline per case
  1. identity   - resolve request email -> user_id + all historical identifiers
  2. discovery  - resources linked to those identifiers in evidence, explicit
                  catalog links, data-flow / restore lineage, and deletion-worker
                  activity around the reported completion time
  3. state      - latest evidence observation at or before audit_at (activity
                  results are treated as claims, never as proof); full snapshots
                  prove absence
  4. policy     - deletion_rules.csv category -> required treatment
  5. plan       - findings, remediation and verification steps in contract order
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .extract import EvidenceStore, Obs
from .identity import Identity, IdentityIndex
from .util import (DATASET_DIR, EMAIL_RE, RESOURCE_RE, USER_RE, category_of, norm, parse_ts,
                   prefix_of, system_of)

FIND_ORDER = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"]
REM_ORDER = ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"]
VER_ORDER = ["VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED",
             "VERIFY_RECORD_ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"]
STATE_OF = {
    "REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED", "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED", "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED", "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}
# required action -> (finding op, remediation op, verification op)
ACTION_OPS = {
    "DELETE": ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    "REDACT": ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"),
    "ANONYMIZE": ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"),
    "RETAIN": (None, None, "VERIFY_RECORD_PRESENT"),
}
# The deletion workflow acts on a request's resources at characteristic offsets
# from the reported completion time (learned from the public samples):
#   "submitted primary profile"      ~ 40-80 min before the report
#   "Policy action completed"        ~ 3-35 min before the report
#   "received the final result" / status checks ~ 25-125 min after the report
#   legacy single-shot messages      ~ within 15 min of the report
OFFSET_WINDOWS = [
    (re.compile(r"submitted primary profile"), -85, -35),
    (re.compile(r"Policy action completed"), -38, -2),
    (re.compile(r"received the final result|status check confirmed|Restore-access check confirmed"), 20, 130),
    (re.compile(r"reported the requested operation|stopped after|completed some internal work"), -20, 20),
]


RETAINED_LOOKAHEAD = timedelta(days=3)
RETAINED_CATEGORIES = {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}
REPORTED_TO_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}


def offset_window(details: str):
    for rx, lo, hi in OFFSET_WINDOWS:
        if rx.search(details):
            return timedelta(minutes=lo), timedelta(minutes=hi)
    return timedelta(minutes=-90), timedelta(minutes=130)
WORKFLOW_EVENTS = {"DELETE_RECORD", "ANONYMIZE_RECORD", "REDACT_RECORD", "DISABLE_DATA_FLOW",
                   "BLOCK_RESTORE", "CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS", "RETAIN_RECORD"}


def load_rules(dataset_dir=DATASET_DIR) -> dict:
    rules = {}
    for r in csv.DictReader(open(os.path.join(dataset_dir, "deletion_rules.csv"), encoding="utf-8")):
        rules[r["data_category"]] = r
    return rules


def load_activity(dataset_dir=DATASET_DIR) -> list[dict]:
    acts = []
    for a in csv.DictReader(open(os.path.join(dataset_dir, "system_activity.csv"), encoding="utf-8")):
        a["t"] = parse_ts(a["event_time"])
        acts.append(a)
    acts.sort(key=lambda a: (a["t"], a["activity_id"]))
    return acts


@dataclass
class Resource:
    system: str
    resource_id: str
    category: str
    linked_by: set = field(default_factory=set)
    obs: list = field(default_factory=list)          # Obs at/before audit
    state: str = "UNKNOWN"
    pii: bool = False
    evidence_id: str = ""


@dataclass
class CaseResult:
    case_id: str
    status: str
    steps: list
    notes: list = field(default_factory=list)
    user_id: str = ""


class Auditor:
    def __init__(self, store: EvidenceStore, idx: IdentityIndex, activity: list[dict], rules: dict):
        self.store, self.idx, self.act, self.rules = store, idx, activity, rules
        self.obs_by_res: dict[str, list[Obs]] = {}
        for o in store.obs:
            self.obs_by_res.setdefault(o.resource_id, []).append(o)
        self.cov_by_sys: dict[str, list] = {}
        for c in store.coverage:
            self.cov_by_sys.setdefault(c.system, []).append(c)
        # explicit catalog links and lineage from activity
        self.catalog_links: list[tuple] = []     # (t, resource_id, ids, activity_id)
        self.lineage: list[tuple] = []           # (t, source_res, downstream_res, activity_id)
        for a in activity:
            det = a["details"]
            if a["event_type"] == "LINK_RESOURCE_IDENTITY":
                ids = {e.lower() for e in EMAIL_RE.findall(det)} | {u.lower() for u in USER_RE.findall(det)}
                self.catalog_links.append((a["t"], a["resource_id"], ids, a["activity_id"]))
            m = re.search(r"repopulated downstream resource (\S+?)\.?$", det)
            if m:
                self.lineage.append((a["t"], a["resource_id"], m.group(1), a["activity_id"]))
        # owner of each resource according to evidence identifiers (any user)
        self.res_owners: dict[str, set] = {}
        for o in store.obs:
            ow = idx.owners(o.ids)
            if ow:
                self.res_owners.setdefault(o.resource_id, set()).update(ow)
        for _, rid, ids, _ in self.catalog_links:
            ow = idx.owners(ids)
            if ow:
                self.res_owners.setdefault(rid, set()).update(ow)
        self.window_assign: dict[str, set] = {}   # case_id -> resource ids from activity windows

    def file_t(self, fid):
        return parse_ts(self.store.files[fid]["captured_at"])

    since: datetime | None = None   # requested_at of the case being audited

    def usable(self, o: Obs, audit) -> bool:
        """Evidence counts for a case only if it was captured after the request was
        made (older captures predate the deletion) and no later than audit_at."""
        ft = o.file_t or o.t
        if not o.t or o.t > audit or ft > audit:
            return False
        return self.since is None or ft >= self.since

    # ------------------------------------------------------------------
    # activity-window attribution (global, needs every case)
    # ------------------------------------------------------------------
    def assign_windows(self, cases: list[dict], identities: dict[str, Identity]):
        """Attribute deletion-workflow activity with no identifying evidence to a case.

        The workflow acts on a request's resources shortly before/after the
        reported completion time.  Resources whose evidence already names an
        owner go to that owner; unnamed ones (e.g. a 404 account or an already
        anonymised analytics row) are shared among the cases whose window covers
        them, by prefix, in chronological order.
        """
        windows = []
        for q in cases:
            idn = identities.get(q["case_id"])
            if not idn:
                continue
            rep = parse_ts(q["reported_at"])
            windows.append((q, idn, rep))
        by_res_candidates: dict[str, list] = {}
        acts = [a for a in self.act if a["event_type"] in WORKFLOW_EVENTS and a["source_system"] == "deletion_worker"]
        for a in acts:
            a["_win"] = offset_window(a["details"])
        for q, idn, rep in windows:
            for a in acts:
                lo, hi = a["_win"]
                if not (rep + lo <= a["t"] <= rep + hi):
                    continue
                by_res_candidates.setdefault(a["resource_id"], []).append((q, idn, a))
        ambiguous = []
        for rid, cands in by_res_candidates.items():
            owners = self.res_owners.get(rid, set())
            hit = [c for c in cands if c[1].user_id in owners]
            if hit:
                for q, idn, a in hit:
                    self.window_assign.setdefault(q["case_id"], set()).add(rid)
                continue
            if owners:          # evidence names somebody else
                continue
            if len(cands) == 1:
                self.window_assign.setdefault(cands[0][0]["case_id"], set()).add(rid)
            else:
                ambiguous.append((min(c[2]["t"] for c in cands), rid, cands))
        # a case whose own resources were reported back as failed is a "failing" case;
        # unnamed policy-action results belong to cases whose workflow ran cleanly
        failing = set()
        for cid, rids in self.window_assign.items():
            for rid in rids:
                for q, idn, a in by_res_candidates.get(rid, []):
                    if q["case_id"] == cid and re.search(r"received the final result|status check|Restore-access", a["details"]):
                        failing.add(cid)
        # ambiguous unnamed resources: greedy assignment with compatibility scoring
        for _, rid, cands in sorted(ambiguous):
            pfx = prefix_of(rid)

            def score(c):
                q, idn, a = c
                cid = q["case_id"]
                have = [r for r in self.window_assign.get(cid, set()) if prefix_of(r) == pfx]
                sc = 0
                # workflow outcome of the account job mirrors the request's reported status
                if pfx == "account":
                    want = REPORTED_TO_RESULT.get(q["reported_status"])
                    sc += 4 if a["reported_result"] == want else 0
                if not have:
                    sc += 2
                if "Policy action completed" in a["details"] and cid not in failing:
                    sc += 1
                return (-sc, _case_num(cid))
            best = sorted(cands, key=score)[0]
            cid = best[0]["case_id"]
            if any(prefix_of(r) == pfx for r in self.window_assign.get(cid, set())):
                continue      # every candidate already has one of these -> belongs elsewhere
            self.window_assign.setdefault(cid, set()).add(rid)
        # a request has exactly one primary account: prefer the one evidence names
        for cid, rids in self.window_assign.items():
            accts = [r for r in rids if prefix_of(r) == "account"]
            owned = [r for r in accts if self.res_owners.get(r)]
            if owned:
                for r in accts:
                    if r not in owned:
                        rids.discard(r)

    # ------------------------------------------------------------------
    def discover(self, q: dict, idn: Identity, audit: datetime) -> dict[str, Resource]:
        keys = idn.keys()
        self.since = parse_ts(q["requested_at"])
        res: dict[str, Resource] = {}

        def add(rid, why):
            if not RESOURCE_RE.fullmatch(rid or ""):
                return
            r = res.get(rid)
            if not r:
                r = res[rid] = Resource(system_of(rid), rid, category_of(rid))
            r.linked_by.add(why)

        catalog_rids = {rid for t, rid, ids, aid in self.catalog_links if t <= audit and keys & ids}
        for o in self.store.obs:
            if self.usable(o, audit) and keys & o.ids:
                # screenshots list neighbouring records as context; only the record the
                # data catalog ties to this person is taken from a multi-row screen
                if o.source.startswith(("png:", "jpg:")) and o.resource_id not in catalog_rids:
                    continue
                add(o.resource_id, f"evidence:{o.file_id}")
        # retained security records: the obligation to keep them is known even when the
        # only capture is newer than audit_at (used for post-remediation checks only)
        for o in self.store.obs:
            if (o.category in RETAINED_CATEGORIES and keys & o.ids and o.resource_id not in res
                    and self.since <= (o.file_t or o.t) <= audit + RETAINED_LOOKAHEAD
                    and not (o.source.startswith(("png:", "jpg:")) and o.resource_id not in catalog_rids)):
                add(o.resource_id, f"retained_ref:{o.file_id}")
        for t, rid, ids, aid in self.catalog_links:
            if t <= audit and keys & ids:
                add(rid, f"catalog:{aid}")
        for rid in self.window_assign.get(q["case_id"], set()):
            add(rid, "activity_window")
        # lineage: active flows / restores that repopulated a resource
        changed = True
        while changed:
            changed = False
            for t, src, dst, aid in self.lineage:
                if t > audit:
                    continue
                if src in res and dst not in res:
                    add(dst, f"lineage:{aid}"); changed = True
                if dst in res and src not in res:
                    add(src, f"lineage:{aid}"); changed = True
        # search documents that point at a linked source account
        for rid, obs_list in self.obs_by_res.items():
            if rid in res:
                continue
            for o in obs_list:
                if self.usable(o, audit) and any(x in res for x in o.ids if RESOURCE_RE.fullmatch(x)):
                    add(rid, f"source_ref:{o.file_id}")
        # drop resources that evidence attributes exclusively to another person
        for rid in list(res):
            owners = self.res_owners.get(rid, set())
            if owners and idn.user_id not in owners and not any(w.startswith("catalog") for w in res[rid].linked_by):
                del res[rid]
        return res

    # ------------------------------------------------------------------
    def resolve_state(self, r: Resource, audit: datetime):
        obs = [o for o in self.obs_by_res.get(r.resource_id, []) if self.usable(o, audit)]
        r.obs = obs
        latest_t = max((o.t for o in obs), default=None)
        # coverage newer than the latest positive observation proves absence
        covs = [c for c in self.cov_by_sys.get(r.system, []) if c.t <= audit and self.file_t(c.file_id) <= audit
                and (self.since is None or self.file_t(c.file_id) >= self.since)]
        if obs:
            # take the latest file; inside one file any replica that still holds it counts
            last_t = latest_t
            last = [o for o in obs if o.t == last_t]
            # group by file: use the most recent file's observations
            last_file = sorted(last, key=lambda o: o.file_id)[-1].file_id
            same_file = [o for o in obs if o.file_id == last_file]
            present = [o for o in same_file if o.status != "ABSENT"]
            chosen = present[0] if present else same_file[0]
            if present:
                # a replica still exposing PII wins over a clean one
                for o in present:
                    if o.pii:
                        chosen = o
                for o in present:
                    if o.status in ("ACTIVE",):
                        chosen = o
            later_cov = [c for c in covs if c.t > last_t and r.resource_id not in c.resources]
            later_pos = [c for c in covs if c.t > last_t and r.resource_id in c.resources]
            if False and chosen.status != "ABSENT" and later_cov and not later_pos:
                c = max(later_cov, key=lambda c: c.t)
                r.state, r.pii, r.evidence_id = "ABSENT", False, c.file_id
                return
            r.state, r.pii, r.evidence_id = chosen.status, chosen.pii, chosen.file_id
            if chosen.category and chosen.category not in ("UNKNOWN",):
                r.category = chosen.category
            return
        # a complete capture of the account store proves an account is gone; other
        # stores are captured selectively, so absence there proves nothing
        absent_cov = [c for c in covs if r.resource_id not in c.resources] if r.category == "USER_PROFILE" else []
        if absent_cov:
            c = max(absent_cov, key=lambda c: (c.t, c.file_id))
            r.state, r.evidence_id = "ABSENT", c.file_id
        else:
            r.state = "UNKNOWN"

    # ------------------------------------------------------------------
    def required_action(self, r: Resource) -> str:
        cat = r.category
        if cat == "DATA_FLOW":
            return "FLOW"
        rule = self.rules.get(cat)
        return rule["required_action"] if rule else "DELETE"

    def plan(self, q: dict, idn: Identity, res: dict[str, Resource], audit: datetime):
        findings, rem, ver = [], [], []
        for rid, r in res.items():
            self.resolve_state(r, audit)
            act = self.required_action(r)
            pfx = prefix_of(rid)
            ev = r.evidence_id
            if act == "FLOW" or pfx == "data_flow":
                if r.state == "ACTIVE":
                    findings.append((r, "REPORT_ACTIVE_DATA_FLOW", ev))
                    rem.append((r, "DISABLE_DATA_FLOW"))
                    ver.append((r, "VERIFY_DATA_FLOW_DISABLED", ""))
                elif r.state == "DISABLED":
                    ver.append((r, "VERIFY_DATA_FLOW_DISABLED", ev))
                continue
            if r.category == "BACKUP_ARCHIVE":
                if r.state == "ACTIVE":
                    findings.append((r, "REPORT_RESTORE_RISK", ev))
                    rem.append((r, "BLOCK_RESTORE"))
                    ver.append((r, "VERIFY_RESTORE_BLOCKED", ""))
                elif r.state == "BLOCKED":
                    ver.append((r, "VERIFY_RESTORE_BLOCKED", ev))
                continue
            if act == "RETAIN":
                if r.state not in ("ABSENT", "UNKNOWN"):
                    ver.append((r, "VERIFY_RECORD_PRESENT", ev))
                elif r.state == "UNKNOWN":
                    ver.append((r, "VERIFY_RECORD_PRESENT", None))   # only for future checks
                continue
            fop, rop, vop = ACTION_OPS.get(act, ACTION_OPS["DELETE"])
            if act == "DELETE":
                if r.state in ("PRESENT", "ACTIVE"):
                    findings.append((r, fop, ev)); rem.append((r, rop)); ver.append((r, vop, ""))
                elif r.category == "USER_PROFILE":
                    ver.append((r, vop, ev if r.state == "ABSENT" else ""))
                continue
            # REDACT / ANONYMIZE
            if r.state in ("PRESENT", "ACTIVE"):
                if r.pii:
                    findings.append((r, fop, ev)); rem.append((r, rop)); ver.append((r, vop, ""))
                else:
                    ver.append((r, vop, ev))
        status = "INCOMPLETE" if findings else "COMPLETE"
        steps = []

        def emit(phase, r, op, ev):
            steps.append({"step_no": len(steps) + 1, "phase": phase, "system_id": r.system,
                          "resource_id": r.resource_id, "operation": op, "state": STATE_OF[op],
                          "evidence_id": ev})

        if status == "INCOMPLETE":
            for r, op, ev in sorted(findings, key=lambda x: (FIND_ORDER.index(x[1]), x[0].system, x[0].resource_id)):
                emit("FINDING", r, op, ev)
            for r, op in sorted(rem, key=lambda x: (REM_ORDER.index(x[1]), x[0].system, x[0].resource_id)):
                emit("REMEDIATION", r, op, "")
            for r, op, _ in sorted(ver, key=lambda x: (VER_ORDER.index(x[1]), x[0].system, x[0].resource_id)):
                emit("VERIFICATION", r, op, "")
        else:
            for r, op, ev in sorted(ver, key=lambda x: (VER_ORDER.index(x[1]), x[0].system, x[0].resource_id)):
                if ev is None:      # no evidence at audit time -> cannot be claimed as proof
                    continue
                emit("VERIFICATION", r, op, ev)
        return status, steps


def _case_num(cid: str) -> int:
    m = re.search(r"(\d+)$", cid)
    return int(m.group(1)) if m else 0
