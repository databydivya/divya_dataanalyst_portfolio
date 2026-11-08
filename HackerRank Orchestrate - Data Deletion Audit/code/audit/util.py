"""Small shared helpers: paths, timestamps, resource-id conventions."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(CODE_DIR)
DATASET_DIR = os.environ.get("DATASET_DIR", os.path.join(REPO_ROOT, "dataset"))
CACHE_DIR = os.path.join(CODE_DIR, "cache")

RESOURCE_RE = re.compile(
    r"\b((?:account|search|analytics|audit_record|support|email_delivery|data_flow|cache|export|"
    r"backup|tombstone|legal_hold|marketing|object|telemetry)_\d+)\b"
)
USER_RE = re.compile(r"\buser_\d+\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# resource prefix -> (system_id, default data category)
PREFIX_INFO = {
    "account": ("account_service", "USER_PROFILE"),
    "search": ("search_service", "SEARCH_INDEX_ENTRY"),
    "analytics": ("analytics_platform", "ANALYTICS_PROFILE"),
    "audit_record": ("security_service", "SECURITY_AUDIT_LOG"),
    "support": ("support_platform", "SUPPORT_MESSAGE"),
    "email_delivery": ("email_delivery_service", "EMAIL_DELIVERY_LOG"),
    "data_flow": ("integration_service", "DATA_FLOW"),
    "cache": ("cache_service", "CACHE_ENTRY"),
    "export": ("export_service", "USER_EXPORT"),
    "backup": ("backup_service", "BACKUP_ARCHIVE"),
    "tombstone": ("identity_service", "ACCOUNT_TOMBSTONE"),
    "legal_hold": ("legal_service", "LEGAL_HOLD_RECORD"),
    "marketing": ("marketing_platform", "MARKETING_PROFILE"),
    "object": ("object_storage", "SUPPORT_ATTACHMENT"),
    "telemetry": ("telemetry_service", "PRODUCT_TELEMETRY"),
}


def prefix_of(resource_id: str) -> str:
    return re.sub(r"_\d+$", "", resource_id or "")


def system_of(resource_id: str) -> str:
    return PREFIX_INFO.get(prefix_of(resource_id), ("unknown", "UNKNOWN"))[0]


def category_of(resource_id: str) -> str:
    return PREFIX_INFO.get(prefix_of(resource_id), ("unknown", "UNKNOWN"))[1]


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except ValueError:
        return None


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(v) -> str:
    """Normalise an identifier value for matching."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "null", "none", "[redacted]", "redacted"):
        return ""
    return s.lower()


def norm_phone(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def is_null(v) -> bool:
    return norm(v) == ""


def rid_sort_key(rid: str):
    return rid
