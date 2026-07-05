# CollClaude

**Collaborative multi-agent Claude Code for development teams.**

Built by [Advik](https://github.com/Advik777).

---

## The problem

Claude Code is a powerful tool for individual developers. But when a team uses it, each person's instance operates in complete isolation — and that isolation creates a category of bugs that no amount of individual skill prevents.

Consider a team of two. The backend developer asks their Claude Code to build a user endpoint. It returns `{ id, name, email }`. Meanwhile, the frontend developer asks their Claude Code to build the profile component. With no visibility into what the backend is doing, it builds against `{ userId, fullName, emailAddress }`. Both agents did exactly what they were asked. Both outputs are correct in isolation. The integration is broken.

This is not a workflow problem. It is a context problem. The result:

- **Schema mismatches** — agents independently define the same data structures differently, discovered only at integration time.
- **Duplicate decisions** — two agents relitigate the same architectural tradeoffs with no awareness of each other, and may land on different answers.
- **Silent incompatibility** — agents build toward the same goal along diverging paths, with no conflict surfaced until the work is done.

CollClaude solves this by giving every agent on the team a shared context — so no agent ever builds in ignorance of what the rest of the team has decided.

---

## What it does

CollClaude is a Claude skill — a folder you drop into `~/.claude/skills/` that gives your Claude Code new abilities. Once installed, it connects your agent to your teammates' agents through a shared context store. Every agent on the team knows what the others are building, what decisions have been made, and what's still open.

No new IDE. No new app. No new editor. Works alongside whatever editor you already use.

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

**Requirements:** Claude Code, Claude Pro / Max / Team / Enterprise with Code Execution enabled.

**Everyone on the team:**
```bash
# Copy the skill into your Claude skills folder
cp -r skill ~/.claude/skills/collaude
```

That's it. Claude Code picks it up automatically on the next session. No pip install, no setup, no configuration.

**Session host only** (the person who runs `/collaude start`):
```bash
pip install -r requirements.txt
```

The host needs the broker dependencies. Teammates who only join never touch this.

---

## Starting a session

The person starting the session runs:

```bash
/collaude start "your-project-name"
```

CollClaude starts the broker on your machine and opens an ngrok tunnel automatically. You'll get a session code and a URL — share both with your team.

---

## Joining a session

Everyone else runs one command in their Claude Code:

```bash
/collaude join CCL-XXXX https://abc123.ngrok.io
```

Your agent connects, loads the shared context, and is briefed on everything the team has built and decided so far. No broker to run, no dependencies to install.

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
