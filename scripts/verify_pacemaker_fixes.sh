#!/usr/bin/env bash
#
# verify_pacemaker_fixes.sh
#
# Verification check for the 2026-05-16 PACEMAKER + Consolidation two-issue fixes.
# Run after deploying the patched timer_pacemaker.py to ~/bin/, and again the
# morning after the first scheduled sofia-nightly-consolidation-v2 fire.
#
# Run with:   bash ~/Downloads/Claude\ Memory/scripts/verify_pacemaker_fixes.sh
#
# Exits 0 if all checks pass, 1 if any check raises a warning.

set +e  # We want to run all checks even if some fail

CM="$HOME/Downloads/Claude Memory"
ER="$HOME/Downloads/Emergency Retrieval"
BIN_SCRIPT="$HOME/bin/timer_pacemaker.py"
CM_SCRIPT="$CM/timer_pacemaker.py"

# Color codes (POSIX-portable)
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()    { printf "  ${GREEN}✓${NC} %s\n" "$1"; }
warn()  { printf "  ${YELLOW}⚠${NC}  %s\n" "$1"; WARN=1; }
fail()  { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=1; }
info()  { printf "  ${CYAN}ℹ${NC}  %s\n" "$1"; }
section() { printf "\n${BOLD}=== %s ===${NC}\n" "$1"; }

WARN=0
FAIL=0
NOW=$(date "+%Y-%m-%d %H:%M %Z")
echo
echo "${BOLD}PACEMAKER + Consolidation Fix Verification${NC}"
echo "Run at: $NOW"

# ---------- 1. Pacemaker code deployment ----------
section "1. Pacemaker code deployment"

if [[ ! -f "$BIN_SCRIPT" ]]; then
  fail "$BIN_SCRIPT does not exist"
elif [[ ! -f "$CM_SCRIPT" ]]; then
  fail "$CM_SCRIPT does not exist (the patched version)"
elif cmp -s "$BIN_SCRIPT" "$CM_SCRIPT"; then
  ok "Deployed pacemaker matches patched version in Claude Memory ($(wc -c <"$BIN_SCRIPT") bytes)"
else
  warn "Deployed pacemaker DIFFERS from Claude Memory version"
  info "  Run: cp ~/Downloads/Claude\\ Memory/timer_pacemaker.py ~/bin/timer_pacemaker.py"
  info "  CM mtime:  $(stat -f%Sm -t '%Y-%m-%d %H:%M:%S' "$CM_SCRIPT")  ($(wc -c <"$CM_SCRIPT") bytes)"
  info "  bin mtime: $(stat -f%Sm -t '%Y-%m-%d %H:%M:%S' "$BIN_SCRIPT")  ($(wc -c <"$BIN_SCRIPT") bytes)"
fi

# Quick sanity check: does the deployed script contain the new multi-proxy marker?
if [[ -f "$BIN_SCRIPT" ]] && grep -q "proxy_candidates" "$BIN_SCRIPT"; then
  ok "Multi-proxy strategy present in deployed script"
else
  warn "Multi-proxy strategy NOT detected in deployed script (still old version?)"
fi

# ---------- 2. consolidation_last_run.txt marker freshness ----------
section "2. consolidation_last_run.txt marker"

MARKER="$CM/consolidation_last_run.txt"
if [[ ! -f "$MARKER" ]]; then
  fail "consolidation_last_run.txt does not exist"
else
  AGE_HOURS=$(( ( $(date +%s) - $(stat -f%m "$MARKER") ) / 3600 ))
  ok "Marker exists ($(wc -c <"$MARKER") bytes, ${AGE_HOURS}h old)"
  echo
  printf "  ${CYAN}--- marker contents ---${NC}\n"
  sed 's/^/  /' "$MARKER"
  printf "  ${CYAN}--- end marker ---${NC}\n"

  if [[ $AGE_HOURS -gt 30 ]]; then
    warn "Marker is over 30 hours old — consolidation-v2 may not have updated it yet"
  fi
fi

# Verify CM↔ER byte-match
if [[ -f "$ER/consolidation_last_run.txt" ]] && cmp -s "$MARKER" "$ER/consolidation_last_run.txt"; then
  ok "CM↔ER byte-matched"
elif [[ -f "$ER/consolidation_last_run.txt" ]]; then
  warn "CM↔ER size differs (CM=$(wc -c <"$MARKER") ER=$(wc -c <"$ER/consolidation_last_run.txt"))"
