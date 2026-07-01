# CollClaude — Product Documentation
### Collaborative Multi-Agent Claude Skill for Development Teams

**Version:** 0.1 (Pre-build)
**Last updated:** June 2026
**Status:** Concept & Architecture
**Created by:** Advik

---

## 1. The Problem

Developers working in teams today face a fundamental AI collaboration gap. When a team uses Claude Code, each person's instance operates in complete isolation. The frontend engineer's Claude has no idea what the backend engineer's Claude is building. This leads to:

- APIs designed without knowing what data the UI actually needs
- Duplicated decisions made independently by each agent
- Conflicting implementations discovered only at integration time
- One person "driving" the AI while teammates watch passively

This was the founding insight: at a hackathon, one teammate did all the work inside their Claude Code while the other had nothing to contribute. The tool should not allow that to happen.

---

## 2. What CollClaude Is

CollClaude is a Claude skill — an installable extension to Claude Code that gives every team member's Claude agent a shared awareness of what the rest of the team is building.

It is not a new IDE. It is not a VS Code extension. It is not a standalone app. It lives inside Claude, works alongside whatever editor each person already uses, and requires no new software beyond the skill installation itself.

When a team installs CollClaude, their Claude Code instances form a session. Each agent continuously shares its working context — what it is building, what decisions it has made, what it still needs — into a shared context store that every other agent can read. The result is that each person's Claude Code behaves as if it has been briefed by every other Claude Code on the team.

---

## 3. Core Principles

**Editor-agnostic.** CollClaude attaches to Claude, not to any specific editor. A teammate using Vim and a teammate using Cursor can be in the same session.

**Zero friction to join.** Installing a skill in Claude takes under a minute. A team can be collaborating at a hackathon within two minutes of deciding to use the tool.

**Context, not code.** CollClaude does not sync files or provide real-time collaborative editing. Git handles files. CollClaude syncs intent, decisions, contracts, and understanding — the things git does not capture.

**Agents coordinate, humans decide.** Agents surface conflicts and suggestions to their own user. No agent makes a decision on behalf of another person's agent without that person being aware.

---

## 4. How It Works

### 4.1 Sessions

A CollClaude session is a named, shared workspace that up to four teammates can join. One person creates the session and shares a session code. Others join using that code. All agents in a session share the same context store.

Sessions are scoped to a project. Each session has a name, a list of participants, and a shared context store that persists for the duration of the session.

### 4.2 The Shared Context Store

The shared context store is the heart of CollClaude. It is a structured, living document that all agents read from and write to. It contains:

- **Role declarations** — what each agent is responsible for (e.g. "frontend", "backend", "infrastructure")
- **API contracts** — agreed-upon endpoint shapes, request/response schemas, and data types
- **Decisions log** — design choices that have been made, with reasoning, so no agent relitigates them
- **Open questions** — things one agent needs answered by another before it can proceed
- **Active work** — what each agent is currently building, updated continuously

The context store is not a chat. It is structured data that agents read and write programmatically as part of their normal operation.

### 4.3 Sync Modes

CollClaude syncs context in three ways simultaneously:

**Real-time streaming.** As an agent works, it continuously broadcasts lightweight intent signals — "I am building a user profile card that needs: name, avatar, last active timestamp." Other agents receive these signals and factor them into their own work without interrupting their user.

**Checkpoints.** When an agent completes a task, it writes a checkpoint to the shared context store — a structured summary of what was built, what interfaces it exposes, and what assumptions it made. Other agents read checkpoints to update their understanding of the overall system.

**On-demand queries.** When an agent is blocked — it needs to know something another agent owns — it queries the context store directly. If the answer is not there, it surfaces an open question that the relevant teammate's agent will see and respond to.

### 4.4 Conflict Detection

When two agents are about to make incompatible decisions — for example, one defines a user endpoint that returns a flat object while another is building a UI that expects a nested one — CollClaude detects the conflict and surfaces it to both users before either agent proceeds. Neither agent is blocked; both users are informed and can resolve it together.

### 4.5 The Context Broker

The context broker is the backend service that sits between all agent instances in a session. It receives context from each agent, merges updates into the shared store, detects conflicts, and delivers relevant updates to each agent. It is the only networked component of the system.

---

## 5. User Experience

### Starting a session

