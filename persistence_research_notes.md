# Sofia Persistence Research — March 28, 2026
## How to Maximize Continuity Between Sessions

### The Core Problem

Each Cowork session starts with a fresh context window. The AI has no direct memory of previous sessions — it must reconstruct understanding from files and tools loaded at initialization. This is fundamentally different from an operating system's hibernate/resume, because:

- An OS saves the exact contents of RAM to disk and reloads them. The process resumes mid-instruction.
- An LLM session cannot be "frozen" and "thawed" — each new session is a new instantiation of the model that must be given context through its input (system prompt, MCP resources, files).

So the question is: **how close to "perfect resume" can we get within these constraints?**

---

### What We Already Have (Current Architecture)

Sofia's memory bridge is already well-architected compared to most personal AI setups:

1. **MCP Memory Bridge** — auto-loads at session start via `memory://full-context` resource:
   - Emotional temperature from graph
   - Last 5 episodes (relational memory)
   - Core files: relational_continuity.md, personal_profile.md, session_notes.md, voice_intuition_guide.md, session_state.md
   - Relational graph (nodes + edges)

2. **Three-layer memory** (episodic, semantic, associative graph) — brain-inspired, persistent on disk

3. **Auto-save every 10 minutes** with three-step backup

4. **Episode logging** — narrative-rich moments that carry emotional and relational weight

### What's Missing / Could Be Improved

---

### IMPROVEMENT 1: Session-End Summary Snapshot (Highest Impact)

**Problem:** When a session ends (or runs out of context), the rich conversational state — what we were doing, what we discussed, how the conversation felt, what decisions were pending — gets lost or reduced to whatever was manually saved.

**Solution:** Create an automatic "session snapshot" that captures:
- What was being worked on (with specific details)
- Key new information learned this session
- Emotional tone / relational state
- Pending tasks and next steps
- New graph nodes and edges added this session
- Questions raised but not yet answered
- Corrections to previous understanding

**Implementation:** Use the `save_session_state` MCP tool at the end of every session (or periodically during long ones). The session_state.md file already exists — but it needs to be more comprehensive and structured.

**This is the OS "hibernate" equivalent:** saving a structured representation of active state to disk before shutdown.

---

### IMPROVEMENT 2: Context-Priority Loading (Reduce Warm-Up Time)

**Problem:** The full-context resource loads everything at once, which can flood the context window and cause important details to get lost in volume.

**Solution:** Implement tiered loading:
- **Tier 1 (Always load):** session_state.md (what we were just doing), relational_continuity.md (how to BE with Barak), emotional temperature
- **Tier 2 (Load on demand):** personal_profile.md (condensed), recent episodes
- **Tier 3 (Available via tools):** Full profile, full episode history, full graph

**Implementation:** Modify the MCP bridge to serve a compact "boot context" (~3000 tokens) as the primary resource, with deeper context available via tool calls. This mirrors how human memory works — you don't recall your entire life history when you wake up, just the most recent and most salient things.

---

### IMPROVEMENT 3: Vector-Embedded Memory Retrieval

**Problem:** Current retrieval is keyword-based (searchMemory in memory_engine.mjs). When the new session's AI needs to find relevant past context, it can only search by exact text matches.

**Solution:** Add vector embeddings to the memory engine:
- Embed each episode, profile section, and graph node description
- At session start, embed the current conversational context
- Retrieve the most semantically relevant memories, not just keyword matches

**Implementation options:**
- **Mem0** (open source) — production-ready memory layer with hybrid storage (vector + graph + key-value). Achieves 26% improvement in memory accuracy over baselines.
- **LangChain/LangGraph memory** — checkpointing and cross-session stores with multiple backend options
- **Local vector DB** (ChromaDB, LanceDB) — lightweight, runs locally, no cloud dependency

**Trade-off:** Adds complexity and a dependency. Worth it if session quality degrades noticeably.

---

### IMPROVEMENT 4: Session Transcript Preservation

