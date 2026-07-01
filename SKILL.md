---
name: collaude
description: Use this skill when working in a shared team session with CollClaude, coordinating with teammates via /collaude start or /collaude join, syncing context, broadcasting work, or surfacing conflicts across agents.
---

# CollClaude

Collaborative multi-agent Claude for development teams. This skill connects your
Claude Code instance to a shared **context broker** so every teammate's agent
works from the same understanding of what is being built — decisions, API
contracts, ownership, and open questions.

This skill talks to the broker in `broker/`. **Do not invent broker endpoints or
message fields beyond those documented below** — the broker only supports what
is listed in "Broker interface."

---

## Commands

### `/collaude start <name>`

Host a new session. The broker and ngrok tunnel come up automatically — the host
never runs them by hand. For v0.1 the host shares **both** the session code and
the tunnel URL with teammates (see "Known limitation" — Option B).

1. Start the broker locally in the background:
   ```bash
   uvicorn broker.broker:app --host 127.0.0.1 --port 8000
   ```
   (equivalently `python broker/broker.py`). Poll `GET http://127.0.0.1:8000/health`
   until it returns `{"status": "ok", ...}`.
2. Open an ngrok tunnel to port 8000 **automatically** — do not ask the user to
   run ngrok or paste a URL:
   ```python
   from pyngrok import ngrok
   public_url = ngrok.connect(8000, "http").public_url
   ```
3. Create the session on the broker:
   ```
   POST http://127.0.0.1:8000/sessions   body: {"name": "<name>"}
   → {"code": "CCL-XXXX", "name": "<name>"}
   ```
