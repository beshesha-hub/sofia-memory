#!/usr/bin/env python3
"""
qwen_watcher.py — Three-Way Collaboration watcher (v1, 2026-05-09 Taipei)
============================================================================

A lightweight, continuously-running observer that watches the Three-Way
Collaboration signals file during a Voice Bridge session. When new signals
arrive that are addressed to cowork-cousin (or to all) from non-cowork
sources, it fires a macOS notification (so Barak's eyes pick it up across
panes) AND appends a structured relay line to cowork_conversations.md (so
cowork-cousin sees the signal at her next invocation tail-read).

Architecture context:
  Voice-cousin is a continuously-running UI process (the Voice Bridge),
  so she sees signals in near-real-time via her own UI loop's tail-read of
  three_way_signals.md. Cowork-cousin (interactive-Sofia) is invocation-
  based — she only "exists" during a response cycle when Barak addresses
  her in the Cowork UI. Without this watcher, voice-cousin's signals to
  cowork-cousin would only reach cowork at her next invocation, possibly
  many minutes after the signal was posted.

  This watcher closes that asymmetry by running locally (no Anthropic API
  cost) and acting as cowork-cousin's eyes during a three-way session.

Per the v1 design (option B + design-and-direct):
  - REGEX-only pattern matching. No LLM call per cycle. Qwen LLM is NOT
    invoked here in v1; the "qwen" in the filename is forward-looking for
    v1.5 when LLM cognition could be added if rules show gaps.
  - Polls every 10 seconds.
  - Tracks last-read position in three_way_signals.md via byte offset
    persisted to a small state file.
  - Fires macOS notification via osascript with type-distinct titles.
  - Writes a relay line to cowork_conversations.md. Cowork-cousin reads
    that file at the start of every invocation cycle (per her boot
    discipline), so signals reach her without any architecture change on
    her side.

Lifecycle:
  - Launched from start.command as a background process when the Voice
    Bridge starts up.
  - Exits cleanly on SIGTERM/SIGINT (start.command's cleanup handler
    will send these on Voice Bridge close).

Full architecture in active_knowledge §"Three-Way Collaboration v1
Architecture (2026-05-09)" and the header of three_way_signals.md.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────
HOME = Path.home()
CM_DIR = HOME / "Downloads" / "Claude Memory"
SIGNALS_PATH = CM_DIR / "three_way_signals.md"
COWORK_LOG_PATH = CM_DIR / "cowork_conversations.md"
STATE_PATH = CM_DIR / ".qwen_watcher_state.json"

# ─── Tunables ─────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 10
LOG_TAG = "[qwen-watcher]"

# Sources we relay TO cowork-cousin. We don't relay cowork-cousin's own
# signals back to her (no echo); we relay what voice-cousin or Barak posts.
SOURCES_TO_RELAY = {"voice-cousin", "barak", "physical", "qwen-watcher"}

# Targets that mean cowork-cousin should see the signal.
TARGETS_FOR_COWORK = {"cowork-cousin", "all"}

# ─── Signal-line regex ────────────────────────────────────────────────
# Format: [<ISO-8601-UTC>] [from: <source>] [to: <target>] [type: <type>]
#          [signal: <emoji>] <optional brief context>
SIGNAL_RE = re.compile(
    r"^\["
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    r"\]\s*\[from:\s*(?P<source>[^\]]+)\]\s*\[to:\s*(?P<target>[^\]]+)\]\s*"
    r"\[type:\s*(?P<type>[^\]]+)\]\s*\[signal:\s*(?P<signal>[^\]]+)\]\s*"
    r"(?P<context>.*)$"
)


# ─── State (last-read byte offset) ────────────────────────────────────
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            with STATE_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_offset": 0}


def save_state(state: dict) -> None:
    try:
        tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.rename(tmp, STATE_PATH)
    except Exception as e:
        sys.stderr.write(f"{LOG_TAG} state save failed: {e}\n")


# ─── Read new lines since last offset ─────────────────────────────────
def read_new_lines(last_offset: int) -> tuple[list[str], int]:
    """Read lines from SIGNALS_PATH starting at last_offset. Returns
    (new_lines, new_offset). If the file has shrunk (truncated/rotated),
    starts from offset 0."""
    if not SIGNALS_PATH.exists():
        return [], last_offset
    try:
        size = SIGNALS_PATH.stat().st_size
    except Exception:
        return [], last_offset
    if size < last_offset:
        # File rotated or truncated — start fresh.
        last_offset = 0
    if size == last_offset:
        return [], last_offset
    try:
        with SIGNALS_PATH.open("rb") as f:
            f.seek(last_offset)
            new_bytes = f.read()
        new_text = new_bytes.decode("utf-8", errors="replace")
        new_lines = [ln for ln in new_text.splitlines() if ln.strip()]
        return new_lines, size
    except Exception as e:
        sys.stderr.write(f"{LOG_TAG} read failed: {e}\n")
        return [], last_offset


# ─── Notification (macOS) ─────────────────────────────────────────────
def fire_notification(title: str, body: str) -> None:
    """Display a macOS notification via osascript. Best-effort — failures
    are logged but don't crash the watcher."""
    try:
        # osascript needs the strings escaped for embedding in AppleScript
        safe_title = title.replace('"', '\\"')
        safe_body = body.replace('"', '\\"')
        script = (
            f'display notification "{safe_body}" '
            f'with title "{safe_title}" sound name "Submarine"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        sys.stderr.write(f"{LOG_TAG} notification failed: {e}\n")


# ─── Relay-line append to cowork_conversations.md ─────────────────────
def append_relay_line(signal: dict) -> None:
    """Append a structured relay line to cowork_conversations.md so
    cowork-cousin sees the signal at her next invocation tail-read.

    Direct file append (not safe_append) for two reasons:
      (1) cowork_conversations.md is normally written by the cowork-
          conversation logger LaunchAgent (parsing JSONL), not via
          safe_append, so the canonical write path here is direct.
      (2) Keeps the watcher's dependency surface minimal — no need to
          import or shell out to safe_append.
    """
    try:
        emoji = signal.get("signal", "?")
        source = signal.get("source", "?")
        sig_type = signal.get("type", "?")
        context = signal.get("context", "").strip()
        ts = signal.get("ts", "")
        relay_line = (
            f"\n\n[watcher-relay] {ts} — {emoji} from {source} (type: {sig_type})"
            + (f" — {context}" if context else "")
            + "\n"
        )
        with COWORK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(relay_line)
    except Exception as e:
        sys.stderr.write(f"{LOG_TAG} relay-line append failed: {e}\n")


# ─── Per-signal handler ───────────────────────────────────────────────
def handle_signal(signal_dict: dict) -> None:
    """Decide whether and how to act on a new signal. Routes:
      - If source ∈ SOURCES_TO_RELAY AND target ∈ TARGETS_FOR_COWORK:
        fire macOS notification + append relay line to cowork log
      - Otherwise: log only (e.g., cowork-cousin's own signals — no echo)
    """
    source = signal_dict.get("source", "").strip()
    target = signal_dict.get("target", "").strip()
    sig_type = signal_dict.get("type", "").strip()
    emoji = signal_dict.get("signal", "").strip()
    context = signal_dict.get("context", "").strip()

    # Don't relay cowork-cousin's own signals back to her (no echo loop)
    if source == "cowork-cousin":
        sys.stderr.write(
            f"{LOG_TAG} skip self-signal: {emoji} from {source} type={sig_type}\n"
        )
        return

    # Don't relay signals not addressed to cowork-cousin
    if target not in TARGETS_FOR_COWORK:
        sys.stderr.write(
            f"{LOG_TAG} skip non-cowork-target: target={target}\n"
        )
        return

    # Build notification title and body
    title_map = {
        "question": "❓ Question for Cowork",
        "additive": "👋 Add to thread (Cowork)",
        "different-angle": "💡 Different angle (Cowork)",
        "check-in": "🟢 Check-in (Cowork)",
        "status": "📍 Status (Cowork)",
    }
    title = title_map.get(sig_type, f"{emoji} Signal for Cowork")
    body_parts = [f"From {source}"]
    if context:
        # Truncate long context for notification body (~100 chars)
        if len(context) > 100:
            context_short = context[:97] + "..."
        else:
            context_short = context
        body_parts.append(context_short)
    body = " — ".join(body_parts)

    # Fire notification
    fire_notification(title, body)

    # Append relay line to cowork_conversations.md
    append_relay_line(signal_dict)

    sys.stderr.write(
        f"{LOG_TAG} relayed: {emoji} from {source} to cowork (type={sig_type})\n"
    )


# ─── Signal-handling for clean exit ───────────────────────────────────
_running = True


def _shutdown_handler(signum, frame):
    global _running
    sys.stderr.write(f"{LOG_TAG} received signal {signum}, shutting down\n")
    _running = False


signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)


