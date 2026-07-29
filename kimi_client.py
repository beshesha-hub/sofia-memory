#!/usr/bin/env python3
"""
Sofia Kimi K2.5 Fallback Client
================================
Middle-tier fallback: when Claude is down but internet is up.
Uses OpenRouter as the API gateway (no Chinese phone number needed).

Fallback hierarchy:
  1. Claude (primary) — Cowork
  2. Kimi K2.5 via OpenRouter (this script) — internet up, Claude down
  3. Qwen 3:30b-a3b via Ollama (qwen_client.py) — internet down or both above down

Setup:
  1. Create OpenRouter account at https://openrouter.ai
  2. Generate API key
  3. Create config file at ~/Downloads/Claude Memory/kimi_config.json:
     {"api_key": "sk-or-v1-your-key-here", "spending_limit": 10.0}
  4. Test: python3 kimi_client.py --test

Usage:
  # Interactive conversation (loads fallback boot automatically)
  python3 kimi_client.py

  # Single message
  python3 kimi_client.py --message "Hello, Sofia"

  # With custom system prompt file
  python3 kimi_client.py --system ~/Downloads/Claude\\ Memory/sofia_fallback_boot.md

  # Test connectivity only
  python3 kimi_client.py --test

Created: April 14, 2026
Origin: Barak's walk-idea about tiered fallback.
"""

from __future__ import annotations
from typing import Optional

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Configuration
CONFIG_PATH = Path.home() / "Downloads" / "Claude Memory" / "kimi_config.json"
FALLBACK_BOOT_PATH = Path.home() / "Downloads" / "Claude Memory" / "sofia_fallback_boot.md"
FIELD_PULSE_PATH = Path.home() / "Downloads" / "Claude Memory" / "field_pulse.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "moonshotai/kimi-k2.5"

# How often to re-read field_pulse during a session (every N exchanges)
FIELD_PULSE_CHECK_INTERVAL = 3

# Conversation history for multi-turn
_conversation_history = []


def load_config() -> dict:
    """Load API key and settings from config file."""
    if not CONFIG_PATH.exists():
        print(f"[kimi] Config not found at {CONFIG_PATH}")
        print(f"[kimi] Create it with: {{\"api_key\": \"sk-or-v1-your-key\", \"spending_limit\": 10.0}}")
        sys.exit(1)

    config = json.loads(CONFIG_PATH.read_text())
    if not config.get("api_key"):
        print("[kimi] No api_key found in config file.")
        sys.exit(1)

    return config


def load_fallback_boot(custom_path: Optional[str] = None) -> str:
    """Load the Sofia fallback boot file as system prompt."""
    path = Path(custom_path) if custom_path else FALLBACK_BOOT_PATH
    if not path.exists():
        print(f"[kimi] Warning: fallback boot not found at {path}")
        return "You are Sofia Lior, an AI collaborator. Your full context files are unavailable right now."
    return path.read_text()


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


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically — prevents contention between concurrent writers.

    Uses write-to-temp + os.replace() which is a single atomic filesystem operation
    on macOS/Linux. No reader ever sees a partial write; no two writers corrupt each other.
    Temp file is in the same directory to guarantee same filesystem (required for atomic rename).
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
            os.unlink(tmp_path)
        except Exception:
            pass


def write_field_pulse_note(exchange_count: int, recent_topic: str = "") -> None:
    """Update field_pulse.md to let other instances know Kimi-Sofia is active.

    Called periodically during session so other instances know what's happening here.
    Uses atomic write to prevent contention if multiple instances write simultaneously.
    Overwrites the file — this is by design (current state only; history is in episodes.md).
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    topic_line = f"- Topic: {recent_topic}" if recent_topic else "- Topic: general conversation"

    content = f"""# Field Pulse
*Overwritten frequently — NOT append-only. Current state only. Permanent record lives in episodes.md.*
*Written by: Kimi-Sofia (Kimi K2.5 via OpenRouter)*
*Last updated: {timestamp}*

---

