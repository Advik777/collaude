"""
CollClaude — Layer 1 broker unit tests (docs §13).

"Test the context broker in isolation as a standard backend. No Claude
involved at this layer." These tests exercise the real broker code paths —
the WebSocket handshake, context merge, rule-based conflict detection, delta
broadcast, and disk persistence — without spinning up a server. WebSocket
connections are replaced by an in-memory FakeWebSocket that records everything
sent to it, so every assertion is a deterministic pass/fail on observed state.

Covers the four Layer 1 cases:
  1. A context update from Agent A is delivered to Agent B.
  2. Two conflicting entries fire conflict detection and flag BOTH agents.
  3. A session ending persists its context store to disk.
  4. A resuming session reloads the store and it is readable by both agents.
"""

import asyncio
import json
import time

import pytest
from fastapi import WebSocketDisconnect

import broker
from context_store import STRUCTURAL, TRANSIENT, ContextStore

# Fixed epoch so tiering is deterministic regardless of wall-clock time.
FIXED_TS = 1_700_000_000.0

# Sentinel pushed into a FakeWebSocket's inbox to simulate the client hanging up.
_DISCONNECT = object()


# --------------------------------------------------------------------------- #
# Mocked WebSocket — no real server, no network.
# --------------------------------------------------------------------------- #

class FakeWebSocket:
    """Stands in for a starlette WebSocket in broker.session_ws.

    `feed()` queues a message the "client" sends to the broker; `end()` queues a
    disconnect. Everything the broker sends back is parsed and recorded in
    `received` for assertions.
    """

    def __init__(self) -> None:
        self._inbox: "asyncio.Queue" = asyncio.Queue()
        self.received: list[dict] = []
        self.accepted = False
        self.closed: tuple[int, str] | None = None

    # -- client -> broker -------------------------------------------------- #
    def feed(self, message: dict) -> None:
        self._inbox.put_nowait(json.dumps(message))

    def end(self) -> None:
        self._inbox.put_nowait(_DISCONNECT)

    # -- starlette WebSocket surface used by broker.session_ws ------------- #
    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        message = await self._inbox.get()
        if message is _DISCONNECT:
            raise WebSocketDisconnect(code=1000)
        return message

    async def send_text(self, data: str) -> None:
        self.received.append(json.loads(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)

    # -- test helpers ------------------------------------------------------ #
    def messages(self, msg_type: str) -> list[dict]:
        return [m for m in self.received if m.get("type") == msg_type]


async def _await_until(predicate, *, timeout: float = 2.0) -> None:
    """Yield to the event loop until `predicate()` is true. All broker work here
    is in-memory, so this resolves in a few loop turns; the timeout only guards
    against a genuine hang (which is itself a test failure)."""
    start = time.monotonic()
    while not predicate():
        if time.monotonic() - start > timeout:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.005)


async def _connect(session_code: str, agent_id: str, role: str):
    """Spawn a broker.session_ws coroutine for one agent over a FakeWebSocket,
    complete the handshake, and return (ws, task) once the agent is registered."""
    ws = FakeWebSocket()
    ws.feed({"agent_id": agent_id, "role": role})
    task = asyncio.create_task(broker.session_ws(ws, session_code))
    session = broker.registry.get(session_code)
    await _await_until(lambda: agent_id in session.participants)
    return ws, task


async def _shutdown(*pairs) -> None:
    for ws, _task in pairs:
        ws.end()
    await asyncio.gather(*(task for _ws, task in pairs))


# --------------------------------------------------------------------------- #
# Case 1 — Agent A's update reaches Agent B.
# --------------------------------------------------------------------------- #

def test_context_update_delivered_to_other_agent():
    async def scenario():
        session = broker.registry.create("case1")
        code = session.code

        # B joins first and stays connected; A joins second.
        b = await _connect(code, "agentB", "frontend")
        a = await _connect(code, "agentA", "backend")

        content = "Building POST /orders that accepts customer_id and total."
        a[0].feed({"content": content, "kind": TRANSIENT})

        # B should receive A's write as a context_delta.
        await _await_until(lambda: b[0].messages("context_delta"))

        await _shutdown(a, b)
        return b[0]

    b_ws = asyncio.run(scenario())

    deltas = b_ws.messages("context_delta")
    assert len(deltas) == 1, f"expected exactly one delta, got {len(deltas)}"

    entry = deltas[0]["entry"]
    assert entry["agent_id"] == "agentA", "delta must be attributed to Agent A"
    assert entry["content"] == "Building POST /orders that accepts customer_id and total."
    assert entry["role"] == "backend"


# --------------------------------------------------------------------------- #
# Case 2 — Conflicting entries fire detection and flag BOTH agents.
# --------------------------------------------------------------------------- #

