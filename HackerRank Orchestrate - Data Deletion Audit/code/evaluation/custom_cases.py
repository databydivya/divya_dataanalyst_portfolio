"""Custom evaluation cases written by the team (not part of the supplied dataset).

Each case builds a tiny, self-contained synthetic dataset in a temp folder (same
file formats as dataset/), runs the real pipeline on it and compares the result
with a hand-written expected answer.  They target behaviours the public samples
cover thinly:

  C1 replication drift  - primary deleted the account, the failover replica still has it
  C2 historical email   - request uses an OLD email; the active connector only knows the new one
  C3 time cut-off       - a capture taken AFTER audit_at shows data, but must be ignored
  C4 non-deletion       - marketing opt-out phrased with "remove me" -> NOT_APPLICABLE
  C5 tombstone exposure - deleted-account tombstone still carries name/email -> REDACT
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.util import DATASET_DIR  # noqa: E402

USERS = [
    ("user_9001", "Ghost One", "ghost.one@example.com", "+1 555 0101", "h9001"),
    ("user_9002", "Rene Old", "rene.new@example.com", "+1 555 0102", "h9002"),
    ("user_9003", "Clean Three", "clean.three@example.com", "+1 555 0103", "h9003"),
    ("user_9004", "Opt Out", "opt.out@example.com", "+1 555 0104", "h9004"),
    ("user_9005", "Tomb Stone", "tomb.stone@example.com", "+1 555 0105", "h9005"),
]
REQ = [
    # case, email, requested, status, reported, audit, text
    ("case_c1", "ghost.one@example.com", "2026-09-01T08:00:00Z", "COMPLETE", "2026-09-02T08:00:00Z", "2026-09-05T08:00:00Z",
     "Please permanently delete my account."),
    ("case_c2", "rene.old@example.com", "2026-09-01T08:00:00Z", "PARTIALLY_COMPLETE", "2026-09-03T08:00:00Z", "2026-09-06T08:00:00Z",
     "I changed my email a while ago. Please erase the account under the old and the new address."),
    ("case_c3", "clean.three@example.com", "2026-09-01T08:00:00Z", "COMPLETE", "2026-09-04T08:00:00Z", "2026-09-07T08:00:00Z",
     "Bitte löschen Sie mein Konto und alle personenbezogenen Daten."),
    ("case_c4", "opt.out@example.com", "2026-09-01T08:00:00Z", "NOT_STARTED", "2026-09-02T08:00:00Z", "2026-09-05T08:00:00Z",
     "Please remove me from marketing lists only. Keep my account and order history."),
    ("case_c5", "tomb.stone@example.com", "2026-09-01T08:00:00Z", "PARTIALLY_COMPLETE", "2026-09-05T08:00:00Z", "2026-09-08T08:00:00Z",
     "Delete my account. A deleted-account reference may stay if other records need it."),
]


def S(n, phase, system, rid, op, state, ev=""):
    return {"step_no": n, "phase": phase, "system_id": system, "resource_id": rid,
            "operation": op, "state": state, "evidence_id": ev}


EXPECTED = {
    "case_c1": ("INCOMPLETE", [
        S(1, "FINDING", "account_service", "account_90001", "REPORT_REMAINING_RECORD", "PRESENT", "cev_01"),
        S(2, "REMEDIATION", "account_service", "account_90001", "DELETE_RECORD", "ABSENT"),
        S(3, "VERIFICATION", "account_service", "account_90001", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ]),
    "case_c2": ("INCOMPLETE", [
        S(1, "FINDING", "integration_service", "data_flow_90002", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", "cev_02"),
        S(2, "REMEDIATION", "integration_service", "data_flow_90002", "DISABLE_DATA_FLOW", "DISABLED"),
        S(3, "VERIFICATION", "account_service", "account_90002", "VERIFY_RECORD_ABSENT", "ABSENT"),
        S(4, "VERIFICATION", "security_service", "audit_record_90002", "VERIFY_RECORD_PRESENT", "PRESENT"),
        S(5, "VERIFICATION", "integration_service", "data_flow_90002", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ]),
    "case_c3": ("COMPLETE", [
        S(1, "VERIFICATION", "account_service", "account_90003", "VERIFY_RECORD_ABSENT", "ABSENT", "cev_03"),
        S(2, "VERIFICATION", "analytics_platform", "analytics_90003", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", "cev_03"),
    ]),
    "case_c4": ("NOT_APPLICABLE", []),
    "case_c5": ("INCOMPLETE", [
        S(1, "FINDING", "identity_service", "tombstone_90005", "REPORT_EXPOSED_PII", "PRESENT", "cev_05"),
        S(2, "REMEDIATION", "identity_service", "tombstone_90005", "REDACT_RECORD", "REDACTED"),
        S(3, "VERIFICATION", "account_service", "account_90005", "VERIFY_RECORD_ABSENT", "ABSENT"),
        S(4, "VERIFICATION", "identity_service", "tombstone_90005", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ]),
}


def _w(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def build(root: str):
    shutil.copy(os.path.join(DATASET_DIR, "deletion_rules.csv"), os.path.join(root, "deletion_rules.csv"))
    _w(os.path.join(root, "user_identities.csv"), ["user_id", "name", "email", "phone", "email_hash", "updated_at"],
       [u + ("2026-01-01T00:00:00Z",) for u in USERS])
    _w(os.path.join(root, "user_audit_log.csv"), ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"],
       [("audit_c1", "user_9002", "2026-05-01T00:00:00Z", "email", "rene.old@example.com", "rene.new@example.com")])
    acts = [
        ("activity_c1", "2026-09-02T07:05:00Z", "DELETE_RECORD", "deletion_worker", "account_service", "account_90001",
         "SUCCESS", "Deletion worker submitted primary profile account_90001 to account_service."),
        ("activity_c2", "2026-09-03T07:10:00Z", "DELETE_RECORD", "deletion_worker", "account_service", "account_90002",
         "PARTIAL", "Deletion worker submitted primary profile account_90002 to account_service."),
        ("activity_c3", "2026-09-04T07:00:00Z", "DELETE_RECORD", "deletion_worker", "account_service", "account_90003",
         "SUCCESS", "Deletion worker submitted primary profile account_90003 to account_service."),
        ("activity_c4", "2026-09-04T07:31:00Z", "ANONYMIZE_RECORD", "deletion_worker", "analytics_platform", "analytics_90003",
         "SUCCESS", "Policy action completed for analytics_90003."),
        ("activity_c5", "2026-09-05T07:02:00Z", "DELETE_RECORD", "deletion_worker", "account_service", "account_90005",
         "PARTIAL", "Deletion worker submitted primary profile account_90005 to account_service."),
    ]
    _w(os.path.join(root, "system_activity.csv"),
       ["activity_id", "event_time", "event_type", "source_system", "target_system", "resource_id", "reported_result", "details"], acts)
    ev = os.path.join(root, "evidence")
    os.makedirs(os.path.join(ev, "databases"), exist_ok=True)
    os.makedirs(os.path.join(ev, "records"), exist_ok=True)
    # C1: failover replica still holds the account the primary deleted
    open(os.path.join(ev, "databases", "c1_failover.sql"), "w").write("""-- Captured at: 2026-09-04T00:00:00Z
