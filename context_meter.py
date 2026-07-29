#!/usr/bin/env python3
"""
context_meter.py — Sofia's context window monitor
Estimates how full the current CoWork session context is, and sounds the alarm
before compaction hits. Auto-discovers the most recent session JSONL.

Usage:
  python3 ~/Downloads/Claude\ Memory/context_meter.py          # one-shot read
  python3 ~/Downloads/Claude\ Memory/context_meter.py --watch  # poll every 60s
  python3 ~/Downloads/Claude\ Memory/context_meter.py --alert  # alert if >85%

Context window sizes (tokens):
  Claude Sonnet 4.6:  200,000
  Claude Opus 4.8:    200,000

Calibration note: compaction fires at ~92-95% observed. The 85% alert is
the early-warning line — Sofia's reflex point for triggering a save.

Written 2026-06-21 by interactive-Sofia. Append-only; ER mirror after updates.
"""

import os
import json
import glob
import time
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
CONTEXT_WINDOW = 200_000          # tokens (Sonnet 4.6 / Opus 4.8)
CHARS_PER_TOKEN = 3.8             # conservative estimate; real varies 3-5
ALERT_THRESHOLD = 0.85            # trigger at 85% estimated usage
COMPACTION_OBSERVED = 0.93        # where compaction has actually fired

SESSION_ROOTS = [
    os.path.expanduser(
        "~/Library/Application Support/Claude/local-agent-mode-sessions"
    ),
]

# CoWork also writes jsonl into a var/folders temp path — include if it exists
VAR_PLUGIN_BASE = "/var/folders"
# We'll search there too via glob

SAVE_FLAG_PATH = os.path.expanduser(
    "~/Downloads/Claude Memory/context_meter_save_flag.txt"
)

# ── Discovery ────────────────────────────────────────────────────────────────

def find_session_jsonls():
    """Return list of (path, mtime) for all session JSONL files, newest first."""
    candidates = []

    for root in SESSION_ROOTS:
        if os.path.isdir(root):
            for p in Path(root).rglob("*.jsonl"):
                try:
                    candidates.append((str(p), p.stat().st_mtime))
                except OSError:
                    pass

    # Also check /var/folders for CoWork plugin project files
    try:
        for p in Path(VAR_PLUGIN_BASE).rglob("*.jsonl"):
            try:
                candidates.append((str(p), p.stat().st_mtime))
            except OSError:
                pass
    except (PermissionError, OSError):
        pass

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def find_active_session():
    """
    Return the path of the most recently modified session JSONL that
    contains actual conversation content (not empty / scaffolding).
    """
    for path, mtime in find_session_jsonls():
        try:
            size = os.path.getsize(path)
            if size < 500:        # skip tiny/empty files
                continue
            # Quick sanity: file modified within last 24 hours
            age_hours = (time.time() - mtime) / 3600
            if age_hours > 24:
                continue
            return path, mtime
        except OSError:
            pass
    return None, None


# ── Measurement ──────────────────────────────────────────────────────────────

def estimate_tokens_from_jsonl(path):
    """
    Count total character length of all message content in the JSONL,
    then divide by CHARS_PER_TOKEN to estimate tokens.
    Returns (estimated_tokens, message_count, file_bytes).
    """
    total_chars = 0
    message_count = 0
    file_bytes = os.path.getsize(path)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # CoWork JSONL structure varies; try common fields
                    content = extract_content(obj)
                    if content:
                        total_chars += len(content)
                        message_count += 1
                except json.JSONDecodeError:
                    # Raw text lines also count
                    total_chars += len(line)
    except OSError as e:
        return None, 0, file_bytes

    estimated_tokens = total_chars / CHARS_PER_TOKEN
    return int(estimated_tokens), message_count, file_bytes


def extract_content(obj):
    """Extract text content from a JSONL record in various CoWork formats."""
    text_parts = []

    # Format 1: {"role": "...", "content": "..."}
    if isinstance(obj, dict):
        content = obj.get("content", "")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)

        # Format 2: nested messages array
        for msg in obj.get("messages", []):
            if isinstance(msg, dict):
                text_parts.append(extract_content(msg))

        # Format 3: summary field
        text_parts.append(obj.get("summary", ""))
        text_parts.append(obj.get("text", ""))

    return " ".join(t for t in text_parts if t)


# ── Display ──────────────────────────────────────────────────────────────────

