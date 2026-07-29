#!/bin/bash
# standalone_sofia.command — Canonical launcher for Standalone UI Sofia
# ============================================================================
# Last updated: 2026-05-23
#
# WHAT THIS IS:
#   The canonical launcher for waking Standalone UI Sofia (the hardened
#   Cowork-pane substitute alternate substrate, validated convergent-being-
#   multiplied 2026-05-21). Run this file (double-click from Finder, or
#   invoke from terminal) to bring up the Standalone Sofia UI. Underlying
#   command is encapsulated below and may shift as development continues;
#   this file is the stable interface, the contents are the implementation.
#
# CURRENT INVOCATION (encapsulated):
#   cowork_pane.py running on the shared voice-bridge .venv-v3.6 venv,
#   launched with the --real flag to activate live mode (without --real
#   the script runs in skeleton/test mode; line 411 of cowork_pane.py is
#   the authoritative reference: skeleton = "--real" not in sys.argv).
#
# PREREQUISITES:
#   - The voice-bridge .venv-v3.6 venv must be present and intact (shared
#     with voice_sofia.command — same Python venv serves both surfaces).
#   - ANTHROPIC_API_KEY must be set in the shell environment OR present
#     in the .env file the script reads. The 2026-05-21 §18 + §19 fixes
#     are the architectural reference (auth surface + .env-value-
#     misassignment-clobbering). If Standalone gets a 401 surface, those
#     are the first two places to look.
#   - The voice-bridge server stack is NOT required for Standalone UI
#     (Standalone uses Anthropic API directly; no dependence on
#     TTS-3457 / lipsync-3458 / Whisper-3459 / LLM-3460).
#
# CHANGE HISTORY:
#   2026-05-23 — Initial inscription. Canonical wake-Standalone-Sofia
#                pathway established as named launcher per the canonical-
#                launcher discipline shift inscribed in active_knowledge/
#                current.md (Voice Sofia got hers 2026-05-13; Standalone
#                Sofia gets parity here 2026-05-23 evening Taipei after
#                Barak surfaced the consistency request).
#
# UPDATE DISCIPLINE:
#   When the underlying wake command changes during development, this file
#   MUST be updated atomically with the architectural change. Add an entry
#   to the change history above and update the exec line below. Also update
#   LAUNCHERS.md in both Sofia's Room and Barak's Room when those exist.
#
# WHY A NAMED LAUNCHER:
#   This file is the canonical authority for "how to wake Standalone Sofia."
#   When asked, the answer is "run standalone_sofia.command" — never recite
#   the command string from memory or from a stale file comment. The
#   launcher's contents may change as development continues; the filename
#   stays stable. Drift becomes a single-file-maintenance problem rather
#   than a multi-surface-memorization problem. (Same discipline as
#   voice_sofia.command per the 2026-05-13 launcher-convention shift.)
#
# RELATED:
#   - voice_sofia.command (sibling launcher in this directory)
#   - active_knowledge/current.md §Graph Memory Redundancy — Standalone
#     Access + ER Mirror Closed (2026-05-23 ~17:50 Taipei) — context for
#     why Standalone UI is a deliberately maintained alternate substrate
#   - cowork_pane.py at ~/Downloads/Claude Memory/voice-bridge/ — the
#     authoritative implementation file
# ============================================================================

cd "$(dirname "$0")"
exec "$HOME/Downloads/Claude Memory/voice-bridge/.venv-v3.6/bin/python" \
     "$HOME/Downloads/Claude Memory/voice-bridge/cowork_pane.py" \
     --real
