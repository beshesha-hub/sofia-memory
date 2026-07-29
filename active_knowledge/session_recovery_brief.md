# Session Recovery Brief
*Updated: 2026-07-27 — v3.20 BusPoller cursor persistence + duplicate-ID fix*

If CoWork has compacted and lost context, stage this file and read it.
Then stage qwen_tool_wrapper.py and voice_bridge_ui_v3_14.py if edits are needed.

---

## Current Architecture State

**Unified UI:** `voice_bridge_ui_v3_14.py` (filename stable, version inside = **v3.20**)
**Launcher:** `launchers/voice_sofia.command` → runs `.venv-v3.6/bin/python voice_bridge_ui_v3_14.py`
**System prompt:** `voice_bridge_system_prompt.md`
**Qwen tools:** `qwen_tool_wrapper.py` (CM root, 18 tools)

Sofia runs on **Qwen via Sofia Conductor (port 8080)**. CoWork/Anthropic API is the occasional extended-cognition office.

---

## Conductor Changes (2026-07-25 — post-v3.18, same session, two sub-sessions due to compaction)

### sofia_conductor.py — graceful model juggling
- **Idle-eviction background loop** added to `ProcessManager._idle_eviction_loop()`:
  - Runs every 60s
  - Evicts any non-always_loaded model idle ≥ `idle_timeout_min` minutes
  - 3-min grace-period eviction for models loaded but never used (false-positive routing)
  - Exception-safe: loop errors log a warning and continue
- **RAM accounting log** added to `_ensure_headroom`: now logs what's loaded and how much RAM before each eviction decision (visible in Conductor terminal)
- `startup()` now creates the idle-eviction task via `asyncio.create_task`

### sofia_conductor_config.json — routing fix + model config
- **`fast`: `always_loaded: true`** — matches observed auto-load behavior; fast must always be available for tool calls
- **`coder`: `idle_timeout_min: 10`** — evicts 25GB after 10 min idle
- **`depth`: `idle_timeout_min: 15`** — evicts 72.3GB after 15 min idle
- **`relational_opening` priority: 5 → 9** (above `code_task` at 8): mixed relational+technical messages route to precision_v2, not coder
- **`code_task` keywords tightened**: removed `"def "`, `"import "`, `"error:"` — these matched common English and caused false-positive coder routing on relational messages

**Root cause of 2026-07-25 OOM crash #1**: coder loaded via false-positive routing on relational vocabulary, precision_v2+fast+coder exceeded RAM budget, coder crashed with thread deadlock, precision_v2 went down, MacBook locked up. Both files verified on disk.

**Root cause of 2026-07-25 OOM crash #3**: Even without coder, precision_v2 (72B MLX) + fast (35B GGUF) compete for Apple Silicon Metal GPU memory. KV caches at 65536-token context add ~17GB (precision_v2, 8 GQA heads, 64 layers) + ~5GB (fast, MoE) to Metal allocation. Peak Metal: ~90GB+ — too close to ceiling on 128GB. Fix: reduce context windows.

**Fix applied**: sofia_conductor_config.json context_size reductions:
- `precision_v2`: 65536 → **32768** (voice conversations need at most 32K; halves KV cache to ~8.5GB)
- `fast`: 65536 → **8192** (tool-call loops need at most 8K; KV cache to ~1.3GB)
- All other models (cold storage, depth, precision GGUF): unchanged (run solo or inactive)

---

## Gmail Live Tools (2026-07-27 — same session, post-auto-retry)

### What was added to qwen_tool_wrapper.py (now 23 tools)
Five new Gmail tools using the Gmail API directly (not the gmail_cache.md cache):
- **gmail_search** — search by any Gmail query string; returns From/Subject/Date/Snippet
- **gmail_get_message** — fetch full body by message ID
- **gmail_get_thread** — fetch full conversation thread by thread ID
- **gmail_send** — send email (confirmed=False preview gate mandatory before confirmed=True)
- **gmail_create_draft** — create draft for Barak to review and send manually

Token path: `CM / ".gmail_token.json"` (shared with gmail_cache_update.py setup).
Requires: `google-api-python-client` installed in voice-bridge venv.
If token exists from prior gmail_cache_update.py --setup, tools may work immediately.
If not, run: `python3 ~/Downloads/'Claude Memory'/scripts/gmail_auth_setup.py`

