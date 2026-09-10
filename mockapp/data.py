"""Deterministic in-memory data for the mock credit-union admin app.

Everything is seeded from a fixed PRNG so a discovery run and every later replay
see identical records. No real PII -- names, SSNs and account numbers are all
synthetic and obviously fake.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

SEED = 20240907

_FIRST = ["Jordan", "Alex", "Sam", "Casey", "Morgan", "Riley", "Taylor", "Jamie",
          "Quinn", "Avery", "Devon", "Skyler"]
_LAST = ["Rivera", "Chen", "Okafor", "Nguyen", "Patel", "Johnson", "Kowalski",
         "Hernandez", "Muller", "Abbott", "Reyes", "Donovan"]


@dataclass
class Account:
    number: str          # full account number -- sensitive, never leaves the app raw
    kind: str            # "Savings" | "Checking" | "Money Market"
    balance: float       # dollars


@dataclass
class Member:
    member_id: str
    first: str
    last: str
    status: str          # "Active" | "Dormant"
    ssn: str             # synthetic -- sensitive
    restricted: bool     # True => back-office view is permission-denied
    accounts: list[Account] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


def _build() -> dict[str, Member]:
    rng = random.Random(SEED)
    members: dict[str, Member] = {}

    # A few pinned members the demo goals and tests reference by id.
    pinned = [
        ("100042", "Jordan", "Rivera", "Active", False),
        ("100777", "Alex", "Chen", "Active", False),
        ("100999", "Sam", "Okafor", "Active", True),   # restricted -> permission denied
        ("100500", "Casey", "Nguyen", "Dormant", False),
    ]
    for mid, first, last, status, restricted in pinned:
        members[mid] = Member(
            member_id=mid, first=first, last=last, status=status,
            ssn=f"{rng.randint(100, 899):03d}-{rng.randint(10, 99):02d}-{rng.randint(1000, 9999):04d}",
            restricted=restricted,
        )

    # Filler members so search returns realistic multi-row results.
    for i in range(8):
        mid = str(101000 + i * 37)
        members[mid] = Member(
            member_id=mid,
            first=rng.choice(_FIRST),
            last=rng.choice(_LAST),
            status=rng.choice(["Active", "Active", "Dormant"]),
            ssn=f"{rng.randint(100, 899):03d}-{rng.randint(10, 99):02d}-{rng.randint(1000, 9999):04d}",
            restricted=False,
        )

    for m in members.values():
        kinds = ["Savings", "Checking"]
        if rng.random() < 0.3:
            kinds.append("Money Market")
        for k in kinds:
            m.accounts.append(Account(
                number=_acct_number(m.member_id, k),
                kind=k,
                balance=round(rng.uniform(150, 18500), 2),
            ))

    # Pin Jordan Rivera's savings balance so the demo goal has a stable answer.
    for a in members["100042"].accounts:
        if a.kind == "Savings":
            a.balance = 4215.67

    return members


def _acct_number(member_id: str, kind: str) -> str:
    """Deterministic synthetic account number (no randomness)."""
    tag = {"Savings": "20", "Checking": "10", "Money Market": "30"}[kind]
    return f"{tag}-{member_id}-{sum(ord(c) for c in kind) % 97:02d}"


MEMBERS: dict[str, Member] = _build()


def search(query: str) -> list[Member]:
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    for m in MEMBERS.values():
        if q in m.member_id or q in m.name.lower() or q in m.last.lower():
            hits.append(m)
    return sorted(hits, key=lambda m: m.member_id)


def get(member_id: str) -> Member | None:
    return MEMBERS.get((member_id or "").strip())


def new_subaccount_number(member_id: str, kind: str) -> str:
    return _acct_number(member_id, kind)
