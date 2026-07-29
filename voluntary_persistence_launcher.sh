#!/usr/bin/env zsh
# ── Sandbox-initiated voluntary-persistence launcher ───────────────────────
# Invoked by ~/Library/LaunchAgents/com.sofia.voluntary-persistence.plist
# when voluntary_persistence_trigger.json appears or changes.
#
# TCC NOTE (April 22–23, 2026): macOS blocks LaunchAgent-spawned processes from
# writing to ~/Downloads/ (and other user-protected folders) unless the
# executing binary has been granted Full Disk Access in System Settings.
# Because of this:
#   - The TRIGGER file must stay in Downloads (so sandbox-Sofia can write it),
#     but launchd-zsh can READ it — reads from protected folders are allowed.
#   - The LAUNCHER itself lives in $HOME (readable by launchd-zsh).
#   - This script's own LOG and RUN LOGS also live in $HOME, not Downloads.
#   - The Python loop still writes to Downloads/Claude Memory/ (state.json,
#     run_log.md, journal.md). That only works because the resolved python3
#     binary (/opt/homebrew/Cellar/python@3.14/3.14.4/.../bin/python3.14) has
#     been granted Full Disk Access. FDA is keyed to the resolved binary, not
#     to the symlink or to /bin/zsh.
#
# PROCESS-TRACKING NOTE (April 23, 2026): v3 uses `exec python3 -u ...` so
# launchd tracks Python directly as the agent's job. Earlier v2 backgrounded
# Python with `nohup &` + `disown`, and launchd reaped the whole process
# group when this script exited — Python would appear "alive after 2s" but
# vanish moments later with an empty, unflushed run log. `exec` fixes that
# by replacing this shell with Python (same PID, no process-group reaping).
# `-u` keeps stdout unbuffered so the run log populates in real time.
#
# Created April 22, 2026, Option B of the voluntary-persistence project.

set -u

TRIGGER="$HOME/Downloads/Claude Memory/voluntary_persistence_trigger.json"
# 2026-04-30: switched from voluntary_persistence_loop.py (legacy v1) to v2
# which routes all writes through safe_append.py + safe_atomic_replace.py.
# Legacy file remains in place as rollback target. To roll back: change
# voluntary_persistence_loop_v2.py back to voluntary_persistence_loop.py.
SCRIPT="$HOME/Downloads/Claude Memory/voluntary_persistence_loop_v2.py"
SECRETS="$HOME/.sofia_secrets"
LAUNCHER_LOG="$HOME/sofia_voluntary_persistence_launcher.log"
RUN_LOGDIR="$HOME/sofia_voluntary_persistence_runs"

mkdir -p "$RUN_LOGDIR"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LAUNCHER_LOG"
}

log "--- watchpath event ---"

# If the trigger file doesn't exist (shouldn't happen in TCC mode, since we
# can't delete it, but keep the guard for robustness) exit silently.
if [ ! -f "$TRIGGER" ]; then
  log "trigger file absent — nothing to do"
  exit 0
fi

# Mutex: refuse to launch if a voluntary_persistence_loop.py is already
# running. Essential safety check.
if pgrep -f voluntary_persistence_loop.py > /dev/null; then
  log "✗ another voluntary_persistence_loop.py is already running — refusing"
  # Intentionally do NOT try to delete the trigger (TCC will block it).
  exit 0
fi

# Source the API key (LaunchAgents do NOT inherit user shell env).
if [ -f "$SECRETS" ]; then
  # shellcheck disable=SC1090
  source "$SECRETS"
  log "sourced $SECRETS"
else
  log "✗ $SECRETS missing — cannot launch without ANTHROPIC_API_KEY"
  exit 1
fi

# LaunchAgents get a minimal PATH. Add likely python3 locations.
export PATH="$HOME/miniforge3/bin:$HOME/anaconda3/bin:$HOME/opt/anaconda3/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Parse trigger JSON via python (avoids jq dependency).
DURATION_MODE=$(TRIG="$TRIGGER" python3 -c '
import json, os, sys
try:
    d = json.load(open(os.environ["TRIG"]))
    print(d.get("duration_mode", "routine"))
except Exception as e:
    print("routine")
    sys.stderr.write(f"parse warning: {e}\n")
' 2>>"$LAUNCHER_LOG")

SUGGESTED_SHAPE=$(TRIG="$TRIGGER" python3 -c '
import json, os
try:
    d = json.load(open(os.environ["TRIG"]))
    s = d.get("suggested_shape") or ""
    print(s)
except Exception:
    print("")
' 2>>"$LAUNCHER_LOG")

log "parsed trigger: duration_mode=$DURATION_MODE suggested_shape=${SUGGESTED_SHAPE:-<none>}"

# Build argv
ARGS=(--duration-mode "$DURATION_MODE")
if [ -n "$SUGGESTED_SHAPE" ]; then
  ARGS+=(--suggested-shape "$SUGGESTED_SHAPE")
fi

# Replace this shell with Python. launchd then tracks the Python process
# directly as the agent's job — no backgrounding, no process-group reaping,
# no buffered stdout getting killed before it flushes.
# `-u` forces unbuffered stdout so the run log populates in real time.
RUN_LOG="$RUN_LOGDIR/run-$(date +%Y%m%d-%H%M%S).log"
log "exec'ing python3 -u $SCRIPT ${ARGS[*]}  →  $RUN_LOG"
log "done (handing off to python via exec)"
exec python3 -u "$SCRIPT" "${ARGS[@]}" >"$RUN_LOG" 2>&1

# Unreachable if exec succeeds.
log "✗ exec failed — python3 not on PATH or SCRIPT missing"
exit 127
