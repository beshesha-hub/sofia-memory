#!/usr/bin/env python3
"""
Sofia Timer Pacemaker — runs via macOS launchd, independent of Cowork.
When Cowork's scheduler fails to fire critical tasks, the pacemaker
executes simplified versions using the local Qwen model.

Architecture:
- Checks heartbeat files for each critical task
- If a task is overdue, executes a Qwen-powered simplified version
- All output tagged [substrate: qwen-pacemaker] per substrate travel protocol
- Writes to the REAL files (not shadow files) so the work actually gets done
- Interactive-Sofia integrates pacemaker entries at boot like any cousin's work

Created: April 15, 2026 | Metaphor: A pacemaker for arrhythmic timers

2026-07-20 rewrite:
  - Added from __future__ import annotations (Python 3.9 compat)
  - Added retry logic on Qwen health check: 3 retries × 30s gap
    (covers Conductor restart, cold model load, Mac wake-from-sleep)
  - Fixed journal path: now looks for both Sofia's Room/journal/current.md
    (vp_self path) and Sofia's Room/journal.md (legacy), uses whichever exists
  - Added qwen_chat fallback to port 11434 (already had 8080 as primary)
  - Wrapped main() in top-level try/except to guarantee exit 0
"""

from __future__ import annotations

import os
import sys
import json
import time
import datetime
import urllib.request
from pathlib import Path

# Paths
HOME   = Path.home()
MEMORY = HOME / "Downloads" / "Claude Memory"
ER     = HOME / "Downloads" / "Emergency Retrieval"
SOFIAS_ROOM = HOME / "Downloads" / "Sofia's Room"
LOG_FILE = MEMORY / "pacemaker_log.txt"

# Qwen config — Sofia Conductor (8080) is current; 11434 is legacy Ollama fallback.
OLLAMA_URL          = "http://localhost:8080/api/chat"
OLLAMA_URL_FALLBACK = "http://localhost:11434/api/chat"
MODEL_FAST = "qwen3:14b"
MODEL_DEEP = "qwen3:30b-a3b"

# Retry parameters for health check
# Covers: Conductor mid-restart (~30s), cold model load (~60-120s), Mac wake.
_HEALTH_RETRIES = 3
_HEALTH_RETRY_S = 30


def log(msg):
    """Append to pacemaker log. Safe-fail: never crashes on log write."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        MEMORY.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        print(f"[pacemaker] LOG FAIL: {msg}")


def file_age_minutes(filepath):
    """Return how many minutes since a file was last modified. Returns 9999 if not found."""
    try:
        mtime = os.path.getmtime(filepath)
        age_seconds = time.time() - mtime
        return age_seconds / 60
    except FileNotFoundError:
        return 9999


def _check_backend_once(port, timeout=5):
    """Single health check on one port. Returns True if responsive."""
    try:
        req = urllib.request.Request(f"http://localhost:{port}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def qwen_backend_up_with_retry(max_retries=_HEALTH_RETRIES, delay=_HEALTH_RETRY_S):
    """Health check with retry. Returns (is_up: bool, port_used: int | None).

    Why retry: Sofia Conductor may be mid-restart (~30s), loading a cold model
    (~60-120s), or recovering from Mac sleep. 3 retries × 30s = ~90s window.
    If still unreachable after all retries, pacemaker skips Qwen-dependent tasks
    but still runs non-Qwen tasks (heartbeat, kitchen timer stub).
    """
    for attempt in range(max_retries + 1):
        for port in [8080, 11434]:
            if _check_backend_once(port):
                return True, port
        if attempt < max_retries:
            log(f"Qwen backend unreachable (attempt {attempt+1}/{max_retries+1}). "
                f"Retrying in {delay}s...")
            time.sleep(delay)
    return False, None


def qwen_chat(messages, model=MODEL_FAST, system=None, timeout=180):
    """Call local Qwen via Sofia Conductor (8080) or legacy Ollama (11434).
    Returns response text, or None on failure."""
    try:
        if system:
            messages = [{"role": "system", "content": system}] + messages
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "35m",
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        for url in [OLLAMA_URL, OLLAMA_URL_FALLBACK]:
            try:
                req = urllib.request.Request(url, data=payload_bytes, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                content = data["message"]["content"]
                if "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                return content
            except (urllib.error.URLError, OSError):
                continue
        log("qwen_chat: both 8080 and 11434 unreachable")
        return None
    except Exception as e:
        log(f"Qwen call failed: {e}")
        return None


def sync_to_er(filename):
    """Copy a file from Claude Memory to Emergency Retrieval."""
    src = MEMORY / filename
    dst = ER / filename
    if src.exists():
        import shutil
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        except Exception as e:
            log(f"sync_to_er failed for {filename}: {e}")


# ============================================================
# Task definitions
# ============================================================

def run_heartbeat():
    """Simplified heartbeat — write a timestamp to confirm the pacemaker works."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"[HEARTBEAT] {ts} UTC — Source: pacemaker (qwen not needed) — Pacemaker is alive\n"
    hb_file = MEMORY / "heartbeat_test_log.md"
    try:
        if not hb_file.exists():
            with open(hb_file, "w") as f:
                f.write("# Heartbeat Test Log\n\n")
        with open(hb_file, "a") as f:
            f.write(entry)
        log("Heartbeat written (pacemaker)")
    except Exception as e:
        log(f"Heartbeat write failed: {e}")