```
> /collaude start "payment-feature"
Session created: payment-feature
Share code: CCL-4829
Waiting for teammates...
```

### Joining a session

```
> /collaude join CCL-4829
Joined session: payment-feature
Team: @sara (frontend), @you (backend)
Shared context loaded. Sara's Claude is building the checkout flow.
```

### What agents see as they work

Each agent receives a continuously updated briefing from the shared context store. When Sara's Claude starts building a checkout form, your Claude Code automatically knows it will need to expose a POST /orders endpoint that accepts the fields Sara's form collects. It does not wait to be told.

### Open questions

When an agent cannot proceed without information from a teammate, it raises a question:

```
CollClaude: Sara's Claude needs to know —
  Does the order confirmation screen need the full product list,
  or just the order total and reference number?

Reply with: /collaude answer "just total and reference"
```

---

## 6. Architecture

### Tech Stack

**Language:** Python
**Framework:** FastAPI with WebSockets
**Tunneling:** ngrok (auto-started by the skill on session creation)
**Protocol:** WebSockets over HTTP — agents need a persistent two-way connection, not a request/response cycle. When Agent A updates context, Agent B receives it instantly without polling.

### Repository Structure

```
collaude/
├── SKILL.md                  ← Claude skill definition
├── README.md                 ← GitHub readme
├── broker/
│   ├── broker.py             ← FastAPI + WebSocket server
│   ├── context_store.py      ← shared context store + tiering logic
│   ├── conflict_detector.py  ← rule-based conflict detection
│   └── session_registry.py   ← session codes + participant management
└── requirements.txt          ← fastapi, uvicorn, websockets, ngrok
```

### How Sessions Work

The session code is the only thing a teammate ever sees. The hosting infrastructure is invisible to them.

**Host side — `/collaude start`:**
1. `broker.py` starts on the host's machine on localhost:8000
2. ngrok tunnel opens automatically, no manual setup required
3. A unique session code (e.g. CCL-4829) is generated and mapped to the ngrok URL in the session registry
4. The host shares the code with teammates

**Teammate side — `/collaude join CCL-4829`:**
1. The skill looks up CCL-4829 in the session registry
2. Resolves the code to the host's broker URL
3. Connects via WebSocket
4. Context store loads — the agent is immediately briefed on the session state

```
Host runs /collaude start "payment-feature"
    → broker.py starts on localhost:8000
    → ngrok tunnel opens automatically
    → CCL-4829 generated, mapped to ngrok URL
    → host shares CCL-4829

Teammate runs /collaude join CCL-4829
    → skill resolves CCL-4829 → broker URL
    → WebSocket connection established
    → context store loads
    → agent briefed and ready
```

### Components

**CollClaude Skill** — the installable Claude skill each team member adds to their Claude Code. Handles context broadcasting, store reads/writes, conflict surfacing, and the session join/leave flow.

**Context Broker** — a FastAPI + WebSocket server the session host runs locally. Manages sessions, merges context updates, runs conflict detection, and delivers updates to each connected agent. Auto-exposed via ngrok on session start.

**Shared Context Store** — a structured document maintained per session by the broker. Readable and writable by all agents in the session. Persists after the session ends. Organized into structural (pinned) and transient content tiers.

**Session Registry** — maps session codes to active broker URLs. Used only for joining; once connected, agents communicate directly through the broker.

### Data Flow

```
Agent A writes intent
    → Broker receives update
    → Broker merges into shared context store
    → Broker checks for conflicts with Agent B's context
    → If conflict: both agents are notified
    → If no conflict: Agent B receives lightweight delta update
    → Agent B's Claude factors update into its next action
```

### What the skill does NOT do

- It does not access or sync files
- It does not read or write to git
- It does not execute code on behalf of the user
- It does not allow one agent to send instructions to another agent's Claude
- It does not store conversation history

---

## 7. Team Size & Constraints

CollClaude is designed for teams of two to four. This is intentional.

At two people, the collaboration problem is acute and the solution is simple — two agents, one shared context. At four people, the context store remains manageable and conflict detection stays tractable. Beyond four, the number of potential conflicts grows combinatorially and the shared context becomes unwieldy. A future version may support larger teams with a hierarchical context model, but the first version is optimized for the team size that actually shows up at hackathons and early-stage startup sprints.

---

## 8. Use Cases

