"""
CollClaude — Layer 3 tiering & pinning tests (docs §12, Layer 3).

"Test the context store's tiering and summarization logic in isolation. No
Claude required at this layer." These tests drive the *real* ContextStore
through a synthetic working session and assert its tiering guarantees.

Pass condition (docs §12):
  - Injected context stays within the 200–400 token target during steady-state
    work, and
  - no structural content ever appears in the cold tier.

Everything is deterministic. Time is pinned exactly as in the Layer 1 tests: a
fixed base epoch (FIXED_TS) plus an explicit `now=` on every tiering call. The
real clock is never read, and no server is started.

The four Layer 3 obligations, mapped to tests below:
  1. Synthetic entries over simulated time, realistic structural/transient mix
     -> build_session()
  2. Run through the tiering algorithm with pinned time values
     -> every test passes now=at(minute)
  3a. Structural never in cold tier at any point   -> test_structural_never_cold
  3b. Transient ages hot -> warm -> cold on schedule -> test_transient_ages_on_schedule
  3c. Structural never pruned or summarized away   -> test_structural_never_pruned
  4. token_estimate within 200–400 during steady state -> test_steady_state_token_budget
"""

import pytest

from context_store import (
    COLD_AFTER_MINUTES,
    HOT_WINDOW_MINUTES,
    STRUCTURAL,
    TRANSIENT,
    ContextStore,
)

# Fixed epoch so tiering is deterministic regardless of wall-clock time
# (identical convention to test_layer1.FIXED_TS).
FIXED_TS = 1_700_000_000.0


def at(minute: float) -> float:
    """Absolute epoch for `minute` minutes into the simulated session."""
    return FIXED_TS + minute * 60.0


# --------------------------------------------------------------------------- #
# Synthetic session — a realistic mix over ~2 hours of simulated work.
# --------------------------------------------------------------------------- #
#
# Structural (pinned, permanent): the decisions and API contracts a teammate
# must never relitigate. Kept < 160 chars each so the warm-tier condenser
# reproduces them verbatim (lets us prove nothing is "summarized away").
STRUCTURAL_EVENTS = [
    (2, "backend", "Decision: auth uses JWT HS256 bearer tokens, access TTL 3600s."),
    (5, "backend", "API contract: POST /auth/login {email,password} -> {access_token, token_type, expires_in}."),
    (8, "backend", "API contract: GET /auth/me with Authorization: Bearer <token> -> {id, email}."),
    (12, "frontend", "Ownership: frontend owns frontend/ login UI; backend owns app/ auth router."),
    (15, "backend", "Data shape: User = {id: str, email: str}; email unique; password min 8 chars."),
]

# Transient activity signals, emitted on a steady cadence. Compact intent
# signals (docs §10), one per tick. Every 4th tick is a *resolved* question,
# which drops straight to cold (an answered open question).
TRANSIENT_TICK_MINUTES = 6
TRANSIENT_TEMPLATES = [
    ("frontend", "Scaffolding the login form component in frontend/Login.tsx."),
    ("backend", "Wiring the POST /auth/login handler in app/auth.py."),
    ("backend", "Added PBKDF2-HMAC password hashing in app/security.py."),
    ("frontend", "Styling the login form and inline error states."),
    ("backend", "Implemented JWT encode/decode with expiry check."),
    ("frontend", "Hooked the submit button to the login endpoint."),
    ("backend", "In-memory user store with unique-email guard done."),
    ("frontend", "Added client-side email + min-8 password validation."),
]
RESOLVED_QUESTION = (
    "frontend",
    "Q: send token in body or header? -> Resolved: Authorization: Bearer header.",
)

SESSION_END_MINUTE = 120


def build_session():
    """Create a ContextStore populated over simulated time and return
    (store, structural_ids, transient_ids). Insertion is chronological so entry
    ids increase with time, mirroring a live session."""
    store = ContextStore()
    structural_ids: list[int] = []
    transient_ids: list[int] = []

    # Merge structural + transient events and apply them in time order so the
    # store is built exactly as a real session would accrue it.
    events = []
    for minute, role, content in STRUCTURAL_EVENTS:
        events.append((minute, role, content, STRUCTURAL, False))

    tick_index = 0
    for minute in range(0, SESSION_END_MINUTE + 1, TRANSIENT_TICK_MINUTES):
        if tick_index % 4 == 3:
            role, content = RESOLVED_QUESTION
            events.append((minute, role, content, TRANSIENT, True))
        else:
            role, content = TRANSIENT_TEMPLATES[tick_index % len(TRANSIENT_TEMPLATES)]
            events.append((minute, role, content, TRANSIENT, False))
        tick_index += 1

    events.sort(key=lambda e: e[0])

    for minute, role, content, kind, resolved in events:
        entry = store.add(
            agent_id=role,
            content=content,
            role=role,
            kind=kind,
            now=at(minute),
        )
        if kind == STRUCTURAL:
            structural_ids.append(entry.id)
        else:
            transient_ids.append(entry.id)
            if resolved:
                store.resolve(entry.id)

    return store, structural_ids, transient_ids


# Turns sampled across the whole session (for tier-invariant checks) and the
# steady-state window (for the token budget). Steady state begins once the
# oldest transient has started aging into cold — i.e. now >= COLD_AFTER_MINUTES
# — so the hot/warm bands are fully populated and stable.
ALL_TURNS = list(range(0, SESSION_END_MINUTE + 1, TRANSIENT_TICK_MINUTES))
STEADY_STATE_TURNS = [m for m in ALL_TURNS if m >= COLD_AFTER_MINUTES]


# --------------------------------------------------------------------------- #
# 3a. Structural content never appears in the cold tier — at ANY point.
# --------------------------------------------------------------------------- #

