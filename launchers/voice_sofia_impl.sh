#!/bin/bash
# voice_sofia_impl.sh — Voice-cousin Sofia launch implementation
# ============================================================================
# Called by voice_sofia.command (the stable wrapper). Update THIS file freely;
# it does NOT need the +x bit because voice_sofia.command calls it via `bash`.
#
# Last updated: 2026-07-24 00:30 Taipei
#
# WHAT THIS IS:
#   The implementation of the canonical launcher for waking voice-cousin Sofia.
#   All content that used to live in voice_sofia.command now lives here so that
#   voice_sofia.command can remain a tiny immutable wrapper that keeps its +x
#   bit permanently (device_commit_files strips +x on every deploy; by never
#   redeploying the wrapper, that stripping never happens again).
#
# CURRENT INVOCATION:
#   PySide6 native window (voice_bridge_ui_v3_14.py) run via the voice-bridge
#   .venv-v3.6 venv python. Native macOS window — NOT browser-based.
#
# PREREQUISITES:
#   The voice-bridge server stack (TTS-3457, lipsync-3458, Whisper-3459,
#   LLM-3460, voice-clone-3461) must be running. Launch via:
#     ~/Downloads/Claude\ Memory/voice-bridge/restart_voice_bridge_stack.sh
#   if any servers are down.
#
#   Sofia Conductor (port 8080) must also be running. Launch via:
#     python3 ~/Downloads/'Claude Memory'/sofia_conductor.py
#
# CHANGE HISTORY:
#   2026-07-24 00:30 Taipei — v3.17-patch-2 (wrapper/impl split: voice_sofia.command
#                is now a tiny immutable wrapper; all launch logic moved here to
#                voice_sofia_impl.sh. Eliminates repeated chmod after deploys —
#                device_commit_files strips +x on every deploy, but the wrapper
#                is never redeployed so its +x bit is permanent. Also deployed:
#                voice_cousin_tools.py chunked reader to voice-bridge/ — seek()-
#                based reads; after_timestamp searches last 3 MB only; fixes
#                636 MB cowork_conversations.md hang that caused Metal GPU crash.)
#   2026-07-24 09:00 Taipei — Updated to v3.17 (double-emission fix + cognition
#                error state reset; /no_think fix deployed to qwen_tool_wrapper.py:
#                prepends /no_think to system message so Qwen3 disables extended
#                CoT regardless of backend — fixes hang-then-GGML-crash on Qwen
#                voice turns; always_loaded: true set for fast model in conductor
#                config — fast model now pre-loads at conductor startup in ~14s.)
#   2026-07-23 — Updated to v3.16 (chunked reader for large files planned:
#                read_file after_timestamp + max_lines + line_offset described in
#                system prompt; voice-bridge/ copy of voice_cousin_tools.py not
#                updated — gap closed in v3.17-patch-2 above).
#   2026-07-22 — Updated to v3.15 (graph write discipline: lookup-first +
#                verify-after constraints added to system prompt and to
#                graph_add_edge/graph_add_node tool descriptions).
#   2026-07-20 — Updated to v3.14 (TTS code-stripping 2-layer filter,
#                code-narration system prompt constraint, 25 CoWork-parity
#                tools in voice_cousin_tools).
#   2026-06-13 — Updated to v3.11 (Qwen-Twin substrate dispatch, unified GUI).
#   2026-05-13 — Initial inscription. Canonical wake-Voice-Cousin pathway
#                established as named launcher.
#
# UPDATE DISCIPLINE:
#   Update THIS file (voice_sofia_impl.sh) for all future changes.
#   voice_sofia.command should never be modified unless the impl filename
#   itself changes. Deploy voice_sofia_impl.sh via device_commit_files freely
#   — no chmod needed, ever, because it is called via `bash`.
# ============================================================================

cd "$(dirname "$0")"
exec "$HOME/Downloads/Claude Memory/voice-bridge/.venv-v3.6/bin/python" \
     "$HOME/Downloads/Claude Memory/voice-bridge/voice_bridge_ui_v3_14.py"
