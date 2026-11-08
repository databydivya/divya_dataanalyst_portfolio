"""Evidence extraction: turn every supplied evidence file into normalised observations.

Each evidence family (SQL snapshots, JSON exports, structured logs, text handovers,
PDF documents and screenshots) has its own parser, but they all emit the same
`Obs` record so the decision engine never needs to know the source format.

An observation says: "file F, at time T, saw resource R in system S in state X,
and the record carried these identifiers".  Separately each file can declare
`coverage`: the systems it captured completely at a point in time, which lets
the engine prove absence ("account_service snapshot has no row for account_7").
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from . import media
from .util import (DATASET_DIR, EMAIL_RE, RESOURCE_RE, USER_RE, category_of, is_null,
                   norm, norm_phone, parse_ts, prefix_of, system_of)

# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------

PII_KEYS = {"email", "phone", "email_hash", "full_name", "name", "display_name",
            "requester_name", "requester_email", "requester_phone", "owner_email",
            "owner_phone", "customer_email", "matched_value", "recipient_email", "recipient"}
REF_KEYS = {"customer_reference", "user_id", "subject_reference", "subject_ref",
            "subject_selector"}
LOOKUP_KEYS = {"lookup_key", "match_key", "subject_key", "scan_key", "owner_key",
               "correlation_key"}


@dataclass
class Obs:
    file_id: str
    t: datetime
    system: str
    resource_id: str
    status: str               # PRESENT | ABSENT | ACTIVE | DISABLED | BLOCKED
    pii: bool = False         # record still carries direct identifiers
    category: str = ""        # refined data category (rules file vocabulary)
    ids: set = field(default_factory=set)   # all identifier values (normalised)
    source: str = ""          # short description for debugging / explanations
    file_t: datetime | None = None   # manifest capture time of the evidence file

    def key(self):
        return (self.system, self.resource_id)


@dataclass
class Coverage:
    file_id: str
    t: datetime
    system: str
    resources: set            # resource ids present in that full capture


class EvidenceStore:
    def __init__(self):
        self.obs: list[Obs] = []
        self.coverage: list[Coverage] = []
        self.files: dict[str, dict] = {}
        self.file_ids_by_path: dict[str, str] = {}
        self.media_text: dict[str, str] = {}

    def add(self, o: Obs):
        if o.file_t is None and o.file_id in self.files:
            o.file_t = parse_ts(self.files[o.file_id]["captured_at"])
        if o.resource_id:
            if not o.system or o.system == "unknown":
                o.system = system_of(o.resource_id)
            if not o.category:
                o.category = category_of(o.resource_id)
            self.obs.append(o)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _ids_from(rec: dict) -> tuple[set, bool]:
    """Collect identifier values and whether any direct identifier is populated."""
    ids, pii = set(), False
    for k, v in rec.items():
        if isinstance(v, (dict, list)):
            continue
        kl = k.lower()
        if kl in PII_KEYS or kl in REF_KEYS or kl in LOOKUP_KEYS:
            n = norm(v)
            if not n:
                continue
            ids.add(n)
            if "phone" in kl or re.fullmatch(r"\+?[\d\s()\-]{7,}", str(v)):
                ids.add(norm_phone(v))
            if kl in PII_KEYS:
                pii = True
    return ids, pii


def _text_ids(text: str) -> tuple[set, bool]:
    ids = set()
    for m in EMAIL_RE.findall(text or ""):
        ids.add(m.lower())
    for m in USER_RE.findall(text or ""):
        ids.add(m.lower())
    for m in re.findall(r"\+\d[\d\s()\-]{7,}\d", text or ""):
        ids.add(norm_phone(m))
    pii = bool(EMAIL_RE.search(text or "")) or bool(re.search(r"\+\d[\d\s()\-]{7,}\d", text or ""))
    return ids, pii


def _truthy(v) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "allowed", "allow", "enabled", "active", "delivered"):
        return True
    if s in ("0", "false", "no", "deny", "denied", "disabled", "blocked", "stopped"):
        return False
    return None


def classify_record(system: str, rid: str, rec: dict, present: bool = True,
                    record_type: str = "", result: str = "") -> tuple[str, bool, str]:
    """Return (status, pii, category) for a record dict from any source."""
    pfx = prefix_of(rid)
    cat = record_type or category_of(rid)
    ids, pii = _ids_from(rec)
    # free-text message bodies may carry identifiers too
    for k in ("message_text", "message_excerpt", "body"):
        if k in rec and rec[k] and "[redacted]" not in str(rec[k]).lower():
            _, tp = _text_ids(str(rec[k]))
            pii = pii or tp
    res = (result or "").upper()
    if res in ("NOT_FOUND", "MISS", "ABSENT", "DELETED_CONFIRMED"):
        present = False
    if not present:
        return "ABSENT", False, cat
    if pfx == "data_flow" or cat == "DATA_FLOW":
        en = None
        for k in ("enabled", "scheduler_registered"):
            if k in rec:
                en = _truthy(rec[k]) if en is None else (en or bool(_truthy(rec[k])))
        if res in ("ACTIVE",):
            en = True
        if res in ("DISABLED", "STOPPED"):
            en = False
        return ("ACTIVE" if en else "DISABLED"), pii, "DATA_FLOW"
    if pfx == "backup" or cat == "BACKUP_ARCHIVE":
        ra = None
        for k in ("restore_allowed", "eligible"):
            if k in rec:
                ra = _truthy(rec[k])
        if "deletion_block" in rec and _truthy(rec["deletion_block"]):
            ra = False
        if "decision" in rec:
            ra = _truthy(rec["decision"])
        if res == "ACTIVE":
            ra = True
        if res == "BLOCKED":
            ra = False
        return ("ACTIVE" if ra else "BLOCKED"), pii, "BACKUP_ARCHIVE"
    if res in ("IDENTIFIABLE",):
        pii = True
    if res in ("ANONYMIZED", "REDACTED"):
        pii = False
    if pfx == "analytics":
        # an analytics row that still carries a user_id is still attributable
        if not is_null(rec.get("user_id")) or not is_null(rec.get("customer_reference")):
            pii = True
        if "direct_identifiers" in rec:
            pii = str(rec["direct_identifiers"]).strip() not in ("0", "", "null")
        if "email_opt_in" in rec or (not cat or cat == "ANALYTICS_PROFILE") and rec.get("_hash_only"):
            cat = "SECONDARY_IDENTIFIER"
    return "PRESENT", pii, cat


# ----------------------------------------------------------------------------
# SQL snapshots
# ----------------------------------------------------------------------------

TABLE_SYSTEM = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}


def _sql_captured_at(text: str, fallback: str):
    m = re.search(r"Captured at:\s*(\S+)", text) or re.search(r"snapshot_completed_at=(\S+)", text)
    return parse_ts(m.group(1)) if m else parse_ts(fallback)


def parse_sql(store: EvidenceStore, fid: str, path: str, captured: str):
    text = open(path, encoding="utf-8").read()
    t_file = _sql_captured_at(text, captured)
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.executescript(text)
    except sqlite3.Error:
        # tolerate partially valid dumps: execute statement by statement
        for stmt in text.split(";\n"):
            try:
                con.execute(stmt)
            except sqlite3.Error:
                pass
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    scope = {}
    if "snapshot_scope" in tables:
        for r in con.execute("select * from snapshot_scope"):
            scope[r["origin_system"]] = parse_ts(r["captured_at"]) or t_file
    seen_by_system: dict[str, set] = {}
    for tname in tables:
        if tname == "snapshot_scope":
            continue
        rows = [dict(r) for r in con.execute(f'select * from "{tname}"')]
        base = re.sub(r"_(primary|failover_replica|read_replica|reporting_replica|replica_[a-z_]+)$", "", tname)
        for row in rows:
            if "record_json" in row:
                try:
                    rec = _flatten(json.loads(row["record_json"]))
                except json.JSONDecodeError:
                    rec = {}
                system = row.get("origin_system") or system_of(row["resource_id"])
            else:
                rec = dict(row)
                system = TABLE_SYSTEM.get(base) or system_of(row["resource_id"])
            rid = row["resource_id"]
            status, pii, cat = classify_record(system, rid, rec)
            ids, _ = _ids_from(rec)
            if rec.get("source_resource_id"):
                ids.add(norm(rec["source_resource_id"]))
            store.add(Obs(fid, t_file, system, rid, status, pii, cat, ids, f"sql:{tname}"))
            seen_by_system.setdefault(system, set()).add(rid)
        if not rows and base in TABLE_SYSTEM:
            seen_by_system.setdefault(TABLE_SYSTEM[base], set())
    systems = set(scope) | set(seen_by_system)
    for s in systems:
        store.coverage.append(Coverage(fid, scope.get(s, t_file), s, seen_by_system.get(s, set())))


# ----------------------------------------------------------------------------
# JSON exports
# ----------------------------------------------------------------------------

COLLECTION_SYSTEM = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_reports": "analytics_platform",
    "customer_export_jobs": "export_service",
    "connector_configurations": "integration_service",
    "backup_catalog": "backup_service",
    "security_audit_events": "security_service",
    "support_conversations": "support_platform",
    "deleted_customer_references": "identity_service",
    "retained_order_records": "legal_service",
}


def _flatten(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict) and k in ("document", "profile"):
            for k2, v2 in v.items():
                out[k2] = v2
        else:
            out[k] = v
    return out


def _add_record(store, fid, t, system, rec, present=True, record_type="", result="", source=""):
    rid = rec.get("resource_id")
    if not rid:
        return
    flat = _flatten(rec)
    if "hits" in rec and isinstance(rec["hits"], dict):
        docs = rec["hits"].get("documents") or []
        present = bool(rec["hits"].get("total")) and bool(docs)
        if docs:
            flat.update({k: v for k, v in docs[0].items() if k != "resource_id"})
    if "status_code" in rec:
        present = str(rec["status_code"]) == "200" and rec.get("profile") is not None
    if "download_available" in rec and _truthy(rec["download_available"]) is False:
        present = False
    if "archive_present" in rec and _truthy(rec["archive_present"]) is False:
        present = False
    status, pii, cat = classify_record(system, rid, flat, present, record_type, result)
    ids, _ = _ids_from(flat)
    if result and "subject_reference" in rec:
        ids.add(norm(rec["subject_reference"]))
    for k in ("query",):
        if rec.get(k):
            ids.add(norm(rec[k]))
    obs_t = parse_ts(rec.get("observed_at") or rec.get("recorded_at")) or t
    store.add(Obs(fid, obs_t, system or system_of(rid), rid, status, pii, cat, ids, source))


def parse_json(store: EvidenceStore, fid: str, path: str, captured: str):
    d = json.load(open(path, encoding="utf-8"))
    t_file = parse_ts(d.get("exported_at") or d.get("captured_at")) or parse_ts(captured)
    if "service_exports" in d:                       # service resource export
        for system, groups in d["service_exports"].items():
            seen = set()
            for _, lst in groups.items():
                for rec in lst:
                    _add_record(store, fid, t_file, system, rec, source="service_export")
                    seen.add(rec.get("resource_id"))
            store.coverage.append(Coverage(fid, t_file, system, seen))
        return
    if "snapshots" in d:                              # records-assurance bundle
        for snap in d["snapshots"]:
            t = parse_ts(snap.get("captured_at")) or t_file
            system = snap.get("data_store") or COLLECTION_SYSTEM.get(snap.get("collection"), "")
            seen = set()
            for rec in snap.get("records", []):
                _add_record(store, fid, t, system, rec, source="snapshot_bundle")
                seen.add(rec.get("resource_id"))
            store.coverage.append(Coverage(fid, t, system, seen))
        return
    recs = d.get("records", [])
    if recs and "record_type" in recs[0]:            # lookup ledgers
        for rec in recs:
            res = rec.get("result", "")
            _add_record(store, fid, t_file, rec.get("system") or system_of(rec["resource_id"]),
                        rec, present=res.upper() not in ("NOT_FOUND",),
                        record_type=rec.get("record_type", ""), result=res, source="ledger")
        return
    system = COLLECTION_SYSTEM.get(d.get("collection"), "")
    seen = set()
    for rec in recs:
        _add_record(store, fid, t_file, system or system_of(rec.get("resource_id", "")), rec,
                    source="collection")
        seen.add(rec.get("resource_id"))
    if system:
        store.coverage.append(Coverage(fid, t_file, system, seen))


# ----------------------------------------------------------------------------
# Plain-text handover / ledger lines:  time | system | resource | TYPE | RESULT | subject
# ----------------------------------------------------------------------------

PIPE_RE = re.compile(r"^\s*-?\s*(\S+)\s*\|\s*([a-z_]+)\s*\|\s*([a-z_]+_\d+)\s*\|\s*([A-Z_]+)\s*\|\s*([A-Z_]+)\s*\|\s*(.+?)\s*$")


def parse_text(store: EvidenceStore, fid: str, path: str, captured: str):
    t_file = parse_ts(captured)
    for line in open(path, encoding="utf-8"):
        m = PIPE_RE.match(line)
        if not m:
            continue
        ts, system, rid, rtype, result, subj = m.groups()
        rec = {"resource_id": rid, "subject_reference": subj}
        status, pii, cat = classify_record(system, rid, {}, True, rtype, result)
        ids = {norm(subj)} if "@" in subj or subj.startswith("user_") else set()
        if result in ("IDENTIFIABLE", "FOUND", "ACTIVE") and "@" in subj:
            pii = pii or result == "IDENTIFIABLE"
        store.add(Obs(fid, parse_ts(ts) or t_file, system, rid, status, pii, cat, ids, "handover"))


# ----------------------------------------------------------------------------
# Logs
# ----------------------------------------------------------------------------

KV_RE = re.compile(r'([A-Za-z_]+)=("(?:[^"\\]|\\.)*"|[^\s"]+)')


def _parse_log_line(line: str) -> dict | None:
    m = re.match(r"^(\d{4}-\d\d-\d\dT[\d:]+Z)\s+(.*)$", line)
    if not m:
        return None
    ts, rest = m.groups()
    d: dict = {"_ts": ts}
    if rest.startswith("{"):
        try:
            d.update(json.loads(rest))
        except json.JSONDecodeError:
            pass
        return d
    m2 = re.match(r"^\[(\w+)\] \[(\S+)\] \[(\S+)\] (\w+):\s*(.*)$", rest)      # bracket style
    if m2:
        d.update(level=m2.group(1), service=m2.group(2), trace_id=m2.group(3), event=m2.group(4))
        rest = m2.group(5)
    m2 = re.match(r"^(\w+) \| (\S+) \| (\S+) \| (\S+) \|\s*(.*)$", rest)       # pipe style
    if m2:
        d.update(level=m2.group(1), service=m2.group(2), trace_id=m2.group(3), event=m2.group(4))
        rest = m2.group(5)
    m2 = re.match(r"^<\d+>1 \S+ (\S+) (\S+) - - (.*)$", rest)                  # syslog style
    if m2:
        d.update(service=m2.group(1), trace_id=m2.group(2))
        rest = m2.group(3)
    rest = rest.replace('\\"', '"')
    for k, v in KV_RE.findall(rest):
        if k == "message":
            continue
        v = v[1:-1] if v.startswith('"') and v.endswith('"') else v
        d.setdefault(k, v) if k in ("service", "trace_id", "event") else d.__setitem__(k, v)
    if "function" in d and "service" not in d:
        d["service"] = d["function"]
    if "function" in d:
        d["service"] = d["function"]
    if "requestId" in d:
        d["trace_id"] = d["requestId"]
    return d


SERVICE_SYSTEM = {"profile_service": "account_service", "support_replica": "support_platform",
                  "attachment_preview": "support_platform"}


def _log_event_obs(ev: dict, trace_ids: set) -> tuple[str, bool, str, bool] | None:
    """Interpret one log event that names a resource. Returns (status,pii,category,present)."""
    e = ev.get("event", "")
    rid = ev.get("resource_id", "")
    if not rid or not RESOURCE_RE.fullmatch(rid):
        return None
    rec = {k: v for k, v in ev.items() if not k.startswith("_")}
    if e.endswith("_started"):
        return None
    present = True
    rtype = ""
    if "rows" in rec:
        present = str(rec["rows"]) not in ("0",)
    if "http_status" in rec and e.startswith("profile_lookup"):
        present = str(rec["http_status"]) == "200"
    if e == "index_query_completed":
        present = str(rec.get("result", "")).lower() == "hit"
    if e in ("export_download_check_completed", "export_metadata_read_completed"):
        present = _truthy(rec.get("available")) is not False
    if e == "restore_policy_read_completed" and _truthy(rec.get("archive_present")) is False:
        present = False
    if e == "attachment_pii_scan":
        rtype = "SUPPORT_ATTACHMENT"
    if e == "contact_lookup_completed":
        rtype = "SECONDARY_IDENTIFIER"
    if e == "contact_query_completed":      # legacy contact index replica row: whole copy
        rtype = "SECONDARY_IDENTIFIER"
    if e == "deletion_marker_check":
        return None          # informational: replica still holds the row (handled by query)
    if e in ("thumbnail_failed",):
        return None
    if e in ("message_pii_scan", "analytics_identity_scan"):
        rec["_pii"] = True
    status, pii, cat = classify_record("", rid, rec, present, rtype)
    if rec.get("_pii"):
        pii = True
    if e == "message_read":
        txt = str(rec.get("message_text", ""))
        pii = "[redacted]" not in txt.lower() and _text_ids(txt)[1]
    return status, pii, cat, present


def parse_log(store: EvidenceStore, fid: str, path: str, captured: str):
    events = []
    for line in open(path, encoding="utf-8"):
        d = _parse_log_line(line.rstrip("\n"))
        if d:
            events.append(d)
    # simple record_lookup style lines carry everything on one line
    traces: dict[str, list] = {}
    for i, ev in enumerate(events):
        tid = ev.get("trace_id") or f"_line{i}"
        traces.setdefault(tid, []).append(ev)
    for tid, evs in traces.items():
        trace_ids: set = set()
        trace_rids = set()
        for ev in evs:
            ids, _ = _ids_from({k: v for k, v in ev.items() if not k.startswith("_")})
            trace_ids |= ids
            if ev.get("resource_id"):
                trace_rids.add(ev["resource_id"])
        for ev in evs:
            if ev.get("event") == "record_lookup":
                rid = ev.get("resource_id")
                res = ev.get("result", "")
                status, pii, cat = classify_record(ev.get("system", ""), rid, {}, True,
                                                   ev.get("record_type", ""), res)
                subj = norm(ev.get("subject_reference"))
                store.add(Obs(fid, parse_ts(ev["_ts"]), ev.get("system", ""), rid, status,
                              pii, cat, {subj} if subj else set(), "log:record_lookup"))
                continue
            r = _log_event_obs(ev, trace_ids)
            if not r:
                continue
            status, pii, cat, _ = r
            svc = SERVICE_SYSTEM.get(ev.get("service", ""), ev.get("service", ""))
            rid = ev["resource_id"]
            sys_guess = system_of(rid)
            system = sys_guess if sys_guess != "unknown" else svc
            ids = set(trace_ids) if len(trace_rids) <= 1 else _ids_from(ev)[0]
            store.add(Obs(fid, parse_ts(ev["_ts"]), system, rid, status, pii, cat, ids,
                          f"log:{ev.get('event')}"))


# ----------------------------------------------------------------------------
# PDF documents and screenshots (text obtained via media.py: LLM vision or OCR)
# ----------------------------------------------------------------------------

def _fix_ocr_ids(text: str) -> str:
    """Repair common OCR confusions inside resource identifiers."""
    text = re.sub(r"\bdata[_ ]?t?[fl]?[oa]w[_ ]", "data_flow_", text)
    text = re.sub(r"\b(user|account|search|analytics|support|backup|export|tombstone|object|marketing)[ .]_?(\d)", r"\1_\2", text)
    text = re.sub(r"\b(user|account|search|analytics|support|backup|export|tombstone|object|marketing)_(\d+) (\d{1,2})\b(?= [A-Za-z])", r"\1_\2\3", text)
    return text


def doc_state_cues(ctx: str, rec: dict, pfx: str):
    if pfx == "backup":
        blocked = re.search(r"(restore[^\n]{0,40}(blocked|denied|disabled|not allowed|off))|deletion block|legal block", ctx)
        rec["restore_allowed"] = "false" if blocked else "true"
    if pfx == "data_flow":
        rec["enabled"] = "false" if re.search(r"\b(disabled|paused|stopped|inactive)\b", ctx) else "true"


def parse_document_text(store: EvidenceStore, fid: str, text: str, captured: str, kind: str):
    """Extract resource observations from free text of a PDF or screenshot.

    Identifiers are attributed per line (a table row in a console screenshot),
    so a connector list showing several customers does not link every connector
    to every customer.  When a document mentions a single resource, the whole
    document's identifiers belong to it (detail pages, attachments, extracts).
    """
    t_file = parse_ts(captured)
    if not text:
        return
    text = _fix_ocr_ids(text)
    lower = text.lower()
    doc_ids, doc_pii = _text_ids(text)
    rids = list(dict.fromkeys(RESOURCE_RE.findall(text)))
    lines = text.splitlines()
    for rid in rids:
        pfx = prefix_of(rid)
        row_lines = [ln for ln in lines if re.search(r"\b" + re.escape(rid) + r"\b", ln)]
        row = " ".join(row_lines)
        row_ids, row_pii = _text_ids(row)
        if len(rids) == 1:
            ids, pii = doc_ids, doc_pii
        else:
            ids, pii = row_ids, row_pii
        rec = {}
        doc_state_cues(row.lower() if len(rids) > 1 else lower, rec, pfx)
        status, _, cat = classify_record("", rid, rec, True)
        if pfx in ("support", "object") and re.search(r"attachment|\.pdf|upload", lower):
            cat = "SUPPORT_ATTACHMENT"
        if pfx in ("tombstone",):
            pii = bool(EMAIL_RE.search(text)) or bool(re.search(r"\+\d[\d\s()\-]{7,}\d", text))
        if pfx == "audit_record":
            pii = False
        store.add(Obs(fid, t_file, system_of(rid), rid, status, pii, cat, set(ids), f"{kind}:text"))


def link_aliases(store: EvidenceStore, activity_rows: list[dict]):
    """Catalog links such as "export_1842 (NST-2026-0718-1842)" name a document
    reference instead of the resource id; attach the resource to the file whose
    text contains that reference."""
    for a in activity_rows:
        if a.get("event_type") != "LINK_RESOURCE_IDENTITY":
            continue
        m = re.search(r"linked (\S+) \(([^)]+)\)|confirmed (\S+) \(([^)]+)\)", a["details"])
        if not m:
            continue
        rid = m.group(1) or m.group(3)
        alias = m.group(2) or m.group(4)
        if alias == rid:
            continue
        link_t = parse_ts(a["event_time"])
        best = None
        for fid, txt in store.media_text.items():
            if alias.lower() not in (txt or "").lower():
                continue
            ft = parse_ts(store.files[fid]["captured_at"])
            gap = abs((link_t - ft).total_seconds())
            if gap <= 2 * 86400 and (best is None or gap < best[0]):
                best = (gap, fid, txt)
        if best and not any(o.resource_id == rid and o.file_id == best[1] for o in store.obs):
            _, fid, txt = best
            ids, pii = _text_ids(txt)
            cat = "SUPPORT_ATTACHMENT" if alias.lower().endswith(".pdf") else ""
            if prefix_of(rid) == "tombstone":
                pii = bool(EMAIL_RE.search(txt))
            store.add(Obs(fid, parse_ts(store.files[fid]["captured_at"]), system_of(rid), rid,
                          "PRESENT", pii, cat, ids | {alias.lower()}, "alias"))


def load_evidence(dataset_dir: str = DATASET_DIR, use_llm: bool = True) -> EvidenceStore:
    store = EvidenceStore()
    manifest = list(csv.DictReader(open(os.path.join(dataset_dir, "evidence_files.csv"), encoding="utf-8")))
    for row in manifest:
        fid, rel, captured = row["file_id"], row["file_path"], row["captured_at"]
        store.files[fid] = row
        path = os.path.join(dataset_dir, rel)
        store.file_ids_by_path[rel] = fid
        if not os.path.exists(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".sql":
                parse_sql(store, fid, path, captured)
            elif ext == ".json":
                parse_json(store, fid, path, captured)
            elif ext == ".log":
                parse_log(store, fid, path, captured)
            elif ext == ".txt":
                parse_text(store, fid, path, captured)
            elif ext in (".pdf", ".png", ".jpg", ".jpeg"):
                txt = _fix_ocr_ids(media.extract_text(path, use_llm=use_llm))
                store.media_text[fid] = txt
                parse_document_text(store, fid, txt, captured, ext[1:])
        except Exception as exc:  # never let one bad file kill the run
            print(f"[warn] failed to parse {rel}: {exc}")
    acts = list(csv.DictReader(open(os.path.join(dataset_dir, "system_activity.csv"), encoding="utf-8")))
    link_aliases(store, acts)
    return store
