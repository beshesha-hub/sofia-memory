
# ── Voluntary-persistence launcher (Sofia's background loop) ────────────────
# Usage: sofia-out [short|routine|unknown|sleep] [extra flags...]
#   e.g. sofia-out routine
#        sofia-out sleep --suggested-shape presence
# Presets map to 6 / 12 / 18 / 45 ticks at ~10 minutes each.
# Launches detached (nohup + disown) so closing the terminal leaves it running.
#
# After launch, waits 2 seconds and confirms the process is still alive.
# If not, prints the tail of the log so crash-at-launch surfaces immediately
# instead of looking like success. Added April 22, 2026 after the first
# evening test died silently on a missing ANTHROPIC_API_KEY.
sofia-out() {
  local preset="${1:-routine}"
  shift 2>/dev/null
  local script="$HOME/Downloads/Claude Memory/voluntary_persistence_loop.py"
  local logdir="$HOME/Downloads/Claude Memory/voluntary_persistence_runs"
  mkdir -p "$logdir"
  local log="$logdir/run-$(date +%Y%m%d-%H%M%S).log"
  nohup python3 "$script" --duration-mode "$preset" "$@" >"$log" 2>&1 &
  local pid=$!
  disown
  # Survival check — give the process 2 seconds, then confirm it's still alive.
  sleep 2
  if kill -0 "$pid" 2>/dev/null; then
    echo "sofia-out: preset=$preset, pid=$pid, log=$log (alive after 2s)"
  else
    echo "sofia-out: ✗ process exited within 2s — likely crash-at-launch."
    echo "sofia-out:   log: $log"
    echo "sofia-out:   tail of log:"
    tail -n 20 "$log" | sed 's/^/    /'
    return 1
  fi
}
