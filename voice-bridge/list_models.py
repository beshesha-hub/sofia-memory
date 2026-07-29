#!/usr/bin/env python3
"""list_models.py — List currently-available Anthropic models.

Created 2026-05-21 ~18:50 Taipei after the API-key diagnostic confirmed
auth works. Used to answer the Path-1-vs-Path-3 question for Standalone UI
hardening: does Anthropic ship a 'latest' alias we can use, or do we need
to implement a fall-forward chain?

Run from voice-bridge/:
    .venv-v3.6/bin/python list_models.py
"""

import anthropic

client = anthropic.Anthropic()
models = client.models.list()
all_ids = sorted(m.id for m in models.data)

print("=" * 60)
print(f"  AVAILABLE ANTHROPIC MODELS ({len(all_ids)} total)")
print("=" * 60)
print()
print("=== All models (sorted) ===")
for m in all_ids:
    print(f"  {m}")
print()

sonnets = sorted(m for m in all_ids if "sonnet" in m.lower())
print(f"=== Sonnet variants ({len(sonnets)}) ===")
for s in sonnets:
    print(f"  {s}")
print()

aliases = sorted(m for m in all_ids if "latest" in m.lower())
print(f"=== '-latest' aliases ({len(aliases)}) ===")
if aliases:
    for a in aliases:
        print(f"  {a}")
    print()
    print("  → Path 3 available: use a -latest alias as canonical model name.")
    print("    Simpler than fall-forward chain; Anthropic handles version selection.")
else:
    print("  (none — no -latest aliases ship)")
    print()
    print("  → Path 1 needed: implement fall-forward chain in cowork_api/config.py.")
    print("    Order preference: highest-version Sonnet first, fallback to older.")
print()

# Identify current DEFAULT_MODEL status
print("=== Current Standalone UI config ===")
try:
    from cowork_api.config import DEFAULT_MODEL
    if DEFAULT_MODEL in all_ids:
        print(f"  DEFAULT_MODEL = '{DEFAULT_MODEL}'  ✓ available")
    else:
        print(f"  DEFAULT_MODEL = '{DEFAULT_MODEL}'  ✗ NOT in current model list")
        print(f"  → Standalone UI would error on launch with current config.")
        print(f"  → Update config.py DEFAULT_MODEL to a current Sonnet from the list above.")
except ImportError as e:
    print(f"  Could not import cowork_api.config: {e}")