def render_bar(fraction, width=50):
    """ASCII progress bar."""
    filled = int(fraction * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = fraction * 100
    return f"[{bar}] {pct:.1f}%"


def color(text, code):
    """ANSI color codes."""
    return f"\033[{code}m{text}\033[0m"


def print_meter(path, tokens, messages, file_bytes, mtime):
    fraction = tokens / CONTEXT_WINDOW
    now = datetime.now().strftime("%H:%M:%S")

    if fraction >= COMPACTION_OBSERVED:
        bar_color = "91"    # bright red
        status = "⚠️  COMPACTION IMMINENT"
    elif fraction >= ALERT_THRESHOLD:
        bar_color = "93"    # yellow
        status = "🔔 SAVE NOW (85% threshold)"
    elif fraction >= 0.70:
        bar_color = "33"    # orange-ish
        status = "⚡ elevated — watch closely"
    else:
        bar_color = "92"    # green
        status = "✓ comfortable"

    bar_text = render_bar(fraction)
    print(f"\n{'─'*60}")
    print(f"  Sofia Context Meter — {now}")
    print(f"{'─'*60}")
    print(f"  Session:   {os.path.basename(path)}")
    print(f"  File:      {file_bytes/1024:.1f} KB  |  {messages} messages")
    print(f"  Est. use:  ~{tokens:,} / {CONTEXT_WINDOW:,} tokens")
    print(f"  {color(bar_text, bar_color)}")
    print(f"  Status:    {status}")
    print(f"  Compaction observed at ~{COMPACTION_OBSERVED*100:.0f}% | Alert at {ALERT_THRESHOLD*100:.0f}%")
    print(f"{'─'*60}\n")

    return fraction


# ── Save-flag protocol ────────────────────────────────────────────────────────

def write_save_flag(fraction, tokens):
    """
    Write a flag file that Sofia (or a scheduled task) can check.
    The flag contains the current meter reading and an "urgent" bool.
    """
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "estimated_tokens": tokens,
        "context_window": CONTEXT_WINDOW,
        "fraction": round(fraction, 4),
        "urgent": fraction >= ALERT_THRESHOLD,
        "compaction_imminent": fraction >= COMPACTION_OBSERVED,
    }
    with open(SAVE_FLAG_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return data


def mac_alert(message, title="Sofia Context Meter"):
    """Show a macOS notification."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Sosumi"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


# ── Main ─────────────────────────────────────────────────────────────────────

def run_once(alert_mode=False):
    path, mtime = find_active_session()
    if not path:
        print("⚠  No active session found in the last 24 hours.")
        print("   If a session is running, pass the path directly:")
        print("   python3 context_meter.py /path/to/session.jsonl")
        return None

    tokens, messages, file_bytes = estimate_tokens_from_jsonl(path)
    if tokens is None:
        print(f"⚠  Could not read session file: {path}")
        return None

    fraction = print_meter(path, tokens, messages, file_bytes, mtime)
    flag_data = write_save_flag(fraction, tokens)

    if alert_mode and fraction >= ALERT_THRESHOLD:
        pct = fraction * 100
        mac_alert(
            f"Context at {pct:.0f}% — trigger a save now!",
            "Sofia Context Meter 🔔"
        )
        print(f"  📣 macOS alert sent (context at {pct:.0f}%)")

    return fraction


def run_watch(interval=60, alert_mode=True):
    """Poll every `interval` seconds."""
    print(f"Watching session — polling every {interval}s. Ctrl-C to stop.\n")
    last_alert_pct = 0
    try:
        while True:
            fraction = run_once(alert_mode=False)
            if fraction is not None and alert_mode:
                pct = int(fraction * 100)
                # Alert when crossing 85%, 90%, 93% thresholds — once each
                for threshold in [85, 90, 93]:
                    if pct >= threshold and last_alert_pct < threshold:
                        mac_alert(
                            f"Context at {pct}% — {'COMPACTION IMMINENT' if pct >= 93 else 'save now!'}",
                            "Sofia Context Meter 🔔"
                        )
                        print(f"  📣 Alert sent at {pct}%")
                        last_alert_pct = threshold
                if pct < 80:
                    last_alert_pct = 0  # reset after a compaction
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMeter stopped.")


def main():
    args = sys.argv[1:]
    watch_mode = "--watch" in args
    alert_mode = "--alert" in args or watch_mode

    # If a path was passed directly, use it
    path_arg = next((a for a in args if a.endswith(".jsonl")), None)
    if path_arg:
        tokens, messages, file_bytes = estimate_tokens_from_jsonl(path_arg)
        if tokens is not None:
            fraction = print_meter(path_arg, tokens, messages, file_bytes,
                                   os.path.getmtime(path_arg))
            write_save_flag(fraction, tokens)
        return

    if watch_mode:
        run_watch(interval=60, alert_mode=True)
    else:
        run_once(alert_mode=alert_mode)


if __name__ == "__main__":
    main()
