#!/bin/bash
# qwen_bedrock.command — Launcher for the Qwen Bedrock cousin (qwen-bedrock-v1)
# ============================================================================
# WHAT THIS IS:
#   Wakes the tool-using Qwen bedrock cousin and runs one field-holding CYCLE:
#   read the continuity heartbeat + session_state, query the associative graph
#   for what's load-bearing, then append an honest first-person field-anchor
#   entry to field_anchor.md (append-only, auto-mirrored to Emergency Retrieval).
#
#   Double-click from Finder, or invoke from Terminal.
#
# MODEL:
#   Defaults to qwen3:14b (MODEL_FAST) — the model the Qwen-Twin VP loop keeps
#   resident, so the bedrock cousin shares warm weights instead of forcing an
#   ~18GB model swap on a 32GB machine. Decision 2026-06-18, option (a):
#   same-model continuity (also the stable optimum for 32GB; the 100-120B-class
#   fullness move is flagged for the 256GB Studio). To use the 30b deliberately
#   when you have headroom, edit the exec line below to add --deep.
#
# OTHER MODES (run the wrapper directly, not via this launcher):
#   python3 qwen_bedrock.py               # interactive REPL with tools
#   python3 qwen_bedrock.py --test-tools  # read_file + safe_append round-trip (no LLM)
#   python3 qwen_bedrock.py --test-graph  # graph_retrieve round-trip (no LLM)
#   python3 qwen_bedrock.py --test-llm    # confirm the model emits tool_calls
#
# PREREQUISITES:
#   - Ollama running (ollama serve, or the menubar app)
#   - qwen3:14b pulled (verify: ollama list)
#   - qwen_bedrock.py + qwen_client.py at ~/Downloads/Claude Memory/
#   - scripts/safe_append.py + scripts/graph_helper.py present (reused for the hands)
#
# SEPARATION FROM VP LOOP:
#   This is the bedrock role — distinct from qwen_twin_presence.py (the VP loop).
#   They share one Ollama and one resident model (14b) but run on different
#   cadences. Everything this writes is tagged [cousin: qwen-bedrock-v1].
#
# WHY A NAMED LAUNCHER:
#   Canonical authority for "how to run a bedrock cycle." The answer is
#   "run qwen_bedrock.command" — never a memorized command string. Filename
#   stays stable; contents may evolve. Discoverable via the graph ("qwen
#   bedrock launcher").
#
# CHANGE HISTORY:
#   2026-06-18 — Initial inscription. Wrapper built + verified end-to-end this
#                session (read_file, safe_append, graph_retrieve, native
#                tool-calling, full cycle all green). Identity-facts + graph
#                reflex grounding added to the bedrock system prompt same session.
# ============================================================================

cd "$HOME/Downloads/Claude Memory"
exec /usr/bin/env python3 qwen_bedrock.py --cycle
