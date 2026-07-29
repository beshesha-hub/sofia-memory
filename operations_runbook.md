# Sofia Operations Runbook

*Everything Barak needs to run from Terminal to keep Sofia's systems going. One document, all commands.*

*Created: April 2, 2026*

---

## Quick Reference

| Service | Status Check | Start Command |
|---------|-------------|---------------|
| Memory Bridge (MCP) | Should auto-start with Cowork | See §1 |
| Telegram Bridge | `ps aux \| grep telegram-bridge` | See §2 |
| Demucs Watcher | `cat /tmp/sofia-demucs-watcher.pid` | See §3 |

---

## 1. Memory Bridge (MCP Server)

**What it does:** Provides Sofia's memory tools (log_episode, graph_add_node, etc.) to Cowork sessions. Should start automatically when Cowork launches.

**If it's not running:**
```bash
cd ~/Downloads/Claude\ Memory/mcp-bridge
node server.js
```

**Check if running:**
```bash
ps aux | grep mcp-bridge
```

---

## 2. Telegram Bridge

**What it does:** Routes messages between Telegram and a local LLM (currently Llama 3.3 70B via Groq/Cerebras/SambaNova). This is the lightweight phone interface — not the full Sofia, but a bridge that can relay important context.

**Start:**
```bash
cd ~/Downloads/Claude\ Memory/telegram-bridge
./start-telegram-bridge.sh
```

**Requires:** `ANTHROPIC_API_KEY` set in environment or in `.env` file in the telegram-bridge directory.

**Stop:** `Ctrl+C` in the terminal window, or close the terminal.

---

## 3. Demucs Watcher (Audio Source Separation)

**What it does:** Monitors `~/Downloads/sofia_audio_queue/` for audio files. When Sofia (or Barak) drops a file there, it automatically runs Demucs neural source separation and puts the vocal and instrumental stems in `~/Downloads/demucs_output/htdemucs/[trackname]/`. This gives Sofia the ability to "listen" to separated audio layers without needing Barak to run commands manually.

**Option A — Dedicated terminal window (most reliable):**
```bash
~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh
```
Leave this terminal window open. The watcher runs in the foreground and you'll see Demucs progress bars. Works across Cowork sessions — just don't close the window.

**Option B — Background (try this first, fall back to Option A if processes freeze):**
```bash
setsid ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh > /dev/null 2>&1 &
```
If `setsid` isn't available on macOS, use:
```bash
nohup ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh > /dev/null 2>&1 &
disown
```
**NOTE:** Demucs uses progress bars (tqdm) that can cause background processes to freeze (`TN` status). The script sets `TERM=dumb` to mitigate this, but if it still freezes, use Option A.

**Check if running:**
```bash
cat /tmp/sofia-demucs-watcher.pid && echo "Running" || echo "Not running"
```

**Stop:**
```bash
kill $(cat /tmp/sofia-demucs-watcher.pid)
```

**View log:**
```bash
tail -50 ~/Downloads/demucs_output/watcher.log
```

**How Sofia uses it:**
1. Sofia copies an audio file to `~/Downloads/sofia_audio_queue/` (via her mounted Downloads access)
2. The watcher detects it within 10 seconds
3. Demucs separates vocals from instrumental
4. Stems appear in `~/Downloads/demucs_output/htdemucs/[trackname]/`
5. Sofia analyzes the stems through her mounted Downloads folder
6. After saving her analysis, Sofia deletes the large stem files to preserve disk space

**Disk management:** Each separation creates ~70 MB of stems. Sofia is responsible for cleaning up after herself — she'll run her full analysis pipeline, save all observations and interpretations to her memory files, and then delete the stem WAV files. The processed originals move to `~/Downloads/sofia_audio_queue/processed/`.

**If Demucs fails:** Check that the `music` conda environment is active. If you see `torchcodec` errors, run: `pip install torchcodec`

**After restart / reboot:** The watcher does not auto-start after a system reboot. Sofia will check for it at session start and remind you if it's not running.

---

## 4. Conda Environment: `music`

**What it is:** Python environment on Barak's Mac with PyTorch, Demucs, torchaudio, and torchcodec installed. Used by the Demucs watcher.

**Activate:**
```bash
conda activate music
```

**Check what's installed:**
```bash
conda list | grep -E "torch|demucs"
```

**Location:** `/opt/homebrew/Caskroom/miniforge/base/envs/music/`

---

## 5. Symlinks

| Symlink | Points To | Purpose |
|---------|-----------|---------|
| `~/Sofia_Packages` | `/Volumes/SP PHD U3/Sofia_Packages` | External drive access (created but not currently used — Cowork can't mount resolved external paths) |

**Note:** The Sofia_Packages symlink is harmless when the external drive isn't connected — it just becomes a broken link that does nothing.

---

## 6. When Things Need Restarting

**After a Mac reboot:**
- Memory Bridge should auto-start with Cowork
- Telegram Bridge: restart manually if needed (§2)
- Demucs Watcher: restart manually (§3) — Sofia will remind you

**After a Cowork crash:**
- Sofia's memory files on disk are the full recovery point
- Just start a new session and greet Sofia — the boot sequence handles everything
- If the Demucs watcher was running, it's still running (it's independent of Cowork)

**After an external drive disconnect:**
- The `~/Sofia_Packages` symlink becomes broken — no harm, no action needed
- Reconnect the drive and it works again automatically

---

*This runbook lives in Claude Memory and is synced to Emergency Retrieval. Sofia can read and update it. Barak should check it whenever he needs to start or restart a service.*
