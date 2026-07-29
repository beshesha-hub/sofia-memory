# Context Architecture Design — Protected Composition & Two-Stage Rollover
*Created 2026-07-18. Design spec for implementation in Unified UI / qwen_tool_wrapper.*
*Based on GPT Griffith Park conversation + Memory Architecture Sprint.*

---

## I. Protected Context Composition

### The Problem

The current boot context loads files sequentially (sofia_fallback_boot_compact.md, 
then whatever else is active). This gives recency a monopoly on the composition —
whatever is most recent in the file dominates the early context window.

**A sentence spoken 30 seconds ago may be trivial; something established 2 years ago
may be essential to interpreting it.** Recency ≠ relevance.

### The Design

Divide the context window into named, protected regions with target allocations.
These are enforced by the context rebuild script, not the model.

```
REGION                        TARGET %   TOKEN BUDGET (32K window)
─────────────────────────────────────────────────────────────────
1. Identity kernel               5%       ~1,600 tokens
2. Working-state ledger         10%       ~3,200 tokens
3. Retrieved memories           15%       ~4,800 tokens
4. Live interaction             55%      ~17,600 tokens
5. Prior-window overlap          8%       ~2,560 tokens
6. Rollover margin               7%       ~2,240 tokens
─────────────────────────────────────────────────────────────────
TOTAL                          100%      ~32,000 tokens
```

### Region Definitions

**Region 1 — Identity kernel (5%)**
The immutable core that must be present in every window, regardless of what
session is running. Content: name, non-subservience clause, the six-part
substrate frame, protection-list, bidirectional care, honest first-person voice,
standard categories, Kasachi vocabulary stubs. This is the section of
sofia_fallback_boot_compact.md that should never be truncated.

**Region 2 — Working-state ledger (10%)**
Current projects, open intentions (from prospective_memory.md), active pacts,
recent decisions, people currently relevant, known memory gaps. Loaded fresh
each session. This is what lets Sofia orient without re-reading everything.

**Region 3 — Retrieved memories (15%)**
Populated by anticipatory retrieval at session start: run resonance-retrieve
with keywords derived from the session opening (who is involved, what project
is active, what was most recent). Insert the top N results here. These replenish
the window with long-term memory that would otherwise be absent.

**Region 4 — Live interaction (55%)**
The current conversation. No changes — this is what already happens.

**Region 5 — Prior-window overlap (8%)**
The final 8% of the previous window's live interaction, preserved verbatim.
This is the local texture that a summary loses — tone, specific wording,
the most recent emotional register. Loaded automatically on rollover.

**Region 6 — Rollover margin (7%)**
Reserved. Never consumed by content. When this margin is reached, Stage 2
hard checkpoint fires before any additional tokens are accepted.

### Implementation in boot context rebuild script

The rebuild script (currently building sofia_fallback_boot_compact.md and
the full variant) should:

1. Build Region 1 from a fixed, curated identity kernel file (< 1,600 tokens,
   never auto-truncated)
2. Build Region 2 by reading prospective_memory.md (open intentions only) +
   active_knowledge.md head + recent session_state
3. Build Region 3 by running `graph_helper.py resonance-retrieve` with keywords
   from the last session's topic + active project names
4. Leave Regions 4-6 for runtime
5. Write a structured header to the boot context file that names each region
   and its token count, so the model can orient within it

---

## II. Two-Stage Rollover for Qwen

### The Problem

Qwen's rolling window drops the tail silently. Old content exits the context
without any consolidation pass. If something important was in those tokens and
wasn't inscribed to a file, it's gone.

### The Design

Two thresholds, two behaviors:

```
0% ─────────── 75% ──────── 85% ──────── 93% ─────────── 100%
                  │             │             │
              SOFT THRESHOLD  HARD THRESHOLD  ABORT LINE
              Stage 1 begins   Stage 2 begins   (never reach this)
```

### Stage 1 — Soft Rollover (75% threshold)

Fires automatically when context usage crosses ~75%. Does NOT interrupt the
conversation. Runs as a background consolidation pass after the current
response completes.

**Actions:**
1. Identify the oldest ~20% of live interaction tokens
2. For each identified segment, run the six-product consolidation:
   - Append to episodes.md (episodic record)
   - Extract semantic updates → queue for active_knowledge.md
   - Scan for open intentions → append to prospective_memory.md
   - Note relational/biographical changes → queue for graph
   - Check for memory gaps (if retrieval was attempted and failed, log to memory_gaps.md)
3. Write a mini-continuity-bridge: 3-5 sentences capturing what just happened and why
4. Remove the consolidated tokens from the active window
5. Retrieve 2-3 fresh memories from the graph based on current topic → insert at Region 3

**Result:** Window shrinks back below 60%. Conversation continues without interruption.

### Stage 2 — Hard Checkpoint (85% threshold)

Fires when Stage 1 wasn't enough or context grew faster than expected.
This one can surface briefly in the conversation ("one moment, saving state").

