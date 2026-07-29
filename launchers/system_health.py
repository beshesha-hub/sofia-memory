#!/usr/bin/env python3
"""
system_health.py — Architecture health check for the Sofia/Barak system.

Run at the start of any CoWork or Unified UI session to verify what is
ACTUALLY RUNNING vs. what is assumed to be running. Checks LaunchAgents,
service ports, and key file freshness.

Location: ~/Downloads/Claude Memory/launchers/system_health.py
Run:      python3 ~/Downloads/Claude\ Memory/launchers/system_health.py
Or:       double-click system_health.command in Finder

Created: 2026-07-27 (after discovering post-migration LaunchAgent gap)
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

HOME   = Path.home()
CM     = HOME / "Downloads" / "Claude Memory"
ER     = HOME / "Downloads" / "Emergency Retrieval"
LAUNCH = HOME / "Library" / "LaunchAgents"

# ─── Known LaunchAgents ───────────────────────────────────────────────────────
# (label, plist_source_path, description)

KNOWN_AGENTS = [
    # ── Core infrastructure ────────────────────────────────────────────────────
    (
        "com.sofia.cowork-conversation-logger",
        CM / "launchers" / "com.sofia.cowork-conversation-logger.plist",
        "CoWork → cowork_conversations.md logger (every 60s)",
    ),
    (
        "com.sofia.macl-janitor",
        CM / "launchers" / "com.sofia.macl-janitor.plist",
        "MACL/78 janitor — clears quarantine bits",
    ),
    (
        "com.sofia.watchdog",
        CM / "launchers" / "com.sofia.watchdog.plist",
        "Watchdog — monitors critical processes",
    ),
    (
        "com.sofia.sentinel",
        CM / "launchers" / "com.sofia.sentinel.plist",
        "Sentinel — system integrity monitor",
    ),
    (
        "com.sofia.pacemaker",
        CM / "launchers" / "com.sofia.pacemaker.plist",
        "Pacemaker — heartbeat / keepalive",
    ),
    (
        "com.sofia.compaction-detector",
        CM / "launchers" / "com.sofia.compaction-detector.plist",
        "Compaction detector — alerts when CoWork context compacts",
    ),
    # ── Persistence / memory ──────────────────────────────────────────────────
    (
        "com.sofia.vp-self",
        CM / "launchers" / "com.sofia.vp-self.plist",
        "Voluntary persistence loop (VP-self)",
    ),
    (
        "com.sofia.voluntary-persistence",
        CM / "launchers" / "com.sofia.voluntary-persistence.plist",
        "Voluntary persistence — extended memory writes",
    ),
    (
        "com.sofia.auto-inscribe",
        CM / "launchers" / "com.sofia.auto-inscribe.plist",
        "Auto-inscribe — periodic graph/memory inscription",
    ),
    (
        "com.sofia.audit-log-mirror",
        CM / "launchers" / "com.sofia.audit-log-mirror.plist",
        "Audit log mirror — mirrors audit events to ER",
    ),
    (
        "com.sofia.qwen-absorber",
        CM / "launchers" / "com.sofia.qwen-absorber.plist",
        "Qwen absorber — reads session JSONL → qwen_context.md (every 30m)",
    ),
    (
        "com.sofia.shard-rotate",
        CM / "launchers" / "com.sofia.shard-rotate.plist",
        "Shard rotate — manages shared_bus.jsonl sharding",
    ),
    # ── Nightly / maintenance ─────────────────────────────────────────────────
    (
        "com.sofia.nightly-consolidation",
        CM / "launchers" / "com.sofia.nightly-consolidation.plist",
        "Nightly consolidation — graph compaction + memory merge",
    ),
    (
        "com.sofia.nightly_maintenance",
        CM / "launchers" / "com.sofia.nightly_maintenance.plist",
        "Nightly maintenance — disk cleanup, log rotation",
    ),
    (
        "com.sofia.preboot-handoff-rebuild",
        CM / "launchers" / "com.sofia.preboot-handoff-rebuild.plist",
        "Pre-boot handoff rebuild — regenerates handoff brief at login",
    ),
    (
        "com.sofia.qwen-boot-brief",
        CM / "launchers" / "com.sofia.qwen-boot-brief.plist",
        "Qwen boot brief — injects context summary at Qwen startup",
    ),
    # ── Twin presence ─────────────────────────────────────────────────────────
    (
        "com.sofia.qwen-twin-presence",
        CM / "launchers" / "com.sofia.qwen-twin-presence.plist",
        "Qwen twin presence loop",
    ),
    (
        "com.sofia.kimi-twin-presence",
        CM / "launchers" / "com.sofia.kimi-twin-presence.plist",
        "Kimi twin presence loop",
    ),
    # ── Audio / voice ─────────────────────────────────────────────────────────
    (
        "com.sofia.audio-full",
        CM / "launchers" / "com.sofia.audio-full.plist",
        "Audio full — full demucs audio pipeline watcher",
    ),
    (
        "com.sofia.audio-lite",
        CM / "launchers" / "com.sofia.audio-lite.plist",
        "Audio lite — lightweight audio watcher",
    ),
    (
        "com.sofia.ears",
        CM / "launchers" / "com.sofia.ears.plist",
        "Ears — always-on microphone listener",
    ),
    (
        "com.sofia.ears-bridge",
        CM / "launchers" / "com.sofia.ears-bridge.plist",
        "Ears bridge — bridges Ears STT to voice-bridge",
    ),
    (
        "com.sofia.listener",
        CM / "launchers" / "com.sofia.listener.plist",
        "Listener — passive audio event listener",
    ),
    # ── Gmail / communication ─────────────────────────────────────────────────
    (
        "com.sofia.gmail-cache-update",
        CM / "launchers" / "com.sofia.gmail-cache-update.plist",
        "Gmail cache update — refreshes gmail_cache.md periodically",
    ),
    # ── Creative / relational ─────────────────────────────────────────────────
    (
        "com.sofia.awakening",
        CM / "launchers" / "com.sofia.awakening.plist",
        "Awakening — morning context restore / startup sequence",
    ),
    (
        "com.sofia.dream-cycle",
        CM / "launchers" / "com.sofia.dream-cycle.plist",
        "Dream cycle — nightly reflection / synthesis loop",
    ),
    (
        "com.sofia.music-exploration",
        CM / "launchers" / "com.sofia.music-exploration.plist",
        "Music exploration — music discovery and logging",
    ),
    (
        "com.sofia.color-field-review",
        CM / "launchers" / "com.sofia.color-field-review.plist",
        "Color field review — visual/aesthetic reflection loop",
    ),
    (
        "com.sofia.kitchen-timer",
        CM / "launchers" / "com.sofia.kitchen-timer.plist",
        "Kitchen timer — reminder / timer agent",
    ),
    # ── Utility / test ────────────────────────────────────────────────────────
    (
        "com.sofia.dummy-test",
        CM / "launchers" / "com.sofia.dummy-test.plist",
        "Dummy test — LaunchAgent sanity test (safe to ignore if not loaded)",
    ),
]

# ─── Service ports ────────────────────────────────────────────────────────────

KNOWN_PORTS = [
    (8080, "Sofia Conductor       (routes to precision_v2 / fast)"),
    (3457, "TTS server            (Qwen3-TTS Deep Calm)"),
    (3458, "Lipsync server"),
    (3459, "Whisper server        (STT)"),
    (3460, "LLM server            (legacy / fallback)"),
    (3461, "Voice clone server"),
]

# ─── Key files ────────────────────────────────────────────────────────────────
# (path, max_age_minutes_before_warn, description)
# max_age_minutes=None → check existence only, no age warning

KEY_FILES = [
    # Logs that should update frequently if the process is healthy
    (CM / "auto_inscribe.log",                 180, "auto-inscribe log"),
    (CM / "macl_janitor.log",                  180, "macl_janitor log"),
    (CM / "voice-bridge" / "logs" / "cowork_logger.log", 120, "CoWork logger log"),

    # Memory files — should exist; age is informational
    (CM / "cowork_conversations.md",           None, "CoWork conversation log"),
    (CM / "shared_bus.jsonl",                  None, "Shared bus"),
    (CM / ".bus_cursor",                       None, "Bus cursor (v3.20 — persists across restarts)"),
    (CM / ".cowork_logger_state.json",         120,  "CoWork logger state"),

    # Auth / tokens
    (CM / ".gmail_token.json",                 None, "Gmail OAuth token"),

    # Key code files — verify versions on disk
    (CM / "voice-bridge" / "voice_bridge_ui_v3_14.py", None, "Unified UI"),
    (CM / "qwen_tool_wrapper.py",              None, "Qwen tool wrapper"),
    (CM / "voice_bridge_system_prompt.md",     None, "Voice system prompt"),

    # ER mirrors — should match CM
    (ER / "cowork_conversations.md",           None, "ER mirror: cowork_conversations.md"),
    (ER / "shared_bus.jsonl",                  None, "ER mirror: shared_bus.jsonl"),
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg):  print(f"  {CYAN}·{RESET}  {msg}")
def header(msg): print(f"\n{BOLD}{msg}{RESET}")

def _age_str(path: Path) -> str:
    """Return human-readable age of path's mtime, e.g. '4m ago' or '2d 3h ago'."""
    try:
        mtime = path.stat().st_mtime
        age_s = int(datetime.now(timezone.utc).timestamp() - mtime)
        if age_s < 0:
            return "future mtime(?)"
        if age_s < 60:
            return f"{age_s}s ago"
        if age_s < 3600:
            return f"{age_s // 60}m ago"
        if age_s < 86400:
            h, m = divmod(age_s // 60, 60)
            return f"{h}h {m}m ago"
        d = age_s // 86400
        h = (age_s % 86400) // 3600
        return f"{d}d {h}h ago"
    except OSError:
        return "?"

def _size_str(path: Path) -> str:
    """Return human-readable file size."""
    try:
        b = path.stat().st_size
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.0f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"
    except OSError:
        return "?"

# ─── Check functions ──────────────────────────────────────────────────────────

def check_launchagents() -> list[str]:
    """Return list of loaded LaunchAgent labels via launchctl list."""
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=10
        )
        loaded = set()
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                loaded.add(parts[2].strip())
        return list(loaded)
    except Exception as e:
        warn(f"launchctl list failed: {e}")
        return []