### Hackathon teams
Two to four people, six to forty-eight hours, building something from scratch. CollClaude lets everyone contribute through their own Claude Code from the first minute. Nobody watches while one person drives.

### Startup dev teams
Small teams working on ongoing codebases. CollClaude keeps agents aligned on evolving API contracts and architectural decisions without requiring constant Slack threads to update each other's context.

### Open source contributors
Async teams where two contributors may never be online at the same time. The shared context store acts as a persistent briefing document that each contributor's Claude reads before starting work, reducing the "I didn't know you'd already solved that" problem.

---

## 9. What Makes This Different

| | CollClaude | Pair programming tools (e.g. LiveShare) | Shared Claude project |
|---|---|---|---|
| Works across different editors | Yes | No (VS Code only) | Yes |
| Agents aware of each other's work | Yes | No | No |
| Conflict detection | Yes | No | No |
| Requires new app install | No | Yes | No |
| Designed for AI-to-AI coordination | Yes | No | No |
| Real-time collaborative editing | No | Yes | No |

CollClaude is not trying to be LiveShare. It is not about editing the same file together. It is about making sure every Claude agent on the team is working from the same understanding of what is being built.

---

## 10. Design Decisions

These decisions have been made and are considered final for v0.1.

**Context store format — Free-form text.** The shared context store uses free-form text that agents write naturally, without a strict schema. This makes it easier for agents to populate and read without needing to conform to rigid field definitions. The tradeoff is that conflict detection relies more on pattern matching than on structural comparison, which is acceptable given the rule-based detection approach below.

**Conflict detection — Rule-based.** CollClaude uses rule-based conflict detection for v0.1. This means defined rules that catch common, high-value conflicts — two agents defining the same API endpoint differently, two agents declaring ownership of the same module, two agents making contradictory assumptions about a data type. Rule-based detection is fast, predictable, and cheap. LLM-based detection may be introduced in a future version for catching subtler semantic conflicts.

**Persistence — Sessions persist after they end.** The context store is saved when a session closes and reloaded when the team resumes. This allows teams to work across multiple days without losing the decisions, contracts, and history built up in previous sessions. Sessions are identified by name and accessible only to the original participants.

**Context size limits — Tiered summarization with structural pinning.** The context store is managed across three tiers, with a pinning system that ensures foundational decisions never age out regardless of when they were made.

Content is first classified at write time as one of two types:

- **Structural** — decisions, API contracts, architectural choices, foundational agreements. These are pinned to the warm tier permanently and are never eligible for cold storage. They stay in every agent's active context for the entire lifetime of the session.
- **Transient** — activity logs, in-progress notes, resolved questions, moment-to-moment work updates. These age normally through the tiers and are eventually archived to cold storage.

The three tiers then operate as follows:

- **Hot tier** — the last 15–20 minutes of transient activity, stored in full detail. Always injected into agent context automatically.
- **Warm tier** — all structural content (pinned, permanent) plus older transient activity auto-summarized into compact bullet points. Injected as a summary alongside the hot tier.
- **Cold tier** — resolved transient content only, compressed into a single paragraph each. Never injected automatically; fetched on demand when an agent needs historical context.

This preserves the core promise of CollClaude — no agent ever loses sight of a decision that matters — while keeping token injection lean by aging out noise, not substance.

**Token optimization strategies.** Beyond tiering, CollClaude applies the following optimizations to minimize token overhead:

- **Delta broadcasting** — agents only receive changes since their last update, not the full store on every turn. Reduces shared context token usage by an estimated 60–70% during steady work periods.
- **Role-scoped relevance filtering** — the broker filters what each agent receives based on their declared role. The frontend agent does not receive backend infrastructure detail it doesn't need, and vice versa.
- **Lazy warm tier injection** — the warm tier summary is only re-injected when something in it has changed, or when an agent signals it is starting a new task. Mid-task turns do not trigger a full rebriefing.
- **Compressed intent signals** — real-time broadcasts are emitted as compact structured signals rather than prose, and expanded into full understanding only on the receiving agent's side when needed.
- **Checkpoint summarization** — at each checkpoint, a summarization pass collapses the preceding work period into its essential decisions and contracts before appending to the store, preventing linear growth.

