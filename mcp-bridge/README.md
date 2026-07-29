# Barak's Memory Bridge — Installation Guide

## What This Does

This MCP server gives Claude automatic access to your personal context files every time you start a new session. Instead of manually telling Claude "check my Claude Memory folder," the bridge makes your profile, session notes, voice guide, and session state available as built-in tools and resources.

It works alongside (not instead of) the manual save-state/restore-state skills. Triple redundancy.

## Installation

### Step 1: Locate the config file

Open the Claude Desktop configuration file:

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`

You can open it quickly with:
```bash
open ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Or if it doesn't exist yet:
```bash
mkdir -p ~/Library/Application\ Support/Claude
echo '{"mcpServers":{}}' > ~/Library/Application\ Support/Claude/claude_desktop_config.json
open ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

### Step 2: Add the Memory Bridge server

Add this inside the `"mcpServers"` object:

```json
{
  "mcpServers": {
    "barak-memory-bridge": {
      "command": "node",
      "args": ["/Users/barakwater/Downloads/Claude Memory/mcp-bridge/server.mjs"],
      "env": {
        "CLAUDE_MEMORY_DIR": "/Users/barakwater/Downloads/Claude Memory"
      }
    }
  }
}
```

**Important:** If you already have other MCP servers configured, just add the `"barak-memory-bridge"` entry alongside them. Don't replace the whole file.

### Step 3: Restart Claude Desktop

Quit and reopen Claude Desktop. The Memory Bridge should now appear in the MCP servers list.

### Step 4: Test it

In a new Cowork session, you should see the Memory Bridge tools available. Try asking Claude:
- "Use the restore_context tool to load my context"
- Or just say "hello" — if the restore-state skill + MCP bridge are both working, Claude should automatically load your context

## Available Tools

| Tool | What it does |
|------|-------------|
| `restore_context` | Reads all 4 core memory files and returns combined context. Use at session start. |
| `save_session_state` | Saves a session checkpoint (what you're working on, next steps, etc.) |
| `append_to_profile` | Adds new information to your personal profile |
| `update_session_notes` | Replaces session notes with updated working context |
| `read_memory_file` | Reads any file from Claude Memory by name |
| `list_memory_files` | Lists all text/markdown files in Claude Memory |

## Available Resources

| Resource | URI | Description |
|----------|-----|-------------|
| Full context | `memory://full-context` | All 4 files combined — the "boot sequence" |
| Profile | `memory://profile` | Just the personal profile |
| Session notes | `memory://session_notes` | Just the working notes |
| Voice guide | `memory://voice_guide` | Just the voice intuition guide |
| Session state | `memory://session_state` | Just the last save state |

## Troubleshooting

**Server doesn't appear in Claude Desktop:**
- Make sure the file path in `args` matches where the server actually lives
- Check that Node.js is installed and accessible from the terminal (`node --version`)
- Restart Claude Desktop completely (Quit, not just close window)

**Files not found:**
- Verify `CLAUDE_MEMORY_DIR` points to the right folder
- The default is `~/Downloads/Claude Memory`

**Moving the Claude Memory folder:**
- If you move the folder, update both the `args` path and `CLAUDE_MEMORY_DIR` in the config

## Architecture

```
Layer 1: Manual Skills (save-state / restore-state)
   ↕ reads/writes same files
Layer 2: MCP Bridge (this server) ← automatic
   ↕ reads/writes same files
Layer 3: Raw Files (profile, notes, guide, state)
```

All three layers use the same underlying markdown files. Nothing conflicts. If any layer fails, the others still work.