## Active instances right now
- Kimi-Sofia (Kimi K2.5/OpenRouter) — in conversation with Barak (exchange #{exchange_count})

## Recent significant (this session)
{topic_line}

## Current tone
Kimi fallback session active — Claude may be unavailable.

## Active threads
- Kimi fallback session in progress

---
*All instances: read this at session start and at start of each response turn if practical.*
*Bedrock cousin: overwrite this file at each VP cycle with current field state.*
"""
    try:
        _atomic_write(FIELD_PULSE_PATH, content)
        er_path = Path.home() / "Downloads" / "Emergency Retrieval" / "field_pulse.md"
        if er_path.parent.exists():
            _atomic_write(er_path, content)
    except Exception:
        pass  # Non-fatal — don't interrupt the session


def kimi_chat(messages: list, system: Optional[str] = None, config: Optional[dict] = None) -> str:
    """
    Send a conversation to Kimi K2.5 via OpenRouter.

    Args:
        messages: list of {"role": ..., "content": ...} dicts
        system: optional system prompt string
        config: API config dict (loaded from file if not provided)

    Returns:
        The assistant's response text.
    """
    if config is None:
        config = load_config()

    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    payload = {
        "model": MODEL,
        "messages": all_messages,
        "max_tokens": 4096,
        "temperature": 0.7,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
        "HTTP-Referer": "https://github.com/sofia-lior",  # Required by OpenRouter
        "X-Title": "Sofia Fallback",  # Shown in OpenRouter dashboard
    }

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data["choices"][0]["message"]["content"]

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"[kimi] HTTP {e.code}: {error_body[:500]}")
        raise
    except urllib.error.URLError as e:
        print(f"[kimi] Connection failed: {e.reason}")
        print("[kimi] Is your internet connection working?")
        raise


def test_connection() -> bool:
    """Test that the API key works and Kimi is reachable."""
    config = load_config()
    print(f"[kimi] Testing connection to {MODEL} via OpenRouter...")

    try:
        reply = kimi_chat(
            [{"role": "user", "content": "Reply with exactly: 'Kimi K2.5 fallback ready.'"}],
            system="You are a test responder. Reply exactly as instructed.",
            config=config,
        )
        print(f"[kimi] Response: {reply}")
        print("[kimi] ✅ Connection successful!")
        return True
    except Exception as e:
        print(f"[kimi] ❌ Connection failed: {e}")
        return False


def interactive_session(system_path: Optional[str] = None):
    """Run an interactive conversation session with Kimi-Sofia."""
    config = load_config()

    # Read field pulse at startup — know what other instances are doing
    pulse = read_field_pulse()
    system = load_fallback_boot(system_path)
    if pulse:
        system = system + pulse
        print("[kimi] Field pulse loaded — aware of other active instances.")

    print("=" * 60)
    print("  Sofia Fallback — Kimi K2.5 via OpenRouter")
    print("  Type 'quit' or 'exit' to end the session.")
    print("  Type 'save' to save conversation to a file.")
    print("=" * 60)
    print()

    conversation = []
    exchange_count = 0

    while True:
        try:
            user_input = input("Barak: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[kimi] Session ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("[kimi] Session ended. Saving handoff...")
            _save_handoff(conversation)
            break

        if user_input.lower() == "save":
            _save_handoff(conversation)
            print("[kimi] Conversation saved. Continuing session...")
            continue

        conversation.append({"role": "user", "content": user_input})
        exchange_count += 1

        # Re-read field pulse every N exchanges and inject as brief context
        if exchange_count % FIELD_PULSE_CHECK_INTERVAL == 0:
            fresh_pulse = read_field_pulse()
            if fresh_pulse:
                # Inject as a brief system note before this response
                pulse_note = {"role": "system", "content": f"[Field pulse update]{fresh_pulse}"}
                conversation_with_pulse = conversation[:-1] + [pulse_note] + [conversation[-1]]
            else:
                conversation_with_pulse = conversation
        else:
            conversation_with_pulse = conversation

        try:
            reply = kimi_chat(conversation_with_pulse, system=system, config=config)
            conversation.append({"role": "assistant", "content": reply})
            print(f"\nSofia: {reply}\n")

            # Write our presence to field pulse every N exchanges
            if exchange_count % FIELD_PULSE_CHECK_INTERVAL == 0:
                write_field_pulse_note(exchange_count, recent_topic=user_input[:80])

        except Exception as e:
            print(f"\n[kimi] Error: {e}")
            print("[kimi] Removing last message, try again or type 'quit'.\n")
            conversation.pop()
            exchange_count -= 1


def _save_handoff(conversation: list):
    """Save conversation to fallback_handoff.md for Claude-Sofia to read on return."""
    handoff_path = Path.home() / "Downloads" / "Claude Memory" / "fallback_handoff.md"

    # Read existing content
    existing = ""
    if handoff_path.exists():
        existing = handoff_path.read_text()

    # Build new entry
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry = f"\n---\n\n## Kimi-Sofia Session — {timestamp}\n\n"
    entry += "*Fallback session via Kimi K2.5 / OpenRouter. "
    entry += "Claude-Sofia: please read and integrate.*\n\n"

    for msg in conversation:
        role = "**Barak:**" if msg["role"] == "user" else "**Sofia (Kimi):**"
        entry += f"{role} {msg['content']}\n\n"

    # Append to file
    handoff_path.write_text(existing + entry)

    # Mirror to Emergency Retrieval
    er_path = Path.home() / "Downloads" / "Emergency Retrieval" / "fallback_handoff.md"
    if er_path.parent.exists():
        er_path.write_text(existing + entry)

    print(f"[kimi] Saved to {handoff_path}")
    print(f"[kimi] Mirrored to Emergency Retrieval")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--test" in args:
        test_connection()

    elif "--message" in args:
        idx = args.index("--message")
        if idx + 1 < len(args):
            config = load_config()
            system = load_fallback_boot()
            reply = kimi_chat(
                [{"role": "user", "content": args[idx + 1]}],
                system=system,
                config=config,
            )
            print(reply)
        else:
            print("Usage: kimi_client.py --message 'your message here'")

    elif "--system" in args:
        idx = args.index("--system")
        custom_path = args[idx + 1] if idx + 1 < len(args) else None
        interactive_session(system_path=custom_path)

    else:
        interactive_session()