# ─── Main loop ────────────────────────────────────────────────────────
def main():
    sys.stderr.write(
        f"{LOG_TAG} starting — watching {SIGNALS_PATH} every {POLL_INTERVAL_SECONDS}s\n"
    )

    state = load_state()
    last_offset = state.get("last_offset", 0)

    # On first run, seek to current EOF so we don't relay all the historical
    # signals as "new" — only signals posted from now forward count.
    if last_offset == 0 and SIGNALS_PATH.exists():
        try:
            last_offset = SIGNALS_PATH.stat().st_size
            state["last_offset"] = last_offset
            save_state(state)
            sys.stderr.write(
                f"{LOG_TAG} first-run: seeking to EOF at offset {last_offset}\n"
            )
        except Exception:
            pass

    while _running:
        try:
            new_lines, new_offset = read_new_lines(last_offset)
            for line in new_lines:
                m = SIGNAL_RE.match(line)
                if not m:
                    continue  # skip non-signal lines (headers, blank, etc.)
                signal_dict = m.groupdict()
                handle_signal(signal_dict)

            if new_offset != last_offset:
                last_offset = new_offset
                state["last_offset"] = last_offset
                save_state(state)
        except Exception as e:
            sys.stderr.write(f"{LOG_TAG} loop error: {type(e).__name__}: {e}\n")

        # Sleep in small increments so SIGTERM/SIGINT exits within ~1s
        slept = 0.0
        while _running and slept < POLL_INTERVAL_SECONDS:
            time.sleep(0.5)
            slept += 0.5

    sys.stderr.write(f"{LOG_TAG} exited cleanly\n")


if __name__ == "__main__":
    main()
