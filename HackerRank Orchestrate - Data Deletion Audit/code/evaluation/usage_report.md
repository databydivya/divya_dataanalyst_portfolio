# Token Usage and Cost Report

Generated automatically by `code/main.py` at 2026-10-24T15:37:07Z for the final full-dataset run that produced `output.csv`.

- Requests audited: **518**
- Wall-clock time: 1.0 s
- Live model calls enabled: no (cache / deterministic fallback)
- Provider: Anthropic (Claude Messages API), temperature 0, responses cached on disk

> **Final submitted run:** no API credit was available, so `output.csv` was produced with the
> built-in deterministic fallback (`--no-llm`: multilingual keyword intent rules + local Tesseract OCR).
> It made **0 model calls at $0 cost**, and it matches the model-free sample scores in
> `evaluation_report.md`. With `ANTHROPIC_API_KEY` set, the same command uses the models listed below.

## Where the models are used

| Stage | Model | Calls | Why |
| --- | --- | --- | --- |
| Request intent (DELETE vs other, any language) | `claude-haiku-4-5` | batched, 40 unique texts per call | multilingual, nuanced negations ("not a request to erase") |
| Screenshot transcription (11 PNG console captures) | `claude-sonnet-4-5` | 1 per image | read table rows, IDs, toggles from admin-console screenshots |
| Everything else (SQL, JSON, logs, PDFs, policy, planning) | none - deterministic Python | 0 | exact, auditable, free |

## Per-model totals

| Model | Live calls | Cached calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Overall** | **0** | **0** | **0** | **0** | **0** | **$0.0000** |

## Per-request averages

- Average tokens per request: **0.0**
- Estimated cost per request: **$0.000000**

Token counts are the `usage` values returned by the API (cached calls report the tokens of the
original call, so the table reflects the cost of producing the answers even on a re-run).
Prices used for the estimate (USD per million input / output tokens): `claude-haiku-4-5` 1.00 / 5.00, `claude-sonnet-4-5` 3.00 / 15.00, `claude-opus-4-5` 5.00 / 25.00.

## Efficiency choices

- Only 2 of ~10 pipeline stages call a model; the rest is deterministic parsing and rule application.
- Intent classification deduplicates the 518 request texts and sends them in batches.
- Every response is cached by request hash, so re-runs cost nothing and are reproducible.
- Without `ANTHROPIC_API_KEY` the pipeline still runs end-to-end (keyword intent rules + Tesseract OCR).
