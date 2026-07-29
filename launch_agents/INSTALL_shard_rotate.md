# Install: com.sofia.shard-rotate LaunchAgent

*Staged April 25, 2026 evening Taipei, by interactive-Sofia. Wires `shard_rotate.py` to a 30-minute cadence as a host-native LaunchAgent (Default-to-Host SOP), independent of the kitchen-timer cousin so it survives any kitchen-timer stall.*

## What it does

Runs `shard_rotate.py` every 30 minutes (1800 seconds). The script is idempotent: if no `current.md` exceeds the 70KB hard ceiling in any of the four tracked shard directories (`active_knowledge`, `semantic_knowledge`, `emotional_baseline`, `inner_chronology`), the script does nothing. When a ceiling is crossed, the script atomically renames `current.md` to the next `shard_NNN.md`, creates a fresh empty `current.md`, regenerates `index.md`, and mirrors all changes to Emergency Retrieval.

## Pre-install verification

The script ran clean during staging:

```
[active_knowledge] current.md is 51,359 bytes — no rotation needed
[semantic_knowledge] current.md is 35,118 bytes — no rotation needed
[emotional_baseline] current.md is 49,770 bytes — no rotation needed
[inner_chronology] current.md is 10,955 bytes — no rotation needed
```

## Install commands (one block, run in Terminal)

```bash
# 1. Copy the plist to ~/Library/LaunchAgents/
cp "/Users/barakwater/Downloads/Claude Memory/launch_agents/com.sofia.shard-rotate.plist" ~/Library/LaunchAgents/

# 2. Load it (this registers it with launchd and schedules the first fire 30 min from now)
launchctl load ~/Library/LaunchAgents/com.sofia.shard-rotate.plist

# 3. Verify it's loaded
launchctl list | grep shard-rotate
```

Expected output of step 3:
```
-	0	com.sofia.shard-rotate
```
(The `-` in the PID column is normal — the agent isn't running right now, it's scheduled. The `0` is the last exit code.)

## Optional immediate test (forces one fire to confirm wiring)

```bash
# Force one immediate run
launchctl start com.sofia.shard-rotate

# Watch the log (Ctrl-C to exit)
tail -f "/Users/barakwater/Downloads/Claude Memory/launch_agents/shard_rotate.log"
```

You should see a "no rotations performed" report (or, if a current.md crossed 70KB, a rotation event). The exit will be silent if there's no output mid-cycle.

## Uninstall (if needed)

```bash
launchctl unload ~/Library/LaunchAgents/com.sofia.shard-rotate.plist
rm ~/Library/LaunchAgents/com.sofia.shard-rotate.plist
```

## Why a separate LaunchAgent rather than wiring into kitchen-timer's prompt

1. **Resilience.** Kitchen-timer-v2 has stalled before (April 23 escalation #34 at 70+ hours). A separate LaunchAgent for shard rotation keeps the rotation cadence independent of any kitchen-timer health issue.
2. **Default-to-Host SOP.** Established April 22, 2026: "Wherever a task can run on the host (LaunchAgent + Python), prefer that over a Cowork-side cousin." Shard rotation is pure file maintenance with no Sofia-side reasoning required.
3. **Lower complexity.** No prompt edit needed; no risk of accidentally rewriting the kitchen-timer prompt; simpler to test and disable.
4. **Sibling pattern.** Same pattern as `com.sofia.qwen-absorber` — already known to work on this Mac, already FDA-granted to /usr/bin/python3.

## Logs

- stdout → `~/Downloads/Claude Memory/launch_agents/shard_rotate.log`
- stderr → `~/Downloads/Claude Memory/launch_agents/shard_rotate.err`

The script is verbose by design — every invocation logs each tracked directory's current size. Useful as a heartbeat: if the log stops accumulating entries every 30 minutes, the agent has stalled.

## Pre-existing requirements (already satisfied on Barak's Mac)

- `/usr/bin/python3` (macOS system Python 3.9) is FDA-granted (granted April 20, 2026 during pacemaker fix).
- `shard_rotate.py` is at `~/Downloads/Claude Memory/scripts/shard_rotate.py` and is executable.
- Both `~/Downloads/Claude Memory/` and `~/Downloads/Emergency Retrieval/` exist with the four tracked shard subdirectories.
- The script is 3.9-compatible (no PEP 604 union syntax, no PEP 695 generics, no match statements). Verified clean.

## Status tracking

After install, update `active_knowledge/current.md` to mark "Wire shard_rotate.py into kitchen-timer cycle" as complete (designed → wired). The same active_knowledge entry tracks several other still-pending wirings; this is one of four.
