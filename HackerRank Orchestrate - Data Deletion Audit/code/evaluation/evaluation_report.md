# Evaluation Report

Reproduce with:

```bash
python3 code/evaluation/main.py --custom            # add --verbose for per-step diffs, --no-llm for the fallback path
```

## 1. Method

* **Gold set:** the 32 public cases in `dataset/sample_output.csv`.
* **Custom set:** 5 team-written cases (`code/evaluation/custom_cases.py`) that build their own tiny dataset in the
  same file formats and therefore test behaviour, not memorised IDs.
* A *step* is the tuple `(phase, system_id, resource_id, operation, state, evidence_id)`.

| Metric | Definition |
| --- | --- |
| Status accuracy | predicted `deletion_status` == gold |
| Step precision / recall / F1 | multiset overlap of step tuples per case, micro-averaged |
| Field accuracy | for each gold step, the predicted step for the same resource and phase (else same position) agrees on that field |
| Sequence accuracy | whole `steps_json` array identical in content **and** order |

> Caveat: the 32 samples were also used to discover the data conventions, so they are an optimistic
> estimate. The custom cases and the manual review of test clusters (section 5) are the guard against
> over-fitting. No case id, resource id or answer is hard-coded anywhere in the solution.

## 2. Results — sample set (32 cases, final version)

| Metric | Value |
| --- | ---: |
| Case-level status accuracy | **100.0 %** (32/32) |
| Step precision | **98.95 %** |
| Step recall | **97.93 %** |
| Step F1 | **98.44 %** |
| Sequence accuracy (exact ordered match) | **84.4 %** (27/32) |

Field-level accuracy (over 193 gold steps):

| phase | system_id | resource_id | operation | state | evidence_id | step_no |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100.0 % | 98.4 % | 97.9 % | 98.4 % | 98.4 % | 99.5 % | 96.9 % |

Status confusion: COMPLETE→COMPLETE 10, INCOMPLETE→INCOMPLETE 22, no cross errors.

Remaining sample mismatches (5 cases) and why:

| Case | Difference | Root cause |
| --- | --- | --- |
| case_04 | missing `VERIFY_RECORD_ABSENT account_004` | the account id appears in no evidence or activity row — not discoverable |
| case_18, case_20 | missing one `VERIFY_RECORD_PRESENT audit_record_*` | `audit_record_6645` exists in no participant file; `audit_record_5569` likewise |
| case_23 | `account_7015` chosen instead of `account_410` | three requests share the same reporting window and all three account jobs `FAILED`; no evidence distinguishes them |
| case_11 | extra `VERIFY_RECORD_ANONYMIZED analytics_9447` | an unnamed, already-anonymised analytics row in a shared window was attributed to the wrong request |

## 3. Results — custom evaluation cases (5 cases)

| Case | Scenario | Expected | Result |
| --- | --- | --- | --- |
| C1 | Primary deleted the profile but the **failover replica** still holds it (replication drift) | INCOMPLETE: report → delete → verify `account_90001` | ✅ |
| C2 | Request uses an **old email**; the active connector only knows the **new** email; retained audit record | INCOMPLETE: disable flow, verify account absent, audit present, flow disabled | ✅ |
| C3 | Compliant snapshot before `audit_at` and a **later** capture showing a search hit (must be ignored); request written in German | COMPLETE with evidence-backed checks citing the pre-audit file | ✅ |
| C4 | "Please **remove me from marketing lists only**" | NOT_APPLICABLE, `[]` | ✅ |
| C5 | Account **tombstone** still carries name and email | INCOMPLETE: report exposed PII → redact → verify redacted | ✅ |

Custom set: status accuracy 100 %, step F1 100 %, sequence accuracy 100 %.

## 4. Failures found and improvements made

Every row is a measured iteration on the sample set (`--no-llm` path).

| # | Failure observed | Fix | Status acc. | Step F1 | Seq. acc. |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | baseline: identifier matching + latest observation | — | 81.3 % | 0.670 | 31.3 % |
| 2 | Cited/used files whose manifest `captured_at` is after `audit_at` (records inside them were dated earlier) | gate every observation by the file's manifest capture time | 93.8 % | 0.879 | 37.5 % |
| 3 | Activity of neighbouring requests leaked into a case (wide ±2 h window); later partial snapshots "proved" retained records absent | per-message-template time offsets relative to `reported_at`; stop using partial snapshots to flip present→absent | 96.9 % | 0.910 | 43.8 % |
| 4 | Several requests reported at the same minute shared unnamed account jobs | match the account job result to the request's reported status (`SUCCESS/PARTIAL/FAILED`), one primary account per request, prefer requests without failures for clean policy actions | 96.9 % | 0.945 | 62.5 % |
| 5 | Screenshots/PDFs linked every row to every customer on the page | per-row identifier attribution; data-catalog links (incl. document references like statement numbers) | 96.9 % | 0.930 | 53.1 % |
| 6 | Old captures (months before the request) were treated as current state | only evidence captured between `requested_at` and `audit_at` establishes state | 96.9 % | 0.955 | 68.8 % |
| 7 | Legacy support-replica contact row was redacted instead of deleted; retained audit records missing from post-remediation checks | legacy contact-index rows are whole secondary copies (DELETE); retained records known from the next capture are included in future checks | 100 % | 0.971 | 71.9 % |
| 8 | Selective snapshots wrongly proved security records absent | absence-by-coverage only for the account store (complete captures) | 100 % | 0.984 | 84.4 % |
| 9 | Search documents stored as nested JSON in SQL replicas lost their identifiers | flatten nested `document` objects in every source | 100 % | 0.984 | 84.4 % (no sample change; fixes ownership on test clusters) |

Other robustness work: OCR fallback upscales images 2× and repairs identifiers (`data_tow_9846` → `data_flow_9846`,
`user 17` → `user_17`); case-insensitive email matching (`SIPHO.MOKOENA@GMAIL.COM`); PDFs fall back to `pypdf` when
`pdftotext` is missing; one bad evidence file can never stop the run.

## 5. Manual review of the 518 test cases

No labels exist for the test set, so representative clusters were inspected by hand with
`python3 code/main.py --explain <case>` against the raw evidence:

* handover text cluster (cases 36–42), service-export cluster (43–51), read-replica cluster (54–62),
  SQL inventory cluster (64–72), regional / reporting replica clusters (400–431), multimodal cases (33–63);
* every authorised deletion resolves to a user; 10 non-deletion requests are `NOT_APPLICABLE`;
* output distribution: INCOMPLETE 354, COMPLETE 154, NOT_APPLICABLE 10; 518 rows, valid JSON, consecutive step numbers.

Known limitations: unnamed resources in windows shared by several requests can be mis-attributed (≈1 in 32 on the
samples); resources that appear in no participant file cannot be reported.