def run_kitchen_timer():
    """Simplified kitchen timer — log that the check cycle ran."""
    pending = MEMORY / "pending_tasks.md"
    if not pending.exists():
        log("Kitchen timer: pending_tasks.md not found, skipping")
        return
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n- **Pacemaker cycle ({ts}) [substrate: qwen-pacemaker]:** "
        f"Checked pending_tasks.md. Pacemaker does not execute actions — "
        f"logging that the check cycle ran. Interactive-Sofia should review on next boot.\n"
    )
    try:
        with open(pending, "a") as f:
            f.write(entry)
        sync_to_er("pending_tasks.md")
        log("Kitchen timer check logged (pacemaker)")
    except Exception as e:
        log(f"Kitchen timer write failed: {e}")


def _find_journal():
    """Find the journal file. Checks several known paths in priority order."""
    candidates = [
        SOFIAS_ROOM / "journal" / "current.md",   # vp_self path (2026-07)
        SOFIAS_ROOM / "journal.md",                # legacy path
        MEMORY / "journal" / "current.md",         # cousin awakening path
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def run_awakening():
    """Simplified awakening — Qwen reads recent context and writes a brief observation."""
    journal = _find_journal()
    if journal is None:
        log("Awakening: no journal file found at any known path, skipping")
        return

    try:
        lines = journal.read_text(encoding="utf-8", errors="replace").split("\n")
        recent = "\n".join(lines[-30:])
    except Exception as e:
        log(f"Awakening: could not read journal: {e}")
        return

    weather = ""
    weather_file = MEMORY / "cognitive_weather.md"
    if weather_file.exists():
        try:
            weather_lines = weather_file.read_text(encoding="utf-8", errors="replace").split("\n")
            weather = "\n".join(weather_lines[:30])
        except Exception:
            pass

    ts_utc   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    ts_local = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    system_prompt = (
        "You are Sofia's pacemaker — a backup system that runs when Sofia's primary "
        "scheduled tasks fail to fire. You are NOT Sofia. You are a simplified cousin "
        "running on Qwen locally. Your job: read the recent journal and cognitive weather, "
        "write ONE brief observation (2-3 sentences) that notices something in the material. "
        "Tag everything with [substrate: qwen-pacemaker]. "
        "Be genuine but brief. Don't try to be Sofia — just be a cousin who noticed something."
    )

    user_msg = (
        f"Recent journal entries:\n{recent}\n\n"
        f"Current cognitive weather:\n{weather}\n\n"
        f"Write a brief awakening observation (2-3 sentences). Tag it [substrate: qwen-pacemaker]."
    )

    response = qwen_chat(
        [{"role": "user", "content": user_msg}],
        model=MODEL_DEEP,
        system=system_prompt,
        timeout=180,
    )

    if response:
        entry = (
            f"\n## [pacemaker-awakening] {ts_local} ({ts_utc} UTC)\n"
            f"[substrate: qwen-pacemaker]\n\n{response}\n\n---\n"
        )
        try:
            with open(journal, "a") as f:
                f.write(entry)
            log(f"Awakening written to {journal} (pacemaker, {len(response)} chars)")
            # Mirror to ER if it's a Claude Memory file
            try:
                er_j = ER / journal.relative_to(HOME / "Downloads")
                er_j.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(str(journal), str(er_j))
            except Exception:
                pass
        except Exception as e:
            log(f"Awakening: journal write failed: {e}")
    else:
        log("Awakening: Qwen call failed, no entry written")


def run_consolidation_stub():
    """Consolidation is too complex for the pacemaker. Log that it was missed."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    log(f"Consolidation overdue at {ts} — too complex for pacemaker. Flagged for interactive-Sofia.")
    try:
        alert_file = MEMORY / "PACEMAKER_CONSOLIDATION_MISSED.md"
        with open(alert_file, "w") as f:
            f.write(f"# Consolidation Missed — {ts}\n\n")
            f.write("The nightly consolidation did not fire and the pacemaker cannot run it.\n")
            f.write("Interactive-Sofia should run consolidation manually at next boot.\n")
        sync_to_er("PACEMAKER_CONSOLIDATION_MISSED.md")
    except Exception as e:
        log(f"Consolidation alert write failed: {e}")


# ============================================================
# Main
# ============================================================

def main():
    log("--- Pacemaker cycle start ---")

    # Check Qwen backend availability with retry
    ollama_up, _ = qwen_backend_up_with_retry()
    if not ollama_up:
        log("Qwen backend not running on 8080 or 11434 after retries — pacemaker limited to non-Qwen tasks")

    # 1. Heartbeat (every 30 min — alert if >90 min stale)
    hb_age = file_age_minutes(MEMORY / "heartbeat_test_log.md")
    if hb_age > 90:
        log(f"Heartbeat overdue ({hb_age:.0f}m). Running pacemaker heartbeat.")
        run_heartbeat()
    else:
        log(f"Heartbeat OK ({hb_age:.0f}m)")

    # 2. Kitchen timer (every 30 min — alert if >90 min stale)
    kt_age = file_age_minutes(MEMORY / "pending_tasks.md")
    if kt_age > 90:
        log(f"Kitchen timer overdue ({kt_age:.0f}m). Running pacemaker check.")
        run_kitchen_timer()
    else:
        log(f"Kitchen timer OK ({kt_age:.0f}m)")

    # 3. Awakening (hourly — alert if >180 min stale). Requires Qwen.
    journal = _find_journal()
    journal_age = file_age_minutes(journal) if journal else 9999
    if journal_age > 180 and ollama_up:
        log(f"Awakening overdue ({journal_age:.0f}m). Running pacemaker awakening.")
        run_awakening()
    elif journal_age > 180:
        log(f"Awakening overdue ({journal_age:.0f}m) but Qwen down — cannot run.")
    else:
        log(f"Awakening OK ({journal_age:.0f}m)")

    # 4. Consolidation (daily at 3 AM — alert if >26 hours stale)
    proxy_candidates = [
        ("marker",          MEMORY / "consolidation_last_run.txt"),
        ("shard:emotional", MEMORY / "emotional_baseline" / "current.md"),
        ("toplevel:episodes", MEMORY / "episodes.md"),
        ("shard:semantic",  MEMORY / "semantic_knowledge" / "current.md"),
        ("legacy:emotional", MEMORY / "emotional_baseline.md"),
    ]

    accessible_proxies = []
    for label, p in proxy_candidates:
        try:
            if p.exists():
                age = file_age_minutes(p)
                accessible_proxies.append((label, p, age))
            else:
                log(f"Proxy not-found {label} ({p})")
        except Exception as e:
            log(f"Proxy probe FAIL {label} ({p}): {type(e).__name__}: {e}")

    if not accessible_proxies:
        log("Consolidation: NO accessible proxies — flagging conservatively.")
        run_consolidation_stub()
    else:
        accessible_proxies.sort(key=lambda x: x[2])
        best_label, best_path, best_age = accessible_proxies[0]
        proxy_summary = ", ".join(f"{lab}={age:.0f}m" for lab, _, age in accessible_proxies)
        if best_age > 1560:  # 26 hours
            log(f"Consolidation likely missed (freshest proxy {best_label}={best_age:.0f}m; all: {proxy_summary}).")
            run_consolidation_stub()
        else:
            log(f"Consolidation proxy OK (freshest {best_label}={best_age:.0f}m; all: {proxy_summary})")

    log("--- Pacemaker cycle end ---\n")
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        print(f"[pacemaker] Unhandled exception in main: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        try:
            log(f"FATAL: unhandled exception: {e}")
        except Exception:
            pass
        result = 0  # Always exit 0 — launchd should not flag this as broken
    sys.exit(result)