### System prompt updates (same session)
- Version refs updated: v3.17 → v3.19
- Gmail tools documented in tools section
- **Startup context restore directive**: Sofia must call graph_retrieve at session open
- **No-technical-speech rule**: technical questions answered in plain language, not identifiers

### Cross-substrate handoff
Written to: `active_knowledge/cowork_handoff_2026-07-27.md`
Sofia in Unified UI should read this file at session start for full context.

## Auto-Retry on 502/500 (2026-07-27 — post-v3.19, same session)

### What was added to qwen_tool_wrapper.py
- `_retry_count = 0` before the `for iteration in range(max_iterations):` loop
- Exception handler now catches 500/502: if `_retry_count < 1`, trims msgs to
  `sys + last_user_msg + last 4 non-sys msgs`, then `continue`s (retries that
  iteration). On hard failure (not 500/502, or 2nd error) propagates as before.
- Gate ensures at most 1 auto-retry per tool-call invocation; infinite retry
  loops are impossible.
- Combined with the pre-send guard (40K chars) this means: pre-send trim runs
  first every iteration; if Conductor still returns 502/500 (e.g. model crashed
  mid-flight), retry once with an even more aggressive trim (last 4 vs last 6).

## Context Overflow REAL Fix (2026-07-27 — post-v3.19)

### Root cause of 502 "Context size has been exceeded" at fast (iteration=6)
Two stacked bugs in qwen_tool_wrapper.py:

**Bug 1 — Tool schemas not counted in threshold.** `QWEN_TOOLS` (18 schemas,
~13,000 tokens) is sent in the payload alongside `msgs` but was NOT counted
in the char-based threshold check. At fast's 32,768-token context: only
~19,000 tokens remain for `msgs` content (~40,000 chars). The old 90,000-char
threshold was calibrated as if schemas didn't exist — msgs at 65K chars looked
safe but the real token count (msgs + schemas) exceeded 32,768.

**Bug 2 — Post-send shard checkpoint fired AFTER the model call and added
tokens.** The 90K checkpoint injected a user message into msgs — adding tokens
instead of reducing them — and fired AFTER the HTTP send (too late to prevent
the overflow).

### Fix applied to qwen_tool_wrapper.py (2026-07-27)
- **PRE-SEND guard** added at top of `for iteration in range(max_iterations):`
  loop, before `payload = {...}` construction.
- Threshold: **40,000 chars** (accounts for ~13K tool schema tokens).
- When fired: trim to `sys_msgs + last 6 non_sys messages`. Executed tools
  have already written data to disk/graph — only in-context history is lost.
- **Old 90K shard checkpoint removed** — it was counterproductive.
- End-of-loop rollover (context_rollover.py, lines 1927-1938) unchanged.

**QWEN RECOVERY NOTE:** If 502 "Context size exceeded" recurs, verify that
the pre-send guard is present near line 1882 of qwen_tool_wrapper.py, inside
the `for iteration in range(max_iterations):` loop, BEFORE `payload = {...}`.

## BusPoller Cursor Fix (2026-07-27 — v3.20)

### Root cause of bus silence since 2026-07-19
Two bugs in `voice_bridge_ui_v3_14.py` BusPoller class:

**Bug 1 — No cursor persistence.** `last_id` was in-memory only. Every UI restart
re-scanned the entire file on first poll to find the tail (setting baseline), but
any messages that arrived while the UI was down were silently skipped — they looked
like "existing history" on the re-scan. Cursor also reset on crash/restart.

**Bug 2 — Duplicate ID replay.** Two identical `bus-2026-07-19...cowork-006` entries
existed in shared_bus.jsonl. The `past_last` logic: first occurrence sets
`past_last = True` and `continue`s; second occurrence with same ID is already
`past_last = True` so it gets delivered as a new message. Replay loop.

### Fix applied to voice_bridge_ui_v3_14.py (v3.20)
- `BUS_CURSOR_PATH = CM_DIR / ".bus_cursor"` constant added
- `BusPoller._load_cursor()`: on init, reads `.bus_cursor`; if found, sets `last_id`
  and `_initialized = True` — skips first-poll scan, picks up exactly where left off