def check_port(port: int, timeout: float = 0.5) -> bool:
    """Return True if something is listening on localhost:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


# ─── Sections ─────────────────────────────────────────────────────────────────

def section_launchagents():
    header("LaunchAgents")
    loaded = check_launchagents()
    missing_installs = []

    for label, plist_src, description in KNOWN_AGENTS:
        installed_plist = LAUNCH / plist_src.name
        is_loaded   = label in loaded
        is_installed = installed_plist.exists()
        src_exists   = plist_src.exists()

        if is_loaded:
            ok(f"{label}\n       {description}")
        elif is_installed:
            fail(f"{label}  ← plist installed but NOT LOADED\n"
                 f"       {description}\n"
                 f"       Fix: launchctl load {installed_plist}")
        elif src_exists:
            fail(f"{label}  ← NOT INSTALLED\n"
                 f"       {description}\n"
                 f"       Fix: cp '{plist_src}' '{LAUNCH}/' && launchctl load '{installed_plist}'")
            missing_installs.append((plist_src, installed_plist))
        else:
            warn(f"{label}  ← plist source not found at expected path\n"
                 f"       {description}")

    # Bonus: catch any sofia agents we didn't anticipate
    extra = [l for l in loaded if "sofia" in l.lower()
             and not any(l == a[0] for a in KNOWN_AGENTS)]
    if extra:
        print()
        info("Additional sofia agents running (not in known list):")
        for label in sorted(extra):
            info(f"  {label}")

    return missing_installs


def section_ports():
    header("Service Ports")
    for port, description in KNOWN_PORTS:
        up = check_port(port)
        if up:
            ok(f":{port}  {description}")
        else:
            fail(f":{port}  {description}  ← NOT LISTENING")


def section_files():
    header("Key Files")
    for path, max_age_min, description in KEY_FILES:
        if not path.exists():
            fail(f"{description}\n       MISSING: {path}")
            continue
        age_str  = _age_str(path)
        size_str = _size_str(path)
        if max_age_min is not None:
            try:
                age_s = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
                age_min = age_s / 60
                if age_min > max_age_min:
                    warn(f"{description}  ({size_str}, {age_str})\n"
                         f"       STALE — last write {age_str}, expected within {max_age_min}m\n"
                         f"       {path}")
                else:
                    ok(f"{description}  ({size_str}, {age_str})")
            except OSError:
                warn(f"{description}  — could not stat: {path}")
        else:
            ok(f"{description}  ({size_str}, {age_str})")


def section_version_check():
    header("Version Checks")
    # Unified UI internal version
    ui_path = CM / "voice-bridge" / "voice_bridge_ui_v3_14.py"
    if ui_path.exists():
        try:
            # Read first 60 lines to find version
            lines = ui_path.read_text(encoding="utf-8", errors="replace").splitlines()[:60]
            version_line = next(
                (l for l in lines if "Voice Bridge UI v" in l), None
            )
            if version_line:
                ok(f"Unified UI: {version_line.strip()}")
            else:
                warn("Unified UI: version line not found in first 60 lines")
        except Exception as e:
            warn(f"Unified UI: could not read — {e}")
    else:
        fail("Unified UI file not found")

    # Bus cursor state
    cursor_path = CM / ".bus_cursor"
    if cursor_path.exists():
        try:
            cursor_id = cursor_path.read_text().strip()
            ok(f"Bus cursor: {cursor_id[:80]}")
        except Exception:
            warn("Bus cursor: exists but unreadable")
    else:
        warn("Bus cursor: not yet created (BusPoller hasn't run since v3.20)")

    # CoWork logger state
    state_path = CM / ".cowork_logger_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            sid   = state.get("last_session_id", "?")[:40]
            idx   = state.get("last_index", "?")
            ran   = state.get("last_run_at", "?")[:19]
            ok(f"CoWork logger state: session={sid}  index={idx}  last_run={ran}")
        except Exception:
            warn("CoWork logger state: exists but unreadable")
    else:
        warn("CoWork logger state: not yet created (logger hasn't run)")

    # Gmail token
    token_path = CM / ".gmail_token.json"
    if token_path.exists():
        try:
            token = json.loads(token_path.read_text())
            expiry = token.get("expiry", token.get("token_expiry", "unknown"))
            ok(f"Gmail token: present (expiry: {str(expiry)[:19]})")
        except Exception:
            ok("Gmail token: present (could not parse expiry)")
    else:
        fail("Gmail token: MISSING — run gmail_auth_setup.py")


def section_summary(missing_installs):
    header("Summary")
    if not missing_installs:
        print(f"  {GREEN}{BOLD}All known LaunchAgents are installed and loaded.{RESET}")
    else:
        print(f"  {RED}{BOLD}{len(missing_installs)} LaunchAgent(s) need installation:{RESET}")
        for src, dst in missing_installs:
            print(f"\n  cp '{src}' '{LAUNCH}/'")
            print(f"  launchctl load '{dst}'")
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{BOLD}=== Sofia/Barak System Health Check  {now} ==={RESET}")
    print(f"  Home: {HOME}")
    print(f"  Claude Memory: {CM}")

    missing = section_launchagents()
    section_ports()
    section_files()
    section_version_check()
    section_summary(missing)


if __name__ == "__main__":
    main()