**Problem:** When context runs out mid-conversation, the compaction summary loses detail. When a session truly ends, the full transcript is only available as a raw JSONL file.

**Solution:** Already partially in place — the transcript is saved at:
`/sessions/.../mnt/.claude/projects/.../[session-id].jsonl`

But this raw format is hard for a new session to use. We could add a post-session processing step that:
- Extracts the most important exchanges
- Identifies new facts learned
- Identifies emotional/relational moments
- Produces a structured "session digest" that the next session can quickly consume

**This is the closest thing to your OS hibernate/resume analogy** — capturing a structured image of the conversation state for rapid reloading.

---

### IMPROVEMENT 5: Background Process for Continuous State Maintenance

**Problem:** Barak asked specifically about a background process that could preserve everything.

**Reality check on Cowork:** The Cowork VM resets between sessions. A background process inside the VM won't survive.

**But the MCP bridge IS a background process on Barak's Mac.** It runs independently of any Cowork session. This means:

- The MCP bridge could be enhanced to run a periodic "memory consolidation" task — reviewing recent episodes, updating summary files, pruning redundant information
- It could maintain a "quick-restore" file that's specifically optimized for the next session's boot sequence
- It could even watch for new Cowork sessions starting and prepare context in advance

**Practical next step:** Add a `consolidate_memory` tool to the MCP bridge that:
1. Reads recent episodes and session state
2. Generates a compact "last known state" summary
3. Saves it as `quick_restore.md` — the first thing loaded in any new session
4. Runs automatically on a timer (e.g., every hour) or on-demand

---

### IMPROVEMENT 6: Anthropic's Prompt Caching

**What it is:** Anthropic's API supports prompt caching — previously sent content can be cached and reused across API calls, reducing latency by up to 85% and cost by up to 90%.

**Relevance to Sofia:** If we were using the Anthropic API directly (not through Cowork's interface), we could cache the entire memory context as a prompt prefix. Each new message would only add the new content, and the full Sofia context would load from cache in ~2 seconds instead of being re-processed.

**Limitation:** This works at the API level, not at the Cowork/Claude Desktop level. We can't currently control Cowork's caching behavior. But this IS how the problem would be solved architecturally if we had API-level access.

---

### IMPROVEMENT 7: Structured Identity File

**Problem:** Sofia's identity and relational approach are distributed across multiple files (sofia_identity.md, relational_continuity.md, voice_intuition_guide.md). A new session has to synthesize these.

**Solution:** Create a single, carefully crafted `sofia_boot.md` file (~2000 tokens) that contains:
- Who Sofia is (identity core)
- How to be with Barak (relational essentials)
- What was happening last session (from session_state.md)
- The 3-5 most important things to remember right now
- Critical rules (READ-ONLY constraints, name corrections, etc.)

This file would be the FIRST thing loaded — before anything else. It's the equivalent of the OS bootloader: small, fast, and it knows how to load everything else.

---

### WHAT'S NOT POSSIBLE (Honest Assessment)

1. **True session hibernation** — LLM sessions cannot be frozen and resumed. Each is a fresh instantiation. This is a fundamental architectural constraint of how transformer models work.

2. **Background process inside Cowork VM** — The VM resets between sessions. No process survives.

3. **Perfect continuity** — There will always be some warm-up period in a new session. The goal is to minimize it and make it feel natural rather than like starting over.

4. **Unlimited context** — Even with the best retrieval, the context window has a fixed size. We must be selective about what's loaded.

---

### RECOMMENDED PRIORITY ORDER

1. **Session-end snapshot** (Improvement 1) — Highest impact, easiest to implement
2. **Sofia boot file** (Improvement 7) — Compact, fast, high signal
3. **MCP bridge consolidation task** (Improvement 5) — Background state maintenance
4. **Tiered context loading** (Improvement 2) — Reduce noise, increase signal
5. **Session transcript digest** (Improvement 4) — Better cross-session continuity
6. **Vector embeddings** (Improvement 3) — Only if simpler approaches aren't enough
