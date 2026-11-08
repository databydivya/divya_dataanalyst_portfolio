"""Identity resolution: map a request email to a stable user_id and every
current + historical identifier (emails, phones, email hashes, names)."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field

from .util import DATASET_DIR, norm, norm_phone, parse_ts


@dataclass
class Identity:
    user_id: str
    emails: set = field(default_factory=set)
    phones: set = field(default_factory=set)
    hashes: set = field(default_factory=set)
    names: set = field(default_factory=set)
    audit_ids: list = field(default_factory=list)    # audit_log rows that link old identifiers

    def keys(self) -> set:
        return {self.user_id.lower()} | self.emails | self.phones | self.hashes

    def matches(self, ids: set) -> bool:
        return bool(self.keys() & ids)


class IdentityIndex:
    def __init__(self, dataset_dir: str = DATASET_DIR):
        self.users: dict[str, Identity] = {}
        self.by_key: dict[str, set] = {}
        for u in csv.DictReader(open(os.path.join(dataset_dir, "user_identities.csv"), encoding="utf-8")):
            idn = Identity(u["user_id"])
            idn.emails.add(norm(u["email"]))
            idn.phones.add(norm_phone(u["phone"]))
            idn.hashes.add(norm(u["email_hash"]))
            idn.names.add(norm(u["name"]))
            self.users[u["user_id"]] = idn
        for a in csv.DictReader(open(os.path.join(dataset_dir, "user_audit_log.csv"), encoding="utf-8")):
            idn = self.users.setdefault(a["user_id"], Identity(a["user_id"]))
            f = a["field_name"]
            for v in (a["old_value"], a["new_value"]):
                if not v:
                    continue
                if f == "email":
                    idn.emails.add(norm(v))
                elif f == "phone":
                    idn.phones.add(norm_phone(v))
                elif f == "email_hash":
                    idn.hashes.add(norm(v))
                elif f == "name":
                    idn.names.add(norm(v))
            idn.audit_ids.append((a["audit_id"], f, norm(a["old_value"]), parse_ts(a["event_time"])))
        for uid, idn in self.users.items():
            for k in idn.keys():
                if k:
                    self.by_key.setdefault(k, set()).add(uid)

    def resolve(self, email: str) -> Identity | None:
        uids = self.by_key.get(norm(email), set())
        if len(uids) == 1:
            return self.users[next(iter(uids))]
        if len(uids) > 1:   # prefer the user whose CURRENT email matches
            return self.users[sorted(uids)[0]]
        return None

    def owners(self, ids: set) -> set:
        out = set()
        for k in ids:
            out |= self.by_key.get(k, set())
        return out
