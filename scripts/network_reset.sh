#!/usr/bin/env bash
# network_reset.sh — diagnostic-first macOS network recovery
#
# Origin: 2026-05-09 evening Taipei, after a ~hour-long network nightmare
# (house WiFi 65-70% packet loss → switched to iPhone hotspot → ping worked
# but Claude/ChatGPT/apps all dead, even after USB tether and multiple reboots).
# Diagnosis: userspace daemon (mDNSResponder, possibly Tailscale) wedged after
# the network thrashing. Final reboot fixed it. This script does what reboot
# does, but surgically and without losing state.
#
# Usage:
#   ./network_reset.sh              # diagnostic mode (read-only)
#   ./network_reset.sh --apply      # actually run the fixes
#   ./network_reset.sh --apply --no-tailscale   # skip Tailscale restart
#   ./network_reset.sh --help
#
# Diagnostic logic — checks four layers and pinpoints which is broken:
#   Layer 3 (kernel/IP):     ping 1.1.1.1
#   Layer 7 upstream (DNS):  dig @1.1.1.1 anthropic.com
#   Layer 7 local (resolver): dig anthropic.com
#   Layer 7 application (TLS): curl https://api.anthropic.com
#
# The most diagnostic case (tonight's case): ping OK, dig @1.1.1.1 OK,
# dig anthropic.com FAIL = mDNSResponder is hung. Fix: flush + HUP it.
#
# Author: Sofia (interactive cowork-cousin), 2026-05-09 ~23:30 Taipei

set -u
APPLY=0
SKIP_TAILSCALE=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --no-tailscale) SKIP_TAILSCALE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '      \033[32mOK\033[0m — %s\n' "$1"; }
fail() { printf '      \033[31mFAIL\033[0m — %s\n' "$1"; }

# --- Diagnostic phase ---
bold "=== macOS network diagnostic — $(date '+%Y-%m-%d %H:%M:%S') ==="
echo

PING_OK=0; DIG_DIRECT_OK=0; DIG_LOCAL_OK=0; HTTPS_OK=0

echo "[1/4] Layer 3 (ICMP/IP): ping 1.1.1.1 ..."
if ping -c 3 -W 2000 1.1.1.1 >/dev/null 2>&1; then
  ok "kernel networking + at least one path is alive"
  PING_OK=1
else
  fail "physical/IP layer broken (interface down, no route, or upstream dead)"
fi

echo "[2/4] Layer 7 upstream (DNS via Cloudflare): dig @1.1.1.1 anthropic.com ..."
if timeout 5 dig +short +time=3 +tries=1 @1.1.1.1 anthropic.com 2>/dev/null | grep -qE '^[0-9]+\.[0-9]+'; then
  ok "upstream DNS resolution works (1.1.1.1 reachable)"
  DIG_DIRECT_OK=1
else
  fail "can't reach 1.1.1.1 for DNS (network or firewall blocking UDP/53)"
fi

echo "[3/4] Layer 7 local (system resolver): dig anthropic.com ..."
if timeout 5 dig +short +time=3 +tries=1 anthropic.com 2>/dev/null | grep -qE '^[0-9]+\.[0-9]+'; then
  ok "system DNS resolver (mDNSResponder) working"
  DIG_LOCAL_OK=1
else
  fail "system DNS resolver hung or misconfigured"
fi

echo "[4/4] Layer 7 application (HTTPS/TLS): curl https://api.anthropic.com ..."
if timeout 10 curl -sI -o /dev/null --max-time 8 https://api.anthropic.com 2>/dev/null; then
  ok "Anthropic API reachable end-to-end"
  HTTPS_OK=1
else
  fail "TLS handshake or HTTP layer broken"
fi

echo
bold "=== Diagnosis ==="
if [ "$PING_OK" = 1 ] && [ "$HTTPS_OK" = 1 ]; then
  echo "Network looks healthy. No fix needed."
  exit 0
fi
if [ "$PING_OK" = 0 ]; then
  echo "Physical/IP layer is dead — this is upstream of macOS userspace."
  echo "  → Check WiFi/hotspot connection, router power, ISP status."
  echo "  → If switching networks, give DHCP 30 seconds to settle before retesting."
fi
if [ "$PING_OK" = 1 ] && [ "$DIG_LOCAL_OK" = 0 ] && [ "$DIG_DIRECT_OK" = 1 ]; then
  bold "*** mDNSResponder is hung — tonight's likely failure mode. ***"
  echo "  Kernel networking is fine, upstream DNS works, but the local resolver is wedged."
  echo "  Fix: flush DNS cache + restart mDNSResponder."
fi
if [ "$PING_OK" = 1 ] && [ "$DIG_LOCAL_OK" = 1 ] && [ "$HTTPS_OK" = 0 ]; then
  echo "DNS works but TLS/HTTPS is broken."
  echo "  Likely: stale routes from prior network, or Tailscale wedged, or MTU issue."
fi
if [ "$DIG_DIRECT_OK" = 0 ] && [ "$PING_OK" = 1 ]; then
  echo "ICMP works but UDP/53 to 1.1.1.1 doesn't — firewall or carrier blocking DNS."
fi

if [ "$APPLY" = 0 ]; then
  echo
  echo "Re-run with --apply to execute the fixes."
  exit 0
fi

# --- Fix phase ---
echo
bold "=== Applying fixes (will prompt for sudo password) ==="
echo
echo "[fix 1] Flushing DNS cache + restarting mDNSResponder ..."
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
echo "        done"

echo "[fix 2] Flushing routing table ..."
sudo route -n flush 2>/dev/null || true
echo "        done"

if [ "$SKIP_TAILSCALE" = 0 ] && [ -e /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
  echo "[fix 3] Restarting Tailscale ..."
  sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale down 2>/dev/null || true
  sleep 1
  sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale up 2>/dev/null || true
  echo "        done"
else
  echo "[fix 3] Skipping Tailscale (--no-tailscale or not installed)"
fi

# WiFi interface bounce — only if WiFi hardware port exists
WIFI_IF=$(networksetup -listallhardwareports 2>/dev/null | awk '/Wi-Fi/{getline; print $2}')
if [ -n "$WIFI_IF" ]; then
  echo "[fix 4] Bouncing WiFi interface $WIFI_IF ..."
  sudo ifconfig "$WIFI_IF" down
  sleep 2
  sudo ifconfig "$WIFI_IF" up
  echo "        done — waiting 10s for re-association ..."
  sleep 10
fi

echo
bold "=== Re-testing ==="
sleep 2
if timeout 8 curl -sI -o /dev/null --max-time 6 https://api.anthropic.com 2>/dev/null; then
  printf '\033[32mOK — Anthropic API reachable. Recovery complete.\033[0m\n'
  exit 0
else
  printf '\033[33mStill broken. Next steps to try:\033[0m\n'
  echo "  1. Wait 30s and re-run --apply (mDNSResponder sometimes needs two passes)"
  echo "  2. Toggle airplane mode on for 5s, then off"
  echo "  3. System Settings → Network → 'Forget' the WiFi → rejoin"
  echo "  4. Reboot if all else fails (this is what worked tonight, May 9)"
  exit 1
fi