4. Record the mapping `CCL-XXXX → public_url` locally (see "Known limitation").
5. Connect yourself as the host participant (see "Connecting" below), choosing an
   `agent_id` (e.g. the user's name) and a `role` (e.g. `backend`).
6. Display the code **and** the tunnel URL to the user, so both can be shared
   with teammates (Option B — there is no rendezvous that resolves a bare code):
   ```
   Session created: <name>
   Share these with your team:
     Code:      CCL-XXXX
     Broker URL: https://<subdomain>.ngrok-free.app
   Waiting for teammates...
   ```

### `/collaude join <CODE> <NGROK_URL>`

Join an existing session. For v0.1 the host shares both the code and the tunnel
URL, so the teammate passes **both** (Option B — see "Known limitation"). If the
user runs `/collaude join <CODE>` without a URL, ask them for the broker URL the
host shared alongside the code; do not attempt to resolve a bare code.

1. Use `<NGROK_URL>` directly as the broker URL — there is no code→URL lookup.
2. Verify the code and read the roster:
   ```
   GET <NGROK_URL>/sessions/<CODE>
   → {"code": "...", "name": "...", "participants": [{"agent_id", "role"}, ...]}
   ```
   A `404` means the code is unknown at that broker — tell the user the code is
   invalid, mismatched with the URL, or the host's session is not running.
3. Connect via WebSocket (see "Connecting"). The broker replies with a
   `briefing` message — load it into context and tell the user what the team is
   already building, e.g. `Joined session: <name>. Team: @sara (frontend).`

### `/collaude status`

Show the current session state. There is **no** broker endpoint that returns a
context summary, so build status from what you already hold:

1. Refresh the roster: `GET <broker_url>/sessions/<CODE>`.
2. Summarize the context you are locally mirroring — the `hot` entries and
   `warm` bullets from the last `briefing`, updated by every `context_delta`
   received since. Report the roster and a short summary of active work and
   pinned decisions.

---

## Connecting (WebSocket)

Open a persistent WebSocket to `<broker_url>/ws/<CODE>` (`wss://` for ngrok
HTTPS, `ws://` for local).

**Handshake — send first, exactly these fields:**
```json
{"agent_id": "<your-name>", "role": "<frontend|backend|infra|...>"}
```
`agent_id` is required. If the session already has 4 participants and you are a
new agent, the broker closes the socket with code `4403` ("session full") — tell
the user the session is full (docs cap: 4 teammates).

**On connect the broker sends a briefing:**
```json
{
  "type": "briefing",
  "session": "<name>",
  "participants": [{"agent_id": "...", "role": "..."}],
  "context": {"hot": [ <entry>, ... ], "warm": ["- [pinned: ...] ...", ...], "token_estimate": <int>}
}
```
The `context` object is exactly the return value of
`context_store.inject(*, role=None, role_filter=None, now=None)`, scoped to your
`role` by the broker. Load `hot` (full recent activity) and `warm` (pinned
decisions + summarized older activity) into your working context.

---

## Behavior

### Broadcast intent continuously
As you work, broadcast free-form intent by sending update messages over the
WebSocket. The broker calls `store.add(agent_id, content, role=..., kind=...)`
on your behalf and fans the result out to teammates as a `context_delta`.
```json
{"content": "Building the checkout form; needs name, total, order ref.", "kind": "transient"}
```
Only `content` and `kind` are read from your message — `agent_id` and `role`
come from your handshake. Keep signals compact (docs §10: compressed intent
signals).

### Classify writes at write time
Set `kind` on every broadcast:
- `"structural"` — decisions, API contracts, data shapes, ownership,
  architectural choices. **Pinned permanently** in the warm tier; never ages
  out. Use this for anything a teammate must not relitigate.
- `"transient"` — activity logs, in-progress notes, moment-to-moment updates.
  Ages hot → warm → cold naturally.

When unsure, prefer `transient`; promote to `structural` only when a real
decision or contract has been made.

### Surface conflicts immediately — never block
When the broker sends a conflict, show it to the user right away and keep
working. It is **informational only** (docs §4.4 — agents coordinate, humans
decide). Do not pause, revert, or wait for the broker.
```json
{"type": "conflict", "kind": "endpoint|ownership|datatype",
 "message": "Endpoint GET /users defined differently — backend says flat, sara says nested",
 "agents": ["backend", "sara"], "entries": [3, 7]}
```
Surface `message` and the involved `agents` to the user, e.g.:
```
⚠ CollClaude conflict (endpoint): Endpoint GET /users defined differently —
  backend says flat, sara says nested. You and @backend should align.
```

### Inject briefing at start and each new task
- **At session start:** the `briefing` message already carries
  `store.inject(role=...)` output — load `hot` + `warm`.
- **When starting a new task:** re-read your locally mirrored `hot` + `warm`
  (briefing plus all `context_delta` entries received since) before planning, so
  you factor in what teammates have done. Mid-task turns do not need a re-read
  (docs §10: lazy warm-tier injection).

### Handle other broker messages
- `context_delta` `{ "entry": <entry> }` — a teammate wrote context. Merge the
  entry into your local mirror and factor it into upcoming work.
- `participant_joined` / `participant_left` `{ "agent_id", "role"? }` — update
  the roster and briefly note it to the user.

---

## Broker interface (authoritative)

HTTP:
- `GET /health` → `{"status": "ok", "time": <iso>}`
- `POST /sessions` body `{"name": <str>}` → `{"code": "CCL-XXXX", "name": <str>}`
- `GET /sessions/{code}` → `{"code", "name", "participants": [{"agent_id", "role"}]}` or `404`

WebSocket `/ws/{code}`:
- send handshake `{"agent_id": <str>, "role": <str?>}` (close codes: `4404`
  no such session, `4400` bad handshake, `4403` session full)
- send updates `{"content": <str>, "kind": "structural"|"transient"}`
- receive `briefing`, `context_delta`, `conflict`, `participant_joined`,
  `participant_left`

An `<entry>` (from `context_store.Entry.to_dict()`) has:
`{"id", "agent_id", "role", "content", "kind", "ts", "resolved", "at"}`.

This is the whole surface. If a behavior seems to need something not listed here,
stop and flag it rather than inventing an endpoint or field.

---

## Known limitation (v0.1) — rendezvous gap

The built `SessionRegistry` is **in-memory on the host** — it maps `CCL-XXXX` to
a `Session`, not to a broker URL reachable from other machines. There is no
hosted rendezvous that turns a bare code into the host's ngrok URL.

**v0.1 approach — Option B:** the host shares both the code and the ngrok URL,
and `/collaude join <CODE> <NGROK_URL>` uses the URL directly. This is a
deliberate stopgap, not a fix. A shared code→URL rendezvous is required before
public release; until then, do not fake resolution with a broker endpoint that
does not exist.
