"""Request intent: does the request text actually authorise account deletion?

Primary path: Claude classifies each unique request text (batched, cached).
Fallback path (no API key): multilingual keyword rules.  Both are run when the
LLM is available and disagreements are logged so they can be reviewed.
"""
from __future__ import annotations

import json
import re

from . import llm

SYSTEM_PROMPT = """You classify customer privacy requests for an e-commerce company.
For each request decide whether the customer is asking for their ACCOUNT / PERSONAL DATA TO BE DELETED (erasure).
Answer DELETE only for an erasure / account-deletion / account-closure-with-data-removal request.
Answer OTHER for anything else: access or copy of data, data export/portability, correction of details,
changing email or phone, marketing or promotional opt-out (even if phrased "remove me from marketing lists"),
login help, invoices, or any request that explicitly says not to delete.
Requests can be in any language. Return ONLY a JSON object mapping each id to "DELETE" or "OTHER"."""

DELETE_PATTERNS = [
    r"\bdelet", r"\bremov", r"\bclose", r"\berase", r"\berasure", r"\bremove (my|the) (account|profile)", r"\bclose (my|this|the) account",
    r"permanently deleted", r"\bis gone\b", r"\bclosed my account", r"deletion",
    r"supprim", r"suppression",            # fr
    r"eliminaci", r"eliminar",              # es
    r"exclus", r"excluir", r"apagar",       # pt
    r"löschen", r"löschung",                # de
    r"삭제", r"削除", r"消去", r"删除",        # ko / ja / zh
]
NEGATIVE_PATTERNS = [
    r"not a request to erase", r"don't delete", r"do not delete", r"don’t delete",
    r"marketing lists only", r"stop the promotional", r"\bopt[- ]out\b",
    r"copy of (the )?(information|data|last year)", r"download my account information",
    r"portable format", r"what personal information you hold", r"misspelled", r"out of date",
    r"change the email address", r"resetting the login", r"can't access my profile",
    r"invoices for my records",
]


def rule_intent(text: str) -> str:
    t = (text or "").lower()
    if any(re.search(p, t) for p in NEGATIVE_PATTERNS):
        return "OTHER"
    if any(re.search(p, t) for p in DELETE_PATTERNS):
        return "DELETE"
    return "OTHER"


def classify_all(texts: list[str], use_llm: bool = True, batch: int = 40) -> dict[str, str]:
    """Return {text: 'DELETE'|'OTHER'} for every unique text."""
    uniq = sorted(set(texts))
    result = {t: rule_intent(t) for t in uniq}
    if not use_llm:
        return result
    llm_result: dict[str, str] = {}
    for i in range(0, len(uniq), batch):
        chunk = uniq[i:i + batch]
        payload = {f"r{j}": t for j, t in enumerate(chunk)}
        txt = llm.call(llm.MODEL_TEXT, SYSTEM_PROMPT,
                       [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                       max_tokens=60 + 12 * len(chunk))
        if not txt:
            continue
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            ans = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            ans = {}
        for j, t in enumerate(chunk):
            v = str(ans.get(f"r{j}", "")).upper()
            if v in ("DELETE", "OTHER"):
                llm_result[t] = v
    for t, v in llm_result.items():
        if v != result[t]:
            print(f"[intent] LLM/rule disagreement -> using LLM={v}: {t[:90]}")
        result[t] = v
    return result
