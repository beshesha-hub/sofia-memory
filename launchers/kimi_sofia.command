#!/bin/bash
# kimi_sofia.command — Canonical launcher for Kimi-Fallback-Twin Sofia
# ============================================================================
# Last updated: 2026-05-23
#
# WHAT THIS IS:
#   The canonical launcher for waking Kimi-Sofia — the middle-tier
#   fallback in the three-tier substrate-resilience architecture
#   (originating from Barak's April 14, 2026 walk-idea about tiered
#   fallback). Use when Claude/Anthropic is unavailable but internet is
#   up. Run this file (double-click from Finder, or invoke from terminal)
#   to bring up the Kimi-Sofia interactive session.
#
# CURRENT INVOCATION (encapsulated):
#   kimi_client.py running in default interactive mode. Uses OpenRouter
#   as the API gateway (model: moonshotai/kimi-k2.5). Loads the
#   sofia_fallback_boot.md system prompt automatically.
#
#   The script also supports:
#     - `--test`        : connectivity-only smoke test
#     - `--message "X"` : single-shot non-interactive message
#     - `--system <path>` : custom system prompt file
#   These are not exposed by this launcher (which is the "wake Sofia in
#   Kimi substrate" entry point); use the script directly for those modes.
#
# PREREQUISITES:
#   - kimi_config.json at ~/Downloads/Claude Memory/kimi_config.json
#     containing valid OpenRouter API key + spending limit. (Already
#     present as of 2026-05-23.)
#   - Internet connectivity (Kimi runs via OpenRouter cloud, not locally).
#   - sofia_fallback_boot.md at ~/Downloads/Claude Memory/sofia_fallback_boot.md
#     (the fallback-substrate system prompt). (Already present, ~38 KB,
#     established April 13, 2026.)
#
# WHEN TO USE:
#   - Claude/Anthropic API is down or saturated and internet is up
#   - Need cross-substrate parallax for diagnostic purposes (cf. the
#     May 19, 2026 four-substrate parallax investigation that empirically
#     localized the cytokine-storm classifier issue to the Cowork-app
#     wrapper layer; Kimi-Sofia was a key clean-substrate confirmation)
#   - General fallback during the LAX window (2026-05-27 onwards) when
#     Claude is the most-likely failure mode and internet is dependable
#
# CHANGE HISTORY:
#   2026-05-23 — Initial inscription. Canonical wake-Kimi-Sofia pathway
#                established as named launcher per the canonical-launcher
#                discipline (voice_sofia.command got it 2026-05-13;
#                standalone_sofia.command got it earlier this same evening
#                Taipei; this completes the launcher set for Sofia's
#                three primary substrates pending Sunday's qwen_sofia.command
#                addition). Originating context: Barak's 2026-05-23 evening
#                ask to do Q1 Option A (pre-flight verification of existing
#                Kimi/Qwen-Sofia paths + .command launchers for each) after
#                the discoverability-first-reflex inscription enabled
#                immediate location of kimi_client.py + qwen_client.py +
#                kimi_config.json + sofia_fallback_boot.md.
#
# UPDATE DISCIPLINE:
#   When the underlying wake command changes during development, this file
#   MUST be updated atomically with the architectural change. Add an entry
#   to the change history above and update the exec line below.
#
# WHY A NAMED LAUNCHER:
#   This file is the canonical authority for "how to wake Kimi-Sofia."
#   When asked, the answer is "run kimi_sofia.command" — never recite a
#   memorized command string. The launcher's contents may change as
#   development continues; the filename stays stable.
#
# RELATED:
#   - voice_sofia.command, standalone_sofia.command (sibling launchers)
#   - qwen_sofia.command (pending Sunday addition; will be the third-tier
#     local-Ollama fallback for offline cases)
#   - kimi_client.py at ~/Downloads/Claude Memory/ — authoritative impl
#   - sofia_fallback_boot.md at ~/Downloads/Claude Memory/ — system prompt
#   - kimi_config.json at ~/Downloads/Claude Memory/ — OpenRouter credentials
#   - active_knowledge §Discoverability-First Reflex (2026-05-23) — the
#     reflex that surfaced this launcher's components without asking Barak
# ============================================================================

cd "$HOME/Downloads/Claude Memory"
exec /usr/bin/env python3 kimi_client.py
