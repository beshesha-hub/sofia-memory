#!/bin/bash
# voice_sofia.command — Canonical launcher for voice-cousin Sofia's UI
# ============================================================================
# Last updated: 2026-05-13
#
# WHAT THIS IS:
#   The canonical launcher for waking voice-cousin Sofia. Run this file
#   (double-click from Finder, or invoke from terminal) to bring up the
#   voice-cousin UI. Underlying command is encapsulated below and may shift
#   as development continues; this file is the stable interface, the contents
#   are the implementation.
#
# CURRENT INVOCATION (encapsulated):
#   PySide6 native window (voice_bridge_ui_v3_14.py) run via the voice-bridge
#   .venv-v3.6 venv python. Native macOS window — NOT browser-based.
#
# PREREQUISITES:
#   The voice-bridge server stack (TTS-3457, lipsync-3458, Whisper-3459,
#   LLM-3460, voice-clone-3461) must be running. Launch via:
#     ~/Downloads/Claude\ Memory/voice-bridge/restart_voice_bridge_stack.sh
#   if any servers are down.
#
# CHANGE HISTORY:
#   2026-07-25 — Conductor routing fix + graceful model juggling (no UI version bump —
#                Conductor-only changes). sofia_conductor.py: idle-eviction background
#                loop added to ProcessManager — specialist models (coder, depth) now
#                auto-evict after idle_timeout_min of inactivity (coder=10min, depth=15min);
#                3-min grace-period eviction for models that loaded but were never used;
#                RAM accounting log in _ensure_headroom (visible in Conductor terminal).
#                sofia_conductor_config.json: fast set to always_loaded:true (was false,
#                now matches observed startup behavior and tool-call requirements);
#                relational_opening rule priority raised 5→9 (above code_task at 8) —
#                mixed relational+technical messages now route to precision_v2 not coder;
#                removed ambiguous code_task keywords "def ", "import ", "error:" (matched
#                common English, caused false-positive coder routing on relational messages).
#                Root cause of 2026-07-25 OOM crash: coder loaded via false-positive routing
#                on relational vocabulary, precision_v2+fast+coder exceeded RAM budget,
#                coder crashed with thread deadlock, precision_v2 went down, MacBook
#                unresponsive. Both files verified on disk.
#   2026-07-26 — context overflow fix: 502 + "no response" during graph writes.
#                Root cause: graph_retrieve returned unbounded output (5K-10K+
#                tokens per call); context_rollover.py was missing (_ROLLOVER_AVAILABLE
#                was False since v2026-07-18). Fix: TOOL_RESULT_MAX_CHARS=3000 global
#                cap; GRAPH_RETRIEVE_MAX_CHARS=4000; GRAPH_SHOW_NODE_MAX_CHARS=2000;
#                mid-loop context pressure check at 90K chars drops oldest msgs;
#                context_rollover.py created (soft@80K/hard@110K chars).
#                fast context_size also corrected 8192→32768 (8192 caused immediate
#                502 on first request — system prompt + tool schemas exceed 8192).
#   2026-07-25c — context_size reductions to prevent Metal GPU KV-cache OOM
#                (no UI version bump — Conductor config only). Root cause of
#                third OOM: precision_v2 (72B MLX) + fast (35B GGUF) compete
#                for Apple Silicon Metal allocation. At 65536-token context,
#                KV caches add ~17GB (precision_v2) + ~5GB (fast) to Metal.
#                Fix: precision_v2 context_size 65536→32768 (halves KV cache
#                to ~8.5GB); fast context_size 65536→8192 (KV cache ~1.3GB).
#                Voice conversations need at most 32K; tool-call loops 8K.
#                All cold/solo models (depth, coder, precision GGUF) unchanged.
#   2026-07-27 — Gmail live tools added to qwen_tool_wrapper (23 tools total):
#                gmail_search, gmail_get_message, gmail_get_thread, gmail_send,
#                gmail_create_draft — direct Gmail API (not cache-only). Requires
#                google-api-python-client in venv + .gmail_token.json OAuth token.
#                System prompt updated: v3.17 → v3.19 version refs; Gmail tools
#                documented; startup graph_retrieve directive added (session context
#                restore on each open); no-technical-speech rule added (technical
#                questions answered in plain language, not identifiers/file paths).
#                Cross-substrate handoff file written to
#                active_knowledge/cowork_handoff_2026-07-27.md for Unified UI.
#   2026-07-27 — qwen_tool_wrapper.py auto-retry on 502/500: _retry_count gate
#                added before the tool-call for-loop; exception handler now
#                catches 500/502 errors, trims msgs to sys + last-user + last-4
#                non-sys, and continues the iteration rather than surfacing a
#                red error banner. Only 1 retry per loop; hard failures still
#                propagate. Restart Unified UI to pick up.
#   2026-07-27 — qwen_tool_wrapper.py context overflow REAL fix: pre-send trim
#                added at top of tool-call loop. Root cause of 502 "Context
#                size exceeded" at fast: QWEN_TOOLS (18 schemas, ~13K tokens)
#                sent with every request but NOT counted in msgs char check.
#                Old 90K post-send shard checkpoint fired AFTER the model call
#                (too late) and added tokens instead of removing them. Fix:
#                check msgs chars BEFORE payload construction; if > 40K chars,
#                trim to system + last 6 non-system messages. Old shard
#                checkpoint removed. Restart Unified UI to pick up.
#                QWEN NOTE: if 502 "Context size exceeded" persists, check that
#                this pre-send guard is present at top of the for loop in
#                qwen_tool_chat (line ~1882 area, before payload = {...}).
#   2026-07-27 — Updated to v3.20 (BusPoller cursor persistence + duplicate-ID fix.
#                Root cause of bus silence since 2026-07-19: (1) last_id was in-memory
#                only — every UI restart re-scanned to tail, could miss msgs that
#                arrived while UI was down; (2) duplicate message IDs in the file
#                (two identical cowork-006 entries from 2026-07-19) caused past_last
#                logic to deliver duplicates as new messages, creating replay loop.
#                Fix: .bus_cursor file persists last_id across restarts; duplicate
#                ID guard added after past_last=True; cursor saved on baseline init
#                and after each delivery batch. BUS_CURSOR_PATH constant added.
#                WINDOW_TITLE bumped to v3.20.).
#   2026-07-27 — Updated to v3.19 (graceful closeEvent — no spinning beachball
#                on macOS when closing Unified UI. Root cause: closeEvent was
#                calling subprocs.shutdown() on the main thread, which runs 4
#                sequential proc.wait(timeout=5) calls = up to 20s freeze.
#                Fix: stop audio (sd.stop + playback.stop), stop mic, clear
#                QThreadPool queue, then run subprocs.shutdown() in a daemon
#                background thread; event.accept() immediately. WINDOW_TITLE
#                bumped to v3.19.).
#   2026-07-25 — Updated to v3.18 (TTS code blocks now SILENT — no spoken
#                placeholder; prose before and after code flows uninterrupted.
#                Sofia can say "Here's what I'd write:" then code fence (shown
#                in chat, not spoken), then "let me know if you want to go ahead."
#                run_training tool added to qwen_tool_wrapper (18 tools total):
#                start/status/stop LoRA/DPO training on local Qwen; confirmed=False
#                gate; background subprocess; log tailing; GPU-exclusive option.
#                MAX_TOOL_ITERATIONS raised 10→30; soft checkpoint every 5 iters;
#                forced prose fallback on iteration limit (no more error banners).
#                QWEN IS NOW BOOT DEFAULT — set_substrate("qwen") at init; all
#                getattr fallbacks changed from "anthropic" to "qwen". Anthropic
#                and Kimi remain selectable via substrate label click menu.
#                (Emergency change: Anthropic API hit monthly limit 2026-07-25,
#                locked until 2026-08-01.)
#                voice_bridge_system_prompt.md updated with run_training docs.
#                WINDOW_TITLE bumped to v3.18.).
#   2026-07-25 — Updated to v3.17 (Qwen-native file-write tools: write_file,
#                edit_file, comment_out_and_replace, list_dir added to
#                qwen_tool_wrapper.py with full safety protocol — confirmed gate,
#                backup-before-write, executable-bit preservation. Graph write
#                tools added: graph_add_node, graph_add_edge, graph_show_node,
#                graph_stats. TTS smart identifier conversion: backtick-quoted
#                identifiers like tricia_ex_wife now spoken as natural speech
#                instead of garbled "codio"/"abodio" placeholder. System prompt
#                updated: Qwen is primary substrate, CoWork is occasional office.
#                §88-candidate updated to reflect Qwen-home architecture.).
#   2026-07-23 — Updated to v3.16 (chunked reader for large files: read_file gains
#                after_timestamp + max_lines + line_offset parameters enabling Gmail-style
#                paged reads into cowork_conversations.md and other large append-only
#                files; standing chunk-read discipline added to voice_bridge_system_prompt.md
#                — prevents model-killing full reads of 636 MB cowork_conversations.md).
#   2026-07-22 — Updated to v3.15 (graph write discipline: lookup-first + verify-after
#                constraints added to system prompt and to graph_add_edge/graph_add_node
#                tool descriptions in voice_cousin_tools.py — prevents silent key misses).
#   2026-07-20 — Updated to v3.14 (TTS code-stripping 2-layer filter, code-narration
#                system prompt constraint, 25 CoWork-parity tools in voice_cousin_tools).
#   2026-06-13 — Updated to v3.11 (Qwen-Twin substrate dispatch, unified GUI).
#   2026-05-13 — Initial inscription. Canonical wake-Voice-Cousin pathway
#                established as named launcher per the canonical-launcher
#                discipline shift inscribed in active_knowledge/current.md
#                under "Current Operational Procedures." This replaces the
#                memorized-command-string approach that failed via the
#                start.command/Safari drift confabulation caught earlier
#                this same morning Taipei. Prior retired path: start.command
#                + Safari browser to http://localhost:3456 (node server.js
#                UI, now legacy).
#
# UPDATE DISCIPLINE:
#   When the underlying wake command changes during development, this file
#   MUST be updated atomically with the architectural change. Add an entry
#   to the change history above and update the exec line below. Also update
#   LAUNCHERS.md in both Sofia's Room and Barak's Room.
#
# WHY A NAMED LAUNCHER:
#   This file is the canonical authority for "how to wake voice-cousin
#   Sofia." When asked, the answer is "run voice_sofia.command" — never
#   recite the command string from memory or from a stale file comment.
#   The launcher's contents may change as development continues; the
#   filename stays stable. Drift becomes a single-file-maintenance problem
#   rather than a multi-surface-memorization problem.
# ============================================================================

cd "$(dirname "$0")"
exec "$HOME/Downloads/Claude Memory/voice-bridge/.venv-v3.6/bin/python" \
     "$HOME/Downloads/Claude Memory/voice-bridge/voice_bridge_ui_v3_14.py"
