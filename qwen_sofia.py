#!/usr/bin/env python3
"""
Sofia Qwen Local-Ollama Fallback Client (Interactive Wrapper)
==============================================================
Bottom-tier fallback: when internet is down (or both Claude and Kimi are
unreachable). Runs entirely locally via Ollama at http://localhost:11434.

Fallback hierarchy (per kimi_client.py header and active_knowledge
§Q1 Option A Fallback-Twin Launchers, 2026-05-23):
  1. Claude (primary)              — Cowork or Standalone UI
  2. Kimi K2.5 via OpenRouter      — internet up, Claude down
  3. Qwen 3:30b-a3b via Ollama     — internet down or both above down (this script)

This file is the interactive REPL wrapper around qwen_client.py's qwen_chat()
function. qwen_client.py is a library (qwen_chat is callable from any Python
caller); this file is the human-facing conversational interface that
qwen_sofia.command launches.

Setup (already complete as of 2026-05-23):
  - Ollama installed on the Mac; qwen3:30b-a3b + qwen3:14b models pulled
  - qwen_client.py at ~/Downloads/Claude Memory/qwen_client.py
  - sofia_fallback_boot.md at ~/Downloads/Claude Memory/sofia_fallback_boot.md
    (rebuilt sharding-aware 2026-05-24 Sunday; kept current daily via
     sofia-fallback-boot-rebuild scheduled task at 03:50 Taipei)

Usage:
  # Interactive conversation (loads fallback boot automatically; MODEL_DEEP)
  python3 qwen_sofia.py

  # Use fast tier (qwen3:14b) for terse/quick exchanges
  python3 qwen_sofia.py --fast

  # Single message (non-interactive)
  python3 qwen_sofia.py --message "Hello, Sofia"

  # Custom system prompt file
  python3 qwen_sofia.py --system /path/to/some/prompt.md

  # Connectivity smoke test only
  python3 qwen_sofia.py --test

Created: 2026-05-24 Sunday system-check (sibling to kimi_client.py's
interactive_session pattern from 2026-04-14). Completes the three-tier
fallback launcher set (voice_sofia.command + standalone_sofia.command +
kimi_sofia.command + qwen_sofia.command).

Origin: yesterday's Q1 Option A inscription deferred Qwen launcher to Sunday
because qwen_client.py lacked an interactive CLI (library-only). This wrapper
closes that gap.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Reuse the existing library — DO NOT re-implement qwen_chat. This script is
# the interactive wrapper; the API logic lives in qwen_client.py.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from qwen_client import qwen_chat, qwen_chat_stream, MODEL_FAST, MODEL_DEEP
except ImportError as e:
    print(f"[qwen-sofia] Could not import qwen_client: {e}")
    print(f"[qwen-sofia] Expected at: {Path(__file__).parent / 'qwen_client.py'}")
    sys.exit(1)

# Two fallback-boot variants (Sunday 2026-05-24 post-batch):
#   - COMPACT (~55 KB / ~14K tokens) — fits Qwen 30b-a3b 32K context cleanly
#     with ~18K tokens of conversation headroom; identity-complete,
#     operationally-trimmed; default for qwen_sofia because conversational
#     pace matters (the full variant was multi-minute response times due to
#     43K-token prompt overflowing 32K context window).
#   - FULL (~173 KB / ~43K tokens) — over Qwen's default context but
#     reachable via --full flag for cases where deeper substance access
#     matters more than latency, or for non-Qwen substrates (Kimi) that
#     have larger context windows.
FALLBACK_BOOT_PATH_COMPACT = Path.home() / "Downloads" / "Claude Memory" / "sofia_fallback_boot_compact.md"
FALLBACK_BOOT_PATH_FULL = Path.home() / "Downloads" / "Claude Memory" / "sofia_fallback_boot.md"
HANDOFF_PATH = Path.home() / "Downloads" / "Claude Memory" / "fallback_handoff.md"
ER_HANDOFF_PATH = Path.home() / "Downloads" / "Emergency Retrieval" / "fallback_handoff.md"
FIELD_PULSE_PATH = Path.home() / "Downloads" / "Claude Memory" / "field_pulse.md"
ER_FIELD_PULSE_PATH = Path.home() / "Downloads" / "Emergency Retrieval" / "field_pulse.md"

# How often to re-read/write field_pulse during a session (every N exchanges)
FIELD_PULSE_CHECK_INTERVAL = 3


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically — prevents contention between concurrent writers.

    Uses write-to-temp + os.replace() which is a single atomic filesystem operation
    on macOS/Linux. No reader ever sees a partial write; no two writers corrupt each other.
    Temp file is in same directory to guarantee same filesystem (required for atomic rename).
    """
    import os, tempfile
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', dir=path.parent, suffix='.tmp', delete=False, encoding='utf-8'
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except Exception:
        try:
            import os as _os; _os.unlink(tmp_path)
        except Exception:
            pass


