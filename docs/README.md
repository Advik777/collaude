# CollClaude

**Collaborative multi-agent Claude Code for development teams.**

Built by [Advik](https://github.com/Advik777).

---

## The problem

When a team uses Claude Code, every person's instance works in complete isolation. The frontend engineer's Claude has no idea what the backend engineer's Claude is building. You end up with APIs that don't match the UI, decisions made twice, and one person driving while everyone else watches.

CollClaude fixes this.

---

## What it does

CollClaude is a Claude skill. Install it, start a session, share a four-character code with your teammates. From that moment, every Claude Code instance on your team shares the same context — what each person is building, what decisions have been made, what's still open. Each agent works as if it's been briefed by every other agent on the team.

No new IDE. No new app. No new editor. It lives inside Claude and works alongside whatever editor you already use.

---

## How it works

```
/collaude start "payment-feature"
→ Session created. Share code: CCL-4829
```

```
/collaude join CCL-4829 https://abc123.ngrok.io
→ Joined. Sara's Claude is building the checkout flow.
```

From there, your agents coordinate automatically. The backend Claude knows what data shapes the frontend needs before a single API endpoint is written. Conflicts — two agents making incompatible decisions — are surfaced to both users before either proceeds.

---

## Features

- **Shared context store** — a live, persistent document all agents read from and write to. Survives session end so teams can resume across days.
- **Three sync modes** — real-time streaming for live awareness, checkpoints after each task, on-demand queries when an agent is blocked.
- **Structural pinning** — foundational decisions (auth strategy, API contracts, data shapes) stay in every agent's active context forever. Activity logs and in-progress notes age out naturally.
- **Rule-based conflict detection** — catches incompatible decisions before they become integration bugs.
- **Token-efficient** — delta broadcasting, role-scoped filtering, and lazy context injection keep overhead to ~200–400 tokens per turn during steady-state work.
- **Editor-agnostic** — works with VS Code, Cursor, Neovim, anything. It attaches to Claude, not to your editor.

---

## Installation

**Requirements:** Python 3.10+, Claude Code, Claude Pro / Max / Team / Enterprise with Code Execution enabled.

```bash
# Clone the repo
git clone https://github.com/Advik777/collaude
cd collaude

# Install broker dependencies
pip install -r requirements.txt

# Install the skill
cp -r skill ~/.claude/skills/collaude
```

---

## Starting a session

The person who starts the session hosts the broker. It starts automatically — no manual setup needed.

```bash
# In Claude Code
/collaude start "your-project-name"
```

CollClaude starts the broker on your machine and opens an ngrok tunnel automatically. You'll see a session code. Share it with your team.

---

## Joining a session

```bash
# In Claude Code
/collaude join CCL-XXXX https://abc123.ngrok.io
```

Your Claude Code connects to the host's broker using the ngrok URL, loads the shared context store, and your agent is briefed on everything the team has built and decided so far.

> **Note:** In v0.1, the host shares both the session code and the ngrok URL together. This is a known limitation — a rendezvous service that resolves codes to URLs automatically is planned before public release.

---

## Repo structure

```
collaude/
├── SKILL.md                  ← Claude skill definition
├── README.md                 ← this file
├── broker/
│   ├── broker.py             ← FastAPI + WebSocket server
│   ├── context_store.py      ← shared context + tiering logic
│   ├── conflict_detector.py  ← rule-based conflict detection
│   └── session_registry.py   ← session codes + participant management
└── requirements.txt
```

---

## Status

**v0.1 — Built, pre-release.** Core broker, context store, conflict detection, and skill are complete. Testing in progress before first release.

**Known v0.1 limitation:** joining a session requires both the session code and the host's ngrok URL. A rendezvous service that resolves codes to URLs automatically is planned before public release.

Follow this repo to get notified when v0.1 ships.

---

## Built for

- Hackathon teams who want everyone contributing from minute one
- Startup dev teams building fast with shared AI context
- Any team of 2–4 developers who want their Claude Code instances to actually work together

---

## License

MIT — free to use, modify, and distribute.

---

*CollClaude is an independent project by Advik, built on top of Claude Code and the Agent Skills open standard.*