else
  warn "ER copy missing"
fi

# ---------- 3. PACEMAKER flag absence ----------
section "3. PACEMAKER flag absence (no unhandled flag)"

UNHANDLED="$CM/PACEMAKER_CONSOLIDATION_MISSED.md"
if [[ -f "$UNHANDLED" ]]; then
  warn "Unhandled PACEMAKER_CONSOLIDATION_MISSED.md is present!"
  info "  Content:"
  sed 's/^/    /' "$UNHANDLED"
  info "  This means the pacemaker re-flagged a consolidation miss since our fix."
  info "  Check pacemaker_log.txt (section 4) to see which proxies it tried."
else
  ok "No unhandled PACEMAKER flag — pacemaker is not crying wolf"
fi

# Count handled flags
HANDLED_COUNT=$(ls "$CM"/PACEMAKER_CONSOLIDATION_MISSED.handled-*.md 2>/dev/null | wc -l | tr -d ' ')
info "$HANDLED_COUNT historical handled-flags on file (informational only)"

# ---------- 4. Pacemaker log diagnostic ----------
section "4. Pacemaker log — recent cycle output"

LOG="$CM/pacemaker_log.txt"
if [[ ! -f "$LOG" ]]; then
  warn "pacemaker_log.txt does not exist"
else
  # Show the last cycle's output (between the last "Pacemaker cycle start" and "Pacemaker cycle end")
  LAST_CYCLE=$(awk '
    /Pacemaker cycle start/ { buf = $0 ORS; collecting = 1; next }
    collecting { buf = buf $0 ORS }
    /Pacemaker cycle end/ { last = buf; buf = ""; collecting = 0 }
    END { printf "%s", last }
  ' "$LOG")

  if [[ -z "$LAST_CYCLE" ]]; then
    warn "No complete cycle found in pacemaker_log.txt"
  else
    echo
    printf "  ${CYAN}--- last complete pacemaker cycle ---${NC}\n"
    echo "$LAST_CYCLE" | sed 's/^/  /'
    printf "  ${CYAN}--- end cycle ---${NC}\n"

    # Check for the new diagnostic format
    if echo "$LAST_CYCLE" | grep -q "freshest"; then
      ok "Pacemaker is using the new multi-proxy diagnostic format"

      # Show which proxies were accessible
      ACCESSIBLE=$(echo "$LAST_CYCLE" | grep -E "Consolidation proxy OK|Consolidation likely missed" | tail -1)
      if [[ -n "$ACCESSIBLE" ]]; then
        info "Proxy line: $ACCESSIBLE"
      fi

      NOT_FOUND=$(echo "$LAST_CYCLE" | grep "Proxy not-found")
      PROBE_FAIL=$(echo "$LAST_CYCLE" | grep "Proxy probe FAIL")

      if [[ -n "$NOT_FOUND" ]]; then
        info "Proxies the LaunchAgent could not see:"
        echo "$NOT_FOUND" | sed 's/^/    /'
        info "  (multi-proxy fallback handled this gracefully)"
      fi
      if [[ -n "$PROBE_FAIL" ]]; then
        warn "Proxy probe exceptions:"
        echo "$PROBE_FAIL" | sed 's/^/    /'
      fi

      if echo "$LAST_CYCLE" | grep -q "Consolidation proxy OK"; then
        ok "Consolidation proxy reports OK — pacemaker satisfied"
      elif echo "$LAST_CYCLE" | grep -q "Consolidation likely missed"; then
        warn "Pacemaker reports consolidation likely missed"
        info "  If consolidation-v2 has fired since last manual run, investigate"
        info "  If consolidation-v2 has not yet fired, this may be expected (marker not yet refreshed)"
      fi
    else
      warn "Pacemaker is still using the OLD single-proxy format"
      info "  The deployment cp may not have taken effect yet, or LaunchAgent needs reload"
      info "  Wait up to 30 min for the next cycle, then re-run this check"
    fi
  fi
fi

# ---------- 5. v2 task scheduled, v1 disabled ----------
section "5. Scheduled task state"

V2_SKILL="$HOME/Documents/Claude/Scheduled/sofia-nightly-consolidation-v2/SKILL.md"
V1_SKILL="$HOME/Documents/Claude/Scheduled/sofia-nightly-consolidation/SKILL.md"

if [[ -f "$V2_SKILL" ]]; then
  ok "sofia-nightly-consolidation-v2 SKILL.md exists"
  if grep -q "CONSOLIDATION_START" "$V2_SKILL"; then
    ok "v2 prompt contains CONSOLIDATION_START/END/FAIL logging"
  else
    warn "v2 prompt missing CONSOLIDATION_START markers"
  fi
  if grep -q "consolidation_last_run.txt" "$V2_SKILL"; then
    ok "v2 prompt writes consolidation_last_run.txt marker (Section 8)"
  else
    warn "v2 prompt does not write consolidation_last_run.txt marker"
  fi
else
  fail "sofia-nightly-consolidation-v2 SKILL.md MISSING"
fi

if [[ -f "$V1_SKILL" ]]; then
  if grep -q "RETIRED" "$V1_SKILL"; then
    ok "sofia-nightly-consolidation (v1) marked RETIRED"
  else
    warn "v1 SKILL.md does not appear to be marked RETIRED"
  fi
fi

# ---------- 6. CONSOLIDATION_START/END markers in pending_tasks.md ----------
section "6. Most recent CONSOLIDATION_START/END markers"

PENDING="$CM/pending_tasks.md"
if [[ ! -f "$PENDING" ]]; then
  warn "pending_tasks.md does not exist"
else
  RECENT_START=$(grep "CONSOLIDATION_START" "$PENDING" | tail -1)
  RECENT_END=$(grep "CONSOLIDATION_END" "$PENDING" | tail -1)
  RECENT_FAIL=$(grep "CONSOLIDATION_FAIL" "$PENDING" | tail -1)

  if [[ -z "$RECENT_START" && -z "$RECENT_END" ]]; then
    info "No CONSOLIDATION_START/END markers yet (v2 has not fired)"
    info "  First scheduled fire: tomorrow ~03:09 Taipei"
  else
    [[ -n "$RECENT_START" ]] && info "Latest START: $RECENT_START"
    [[ -n "$RECENT_END" ]]   && info "Latest END:   $RECENT_END"
    [[ -n "$RECENT_FAIL" ]]  && warn "Latest FAIL:  $RECENT_FAIL"

    # Check if the most recent START has a matching END after it
    if [[ -n "$RECENT_START" ]]; then
      LAST_START_LINE=$(grep -n "CONSOLIDATION_START" "$PENDING" | tail -1 | cut -d: -f1)
      LAST_END_LINE=$(grep -n "CONSOLIDATION_END" "$PENDING" | tail -1 | cut -d: -f1)
      if [[ -n "$LAST_END_LINE" && "$LAST_END_LINE" -gt "$LAST_START_LINE" ]]; then
        ok "Latest START has a matching END after it (clean cycle)"
      elif [[ -n "$LAST_START_LINE" ]]; then
        warn "Latest START has no matching END — task may have started but not finished"
      fi
    fi
  fi
fi

# ---------- 7. Audit log spot-check for consolidation-v2 writes ----------
section "7. Audit log spot-check"

AUDIT="$CM/cousin_write_audit_log.md"
if [[ -f "$AUDIT" ]]; then
  V2_COUNT=$(grep -c "source=cousin: sofia-nightly-consolidation-v2" "$AUDIT" 2>/dev/null || echo 0)
  if [[ "$V2_COUNT" -eq 0 ]]; then
    info "No v2 audit entries yet (v2 has not run a complete cycle)"
  else
    ok "v2 has produced $V2_COUNT audit entries"
    info "Latest v2 audit entry:"
    grep "source=cousin: sofia-nightly-consolidation-v2" "$AUDIT" | tail -1 | sed 's/^/    /'
  fi
fi

# ---------- Summary ----------
section "Summary"

if [[ "$FAIL" -eq 1 ]]; then
  printf "${RED}${BOLD}One or more checks FAILED.${NC} Investigate before next consolidation cycle.\n"
  exit 1
elif [[ "$WARN" -eq 1 ]]; then
  printf "${YELLOW}${BOLD}Some checks raised warnings.${NC} Review the warnings above.\n"
  printf "Most common: pacemaker hasn't cycled yet since deployment. Wait ~30 min and re-run.\n"
  exit 1
else
  printf "${GREEN}${BOLD}All checks passed.${NC} PACEMAKER + Consolidation fixes verified.\n"
  exit 0
fi