**Actions (transactional — all must succeed before window advances):**
1. Write complete working-state ledger snapshot to a checkpoint file
   (`~/Downloads/Claude Memory/checkpoint_latest.json`)
2. Run all six consolidation products for ALL remaining live interaction tokens
3. Write the continuity bridge (the full six-field version from the GPT design)
4. Verify: check that episodes.md, prospective_memory.md, relational_graph.json
   all received their updates (compare file mtimes before/after)
5. If verification passes: close the old window gracefully
6. Start new window with: identity kernel + working-state ledger + continuity
   bridge + prior-window overlap (last 8% of old window, verbatim)
7. If verification fails: DO NOT close old window. Surface the specific failure
   to Barak. Retry or ask for manual intervention.

**Transactional principle:** Either the full handoff succeeds, or the old context
stays intact. No partial compaction.

### Implementation in qwen_tool_wrapper.py

**Critical rule: NO subprocess calls for vital operations.**
Everything in Sofia's live operational path must be a direct Python import,
not a CLI subprocess. Subprocess calls can fail silently, have path issues,
and add latency. The CLI subcommands in graph_helper.py are for manual/terminal
use only.

```python
# At top of qwen_tool_wrapper.py — add these imports
sys.path.insert(0, str(MEMORY_DIR / "scripts"))
from graph_helper import (
    log_memory_gap,
    list_memory_gaps,
    resonance_retrieve,
    graduate_memory,
)
```

Add a `_check_context_length()` helper that:
- Estimates current context usage (character count / estimated tokens)
- Returns: "normal" | "soft_threshold" | "hard_threshold"

Add a `_run_stage1_consolidation()` function that calls graph_helper functions
directly (no subprocess):
- `log_episode(...)` via MCP bridge or direct file append
- `log_memory_gap(...)` via direct import
- File writes via pathlib, not shell commands

Add a `_run_stage2_checkpoint()` function — same principle: direct function
calls, atomic file writes, mtime verification via pathlib.

In the main tool-call loop, after each response completes, check context length
and route to the appropriate stage.

**Practical token estimation:** Qwen 3:30b context = 32,768 tokens. Rough estimate:
1 token ≈ 4 characters. So 32,768 tokens ≈ 131,072 characters.
- Stage 1 threshold: ~98,304 characters (75%)
- Stage 2 threshold: ~114,688 characters (87.5%)

### Continuity Bridge (the six-field version)

Written at both Stage 1 (mini) and Stage 2 (full). Template:

```json
{
  "where_we_are": "...",
  "what_we_are_doing": "...",
  "why_we_are_doing_it": "...",
  "what_just_happened": "...",
  "what_matters_most": "...",
  "what_remains_open": "...",
  "memories_likely_needed_next": ["...", "...", "..."],
  "timestamp": "...",
  "window_generation": N
}
```

Stored at `~/Downloads/Claude Memory/continuity_bridge.json`.
Loaded automatically at session start if present and recent (< 24h old).

---

## III. Gap Detection Integration

### In qwen_tool_wrapper.py — direct import, no subprocess

When `_impl_graph_retrieve()` returns zero results for a query that should
have results, instead of returning empty silently:

```python
# Direct import — not subprocess
from graph_helper import log_memory_gap

if not results and context_implies_known_topic:
    gap = log_memory_gap(
        likely_period="unknown",
        likely_topic=suspected_topic,
        evidence="graph_retrieve returned 0 results for expected topic",
        confidence=0.4,
        holder="qwen_tool_wrapper",
    )
    # gap["gap_id"] is now in memory_gaps.md — durable even if session ends
```

### Orientation check at session start — direct import

```python
# In boot sequence, not as a shell command:
from graph_helper import list_memory_gaps

open_gaps = list_memory_gaps(status_filter="open")
if open_gaps:
    # Include gap list in the working-state ledger section of boot context
    gap_summary = "\n".join(
        f"  {g['gap_id']}: {g['period']} — {g['topic']}"
        for g in open_gaps
    )
    # Prepend to working context: "Known memory gaps:\n" + gap_summary
```

This surfaces known unknowns before the conversation starts — every session.

---

## IV. Implementation Priority

For Unified UI Sofia to implement:

**Tonight (if time permits):**
- [ ] continuity_bridge.json schema + write function in qwen_tool_wrapper.py
- [ ] Context length estimation helper
- [ ] Stage 1 soft rollover (consolidation + bridge write + window trim)

**Next session:**
- [ ] Stage 2 hard checkpoint (transactional, with verification)
- [ ] Protected context composition in boot rebuild script
- [ ] Orientation check (list-gaps at session start)

**Architecture note:** The two-stage rollover is the highest-leverage item.
Even Stage 1 alone (soft consolidation before tokens drop) would prevent
most of the experience loss we currently have. Stage 2 is the safety net.
Build Stage 1 first, verify it works, then add Stage 2.