BEGIN TRANSACTION;
CREATE TABLE customer_profiles_primary (resource_id TEXT PRIMARY KEY, user_id TEXT, full_name TEXT, email TEXT, phone TEXT, account_status TEXT, updated_at TEXT);
CREATE TABLE customer_profiles_failover_replica (resource_id TEXT PRIMARY KEY, user_id TEXT, full_name TEXT, email TEXT, phone TEXT, account_status TEXT, updated_at TEXT);
INSERT INTO customer_profiles_failover_replica VALUES('account_90001','user_9001','Ghost One','ghost.one@example.com','+1 555 0101','ACTIVE','2026-09-03T23:00:00Z');
COMMIT;
""")
    # C2: active connector keyed by the NEW email, account 404, retained audit record
    json.dump({"exported_at": "2026-09-05T10:00:00Z", "service_exports": {
        "account_service": {"profile_lookups": [{"observed_at": "2026-09-05T09:00:00Z", "profile": None,
                                                 "resource_id": "account_90002", "status_code": 404}]},
        "integration_service": {"connectors": [{"connector_name": "analytics_identity_bridge", "customer_email": "rene.new@example.com",
                                                "customer_reference": None, "enabled": True, "last_delivery_status": "delivered",
                                                "observed_at": "2026-09-05T09:10:00Z", "resource_id": "data_flow_90002"}]},
        "security_service": {"audit_records": [{"event_code": "ACCOUNT_DELETION_RECORDED", "observed_at": "2026-09-05T09:20:00Z",
                                                "resource_id": "audit_record_90002", "retention_until": "2031-12-31T23:59:59Z",
                                                "subject_reference": "user_9002"}]}}},
              open(os.path.join(ev, "records", "c2_export.json"), "w"))
    # C3: compliant snapshot before audit, then a LATER capture with a search hit (must be ignored)
    json.dump({"exported_at": "2026-09-06T12:00:00Z", "snapshots": [
        {"captured_at": "2026-09-06T12:00:00Z", "data_store": "account_service", "collection": "customer_profiles", "records": []},
        {"captured_at": "2026-09-06T12:00:00Z", "data_store": "analytics_platform", "collection": "customer_analytics_reports",
         "records": [{"resource_id": "analytics_90003", "user_id": None, "email": None, "phone": None, "email_hash": None}]}]},
              open(os.path.join(ev, "records", "c3_bundle.json"), "w"))
    json.dump({"exported_at": "2026-09-20T12:00:00Z", "snapshots": [
        {"captured_at": "2026-09-20T12:00:00Z", "data_store": "search_service", "collection": "customer_search_documents",
         "records": [{"resource_id": "search_90003", "document": {"display_name": "Clean Three",
                                                                   "email": "clean.three@example.com", "customer_reference": "user_9003"}}]}]},
              open(os.path.join(ev, "records", "c3_late_bundle.json"), "w"))
    # C5: tombstone still exposing direct identifiers
    json.dump({"exported_at": "2026-09-07T12:00:00Z", "snapshots": [
        {"captured_at": "2026-09-07T12:00:00Z", "data_store": "identity_service", "collection": "deleted_customer_references",
         "records": [{"resource_id": "tombstone_90005", "subject_reference": "user_9005", "name": "Tomb Stone",
                      "email": "tomb.stone@example.com", "phone": None, "email_hash": None, "account_status": "DELETED"}]}]},
              open(os.path.join(ev, "records", "c5_bundle.json"), "w"))
    _w(os.path.join(root, "evidence_files.csv"), ["file_id", "file_path", "origin", "captured_at"], [
        ("cev_01", "evidence/databases/c1_failover.sql", "custom", "2026-09-04T00:00:00Z"),
        ("cev_02", "evidence/records/c2_export.json", "custom", "2026-09-05T10:00:00Z"),
        ("cev_03", "evidence/records/c3_bundle.json", "custom", "2026-09-06T12:00:00Z"),
        ("cev_04", "evidence/records/c3_late_bundle.json", "custom", "2026-09-20T12:00:00Z"),
        ("cev_05", "evidence/records/c5_bundle.json", "custom", "2026-09-07T12:00:00Z"),
    ])
    _w(os.path.join(root, "custom_requests.csv"),
       ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"], REQ)


def run_custom(verbose=False, use_llm=False):
    from audit.pipeline import read_requests, run_cases
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from metrics import score
    root = tempfile.mkdtemp(prefix="custom_cases_")
    build(root)
    reqs = read_requests(os.path.join(root, "custom_requests.csv"))
    results = run_cases(reqs, dataset_dir=root, use_llm=use_llm)
    pred = {r.case_id: (r.status, r.steps) for r in results}
    m = score(EXPECTED, pred, verbose=verbose)
    print("custom cases:", json.dumps({k: m[k] for k in ("cases", "status_accuracy", "step_f1", "sequence_accuracy", "failures")}))
    shutil.rmtree(root, ignore_errors=True)
    return m


if __name__ == "__main__":
    run_custom(verbose=True)
