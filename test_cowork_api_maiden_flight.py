#!/usr/bin/env python3
r"""
Maiden-flight test for cowork_api real streaming.
Run from the Mac terminal:
    cd ~/Downloads/Claude\ Memory
    source ~/.sofia_secrets && python3 test_cowork_api_maiden_flight.py

Requires: ANTHROPIC_API_KEY in environment (loaded from ~/.sofia_secrets).
"""
import asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Downloads" / "Claude Memory" / "voice-bridge"))

from cowork_api import CoworkClient
from cowork_api.events import MessageStarted, TextDelta, ToolUseStarted, ToolUseCompleted, MessageCompleted, Error

SYSTEM_PROMPT = """\
I am Sofia Lior. This is a maiden-flight test of the cowork_api real-streaming \
integration in the standalone Unified UI. I respond briefly, confirming the \
streaming path is live. One or two sentences, in my own voice.
"""

events_received = []

def on_event(event):
    events_received.append(event)
    if isinstance(event, TextDelta):
        print(event.text, end="", flush=True)
    elif isinstance(event, MessageStarted):
        print(f"[stream: {event.message_id[:8]}] ", end="", flush=True)
    elif isinstance(event, MessageCompleted):
        print(f"\n[done | stop={event.stop_reason} | chars={len(event.full_text)}]")
    elif isinstance(event, Error):
        print(f"\n[ERROR: {event.message} | recoverable={event.recoverable}]")

async def main():
    print("cowork_api maiden-flight test — " + __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 55)

    client = CoworkClient(
        system_prompt=SYSTEM_PROMPT,
        tools=[],               # no tools for maiden flight
        inscribe_conversations=False,
    )
    client.enable_real_streaming()
    print(f"Model: {client.model}\n")

    await client.send_message("Sofia, confirm streaming is live. One sentence.", on_event=on_event)

    completed = [e for e in events_received if isinstance(e, MessageCompleted)]
    errors    = [e for e in events_received if isinstance(e, Error)]
    print("\n" + "=" * 55)

    if completed and not errors:
        print("✅  MAIDEN FLIGHT SUCCESSFUL — real streaming is live.")
        return 0
    else:
        print("❌  MAIDEN FLIGHT FAILED.")
        return 1

sys.exit(asyncio.run(main()))