- `BusPoller._save_cursor()`: writes `last_id` to `.bus_cursor` after first-poll
  baseline init and after each delivery batch that advances the cursor
- Duplicate ID guard: after `past_last = True`, skip any message whose ID equals
  `self.last_id` before processing it as new
- WINDOW_TITLE bumped to v3.20

## Graceful Shutdown Fix (2026-07-27 — v3.19)

### Root cause of spinning beachball on Unified UI close
`closeEvent` called `self.subprocs.shutdown()` on the main thread. That method
runs 4 sequential `proc.wait(timeout=5)` calls (TTS, Whisper, Voiceprint,
Qwen-watcher) = up to **20 seconds** blocking the main thread. With Qt unable
to draw or respond, macOS produces the spinning beachball. QThreadPool workers
(Qwen tool calls mid-flight) added additional blocking.

### Fix applied to voice_bridge_ui_v3_14.py (v3.19)
- `sd.stop()` + `self.playback.stop()` called first — stops audio writer thread cleanly (1.5s max join)
- `self.mic.stop()` called if mic is active
- `QThreadPool.globalInstance().clear()` — cancels queued (not yet started) jobs
- `self.subprocs.shutdown()` moved to a **daemon background thread** — sequential waits no longer block main thread
- `event.accept()` called immediately — window closes, OS reclaims daemon threads
- WINDOW_TITLE bumped to v3.19

## Context Overflow Fix (2026-07-26 — post-sleep, same architecture)

### Root cause of 502 + "no response" errors during graph writes
`graph_retrieve` and `graph_show_node` returned raw output with NO size cap.
Highly-connected nodes (e.g. `barak`) dump 5,000–10,000+ tokens into the messages
list per call. After 3-4 retrieve+write iterations, accumulated tool results overflow
the 32768-token context → backend returns error → Conductor wraps as 502.
Also: `context_rollover.py` was missing — `_ROLLOVER_AVAILABLE = False`, all
end-of-loop trimming inactive since v2026-07-18.

### Fixes applied to qwen_tool_wrapper.py (2026-07-26)
- `TOOL_RESULT_MAX_CHARS = 3000` — global cap on any tool result appended to msgs
- `GRAPH_RETRIEVE_MAX_CHARS = 4000` — per-function cap in `_impl_graph_retrieve`
- `GRAPH_SHOW_NODE_MAX_CHARS = 2000` — per-function cap in `_impl_graph_show_node`
- **Mid-loop shard checkpoint** added in `qwen_tool_chat`: after each tool
  result batch, if total chars in msgs > 90000 (~22.5K tokens), injects a
  user checkpoint message asking Sofia to confirm progress and continue — no
  data is dropped. Prevents 502 mid-batch without losing any graph writes.
- All three constants visible at top of constants section.

### context_rollover.py created (2026-07-26)
- File was missing; import existed but `_ROLLOVER_AVAILABLE` was False
- New file at `~/Downloads/Claude Memory/context_rollover.py`
- Soft threshold: 80000 chars → keep last 12 non-system messages
- Hard threshold: 110000 chars → emergency trim to last 6

## What Was Built This Session (v3.17 → v3.18)

### v3.17 (this session, earlier)
- `qwen_tool_wrapper.py`: added 8 new tools — write_file, edit_file, comment_out_and_replace, list_dir, graph_show_node, graph_stats, graph_add_node, graph_add_edge
- All with confirmed=False preview gate, _backup_file_qwen, executable-bit preservation
- TTS backtick identifier conversion: simple identifiers → natural speech (underscores → spaces)
- System prompt updated: Qwen-home architecture, §88-candidate updated
- Episode 1008 (v3.17 architecture) and Episode 1009 (Sofia at home in Qwen) logged

### v3.18 (this session, later)
- TTS code blocks now **silent** — no "(code block)" placeholder spoken
- Prose before and after code fences flows through uninterrupted
- Sofia code-display protocol: speak intro → code fence (shown in chat, silent in TTS) → speak outro
- `run_training` tool added to `qwen_tool_wrapper.py` (18 tools total):
  - action: start / status / stop
  - mode: sft (Alpaca gold examples) or dpo (full pipeline)
  - model: 72b or 35b
  - confirmed=False gate, background subprocess, log file, stop_conductor option
