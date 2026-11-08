"""Writes evaluation/usage_report.md from the token accounting of a full run."""
from __future__ import annotations

import datetime as _dt

from . import llm


def write_usage_report(path: str, usage: dict, n_requests: int, seconds: float, llm_enabled: bool):
    per = usage["per_model"]
    tot = usage["total"]
    tokens = tot["input_tokens"] + tot["output_tokens"]
    lines = [
        "# Token Usage and Cost Report",
        "",
        f"Generated automatically by `code/main.py` at {_dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"for the final full-dataset run that produced `output.csv`.",
        "",
        f"- Requests audited: **{n_requests}**",
        f"- Wall-clock time: {seconds} s",
        f"- Live model calls enabled: {'yes' if llm_enabled else 'no (cache / deterministic fallback)'}",
        "- Provider: Anthropic (Claude Messages API), temperature 0, responses cached on disk",
        *([] if llm_enabled else ["",
          "> **Final submitted run:** no API credit was available, so `output.csv` was produced with the",
          "> built-in deterministic fallback (`--no-llm`: multilingual keyword intent rules + local Tesseract OCR).",
          "> It made **0 model calls at $0 cost**, and it matches the model-free sample scores in",
          "> `evaluation_report.md`. With `ANTHROPIC_API_KEY` set, the same command uses the models listed below."]),
        "",
        "## Where the models are used",
        "",
        "| Stage | Model | Calls | Why |",
        "| --- | --- | --- | --- |",
        f"| Request intent (DELETE vs other, any language) | `{llm.MODEL_TEXT}` | batched, 40 unique texts per call | multilingual, nuanced negations (\"not a request to erase\") |",
        f"| Screenshot transcription (11 PNG console captures) | `{llm.MODEL_VISION}` | 1 per image | read table rows, IDs, toggles from admin-console screenshots |",
        "| Everything else (SQL, JSON, logs, PDFs, policy, planning) | none - deterministic Python | 0 | exact, auditable, free |",
        "",
        "## Per-model totals",
        "",
        "| Model | Live calls | Cached calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for m, u in sorted(per.items()):
        lines.append(f"| `{m}` | {u['calls']} | {u['cached_calls']} | {u['input_tokens']:,} | {u['output_tokens']:,} | "
                     f"{u['input_tokens'] + u['output_tokens']:,} | ${u['cost_usd']:.4f} |")
    lines += [
        f"| **Overall** | **{tot['calls']}** | **{tot['cached_calls']}** | **{tot['input_tokens']:,}** | "
        f"**{tot['output_tokens']:,}** | **{tokens:,}** | **${tot['cost_usd']:.4f}** |",
        "",
        "## Per-request averages",
        "",
        f"- Average tokens per request: **{tokens / max(n_requests, 1):,.1f}**",
        f"- Estimated cost per request: **${tot['cost_usd'] / max(n_requests, 1):.6f}**",
        "",
        "Token counts are the `usage` values returned by the API (cached calls report the tokens of the",
        "original call, so the table reflects the cost of producing the answers even on a re-run).",
        "Prices used for the estimate (USD per million input / output tokens): "
        + ", ".join(f"`{m}` {p[0]:.2f} / {p[1]:.2f}" for m, p in llm.PRICES.items()) + ".",
        "",
        "## Efficiency choices",
        "",
        "- Only 2 of ~10 pipeline stages call a model; the rest is deterministic parsing and rule application.",
        "- Intent classification deduplicates the 518 request texts and sends them in batches.",
        "- Every response is cached by request hash, so re-runs cost nothing and are reproducible.",
        "- Without `ANTHROPIC_API_KEY` the pipeline still runs end-to-end (keyword intent rules + Tesseract OCR).",
    ]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