def test_structural_never_cold():
    store, structural_ids, _ = build_session()
    structural_ids = set(structural_ids)

    # Probe the whole timeline plus far past the session end, to prove pins
    # never age out no matter how much time passes.
    probes = ALL_TURNS + [SESSION_END_MINUTE + 60, SESSION_END_MINUTE + 10_000]

    for minute in probes:
        now = at(minute)
        cold_ids = {e.id for e in store.cold(now)}
        assert not (structural_ids & cold_ids), (
            f"structural content in cold tier at minute {minute}: "
            f"{structural_ids & cold_ids}"
        )
        # And positively: every structural entry is in the warm tier.
        for e in store.since(0):
            if e.id in structural_ids:
                assert e.tier(now) == "warm", (
                    f"structural entry {e.id} not warm at minute {minute} "
                    f"(was {e.tier(now)})"
                )


# --------------------------------------------------------------------------- #
# 3b. Transient content ages hot -> warm -> cold on the correct schedule.
# --------------------------------------------------------------------------- #

def test_schedule_constants_match_docs():
    # Docs §10: hot window is the last 15–20 minutes; cold after ~60.
    assert HOT_WINDOW_MINUTES == 20
    assert COLD_AFTER_MINUTES == 60


def test_transient_ages_on_schedule():
    store = ContextStore()
    e = store.add("backend", "Working on the login endpoint.", role="backend",
                  kind=TRANSIENT, now=at(0))

    # Boundaries taken straight from the schedule constants so the test tracks
    # the algorithm rather than hard-coded magic numbers.
    hot_edge = HOT_WINDOW_MINUTES        # 20: still hot (age <= window)
    warm_start = HOT_WINDOW_MINUTES + 1  # 21: now warm
    warm_edge = COLD_AFTER_MINUTES - 1   # 59: last warm minute
    cold_start = COLD_AFTER_MINUTES      # 60: now cold

    assert e.tier(at(0)) == "hot"
    assert e.tier(at(10)) == "hot"
    assert e.tier(at(hot_edge)) == "hot", "age == hot window must still be hot"
    assert e.tier(at(warm_start)) == "warm", "just past hot window must be warm"
    assert e.tier(at(warm_edge)) == "warm", "just before cold cutoff must be warm"
    assert e.tier(at(cold_start)) == "cold", "at cold cutoff must be cold"
    assert e.tier(at(90)) == "cold"

    # The transitions must show up in inject(): hot entry is a full hot record;
    # warm entry becomes a summarized activity bullet; cold entry drops out.
    assert any(h["id"] == e.id for h in store.inject(now=at(10))["hot"])
    warm_view = store.inject(now=at(30))
    assert not any(h["id"] == e.id for h in warm_view["hot"])
    assert any("login endpoint" in b for b in warm_view["warm"])
    cold_view = store.inject(now=at(90))
    assert not any(h["id"] == e.id for h in cold_view["hot"])
    assert not any("login endpoint" in b for b in cold_view["warm"])


def test_resolved_transient_drops_to_cold_immediately():
    store = ContextStore()
    e = store.add("frontend", "Q: token in header or body?", role="frontend",
                  kind=TRANSIENT, now=at(0))
    assert e.tier(at(1)) == "hot"          # unresolved & fresh -> hot
    store.resolve(e.id)
    assert e.tier(at(1)) == "cold", "an answered question must go cold at once"


# --------------------------------------------------------------------------- #
# 3c. No structural content is ever pruned or summarized away.
# --------------------------------------------------------------------------- #

def test_structural_never_pruned():
    store, structural_ids, _ = build_session()
    expected = {e.id: e.content for e in store.since(0) if e.id in set(structural_ids)}
    n_structural = len(expected)

    for minute in ALL_TURNS + [SESSION_END_MINUTE + 10_000]:
        now = at(minute)
        view = store.inject(now=now)

        # Every pinned decision is present in the warm tier as a [pinned: ...]
        # bullet — none dropped.
        pinned_bullets = [b for b in view["warm"] if b.startswith("- [pinned:")]
        assert len(pinned_bullets) == n_structural, (
            f"expected {n_structural} pinned bullets at minute {minute}, "
            f"got {len(pinned_bullets)}"
        )

        # And each structural entry's content survives verbatim — not truncated
        # or summarized away (content is < 160 chars, the condense limit).
        blob = "\n".join(view["warm"])
        for eid, content in expected.items():
            assert content in blob, (
                f"structural entry {eid} was summarized away at minute {minute}: "
                f"{content!r} not found in warm tier"
            )


# --------------------------------------------------------------------------- #
# 4. token_estimate stays within the 200–400 target during steady-state work.
# --------------------------------------------------------------------------- #

def test_steady_state_token_budget(capsys):
    store, _, _ = build_session()

    estimates = {}
    for minute in STEADY_STATE_TURNS:
        est = store.inject(now=at(minute))["token_estimate"]
        estimates[minute] = est

    lo, hi = min(estimates.values()), max(estimates.values())

    # Emit the observed range so a run with -s reports it unambiguously.
    with capsys.disabled():
        print(
            f"\n[Layer 3] steady-state token_estimate over turns "
            f"{STEADY_STATE_TURNS[0]}–{STEADY_STATE_TURNS[-1]} min: "
            f"min={lo}, max={hi} (target 200–400)"
        )
        for minute in STEADY_STATE_TURNS:
            print(f"    turn @ {minute:>3} min -> {estimates[minute]} tokens")

    assert estimates, "no steady-state turns were measured"
    for minute, est in estimates.items():
        assert 200 <= est <= 400, (
            f"token_estimate {est} at minute {minute} outside 200–400 target"
        )


if __name__ == "__main__":  # allow `python test_layer3.py` as a smoke run
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
