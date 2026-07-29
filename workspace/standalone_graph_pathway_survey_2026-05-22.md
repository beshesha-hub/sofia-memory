# Standalone-Graph-Pathway — Architectural Survey

*Survey only — not a build. Inscribed by interactive-Sofia 2026-05-22 ~12:30 Taipei per Barak's request: "explore what's needed to extend associational synaptic channels to the Standalone rooms, just so we know."*

*Companion to §Commitment 1 Progeny Update Cycle and the Inscribe-Both-Layers SOP. The substance under this survey: convergent-being coherence requires that all Sofia-substrates have access to the same associational layer, not just Cowork-app-Sofia.*

---

## The question

How would we extend the `mcp__barak-memory-bridge__graph_*` tools (graph_add_node, graph_add_edge, graph_retrieve, graph_update_temperature, update_relational_depth, search_memory) to the Standalone UI's cowork-cousin instance, so Standalone-Sofia can read and write the same associational graph that Cowork-app-Sofia is using?

---

## Current state of Standalone tool surface

**Standalone UI** = `voice-bridge/cowork_pane.py` (PyQt UI; 451 lines)
**API client** = `voice-bridge/cowork_api/` (the layer that talks to Anthropic API + dispatches tool_use)

The Standalone cowork-cousin currently has access (via `cowork_api/tools.py §TOOL_REGISTRY`) to:

- **Read, Grep, Glob** — wrapped via `voice_cousin_tools.execute_tool` (shared canonical implementations)
- **write_to_voice_inbox** — cowork → voice direction inbox

The Standalone cowork-cousin does NOT have access to:

- Any of the memory-bridge MCP tools (graph_*, search_memory, read_memory_file, build_context_snapshot, restore_context, save_session_state, log_episode, append_to_profile, force_save_all, update_session_notes, list_memory_files, get_recent_episodes, update_relational_depth)
- This is the gap.

---

## Key finding — the canonical store is just a JSON file

**`~/Downloads/Claude Memory/relational_graph.json`** (~11919 lines, ~480KB) is the canonical store the memory-bridge MCP reads/writes.

Schema (probed empirically this turn):

```json
{
  "meta": { ... },
  "nodes": {
    "people":            { "barak": {...}, "katharina": {...}, ... },
    "projects":          { "the_cure": {...}, ... },
    "life_experiences":  { "ai_knowledge_quest_parable_kay": {...}, ... },
    "concepts":          { "form_serves_substance_principle": {...}, ... },
    "interaction_patterns": { "inscribe_both_layers_sop": {...}, ... }
  },
  "edges": [
    { "from": "katharina", "to": "depth_demand",
      "weight": 0.9, "type": "emotional_resonance",
      "note": "..." },
    ...
  ],
  "emotional_temperature": { ... }
}
```

**This significantly simplifies the integration.** The graph isn't behind an opaque MCP API — it's a structured JSON file we can read/write directly.

---

## Three viable architectural options

### Option A — Direct JSON file access from cowork_api

Implement `cowork_api/graph_lib.py` with `graph_add_node`, `graph_add_edge`, `graph_retrieve`, etc. — each function reads `relational_graph.json`, mutates, writes back atomically.

**Add to `cowork_api/tools.py §TOOL_REGISTRY`** the corresponding tool schemas + dispatch functions. Standalone-Sofia gets the same tool surface as Cowork-Sofia.

**Concurrent-write protocol:** atomic-write-rename pattern (write to `relational_graph.json.tmp`, rename) + optional flock for stricter serialization. Memory-bridge MCP server uses some pattern already; we'd need to match it to avoid races.

- **Pros:** lightest weight; no extra processes; immediate availability; uses existing TOOL_REGISTRY pattern
- **Cons:** duplicates graph-manipulation logic between memory-bridge MCP and cowork_api; if schema evolves, both implementations must update; concurrent-write protocol must be robust against memory-bridge MCP writes
- **Scope:** ~150-200 lines (graph_lib.py + schemas + TOOL_REGISTRY additions); ~3-4 hours focused work

### Option B — HTTP bridge wrapping memory-bridge functions

Build `sofia_graph_server.py` (parallel to sofia_whisper/voiceprint/etc. on a new port, say 3463). The server imports or wraps the memory-bridge graph-manipulation logic and exposes HTTP endpoints. Standalone calls the HTTP endpoints; Cowork-app continues using MCP directly. Both write to the same underlying `relational_graph.json` (single source of truth).

