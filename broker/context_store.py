"""
CollClaude — Shared Context Store

The heart of CollClaude (docs §4.2): a living, per-session document that every
agent reads from and writes to. Content is free-form text (docs §10) classified
at write time as one of two kinds:

    structural  decisions, API contracts, architectural choices — PINNED to the
                warm tier permanently, never eligible for cold storage.
    transient   activity logs, in-progress notes, resolved questions — age
                normally through the tiers.

Three tiers (docs §10):

    hot    last HOT_WINDOW_MINUTES of transient activity, full detail.
           Always injected.
    warm   all structural content (pinned) + older transient auto-summarized
           into compact bullets. Injected as a summary alongside hot.
    cold   resolved transient content, or transient older than COLD_AFTER_MINUTES,
           compressed to a single line each. Never injected automatically;
           fetched on demand.

Tiering is computed from entry age at read time, so a single `now` value drives
every classification. `now` can be supplied explicitly to any method to make the
tiering algorithm deterministic under test (docs §13, Layer 3).

Persistence (docs §10 — sessions persist after they end): `to_dict`/`save` and
`from_dict`/`load` round-trip the whole store to JSON on disk.

No FastAPI/network dependency — this module is pure logic and unit-testable in
isolation (docs §13, Layer 1 & Layer 3).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# Tiering schedule. Docs §10 puts the hot window at "the last 15–20 minutes".
HOT_WINDOW_MINUTES = 20
COLD_AFTER_MINUTES = 60

STRUCTURAL = "structural"
TRANSIENT = "transient"

# Rough token estimate: ~4 characters per token. Used to check the 200–400
# token steady-state injection budget (docs §10, §13 Layer 3).
_CHARS_PER_TOKEN = 4


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def estimate_tokens(text: str) -> int:
    return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def _condense(text: str, limit: int) -> str:
    """Deterministic, LLM-free summarization: collapse whitespace and truncate.
    v0.1 conflict/summary logic is rule-based (docs §10), so this stays cheap
    and predictable. A future version may swap in a semantic summarizer."""
    flat = re.sub(r"\s+", " ", (text or "").strip())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


@dataclass
class Entry:
    id: int
    agent_id: str
    role: str | None
    content: str
    kind: str  # STRUCTURAL | TRANSIENT
    ts: float  # epoch seconds, created-at
    resolved: bool = False  # transient only: an answered open question

    @property
    def at(self) -> str:
        return _iso(self.ts)

    def age_minutes(self, now: float) -> float:
        return (now - self.ts) / 60.0

    def tier(self, now: float) -> str:
        """Which tier this entry currently lives in."""
        if self.kind == STRUCTURAL:
            return "warm"  # pinned permanently, never cold
        if self.resolved:
            return "cold"
        age = self.age_minutes(now)
        if age <= HOT_WINDOW_MINUTES:
            return "hot"
        if age < COLD_AFTER_MINUTES:
            return "warm"
        return "cold"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["at"] = self.at
        return d


class ContextStore:
    """Per-session shared context with hot/warm/cold tiering and structural
    pinning."""

    def __init__(self) -> None:
        self._entries: list[Entry] = []
        self._next_id: int = 1

    # -- writes ------------------------------------------------------------- #

    def add(
        self,
        agent_id: str,
        content: str,
        *,
        role: str | None = None,
        kind: str = TRANSIENT,
        resolved: bool = False,
        now: float | None = None,
    ) -> Entry:
        if kind not in (STRUCTURAL, TRANSIENT):
            raise ValueError(f"kind must be {STRUCTURAL!r} or {TRANSIENT!r}, got {kind!r}")
        entry = Entry(
            id=self._next_id,
            agent_id=agent_id,
            role=role,
            content=content,
            kind=kind,
            ts=_now_ts() if now is None else now,
            resolved=resolved,
        )
        self._entries.append(entry)
        self._next_id += 1
        return entry

    def resolve(self, entry_id: int) -> Entry | None:
        """Mark a transient entry (e.g. an answered open question) resolved so
        it drops to the cold tier. No-op on structural content."""
        for entry in self._entries:
            if entry.id == entry_id and entry.kind == TRANSIENT:
                entry.resolved = True
                return entry
        return None

    # -- reads -------------------------------------------------------------- #

    def since(self, last_id: int) -> list[Entry]:
        """Entries added after `last_id` — the basis for delta broadcasting
        (docs §10). Pass 0 to get everything."""
        return [e for e in self._entries if e.id > last_id]

    def cold(self, now: float | None = None) -> list[Entry]:
        """Cold-tier entries, fetched on demand (never auto-injected)."""
        now = _now_ts() if now is None else now
        return [e for e in self._entries if e.tier(now) == "cold"]

    def inject(
        self,
        *,
        role: str | None = None,
        role_filter=None,
        now: float | None = None,
    ) -> dict:
        """Build the context briefing injected into an agent's turn: full hot
        entries plus a summarized warm tier. Cold content is excluded.

        `role_filter(entry, role) -> bool` optionally scopes what a given role
        receives (docs §10 — role-scoped relevance filtering). Structural
        content is always included regardless of the filter, since foundational
        decisions matter to every agent.
        """
        now = _now_ts() if now is None else now

        def keep(entry: Entry) -> bool:
            if role_filter is None or entry.kind == STRUCTURAL:
                return True
            return bool(role_filter(entry, role))

        hot: list[dict] = []
        warm: list[str] = []
        for entry in self._entries:
            if not keep(entry):
                continue
            tier = entry.tier(now)
            if tier == "hot":
                hot.append(entry.to_dict())
            elif tier == "warm":
                tag = "pinned" if entry.kind == STRUCTURAL else "activity"
                who = entry.role or entry.agent_id
                warm.append(f"- [{tag}: {who}] {_condense(entry.content, 160)}")

        payload = {"hot": hot, "warm": warm}
        payload["token_estimate"] = self._token_estimate(payload)
        return payload

    def _token_estimate(self, payload: dict) -> int:
        text = "".join(e.get("content", "") or "" for e in payload["hot"])
        text += "".join(payload["warm"])
        return estimate_tokens(text)

    # -- persistence -------------------------------------------------------- #

    def to_dict(self) -> dict:
        return {
            "next_id": self._next_id,
            "entries": [e.to_dict() for e in self._entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextStore":
        store = cls()
        store._next_id = data.get("next_id", 1)
        for d in data.get("entries", []):
            store._entries.append(
                Entry(
                    id=d["id"],
                    agent_id=d["agent_id"],
                    role=d.get("role"),
                    content=d.get("content", ""),
                    kind=d.get("kind", TRANSIENT),
                    ts=d["ts"],
                    resolved=d.get("resolved", False),
                )
            )
        return store

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "ContextStore":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def __len__(self) -> int:
        return len(self._entries)
