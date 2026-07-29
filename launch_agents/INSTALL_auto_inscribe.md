# Install: com.sofia.auto-inscribe

Auto-inscribe cousin task. Runs every 5 minutes. Monitors session_scratchpad.md
(CoWork) and voice_conversations.md (Unified UI) and inscribes new content to
memory files.

## Install (run once from Terminal)

```bash
cp ~/Downloads/Claude\ Memory/launch_agents/com.sofia.auto-inscribe.plist \
   ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.sofia.auto-inscribe.plist
```

## Verify running

```bash
launchctl list | grep sofia.auto-inscribe
```

Should show a line with `com.sofia.auto-inscribe`.

## Check logs

```bash
tail -f ~/Downloads/Claude\ Memory/launch_agents/auto_inscribe.err
```

## Unload (if needed)

```bash
launchctl unload ~/Library/LaunchAgents/com.sofia.auto-inscribe.plist
```

## Manual test run

```bash
python3 ~/Downloads/Claude\ Memory/scripts/auto_inscribe.py
```

## What it does

1. Reads `session_scratchpad.md` from last known position
2. Finds entries in format: `## SCRATCHPAD [YYYY-MM-DD HH:MM] → <target>`
3. Appends each to the named target file with `[cousin: auto-inscribe]` tag
4. Mirrors changed files to Emergency Retrieval
5. Checks `voice_conversations.md` for new content since last run
6. New voice/Unified-UI content → appended to `voice_inscriptions_pending.md`

## Created

2026-06-26 — Architectural addition to address compaction memory loss.