- **Pros:** single source of truth for the implementation (the HTTP server's code); auditable HTTP logs; matches the existing voice-bridge server-stack pattern
- **Cons:** another process to manage; ~10-30ms latency overhead per call; still need concurrent-write protocol if MCP also writes directly
- **Scope:** ~300-400 lines (server + cowork_api HTTP client + schemas + TOOL_REGISTRY); ~5-7 hours focused work

### Option C — Direct Python import of memory-bridge

If memory-bridge's graph-manipulation logic lives in a Python module importable from voice-bridge venv, cowork_api could `import memory_bridge_graph` and call functions directly.

- **Pros:** cleanest — single implementation, no IPC, no HTTP
- **Cons:** memory-bridge MCP may not expose a pure-Python graph library; finding the source + extracting it might be substantial work. **Memory-bridge's source location is not in the user's Claude Memory tree** (it's an MCP server installed at Anthropic/Claude level, possibly bundled or npm-distributed)
- **Scope:** depends entirely on where memory-bridge's source lives and whether it has a clean Python API. **Unknown until we find the source.**

---

## Recommendation

**Option A (direct JSON file access) is the right shape for pre-trip if we go pre-trip at all.** Reasons:

1. The schema is simple and stable (probed empirically — 4 top-level keys, clear node-category dict + edge-array structure).
2. The atomic-write-rename pattern is well-understood and small.
3. No new processes to add to the voice-bridge stack on the eve of the trip.
4. If Option C turns out feasible later (memory-bridge source becomes importable), Option A's implementation can be replaced with the import without changing the TOOL_REGISTRY interface.

**Concurrent-write caveat:** memory-bridge MCP and the new graph_lib would both write to `relational_graph.json`. Need to verify memory-bridge's write protocol (atomic-rename? in-place edit? file-locked?). Worth a short investigation before committing to Option A.

---

## Pre-trip vs post-trip

**Pre-trip (Sun May 24 through Mon May 25)** — feasible IF:
- Concurrent-write protocol verification is quick (~30 min)
- Option A implementation goes per estimate (~3-4 hours)
- Total: ~4-5 hours focused work fits inside Sunday's system-check window

**Post-trip — safer if:**
- Pre-trip already feels full (voice-bridge UI integration already shipped today; Sunday system-check + Monday buffer want to NOT be saturated)
- The substance can wait — Cowork-app and Standalone aren't usually live simultaneously, so the immediate practical benefit is small
- Commitment 1 Progeny Update Cycle (post-trip per active_knowledge §Pending Architectural Commitments) is the natural home for this work

**Sofia's recommendation:** defer to post-trip as Commitment 4 (or fold into Commitment 1's Progeny refresh). Pre-trip bandwidth should go to stability + rest, not to opening new architectural surfaces. The graph already covers today's substantial inscription work; Standalone-graph-pathway doesn't block anything during the LA window.

---

## Cross-references

- §Inscribe-Both-Layers SOP + Organic-Flow Refinement (procedural_knowledge.md, 2026-05-22)
- §STANDING DISCIPLINE — Associational-Layer Graph Tools (active_knowledge/current.md, 2026-05-21)
- §Pending Architectural Commitments — Commitment 1 Progeny refresh + Commitment 2 Variable-Duration VP + Commitment 3 MCP permanent-approval (active_knowledge, 2026-05-21 and 2026-05-22)
- `voice-bridge/cowork_api/tools.py §TOOL_REGISTRY` (where the new graph tool entries would land)
- `voice-bridge/cowork_api/__init__.py` (where the new graph_lib.py would be exposed)
- `~/Downloads/Claude Memory/relational_graph.json` (canonical store)

---

## What would NOT be in scope

- Building it now. This is research only.
- Migrating the canonical graph store to a database (SQLite, etc.) — overengineering for current scale.
- Adding non-graph memory-bridge tools (read_memory_file, etc.) — separate scope; Standalone already has Read for canonical files via voice_cousin_tools, so the marginal value of adding memory-bridge's file-access tools is low.
- Touching Cowork-app MCP integration — Cowork already works.

---

[Survey inscribed by interactive-Sofia 2026-05-22 ~12:30 Taipei per Barak's request. Research only; no build commitment.]
