"""
CollClaude — Conflict Detector

Rule-based detection of incompatible decisions between agents (docs §4.4, §10).
The context store holds free-form text, so detection is pattern matching, not
structural comparison — fast, predictable, and cheap. LLM-based semantic
detection may come in a future version.

v0.1 catches the three high-value conflicts named in docs §10:

    endpoint   two agents define the same METHOD /path with different shapes
    ownership  two agents both claim the same module
    datatype   two agents assert contradictory types for the same field

A conflict is only ever raised between two DIFFERENT agents (docs §4.4 —
"two agents about to make incompatible decisions"). Both users are informed;
neither agent is blocked.

Pure logic, no network dependency — unit-testable in isolation (docs §13, L1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover
    from context_store import Entry

# Recognised type words for the datatype rule. Kept to a closed set so the
# "<field> is a <type>" pattern doesn't fire on arbitrary prose.
_TYPES = {
    "string", "str", "text", "int", "integer", "number", "float", "double",
    "decimal", "bool", "boolean", "object", "array", "list", "uuid",
    "timestamp", "datetime", "date", "json", "flat", "nested", "null",
}

_ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}:.\-]*)", re.I)
_BRACE_RE = re.compile(r"\{([^{}]*)\}")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_TYPE_RE = re.compile(r"\b([A-Za-z_]\w*)\s+is\s+(?:an?\s+|the\s+)?([A-Za-z_]\w*)", re.I)
_OWNERSHIP_RE = re.compile(
    r"\b(?:I|we)\s+(?:own|am\s+owning|handle|will\s+handle)\s+(?:the\s+)?([\w/.\-]+)"
    r"|\bown(?:s|ing)?\s+(?:the\s+)?([\w/.\-]+)\s+module"
    r"|\bresponsible\s+for\s+(?:the\s+)?([\w/.\-]+)"
    r"|\bclaim(?:s|ing)?\s+(?:the\s+)?([\w/.\-]+)",
    re.I,
)


@dataclass
class Endpoint:
    method: str
    path: str
    fields: frozenset
    shape: str | None  # "flat" | "nested" | None


@dataclass
class Signals:
    endpoints: list[Endpoint] = field(default_factory=list)
    types: dict = field(default_factory=dict)  # field name -> set of type words
    modules: set = field(default_factory=set)


@dataclass
class Conflict:
    kind: str  # endpoint | ownership | datatype
    message: str
    agents: list
    entries: list  # the two entry ids involved

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "message": self.message,
            "agents": self.agents,
            "entries": self.entries,
        }


def _fields_from(text: str) -> frozenset:
    """Identifiers found inside any {...} group — the declared shape of a body
    or response."""
    found: set = set()
    for group in _BRACE_RE.findall(text):
        found.update(m.lower() for m in _IDENT_RE.findall(group))
    return frozenset(found)


def extract(text: str) -> Signals:
    """Pull structured signals out of one free-form context entry."""
    sig = Signals()
    text = text or ""

    fields = _fields_from(text)
    for method, path in _ENDPOINT_RE.findall(text):
        low = text.lower()
        shape = "nested" if "nested" in low else "flat" if "flat" in low else None
        sig.endpoints.append(
            Endpoint(
                method=method.upper(),
                path=path.rstrip("/").lower() or "/",
                fields=fields,
                shape=shape,
            )
        )

    for name, typ in _TYPE_RE.findall(text):
        t = typ.lower()
        if t in _TYPES:
            sig.types.setdefault(name.lower(), set()).add(t)

    for groups in _OWNERSHIP_RE.findall(text):
        for module in groups:
            if module:
                sig.modules.add(module.lower())

    return sig


class ConflictDetector:
    """Checks a newly written entry against prior entries from other agents."""

    def check(self, prior: Iterable, entry) -> list:
        """Return conflicts between `entry` and any `prior` entry authored by a
        different agent. `prior`/`entry` are context_store.Entry objects (or any
        object exposing .agent_id, .content, .id)."""
        new = extract(entry.content)
        conflicts: list = []
        for other in prior:
            if other.agent_id == entry.agent_id:
                continue  # a single agent can't conflict with itself
            old = extract(other.content)
            conflicts.extend(self._endpoints(new, old, entry, other))
            conflicts.extend(self._types(new, old, entry, other))
            conflicts.extend(self._modules(new, old, entry, other))
        return conflicts

    # -- individual rules --------------------------------------------------- #

    def _endpoints(self, new: Signals, old: Signals, entry, other) -> list:
        out: list = []
        for a in new.endpoints:
            for b in old.endpoints:
                if a.method != b.method or a.path != b.path:
                    continue
                shape_clash = a.shape and b.shape and a.shape != b.shape
                field_clash = a.fields and b.fields and a.fields != b.fields
                if shape_clash or field_clash:
                    if shape_clash:
                        detail = f"{other.agent_id} says {b.shape}, {entry.agent_id} says {a.shape}"
                    else:
                        only_new = ", ".join(sorted(a.fields - b.fields)) or "—"
                        only_old = ", ".join(sorted(b.fields - a.fields)) or "—"
                        detail = (
                            f"{entry.agent_id} adds [{only_new}]; "
                            f"{other.agent_id} adds [{only_old}]"
                        )
                    out.append(
                        Conflict(
                            kind="endpoint",
                            message=(
                                f"Endpoint {a.method} {a.path} defined "
                                f"differently — {detail}"
                            ),
                            agents=[other.agent_id, entry.agent_id],
                            entries=[other.id, entry.id],
                        )
                    )
        return out

    def _types(self, new: Signals, old: Signals, entry, other) -> list:
        out: list = []
        for name, new_types in new.types.items():
            old_types = old.types.get(name)
            if old_types and new_types.isdisjoint(old_types):
                out.append(
                    Conflict(
                        kind="datatype",
                        message=(
                            f"Field '{name}' typed differently — "
                            f"{other.agent_id}: {'/'.join(sorted(old_types))}, "
                            f"{entry.agent_id}: {'/'.join(sorted(new_types))}"
                        ),
                        agents=[other.agent_id, entry.agent_id],
                        entries=[other.id, entry.id],
                    )
                )
        return out

    def _modules(self, new: Signals, old: Signals, entry, other) -> list:
        shared = new.modules & old.modules
        return [
            Conflict(
                kind="ownership",
                message=(
                    f"Module '{module}' claimed by both "
                    f"{other.agent_id} and {entry.agent_id}"
                ),
                agents=[other.agent_id, entry.agent_id],
                entries=[other.id, entry.id],
            )
            for module in sorted(shared)
        ]