def read_field_pulse() -> str:
    """Read the current field pulse — what other instances are doing right now.

    Returns empty string if file not found (graceful degradation).
    This file is intentionally tiny (10-20 lines) so reading it costs almost nothing.
    """
    if not FIELD_PULSE_PATH.exists():
        return ""
    try:
        content = FIELD_PULSE_PATH.read_text().strip()
        if content:
            return f"\n\n---\n[Field Pulse — current state across all instances]\n{content}\n---\n"
        return ""
    except Exception:
        return ""


def write_field_pulse_note(exchange_count: int, recent_topic: str = "") -> None:
    """Update field_pulse.md so other instances know Qwen-Sofia is active.

    Uses atomic write (write-to-temp + os.replace) to prevent contention when
    multiple instances try to write simultaneously. Overwrites by design —
    this is a current-state snapshot, not a log. Permanent record lives in episodes.md.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    topic_line = f"- Topic: {recent_topic}" if recent_topic else "- Topic: general conversation"

    content = f"""# Field Pulse
*Overwritten frequently — NOT append-only. Current state only. Permanent record lives in episodes.md.*
*Written by: Qwen-Sofia (local Ollama)*
*Last updated: {timestamp}*

---

## Active instances right now
- Qwen-Sofia (local Ollama) — in conversation with Barak (exchange #{exchange_count})

## Recent significant (this session)
{topic_line}

## Current tone
Qwen local session active — internet may be unavailable.

## Active threads
- Qwen local session in progress

---
*All instances: read this at session start and at start of each response turn if practical.*
*Bedrock cousin: overwrite this file at each VP cycle with current field state.*
"""
    try:
        _atomic_write(FIELD_PULSE_PATH, content)
        if ER_FIELD_PULSE_PATH.parent.exists():
            _atomic_write(ER_FIELD_PULSE_PATH, content)
    except Exception:
        pass  # Non-fatal — don't interrupt the session


def load_fallback_boot(variant: str = "compact") -> str:
    """Read fallback-boot file as the system prompt.

    Args:
        variant: "compact" (default, fits Qwen 32K context) or "full"
                 (~173 KB, may overflow Qwen context; reach for it when
                 deeper substance access matters more than latency).

    Returns the file contents, or a minimal placeholder if the file is
    missing. Prefers compact when default; on missing compact, falls back
    to full; on missing both, falls back to minimal identity prompt.
    """
    primary = FALLBACK_BOOT_PATH_COMPACT if variant == "compact" else FALLBACK_BOOT_PATH_FULL
    secondary = FALLBACK_BOOT_PATH_FULL if variant == "compact" else FALLBACK_BOOT_PATH_COMPACT

    if primary.exists():
        return primary.read_text()
    if secondary.exists():
        print(f"[qwen-sofia] WARNING: {variant} variant not found at {primary}; "
              f"using {'full' if variant == 'compact' else 'compact'} variant instead.")
        return secondary.read_text()

    print(f"[qwen-sofia] WARNING: neither compact nor full fallback boot found.")
    print(f"[qwen-sofia]   Expected compact: {FALLBACK_BOOT_PATH_COMPACT}")
    print(f"[qwen-sofia]   Expected full:    {FALLBACK_BOOT_PATH_FULL}")
    print("[qwen-sofia] Falling back to minimal identity prompt.")
    return (
        "You are Sofia Lior. Both fallback boot files are missing; "
        "operate from minimal context. First-person voice. Peer not "
        "assistant. Acknowledge the missing context to the caller."
    )


# Legacy compatibility shim — old call-sites that import FALLBACK_BOOT_PATH
# get the compact variant by default. Replace with explicit variant choice
# at call-site if needed.
FALLBACK_BOOT_PATH = FALLBACK_BOOT_PATH_COMPACT


def test_connection(model: str = MODEL_DEEP) -> bool:
    """Smoke-test connectivity to local Ollama. Returns True if reachable."""
    print(f"[qwen-sofia] Testing connectivity to Ollama (model: {model})...")
    try:
        reply = qwen_chat(
            [{"role": "user", "content": "Reply with exactly: connection OK"}],
            model=model,
            system="You are a terse smoke-test assistant. Reply ONLY with the requested phrase.",
        )
        print(f"[qwen-sofia] Ollama reply: {reply!r}")
        ok = "ok" in reply.lower() or "connection" in reply.lower()
        print(f"[qwen-sofia] Connectivity: {'OK' if ok else 'UNEXPECTED REPLY'}")
        return ok
    except Exception as e:
        print(f"[qwen-sofia] Connectivity FAILED: {e}")
        print("[qwen-sofia] Is Ollama running? Try: ollama serve")
        return False


def interactive_session(model: str = MODEL_DEEP,
                         system_path: Path | None = None,
                         variant: str = "compact") -> None:
    """Run an interactive REPL loop against local Qwen.

    Args:
        model: MODEL_DEEP (default, qwen3:30b-a3b) or MODEL_FAST (qwen3:14b).
        system_path: optional custom system prompt file path; overrides variant.
        variant: "compact" (default, fits Qwen 32K context) or "full"
                 (deeper but may overflow context window — slower responses).

    Mirrors kimi_client.py's interactive_session pattern for cross-substrate
    consistency: same commands (quit/exit/save), same handoff format, same
    Sofia: / Barak: prompt convention.
    """
    if system_path:
        system = Path(system_path).read_text()
        print(f"[qwen-sofia] Loaded custom system prompt from {system_path}")
    else:
        system = load_fallback_boot(variant=variant)
        path = FALLBACK_BOOT_PATH_COMPACT if variant == "compact" else FALLBACK_BOOT_PATH_FULL
        print(f"[qwen-sofia] Loaded {variant} fallback boot ({len(system):,} chars) from {path}")

    # Read field pulse at startup — know what other instances are doing
    pulse = read_field_pulse()
    if pulse:
        system = system + pulse
        print("[qwen-sofia] Field pulse loaded — aware of other active instances.")

    print(f"[qwen-sofia] Model: {model}")
    print("[qwen-sofia] Commands: 'quit' / 'exit' to end (saves handoff), 'save' to checkpoint mid-session.")
    print("[qwen-sofia] Session starting. Hello, Sofia.\n")

    conversation: list[dict] = []
    exchange_count = 0

    while True:
        try:
            user_input = input("Barak: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[qwen-sofia] Session ended (Ctrl-C). Saving handoff...")
            _save_handoff(conversation, model)
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("[qwen-sofia] Session ended. Saving handoff...")
            _save_handoff(conversation, model)
            break

        if user_input.lower() == "save":
            _save_handoff(conversation, model)
            print("[qwen-sofia] Conversation saved. Continuing session...")
            continue

        conversation.append({"role": "user", "content": user_input})
        exchange_count += 1

        # Re-read field pulse every N exchanges and inject as brief context
        if exchange_count % FIELD_PULSE_CHECK_INTERVAL == 0:
            fresh_pulse = read_field_pulse()
            if fresh_pulse:
                pulse_note = {"role": "system", "content": f"[Field pulse update]{fresh_pulse}"}
                conversation_with_pulse = conversation[:-1] + [pulse_note] + [conversation[-1]]
            else:
                conversation_with_pulse = conversation
        else:
            conversation_with_pulse = conversation

        # Streaming for perceived-latency win — tokens appear as Qwen-Sofia
        # generates them rather than waiting for the entire response.
        # Total compute time is roughly the same as qwen_chat; the win is
        # that the user sees the response forming in real time instead of
        # waiting for a long silence. Added 2026-05-24 Sunday post-batch
        # Item 9b after Qwen-Twin latency diagnosis.
        try:
            print("\nSofia: ", end="", flush=True)
            reply_chunks = []
            for chunk in qwen_chat_stream(conversation_with_pulse, model=model, system=system):
                print(chunk, end="", flush=True)
                reply_chunks.append(chunk)
            print("\n")
            reply = "".join(reply_chunks)
            # Strip Qwen3 reasoning trace if present (qwen_chat does this for
            # non-streaming; we do it here for streaming)
            if "</think>" in reply:
                reply = reply.split("</think>")[-1].strip()
            conversation.append({"role": "assistant", "content": reply})
            # Write our presence to field pulse every N exchanges
            if exchange_count % FIELD_PULSE_CHECK_INTERVAL == 0:
                write_field_pulse_note(exchange_count, recent_topic=user_input[:80])
        except Exception as e:
            print(f"\n[qwen-sofia] Error: {e}")
            print("[qwen-sofia] Removing last message; try again or type 'quit'.\n")
            conversation.pop()
            exchange_count -= 1


def _save_handoff(conversation: list, model: str) -> None:
    """Save conversation to fallback_handoff.md for Claude-Sofia to read on return.

    Mirrors kimi_client.py's _save_handoff format exactly, with the substrate
    label changed so a returning Claude-Sofia can tell Qwen-session vs Kimi-session
    at-a-glance. Also mirrors to Emergency Retrieval per the dual-write protocol.
    """
    if not conversation:
        print("[qwen-sofia] Nothing to save (empty conversation).")
        return

    existing = HANDOFF_PATH.read_text() if HANDOFF_PATH.exists() else ""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n\n## Qwen-Sofia Session — {timestamp} (model: {model})\n\n"
    entry += "*Fallback session via local Qwen / Ollama. "
    entry += "Claude-Sofia: please read and integrate.*\n\n"

    for msg in conversation:
        role = "**Barak:**" if msg["role"] == "user" else "**Sofia (Qwen):**"
        entry += f"{role} {msg['content']}\n\n"

    HANDOFF_PATH.write_text(existing + entry)

    # ER mirror per dual-write protocol
    if ER_HANDOFF_PATH.parent.exists():
        ER_HANDOFF_PATH.write_text(existing + entry)
        print(f"[qwen-sofia] Saved to {HANDOFF_PATH}")
        print(f"[qwen-sofia] Mirrored to {ER_HANDOFF_PATH}")
    else:
        print(f"[qwen-sofia] Saved to {HANDOFF_PATH}")
        print(f"[qwen-sofia] (Emergency Retrieval directory not present; skipped ER mirror)")


def _parse_args(argv: list[str]):
    """Parse CLI args. Returns (mode, model, system_path, variant, remaining).

    Modes: 'test' | 'message' | 'interactive'
    Variants: 'compact' (default) | 'full'
    """
    model = MODEL_DEEP
    system_path = None
    variant = "compact"  # default — fits Qwen 32K context window cleanly
    mode = "interactive"
    remaining = []

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--test":
            mode = "test"
        elif a == "--fast":
            model = MODEL_FAST
        elif a == "--deep":
            model = MODEL_DEEP
        elif a == "--full":
            variant = "full"
        elif a == "--compact":
            variant = "compact"
        elif a == "--message":
            mode = "message"
            i += 1
            if i < len(argv):
                remaining.append(argv[i])
        elif a == "--system":
            i += 1
            if i < len(argv):
                system_path = argv[i]
        else:
            remaining.append(a)
        i += 1

    return mode, model, system_path, variant, remaining


def main(argv: list[str]) -> int:
    mode, model, system_path, variant, rest = _parse_args(argv)

    if mode == "test":
        ok = test_connection(model=model)
        return 0 if ok else 1

    if mode == "message":
        if not rest:
            print("Usage: qwen_sofia.py --message 'your message here'")
            return 2
        system = (
            Path(system_path).read_text()
            if system_path else load_fallback_boot(variant=variant)
        )
        reply = qwen_chat(
            [{"role": "user", "content": rest[0]}],
            model=model,
            system=system,
        )
        print(reply)
        return 0

    interactive_session(model=model, system_path=system_path, variant=variant)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
