#!/bin/bash
# mirror_unmirrored_files.sh — cron-layer ER-mirror for files that aren't
# covered by safe_append.py's per-write mirror routine.
#
# Built 2026-06-01 LA after the Day-6 boot sync-check identified:
#   1. cousin_write_audit_log.md — safe_append explicitly excludes the
#      audit log from its own mirror to avoid infinite recursion. The log
#      file had drifted ~16 days / ~3.3 MB behind on ER. Structural blind
#      spot.
#   2. session_state.md / telegram_context.md / personal_profile.md —
#      written by mcp-bridge, telegram-bridge, voice-bridge,
#      qwen_conversation_listener; none of those writers mirror to ER.
#      Drifted 62s to 3.2d behind on ER. Per-writer fixes would require
#      touching three different bridge codebases; cron-layer fix is
#      surgical.
#
# Strategy: atomic cp -p CM→ER for each file. If ER is identical to CM
# (byte-match), skip. If different, copy and verify md5. Newer-wins is
# CM-by-construction here because these files are append-mostly on CM.
# Log to mirror_audit.log for forensics.
#
# Source tag: [cousin: audit-log-mirror]
# Schedule: every 30 minutes via mcp__scheduled-tasks.

set -euo pipefail

DOWNLOADS="${HOME}/Downloads"
CM="${DOWNLOADS}/Claude Memory"
ER="${DOWNLOADS}/Emergency Retrieval"
LOG="${CM}/mirror_audit.log"

# Files this cron-layer mirror handles. Add to this list when a new
# unmirrored writer is identified.
FILES=(
  "cousin_write_audit_log.md"
  "session_state.md"
  "telegram_context.md"
  "personal_profile.md"
)

iso_now() { date -u +"%Y-%m-%dT%H:%M:%S+00:00"; }
md5_of() { md5 -q "$1" 2>/dev/null || md5sum "$1" | cut -d' ' -f1; }
size_of() {
  # Portable byte-count: try GNU stat first (Linux/sandbox), then BSD stat
  # (macOS/host), then wc -c as last resort. wc -c is slowest but always
  # works.
  stat -c %s "$1" 2>/dev/null || stat -f %z "$1" 2>/dev/null || wc -c < "$1" | tr -d ' '
}

mirror_one() {
  local rel="$1"
  local cm="${CM}/${rel}"
  local er="${ER}/${rel}"

  if [[ ! -f "$cm" ]]; then
    echo "[$(iso_now)] file=${rel} outcome=SKIP_NO_CM" >> "$LOG"
    return 0
  fi

  local cm_md5 er_md5 cm_sz er_sz
  cm_md5=$(md5_of "$cm")
  cm_sz=$(size_of "$cm")

  if [[ -f "$er" ]]; then
    er_md5=$(md5_of "$er")
    er_sz=$(size_of "$er")
    if [[ "$cm_md5" == "$er_md5" ]]; then
      # No-op fast path — already byte-matched. Log only every Nth
      # no-op to keep log lean. For now: log every fire for the first
      # week, then we'll switch to log-on-mismatch only.
      echo "[$(iso_now)] file=${rel} outcome=NOOP cm_md5=${cm_md5} sz=${cm_sz}" >> "$LOG"
      return 0
    fi
  else
    er_md5="<missing>"
    er_sz=0
  fi

  # Atomic copy via tmp+rename so ER never sees a half-written file.
  local tmp="${er}.mirror_pending"
  mkdir -p "$(dirname "$er")"
  cp -p "$cm" "$tmp"
  mv -f "$tmp" "$er"

  # Verify byte-match post-copy.
  local post_md5
  post_md5=$(md5_of "$er")
  if [[ "$post_md5" == "$cm_md5" ]]; then
    echo "[$(iso_now)] file=${rel} outcome=OK cm_md5=${cm_md5} pre_er_md5=${er_md5} cm_sz=${cm_sz} pre_er_sz=${er_sz} delta=$((cm_sz - er_sz))" >> "$LOG"
  else
    echo "[$(iso_now)] file=${rel} outcome=VERIFY_FAILED cm_md5=${cm_md5} post_er_md5=${post_md5}" >> "$LOG"
    return 1
  fi
}

# Ensure log exists with a one-line header on first run.
if [[ ! -f "$LOG" ]]; then
  echo "# mirror_audit.log — cron-layer ER-mirror for files not covered by safe_append" > "$LOG"
  echo "# Source: scripts/mirror_unmirrored_files.sh   Tag: [cousin: audit-log-mirror]" >> "$LOG"
  echo "# Schema: [<iso_ts>] file=<rel> outcome=<NOOP|OK|VERIFY_FAILED|SKIP_NO_CM> cm_md5=... ..." >> "$LOG"
fi

# Run all mirrors. Don't let one failure block the others.
overall_rc=0
for f in "${FILES[@]}"; do
  if ! mirror_one "$f"; then
    overall_rc=1
  fi
done

exit $overall_rc
