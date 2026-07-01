"""
CollClaude — Session Registry

Owns session codes and participant management (docs §6). A session is a named,
shared workspace that up to four teammates join with a CCL-XXXX code. The
registry maps codes to live sessions; once connected, agents talk to each other
through the broker, not the registry.

Persistence (docs §10 — sessions persist after they end) is deferred: the
context store owns saving/reloading state and will hook in during Step 2. The
registry keeps sessions in memory for now.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone

MAX_PARTICIPANTS = 4  # docs §7 — sessions are capped at four teammates

# WebSocket is only used as a type hint on Participant. Import lazily via
# typing to keep this module free of a hard FastAPI/starlette dependency.
from typing import TYPE_CHECKING, Any

try:  # support both package and script-style imports (see broker.py)
    from .context_store import ContextStore
except ImportError:  # pragma: no cover
    from context_store import ContextStore

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import WebSocket


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Participant:
    """One agent instance connected to a session."""

    agent_id: str
    role: str | None = None
    websocket: "WebSocket | None" = None


@dataclass
class Session:
    """A named shared workspace backed by a tiered, pinned ContextStore."""

    code: str
    name: str
    participants: dict[str, Participant] = field(default_factory=dict)
    store: ContextStore = field(default_factory=ContextStore)
    created_at: str = field(default_factory=_now)

    @property
    def is_full(self) -> bool:
        return len(self.participants) >= MAX_PARTICIPANTS

    def has_room_for(self, agent_id: str) -> bool:
        """A known agent reconnecting always has room; a new agent needs a free
        slot."""
        return agent_id in self.participants or not self.is_full

    def add_participant(self, participant: Participant) -> None:
        self.participants[participant.agent_id] = participant

    def remove_participant(self, agent_id: str) -> None:
        self.participants.pop(agent_id, None)

    def roster(self) -> list[dict[str, Any]]:
        return [
            {"agent_id": p.agent_id, "role": p.role}
            for p in self.participants.values()
        ]


class SessionRegistry:
    """Maps session codes to live sessions.

    KNOWN v0.1 LIMITATION — rendezvous gap: this registry is in-memory on the
    host and maps a code to a Session object, NOT to a broker URL reachable from
    other machines. There is no hosted service that turns a bare CCL-XXXX into
    the host's ngrok URL. v0.1 works around this with Option B — the host shares
    both the code and the ngrok URL, and `/collaude join <CODE> <NGROK_URL>`
    uses the URL directly (see SKILL.md). A real code→URL rendezvous MUST be
    built before any public release; do not paper over it with a fake endpoint.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def _generate_code(self) -> str:
        while True:
            code = "CCL-" + "".join(random.choices(string.digits, k=4))
            if code not in self._sessions:
                return code

    def create(self, name: str) -> Session:
        session = Session(code=self._generate_code(), name=name)
        self._sessions[session.code] = session
        return session

    def get(self, code: str) -> Session | None:
        return self._sessions.get(code)

    def exists(self, code: str) -> bool:
        return code in self._sessions

    def close(self, code: str) -> Session | None:
        """Remove a session from the live registry and return it. Persistence
        of its context store lands in Step 2."""
        return self._sessions.pop(code, None)