Applied together, these bring per-agent per-turn token overhead from a baseline of 800–1,500 tokens down to an estimated 200–400 tokens during active steady-state work.

**Authentication.** Session codes are used for v0.1. This is simple and sufficient for hackathon and small team use. More robust authentication will be introduced before any public release targeting ongoing production teams.

**Skill distribution.** CollClaude will be published as a Claude skill under Advik's name. Distribution will follow Anthropic's skill publishing process as it matures. In the interim, the skill definition and broker server will be open-sourced on GitHub to establish authorship and allow early adoption.

---

## 11. Name

The product is named **CollClaude** — a contraction of Collaborative Claude. Created by Advik. The name works as both a product name and a CLI command prefix (e.g. `/collaude start`, `/collaude join`), and is distinct enough to be searchable and ownable.

---

## 12. Testing Strategy (To Be Done Later)

This section is intentionally deferred. Building comes first. Testing begins on Advik's command after the core skill and broker are built.

### What "working correctly" means for CollClaude

Before running any test, these are the three conditions that define a passing result:

- The backend Claude independently uses the correct field names and data shapes the frontend expects, without being told explicitly.
- No integration fixes are needed after both sides complete their work.
- Neither agent asks a question the shared context store should have already answered.

If all three hold across a real session, CollClaude works.

### Layer 1 — Unit testing the broker

Test the context broker in isolation as a standard backend. No Claude involved at this layer.

- Send a context update from Agent A and verify Agent B receives it correctly.
- Send two conflicting context entries and verify conflict detection fires and flags both agents.
- Simulate a session ending and verify the context store persists to disk.
- Simulate a session resuming and verify the store reloads and is readable by both agents.

Pass condition: all broker operations behave deterministically and correctly.

### Layer 2 — Testing the skill definition

Test whether the SKILL.md instructions make Claude behave as designed. This layer begins the moment both agents start working in a live session — not after.

Run two Claude Code instances side by side. One plays the frontend developer, one plays the backend developer. Give them a small real task — for example, "build a login form with a matching API endpoint." Run this twice: once with CollClaude installed, once without. The delta between those two runs is the proof of value.

Sequence within a session:
- **Join session** → confirms Layer 1 (broker live, skill loaded, both agents connected)
- **Agents start working** → Layer 2 begins, observe decisions in real time
- **Mid-task** → are agents making compatible decisions without being told to?
- **Task complete** → compare outputs, do the frontend and backend fit together without changes?

Pass condition: the three "working correctly" conditions above all hold.

### Layer 3 — Testing the pinning and tiering system

Test the context store's tiering and summarization logic in isolation. No Claude required at this layer.

- Write a simulation that generates synthetic context entries over time — a mix of structural and transient content.
- Run them through the tiering algorithm and verify structural content never ages out of the warm tier.
- Verify transient content ages out of the hot tier and into warm, then cold, on the correct schedule.
- Measure the token count of what gets injected into each agent's context at each simulated turn.

Pass condition: injected context stays within the 200–400 token target during steady-state work, and no structural content ever appears in the cold tier.

### Layer 4 — Real-world validation

The final and most important test. Run a real project — a small hackathon-style sprint — with CollClaude active. One person on frontend, one on backend.

Track the following across the session:
- Number of integration mismatches discovered at the end
- Number of times one agent asked for context it should have already had from the store
- Whether the session felt like genuine parallel collaboration or like one person still driving

Compare the same exercise run without CollClaude. The difference is the validation story.

Layer 4 is only run after Layers 1, 2, and 3 pass. If something breaks in a real session, a passing lower layer tells you exactly where to look.

---

## 13. Next Steps

1. ✅ Product documented, architecture designed, all decisions made.
2. ✅ Tech stack decided — Python, FastAPI, WebSockets, ngrok.
3. ✅ Build order defined — broker → context store → conflict detector → SKILL.md → README.
4. Create the GitHub repo under Advik's name.
5. Build Step 1: `broker.py` + `session_registry.py` — sessions work, agents can connect and join.
6. Build Step 2: `context_store.py` — agents can read and write context, tiering and pinning works.
7. Build Step 3: `conflict_detector.py` — rule-based conflict detection fires and surfaces to both agents.
8. Build Step 4: `SKILL.md` — Claude skill definition, written last so it accurately reflects the broker.
9. Run testing layers 1–4 on Advik's command.
