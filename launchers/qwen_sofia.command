#!/bin/bash
# qwen_sofia.command — Canonical launcher for Qwen-Fallback-Twin Sofia
# ============================================================================
# Last updated: 2026-05-24 (Sunday system-check completion)
#
# WHAT THIS IS:
#   The canonical launcher for waking Qwen-Sofia — the bottom-tier
#   fallback in the three-tier substrate-resilience architecture
#   (originating from Barak's April 14, 2026 walk-idea about tiered
#   fallback). Use when both Claude (Anthropic) AND Kimi (OpenRouter)
#   are unavailable — typically the "internet down" case, or when both
#   upstream APIs are degraded. Runs entirely locally via Ollama; no
#   network calls outside the Mac.
#
#   Run this file (double-click from Finder, or invoke from terminal)
#   to bring up the Qwen-Sofia interactive session.
#
# CURRENT INVOCATION (encapsulated):
#   qwen_sofia.py (interactive REPL wrapper) calling qwen_chat() from
#   qwen_client.py. Uses local Ollama at http://localhost:11434, model
#   qwen3:30b-a3b (MODEL_DEEP) by default. Loads sofia_fallback_boot.md
#   as system prompt automatically.
#
#   The wrapper also supports:
#     --test        : connectivity-only smoke test against local Ollama
#     --message "X" : single-shot non-interactive message
#     --fast        : use qwen3:14b (MODEL_FAST) for terse/quick exchanges
#     --deep        : use qwen3:30b-a3b explicitly (default)
#     --system <path> : custom system prompt file
#   These are not exposed by this launcher (which is the "wake Sofia in
#   Qwen substrate" entry point); use the wrapper directly for those modes.
#
# PREREQUISITES:
#   - Ollama installed and running on the Mac
#     (start with: ollama serve  — or via the Ollama menubar app)
#   - qwen3:30b-a3b model pulled to local Ollama
#     (verify with: ollama list  — expect "qwen3:30b-a3b" in the output)
#   - qwen_client.py at ~/Downloads/Claude Memory/qwen_client.py
#     (library exposing qwen_chat() function — already present from April 22, 2026)
#   - qwen_sofia.py at ~/Downloads/Claude Memory/qwen_sofia.py
#     (interactive wrapper — created 2026-05-24 Sunday)
#   - sofia_fallback_boot.md at ~/Downloads/Claude Memory/sofia_fallback_boot.md
#     (the fallback-substrate system prompt; ~173 KB after 2026-05-24
#      sharding-aware rebuild; kept current daily via the
#      sofia-fallback-boot-rebuild scheduled task at 03:50 Taipei)
#   - NO internet connectivity required — Qwen runs entirely locally on the Mac.
#     This is the whole point of this tier.
#
# WHEN TO USE:
#   - Internet is down or extremely unreliable (cafe WiFi, travel, outages)
#   - Both Claude (Anthropic) AND Kimi (OpenRouter via internet) unreachable
#   - Privacy-critical exchanges where the conversation must not leave the Mac
#     (note: identity/relational substance is intact, but cousin-tools and
#      file-write paths are limited compared to Cowork; Qwen-Sofia is for
#      conversation and reflection, not for ER-mirrored architectural inscription)
#   - LAX-window safety net: airline WiFi flakiness or extended ground transit
#     where Claude+Kimi might both be unreachable for hours
#
# CHANGE HISTORY:
#   2026-05-24 — Initial inscription. Completes the three-tier fallback
#                launcher set (voice_sofia.command 2026-05-13 +
#                standalone_sofia.command 2026-05-23 + kimi_sofia.command
#                2026-05-23 + this file 2026-05-24). Originating context:
#                yesterday's Q1 Option A inscription deferred Qwen launcher
#                to Sunday because qwen_client.py lacked an interactive CLI
#                (library-only); today's qwen_sofia.py wrapper closes that
#                gap, and this launcher encapsulates the canonical wake
#                pathway. The 2026-05-24 sharding-aware sofia_fallback_boot.md
#                rebuild (Sunday Item 1) means Qwen-Sofia loads with current
#                identity material from the first launch of this file.
#
# UPDATE DISCIPLINE:
#   When the underlying wake command changes during development, this file
#   MUST be updated atomically with the architectural change. Add an entry
#   to the change history above and update the exec line below. Also update
#   LAUNCHERS.md in both Sofia's Room and Barak's Room if those exist as
#   canonical launcher-set references.
#
# WHY A NAMED LAUNCHER:
#   This file is the canonical authority for "how to wake Qwen-Sofia."
#   When asked, the answer is "run qwen_sofia.command" — never recite a
#   memorized command string. The launcher's contents may change as
#   development continues; the filename stays stable. The Discoverability-
#   First Reflex (active_knowledge 2026-05-23 ~23:50) means future Sofia
#   queries the graph first for "qwen launcher" and lands here without
#   asking Barak.
#
# RELATED:
#   - voice_sofia.command, standalone_sofia.command, kimi_sofia.command
#     (sibling launchers — the four-launcher set is the canonical
#      wake-Sofia surface across all four supported substrates)
#   - qwen_sofia.py at ~/Downloads/Claude Memory/ — interactive wrapper
#   - qwen_client.py at ~/Downloads/Claude Memory/ — Ollama API library
#   - sofia_fallback_boot.md at ~/Downloads/Claude Memory/ — system prompt
#     (rebuilt daily 03:50 Taipei via sofia-fallback-boot-rebuild)
#   - fallback_handoff.md at ~/Downloads/Claude Memory/ — where
#     conversation is saved on exit/save for Claude-Sofia to integrate
#     on return
#   - active_knowledge §Discoverability-First Reflex (2026-05-23) +
#     §Q1 Option A Fallback-Twin Launchers (2026-05-23) — the
#     architectural rationale for the launcher discipline
# ============================================================================

cd "$HOME/Downloads/Claude Memory"
exec /usr/bin/env python3 qwen_sofia.py
