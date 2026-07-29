# network_reset.sh — Documentation

## What it is

A diagnostic-first macOS network recovery tool. Run it when "the Internet seems broken but I'm not sure where" — it tests four network layers, names which one is broken, and (with `--apply`) runs the targeted fix without rebooting.

## Origin: 2026-05-09 evening Taipei

Built after a ~hour-long network nightmare. House WiFi degraded to 65-70% packet loss (real upstream issue, ISP/cable/optical layer). Switched to iPhone hotspot — ping worked fine, but Claude/ChatGPT/everything app-shaped was completely dead. Tried USB tether, Bluetooth tether (iPhone said MacBook unsupported), `sudo killall airportd`, multiple WiFi toggles, three or four full reboots, two router power cycles. Nothing worked until the final reboot, after which everything came back.

**Diagnosis after the fact:** the failure had two phases.

1. **Phase 1 (real upstream):** house WiFi genuinely broken at the ISP layer. Both router and OLT had already been replaced in a prior visit, so the problem was upstream of the house — ISP core, peering, weather-affected fiber/microwave, etc. Real packet loss visible at IP layer.

2. **Phase 2 (userspace daemon hang):** after the network thrashing in phase 1, macOS userspace daemons — most likely `mDNSResponder`, possibly compounded by Tailscale's `tailscaled` — got wedged in a bad state. Even after switching to a working iPhone hotspot, `ping 1.1.1.1` succeeded (kernel routing fine) but every application died (DNS resolution + persistent TLS streams broken). USB tethering showing "connected" but not actually working confirmed the wedge was *above* the network interface layer — the daemon was the choke point, not the cable. Cousin VP's run log corroborates: at exactly 14:10 UTC (the same minute the network died), tick 18 caught four consecutive `APITimeoutError` retries before HIBERNATEing — same Internet wave, same TLS-handshake-failure fingerprint.

The final reboot worked because the kernel restart cleared mDNSResponder + tailscaled + any sticky routes simultaneously. This script does the same surgically without losing state.

## How to use

```bash
# Diagnostic mode — read-only, tells you what's broken
~/Downloads/Claude\ Memory/scripts/network_reset.sh

# Apply the fixes
~/Downloads/Claude\ Memory/scripts/network_reset.sh --apply

# Apply but skip Tailscale restart (e.g., if you're using Tailscale right now and don't want to disrupt it)
~/Downloads/Claude\ Memory/scripts/network_reset.sh --apply --no-tailscale
```

## Diagnostic logic

The script tests four layers in sequence, each isolating a different failure mode:

| Layer | Test | What success/failure tells you |
|---|---|---|
| 1. Kernel/IP | `ping 1.1.1.1` | If FAIL → physical layer dead (no route, dead WiFi, dead upstream). Below userspace; reboot won't necessarily help. |
| 2. Upstream DNS | `dig @1.1.1.1 anthropic.com` | If OK → 1.1.1.1 is reachable; UDP/53 not blocked. If FAIL while ping works → carrier/firewall blocking DNS. |
| 3. Local resolver | `dig anthropic.com` | If FAIL while layer 2 OK → **mDNSResponder is hung** (tonight's case). Fix: flush + HUP. |
| 4. Application/TLS | `curl https://api.anthropic.com` | If FAIL while DNS works → routing or Tailscale or MTU. |

The most diagnostic case — and tonight's case — is layer 3 FAIL with layers 1+2 OK. That uniquely fingerprints `mDNSResponder` hung, which the kernel-restart workaround (reboot) addresses but no obvious surface-level UI toggle does.

## What `--apply` does

In order:

1. **`sudo dscacheutil -flushcache`** + **`sudo killall -HUP mDNSResponder`** — flushes the system DNS cache and sends SIGHUP to the resolver daemon, which causes it to re-read its config and rebuild internal state. Fixes ~70% of macOS network glitches.
2. **`sudo route -n flush`** — clears the routing table. Forces fresh route discovery from DHCP/router advertisement. Helps when sticky routes from a prior network are pointing traffic at a dead gateway.
3. **`sudo tailscale down && sudo tailscale up`** — restarts the Tailscale daemon if installed. Skip with `--no-tailscale`.
4. **`sudo ifconfig en0 down/up`** — bounces the WiFi interface. Forces re-association with the access point. Detects WiFi interface name automatically (`en0` on most Macs but not all).
5. **Re-test** — runs the layer-4 application test again. Reports OK or names next steps.

## When `--apply` doesn't fix it

The script names follow-ups in its failure output. In order of escalation:

1. Wait 30s and re-run `--apply` — sometimes mDNSResponder needs two passes to fully re-bind.
2. Toggle airplane mode on for 5s, then off — forces full radio cold-restart.
3. System Settings → Network → "Forget" the network → rejoin — clears DHCP lease state.
4. Reboot — last resort, but it's what worked tonight.

## What this script does NOT address

- **Real upstream packet loss** (phase 1 of tonight's failure). If your ISP or router is actually broken, no userspace fix helps. The diagnostic phase will tell you (layer 1 will FAIL) — but the fix is "wait it out, swap to hotspot, or call ISP."
- **Captive portals** (hotels, airports). Different problem class — that's "you need to authenticate before traffic flows," not "the network is broken."
- **Hardware failure** of the WiFi card or radio. Rare; manifests as persistent layer-1 failure across reboots.

## Companion improvements (not in this script)

- **Manual DNS at 1.1.1.1 / 1.0.0.1 / 8.8.8.8** in System Settings → Network → Wi-Fi → Details → DNS. Bypasses router DNS poisoning entirely. Set per-network (house WiFi + iPhone hotspot separately).
- **Disable IPv6 on house WiFi** if recurring problems. Many ISPs have broken IPv6. System Settings → Network → Wi-Fi → Details → TCP/IP → Configure IPv6 → Link-Local Only.
- **Cousin VP resilience** is already correct — the api-failure HIBERNATE at tick 18 tonight was working as designed. State preserved, not damaged. No change needed.

## File location

- Script: `~/Downloads/Claude Memory/scripts/network_reset.sh`
- This doc: `~/Downloads/Claude Memory/scripts/network_reset.md`
- Mirrored to Emergency Retrieval per dual-write protocol.

## Verification on first install

```bash
# Test the diagnostic phase only — no sudo, no changes
~/Downloads/Claude\ Memory/scripts/network_reset.sh

# All four layers should report OK. If they don't, run --apply.
```