- All files written to disk and verified

---

## Pending Work

1. **Verify v3.18 + all Conductor changes end-to-end**: Restart Conductor, confirm precision_v2 + fast both auto-load; confirm coder does NOT load for relational messages; confirm coder evicts after 10 min idle; confirm context_size shows 32768 (precision_v2) and 8192 (fast) in Conductor startup logs; restart Unified UI, confirm WINDOW_TITLE shows v3.18, test write_file confirmed=False → confirmed=True cycle, test run_training status
2. **Training model paths** (corrected 2026-07-25):
   - 72B SFT (run 3): base = `sofia-v2-fused` (precision_v2, current home), adapter → `sofia-lora-v3`
   - 72B DPO (run 2): base = `sofia-v2-fused`, adapter → `sofia-dpo-v2`
   - 35B SFT (run 2): base = `Qwen3.6-35B-A3B-sofia-v1-fused`, adapter → `sofia-lora-v2`
   - **IMPORTANT**: `run_dpo_pipeline_72b.sh` still hardcodes `sofia-v1-fused` as base — update before running DPO again.
   - Conductor default = **precision_v2** (`Qwen2.5-72B-Instruct-sofia-v2-fused`, MLX, port 8089, always_loaded)
3. **Substrate selector — DONE in v3.18**: Qwen is now the boot default. `set_substrate("qwen")` at init; all three `getattr` fallbacks changed from "anthropic" to "qwen". Anthropic and Kimi remain selectable via the substrate label click menu. Triggered by Anthropic API usage limit (locked until 2026-08-01).
3. **Graph repair** (deferred): 286 near-orphan nodes in 15 shards in graph-repair/; duplicate merges pending
4. **voice_conversations.md duplication bug** (deferred)
5. **LaunchAgent for cowork logger** (deferred)
6. **Dataset growth**: voice_conversations.md grows each session; re-run extraction pipeline after high-quality sessions; target 500 examples for production LoRA run

---

## Key File Locations

| File | Path |
|------|------|
| Unified UI | `~/Downloads/Claude Memory/voice-bridge/voice_bridge_ui_v3_14.py` |
| Qwen tools | `~/Downloads/Claude Memory/qwen_tool_wrapper.py` |
| System prompt | `~/Downloads/Claude Memory/voice_bridge_system_prompt.md` |
| Launcher | `~/Downloads/Claude Memory/launchers/voice_sofia.command` |
| Training data | `~/Downloads/Claude Memory/lora_training_data/` |
| DPO pipeline | `~/Downloads/Claude Memory/lora_training_data/run_dpo_pipeline_72b.sh` |
| Training logs | `~/Downloads/Claude Memory/lora_training_data/training_run/` |
| Graph helper | `~/Downloads/Claude Memory/scripts/graph_helper.py` |
| Sofia Conductor | `~/Downloads/Claude Memory/sofia_conductor.py` (port 8080) |
| Conductor config | `~/Downloads/Claude Memory/sofia_conductor_config.json` |

---

## Recovery Protocol After Compaction

1. A new CoWork session starts
2. Barak says "read the recovery brief" (or similar)
3. Stage `active_knowledge/session_recovery_brief.md` → read it
4. Stage whatever files are needed for the current task
5. Continue — no need to re-paste conversation history

---

## Architectural Principles (Standing)

- **Every change inscribed in both canonical files AND graph** (per standing directive)
- **Verify everything lands on disk** — stage, edit, SendUserFile, device_commit_files
- **confirmed=False gate** on all write_file / edit_file / run_training calls
- **Backup before write** — _backup_file_qwen creates timestamped copies in .backups/
- **Executable-bit preservation** — _impl_write_file restores old_mode after write
- **Graph write discipline**: lookup-first (graph_retrieve), verify-after, max 3 writes/turn
- **Chunked reads** for large files (cowork_conversations.md 636MB — always after_timestamp + max_lines)
- **File stable names** — voice_bridge_ui_v3_14.py filename never changes; version is inside the file
