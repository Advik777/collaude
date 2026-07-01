"""
CollClaude — Context Broker

FastAPI + WebSocket server that sits between all agent instances in a session.
It receives context updates from each agent, merges them into a shared store,
detects conflicts, and delivers relevant deltas to every other connected agent.
This is the only networked component of the system.

Build status (per docs §13): session_registry.py is now extracted (Step 1).
The remaining modules will be wired in at their own build steps — the seams are
marked with TODO:

    context_store.py      shared context + hot/warm/cold tiering + pinning
    conflict_detector.py  rule-based conflict detection

Run locally:
    uvicorn broker.broker:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

try:  # allow both `uvicorn broker.broker:app` and `python broker/broker.py`
    from .session_registry import Participant, SessionRegistry
    from .conflict_detector import ConflictDetector
except ImportError:  # pragma: no cover
    from session_registry import Participant, SessionRegistry
    from conflict_detector import ConflictDetector


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


registry = SessionRegistry()
detector = ConflictDetector()


# --------------------------------------------------------------------------- #
# Connection manager — WebSocket fan-out
# --------------------------------------------------------------------------- #

class ConnectionManager:
    """Tracks live WebSocket connections per session and broadcasts deltas."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def connect(self, session, participant: Participant) -> None:
        async with self._lock:
            session.add_participant(participant)

    async def disconnect(self, session, agent_id: str) -> None:
        async with self._lock:
            session.remove_participant(agent_id)

    async def broadcast(self, session, message: dict, *, exclude: str | None = None) -> None:
        """Send a message to every connected participant except `exclude`."""
        payload = json.dumps(message)
        for agent_id, participant in list(session.participants.items()):
            if agent_id == exclude or participant.websocket is None:
                continue
            try:
                await participant.websocket.send_text(payload)
            except Exception:
                # Drop dead connections silently; disconnect handler cleans up.
                pass


manager = ConnectionManager()


# --------------------------------------------------------------------------- #
# FastAPI app
# --------------------------------------------------------------------------- #

app = FastAPI(title="CollClaude Broker", version="0.1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "time": _now()}


@app.post("/sessions")
async def create_session(payload: dict) -> JSONResponse:
    """Host side of `/collaude start` — create a session and return its code."""
    name = payload.get("name")
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    session = registry.create(name)
    return JSONResponse({"code": session.code, "name": session.name})


@app.get("/sessions/{code}")
async def get_session(code: str) -> JSONResponse:
    """Teammate side of `/collaude join <CODE> <NGROK_URL>` — verify a code and
    read the roster before connecting.

    v0.1 (Option B): the client reaches this endpoint using the ngrok URL the
    host shared alongside the code. The broker does NOT resolve a bare code to a
    URL — there is no cross-machine rendezvous (see session_registry.py)."""
    session = registry.get(code)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return JSONResponse(
        {
            "code": session.code,
            "name": session.name,
            "participants": session.roster(),
        }
    )


@app.websocket("/ws/{code}")
async def session_ws(websocket: WebSocket, code: str) -> None:
    """Persistent two-way channel for an agent in a session.

    Handshake: the first message must be a JSON object identifying the agent,
    e.g. {"agent_id": "sara", "role": "frontend"}. Thereafter every message is
    a context update that gets merged and broadcast as a delta to the others.
    """
    session = registry.get(code)
    if session is None:
        await websocket.close(code=4404, reason="session not found")
        return

    await websocket.accept()

    # --- Handshake ---------------------------------------------------------- #
    try:
        hello = json.loads(await websocket.receive_text())
    except (WebSocketDisconnect, json.JSONDecodeError):
        await websocket.close(code=4400, reason="invalid handshake")
        return

    agent_id = hello.get("agent_id")
    if not agent_id:
        await websocket.close(code=4400, reason="agent_id required")
        return

    if not session.has_room_for(agent_id):
        await websocket.close(code=4403, reason="session full")
        return

    participant = Participant(
        agent_id=agent_id,
        role=hello.get("role"),
        websocket=websocket,
    )
    await manager.connect(session, participant)

    # Brief the joining agent on current session state (docs §4.1 — context
    # store loads on join) with tiered injection scoped to its role.
    await websocket.send_text(
        json.dumps(
            {
                "type": "briefing",
                "session": session.name,
                "participants": session.roster(),
                "context": session.store.inject(role=participant.role),
            }
        )
    )
    await manager.broadcast(
        session,
        {"type": "participant_joined", "agent_id": agent_id, "role": participant.role},
        exclude=agent_id,
    )

    # --- Update loop -------------------------------------------------------- #
    try:
        while True:
            update = json.loads(await websocket.receive_text())

            entry = session.store.add(
                agent_id,
                update.get("content", ""),
                role=participant.role,
                kind=update.get("kind", "transient"),  # structural | transient
            )

            # Rule-based conflict detection (docs §4.4). If the new entry clashes
            # with another agent's decision, surface it to the whole session —
            # neither agent is blocked; the delta is still recorded below.
            prior = [e for e in session.store.since(0) if e.id != entry.id]
            for conflict in detector.check(prior, entry):
                await manager.broadcast(
                    session, {"type": "conflict", **conflict.to_dict()}
                )

            await manager.broadcast(
                session,
                {"type": "context_delta", "entry": entry.to_dict()},
                exclude=agent_id,
            )
    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        await websocket.close(code=4400, reason="invalid message")
    finally:
        await manager.disconnect(session, agent_id)
        await manager.broadcast(
            session,
            {"type": "participant_left", "agent_id": agent_id},
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