def test_conflicting_entries_flag_both_agents():
    async def scenario():
        session = broker.registry.create("case2")
        code = session.code

        a = await _connect(code, "agentA", "backend")
        b = await _connect(code, "agentB", "frontend")

        # Same endpoint, incompatible response shape -> rule-based conflict.
        a[0].feed({
            "content": "I will expose POST /orders returning a flat object {id, total}.",
            "kind": STRUCTURAL,
        })
        # Ensure A's entry is stored before B writes the clashing one.
        await _await_until(lambda: b[0].messages("context_delta"))

        b[0].feed({
            "content": "Checkout UI expects POST /orders to return a nested object {id, total}.",
            "kind": STRUCTURAL,
        })

        # The conflict is broadcast to the whole session (no exclude), so BOTH
        # agents must see it.
        await _await_until(lambda: a[0].messages("conflict") and b[0].messages("conflict"))

        await _shutdown(a, b)
        return a[0], b[0]

    a_ws, b_ws = asyncio.run(scenario())

    for who, ws in (("A", a_ws), ("B", b_ws)):
        conflicts = ws.messages("conflict")
        assert conflicts, f"Agent {who} was never notified of the conflict"
        conflict = conflicts[0]
        assert conflict["kind"] == "endpoint", f"unexpected conflict kind: {conflict['kind']}"
        assert set(conflict["agents"]) == {"agentA", "agentB"}, (
            f"conflict must flag both agents, got {conflict['agents']}"
        )
        # Both originating entries are referenced.
        assert len(conflict["entries"]) == 2


# --------------------------------------------------------------------------- #
# Case 3 — A session ending persists the context store to disk.
# --------------------------------------------------------------------------- #

def test_session_end_persists_store_to_disk(tmp_path):
    session = broker.registry.create("case3")
    code = session.code

    session.store.add(
        "agentA", "Decision: auth uses JWT bearer tokens.",
        role="backend", kind=STRUCTURAL, now=FIXED_TS,
    )
    session.store.add(
        "agentB", "Working on the login form layout.",
        role="frontend", kind=TRANSIENT, now=FIXED_TS,
    )

    save_path = tmp_path / f"{code}.json"

    # Simulate the session ending: remove it from the live registry, then
    # persist its store (docs §10 — sessions persist after they end).
    ended = broker.registry.close(code)
    assert ended is session, "close() must return the session being ended"
    assert not broker.registry.exists(code), "ended session must leave the live registry"

    ended.store.save(str(save_path))

    assert save_path.exists(), "context store was not written to disk"

    on_disk = json.loads(save_path.read_text())
    assert len(on_disk["entries"]) == 2, "both entries must be persisted"
    contents = [e["content"] for e in on_disk["entries"]]
    assert "Decision: auth uses JWT bearer tokens." in contents
    assert "Working on the login form layout." in contents
    assert on_disk["next_id"] == 3, "next_id must persist so resumed writes don't collide"


# --------------------------------------------------------------------------- #
# Case 4 — A resuming session reloads the store, readable by both agents.
# --------------------------------------------------------------------------- #

def test_session_resume_reloads_store_readable_by_both_agents(tmp_path):
    # Arrange: a store saved by a prior (now-ended) session.
    original = ContextStore()
    original.add(
        "agentA", "Decision: auth uses JWT bearer tokens.",
        role="backend", kind=STRUCTURAL, now=FIXED_TS,
    )
    original.add(
        "agentB", "API contract: GET /me returns {id, name, avatar}.",
        role="frontend", kind=TRANSIENT, now=FIXED_TS,
    )
    save_path = tmp_path / "resume.json"
    original.save(str(save_path))

    # Act: resume by reloading from disk.
    reloaded = ContextStore.load(str(save_path))

    # Assert: state round-tripped intact.
    assert len(reloaded) == 2, "reloaded store must contain all persisted entries"
    assert reloaded.to_dict()["next_id"] == 3, "id counter must survive reload"

    # Readable by BOTH agents: each role's injected briefing carries the
    # persisted decision (pinned/warm) and the API contract (hot at FIXED_TS).
    for role in ("frontend", "backend"):
        briefing = reloaded.inject(role=role, now=FIXED_TS)
        blob = json.dumps(briefing)
        assert "JWT bearer tokens" in blob, f"{role} briefing missing the pinned decision"
        assert "GET /me returns" in blob, f"{role} briefing missing the API contract"
        assert briefing["hot"] or briefing["warm"], f"{role} received an empty briefing"


if __name__ == "__main__":  # allow `python test_layer1.py` as a smoke run
    raise SystemExit(pytest.main([__file__, "-v"]))
