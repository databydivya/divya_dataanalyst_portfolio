# Ghost Data Still Exists — Deletion Audit Agent

An agent that audits whether a customer's personal data is really gone, and if not,
produces the ordered findings → remediation → verification plan required by the
challenge contract.

## Quick start

```bash
# from the repository root
python3 -m pip install -r code/requirements.txt      # anthropic, pypdf, pillow
export ANTHROPIC_API_KEY=...                          # optional but recommended
python3 code/main.py                                  # -> ./output.csv + code/evaluation/usage_report.md
python3 code/evaluation/main.py --custom              # scores on the 32 samples + 5 custom cases
```

Useful flags:

| Command | What it does |
| --- | --- |
| `python3 code/main.py --no-llm` | fully deterministic run (keyword intent rules + Tesseract OCR) |
| `python3 code/main.py --explain case_36,case_49` | print the reasoning trace (resources, states, links) |
| `python3 code/main.py --input dataset/sample_deletion_requests.csv --output /tmp/s.csv` | run any request file |
| `python3 code/evaluation/main.py --verbose` | show every missing / extra step per sample case |

Optional tools: `pdftotext` (poppler) is used for PDFs when present, otherwise `pypdf`;
`tesseract` is only needed for screenshots when no API key is set.
Model names can be changed with `AUDIT_TEXT_MODEL` / `AUDIT_VISION_MODEL`.

## Architecture

```
dataset/ ──► extract.py ──► Obs records ──┐
             (SQL, JSON, logs, txt,        │
              PDF, PNG via media.py)       ▼
user_identities + audit_log ──► identity.py ──► engine.py ──► ordered steps ──► output.csv
system_activity ───────────────────────────────►  (discover → state@audit → policy → plan)
request_text ──► intent.py (Claude, batched; rule fallback) ──► NOT_APPLICABLE gate
```

| Module | Responsibility |
| --- | --- |
| `audit/extract.py` | One parser per evidence family; every file becomes normalised observations: *file F saw resource R in system S, state X (present/absent/active/blocked…), still exposing PII or not, carrying identifiers Y*. Full captures also record **coverage** (which systems were captured completely), used to prove an account is absent. Logs are grouped by `trace_id` so a lookup key on a `*_started` line links to the resource on the `*_completed` line. |
| `audit/media.py` | PDFs → text layer. Screenshots → Claude vision transcription (cached); Tesseract OCR fallback with upscaling and identifier repair. |
| `audit/identity.py` | Resolves the request email (current **or historical**, case-insensitive) to a `user_id` and every email / phone / email-hash the user ever had. |
| `audit/intent.py` | Decides whether the request authorises deletion (any language). Claude classifies unique texts in batches; multilingual keyword rules are the fallback and a cross-check. |
| `audit/engine.py` | Discovery, state reconstruction, policy and plan generation (details below). |
| `audit/llm.py` | Anthropic client: temperature 0, disk cache keyed by request hash, per-model token accounting. |
| `audit/report.py` | Writes `evaluation/usage_report.md` after the full run. |

### How a case is decided

1. **Intent gate** – non-deletion requests (access, export, correction, marketing opt-out…) → `NOT_APPLICABLE, []`.
2. **Discovery** – resources are linked to the subject by
   * identifiers inside evidence records (emails incl. historical ones, phones, email hashes, `user_id` references),
   * explicit data-catalog links in `system_activity` (`LINK_RESOURCE_IDENTITY`, incl. document references such as a statement number),
   * lineage: an active connector / restore job that *repopulated* a downstream resource,
   * **deletion-workflow activity**: the workflow touches a request's resources at characteristic offsets from `reported_at` (account job ≈ 40–80 min before, policy actions ≈ 3–35 min before, final results and status checks ≈ 25–125 min after). Records that evidence attributes to someone else are excluded; when several requests share a window, the account job whose result matches the reported status (`COMPLETE↔SUCCESS`, `PARTIALLY_COMPLETE↔PARTIAL`, `NOT_STARTED↔FAILED`) is preferred.
3. **State at `audit_at`** – only evidence captured **after the request and no later than `audit_at`** counts (older captures predate the deletion; later ones are forbidden). The latest capture wins; inside one SQL snapshot a row surviving in *any* replica (failover / regional / reporting / read) means the record still exists (replication drift). Workflow statuses and activity results are treated as claims, never as proof.
4. **Policy** – `deletion_rules.csv` category → treatment: DELETE (profile, search, cache, export, marketing, secondary identifiers, attachments), REDACT (support messages, email logs, account tombstones), ANONYMIZE (analytics, telemetry), RETAIN (security audit, legal hold), data flows must be disabled, backups must have restore blocked.
5. **Plan** – `INCOMPLETE` if any finding exists: findings (cite the evidence file), remediation (disable flows / block restores first, then delete / redact / anonymize), verification of every remediated item, the primary account and retained records. `COMPLETE`: only evidence-backed verification steps. Ordering follows the contract: phase → operation order → `system_id` → `resource_id`.

### Why mostly deterministic?

The grader checks exact resource IDs, operations and evidence IDs. Parsing structured
evidence with code is exact, free and reproducible, so the models are used only where
they add real value: understanding free-text requests in many languages and reading
screenshots. See `evaluation/usage_report.md` for tokens and cost.

## Evaluation

`code/evaluation/main.py` scores predictions against `dataset/sample_output.csv`
(status accuracy, step precision/recall/F1, field accuracy, exact sequence accuracy) and
`--custom` runs five team-written synthetic cases (`evaluation/custom_cases.py`).
Results and the failure log are in `evaluation/evaluation_report.md`.

## Repository layout

```
code/
  main.py                  entry point
  requirements.txt
  audit/                   the agent (extract, media, identity, intent, engine, llm, report)
  evaluation/
    main.py                evaluation harness
    metrics.py             scoring
    custom_cases.py        5 custom evaluation cases
    evaluation_report.md
    usage_report.md        generated by the final full run
  cache/                   model response cache (safe to delete; makes re-runs free)
```

No credentials are stored anywhere in the repository; the API key is read from the environment.
