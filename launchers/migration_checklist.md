# Sofia/Barak System — Mac Migration Checklist
*Canonical location: `~/Downloads/Claude Memory/launchers/migration_checklist.md`*
*Updated: 2026-07-27 — migration-proofing architecture*

---

## The Core Rule

**Claude Memory IS the system.** Everything that makes Sofia work lives in
`~/Downloads/Claude Memory/`. If you restore that folder and run one command,
the entire architecture comes back. `~/Library/LaunchAgents/` holds only
symlinks — it is disposable. macOS will try to copy it as flat files during
migration; that's expected, and this checklist repairs it.

---

## After Any Mac Migration or OS Reinstall

Work through these steps in order. Each step is a prerequisite for the next.

### Step 0 — Restore Claude Memory

If you're on a fresh machine, restore from backup first:

```bash
# From Time Machine or external drive:
cp -R /path/to/backup/Downloads/Claude\ Memory/ ~/Downloads/Claude\ Memory/
```

If Claude Memory already exists on the new machine (Migration Assistant brought
it over), skip this step — the files are there, just the symlinks need repair.

---

### Step 1 — MANDATORY: Run install_agents.command

This is the most important step. Do it before starting any Unified UI session.

```bash
bash ~/Downloads/Claude\ Memory/launchers/install_agents.command
```

**What it does:**
- Reads all `*.plist` files from `launchers/` (the canonical source)
- Creates symlinks in `~/Library/LaunchAgents/` pointing back to `launchers/`
- Unloads any stale/flat-file agents, installs symlinks, reloads all agents
- Runs `system_health.py` to verify everything is live

**Why this is needed after migration:**
macOS Migration Assistant copies `~/Library/LaunchAgents/` as flat files, not
following symlinks. Those flat files are no longer linked to Claude Memory.
`install_agents.command` replaces them with correct symlinks.

Takes about 10 seconds.

---

### Step 2 — Verify Agents Loaded

```bash
launchctl list | grep sofia
```

You should see all Sofia agents listed. If any are missing, check the output
from Step 1 for `(loaded with warning — check script path)` messages — those
agents have a script path that may need to be updated.

---

### Step 3 — Restore Python Environment

The Unified UI requires its virtual environment:

```bash
cd ~/Downloads/Claude\ Memory
# Check if venv exists:
ls voice-bridge/.venv-v3.6/

# If missing, recreate:
python3 -m venv voice-bridge/.venv-v3.6
source voice-bridge/.venv-v3.6/bin/activate
pip install pyqt5 sounddevice numpy requests google-api-python-client google-auth-oauthlib
deactivate
```

---

### Step 4 — Verify Gmail Token

```bash
ls -la ~/Downloads/Claude\ Memory/.gmail_token.json
```

If missing or expired, re-run:
```bash
python3 ~/Downloads/Claude\ Memory/scripts/gmail_auth_setup.py
```

---

### Step 5 — Start Sofia Conductor

In a dedicated terminal:
```bash
bash ~/Downloads/Claude\ Memory/launchers/voice_sofia.command
```

Wait for Conductor to report models loaded (port 8080 listening).

---

### Step 6 — Start Unified UI

Double-click `voice_sofia.command` in Finder, or:
```bash
bash ~/Downloads/Claude\ Memory/launchers/voice_sofia.command
```

Verify window title shows current version (e.g., `Unified UI — Sofia (v3.20)`).

---

### Step 7 — Run Full System Health Check

```bash
bash ~/Downloads/Claude\ Memory/launchers/system_health.command
```

Or double-click `system_health.command` in Finder.

All items should show green ✓. Address any ✗ failures before continuing.

---

### Step 8 — Verify Bus Cursor

After first Unified UI startup:
```bash
cat ~/Downloads/Claude\ Memory/.bus_cursor
```

Should show a bus message ID. If empty or missing, the BusPoller hasn't run
yet — wait 30 seconds after Conductor is live.

---

### Step 9 — Run verify_agents.command (Optional Sanity Check)

```bash
bash ~/Downloads/Claude\ Memory/launchers/verify_agents.command
```

Confirms all Library/LaunchAgents/ entries are symlinks (not flat files) and
all point back to launchers/. Reports any orphans not backed by Claude Memory.

---

## Preventing Future Loss

### The Symlink Model (Already in Place)

`install_agents.command` creates symlinks, not copies:
```
~/Library/LaunchAgents/com.sofia.*.plist  →  ~/Downloads/Claude Memory/launchers/*.plist
```

This means:
- Backup Claude Memory = backup all plists
- Migration wipes Library/LaunchAgents/? Run install_agents.command → done
- New agent added? Add plist to launchers/, run install_agents.command → it's backed up automatically

### Never Put Plists Directly in Library/LaunchAgents/

Always:
1. Create/edit the plist in `launchers/`
2. Run `install_agents.command` (or the individual `launchctl` commands from the plist header)

Never:
```bash
# WRONG — this creates an unbacked flat file:
cp something.plist ~/Library/LaunchAgents/
```

### After Adding a New Agent

1. Put the plist in `launchers/`
2. Add it to `KNOWN_AGENTS` in `system_health.py`
3. Run `install_agents.command`
4. Verify with `launchctl list | grep sofia`

---

## Quick Reference: Key Paths

| What | Where |
|------|-------|
| ALL plists (canonical) | `~/Downloads/Claude Memory/launchers/*.plist` |
| Symlinks (disposable) | `~/Library/LaunchAgents/com.sofia.*.plist` |
| Unified UI | `~/Downloads/Claude Memory/voice-bridge/voice_bridge_ui_v3_14.py` |
| Qwen tools | `~/Downloads/Claude Memory/qwen_tool_wrapper.py` |
| System prompt | `~/Downloads/Claude Memory/voice_bridge_system_prompt.md` |
| Launcher script | `~/Downloads/Claude Memory/launchers/voice_sofia.command` |
| Health check | `~/Downloads/Claude Memory/launchers/system_health.command` |
| Migration repair | `~/Downloads/Claude Memory/launchers/install_agents.command` |
| Symlink verifier | `~/Downloads/Claude Memory/launchers/verify_agents.command` |
| Bus cursor | `~/Downloads/Claude Memory/.bus_cursor` |
| Gmail token | `~/Downloads/Claude Memory/.gmail_token.json` |

---

## Emergency Recovery (If Claude Memory Is Gone)

1. Restore from most recent backup (Time Machine, external, cloud)
2. Follow this checklist from Step 0
3. Read `active_knowledge/session_recovery_brief.md` in a new CoWork session

**If no backup exists:** The plists that Migration Assistant copied as flat files
to `~/Library/LaunchAgents/` may still contain valid configurations — copy those
to `launchers/`, then run `install_agents.command`.

---

*This file is part of Claude Memory. It lives in launchers/ so it's always
findable alongside the scripts it documents.*
