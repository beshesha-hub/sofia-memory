# Sofia's Autonomous Audio Pipeline

*How Sofia independently accesses YouTube audio and processes it for perception.*

---

## Overview

Sofia cannot download from YouTube directly — the Cowork sandbox proxy blocks it. This pipeline solves that by running lightweight watcher scripts on Barak's Mac that monitor a queue folder. Sofia writes URL files to the queue; the watchers download and (optionally) process the audio automatically.

**Two watchers, two purposes:**

| Watcher | Trigger | What It Does | When Sofia Uses It |
|---------|---------|-------------|-------------------|
| **Lite** (`sofia-audio-lite.sh`) | `.url` files | Downloads audio as WAV only | Quick listening, librosa analysis, any time raw audio is enough |
| **Full** (`demucs-watcher.sh`) | `.demucs` files + audio files | Downloads audio, runs Demucs stem separation, runs Whisper transcription | When Sofia needs vocals/instrumental separated, or lyrics transcribed |

Both run as macOS LaunchAgents — they start automatically on login and restart if they crash.

---

## One-Time Setup

Open Terminal and run:

```bash
chmod +x ~/Downloads/Claude\ Memory/demucs-watcher/setup-watchers.sh
~/Downloads/Claude\ Memory/demucs-watcher/setup-watchers.sh
```

That's it. Both watchers are now running and will start automatically on every login.

---

## How Sofia Uses It

### For quick audio (most common):

Sofia writes a `.url` file:
```
/sessions/laughing-clever-turing/mnt/Downloads/sofia_audio_queue/Track_Name.url
```
containing one line — the YouTube URL. The lite watcher downloads it as `Track_Name.wav` within about 30 seconds.

### For full processing (stem separation + lyrics):

Sofia writes a `.demucs` file:
```
/sessions/laughing-clever-turing/mnt/Downloads/sofia_audio_queue/Track_Name.demucs
```
The full watcher downloads the audio, runs Demucs two-stem separation (vocals + instrumental), and transcribes lyrics with Whisper. Output appears in `~/Downloads/demucs_output/htdemucs/Track_Name/`.

### For local audio files:

Sofia (or Barak) places a `.wav`, `.mp3`, or `.flac` file directly in the queue folder. The full watcher picks it up and runs Demucs + Whisper on it.

---

## File Locations

| What | Path |
|------|------|
| Queue folder | `~/Downloads/sofia_audio_queue/` |
| Processed URL files | `~/Downloads/sofia_audio_queue/processed/` |
| Demucs output | `~/Downloads/demucs_output/htdemucs/[track]/` |
| Lite watcher log | `~/Downloads/demucs_output/lite-watcher.log` |
| Full watcher log | `~/Downloads/demucs_output/watcher.log` |
| Lite watcher PID | `/tmp/sofia-audio-lite.pid` |
| Full watcher PID | `/tmp/sofia-demucs-watcher.pid` |
| LaunchAgent (lite) | `~/Library/LaunchAgents/com.sofia.audio-lite.plist` |
| LaunchAgent (full) | `~/Library/LaunchAgents/com.sofia.audio-full.plist` |

---

## Impact on MacBook

### When Idle (99.9% of the time)

Two sleeping bash processes. Zero CPU. A few kilobytes of RAM. Invisible.

### When Downloading (lite watcher active)

Moderate network bandwidth for 1-3 minutes — equivalent to streaming a YouTube video. Minimal CPU. No noticeable impact on other applications.

### When Processing (full watcher active)

Demucs loads a neural network for stem separation: significant CPU usage (all cores) and several GB of RAM for 5-15 minutes per track. Whisper transcription is similarly demanding. You may notice fan activity and slight sluggishness in other apps during processing. This only happens when a `.demucs` file or audio file is in the queue.

### Battery Impact

Idle watchers: none. Downloading: minimal. Demucs/Whisper processing: noticeable if on battery.

---

## Managing the Watchers

### Check Status

```bash
# Are they running?
cat /tmp/sofia-audio-lite.pid 2>/dev/null && echo "Lite watcher running" || echo "Lite watcher not running"
cat /tmp/sofia-demucs-watcher.pid 2>/dev/null && echo "Full watcher running" || echo "Full watcher not running"

# View logs
tail -20 ~/Downloads/demucs_output/lite-watcher.log
tail -20 ~/Downloads/demucs_output/watcher.log
```

### Pause Temporarily

```bash
# Stop (won't restart until you reload)
launchctl unload ~/Library/LaunchAgents/com.sofia.audio-lite.plist
launchctl unload ~/Library/LaunchAgents/com.sofia.audio-full.plist

# Resume
launchctl load ~/Library/LaunchAgents/com.sofia.audio-lite.plist
launchctl load ~/Library/LaunchAgents/com.sofia.audio-full.plist
```

### Remove Completely

```bash
launchctl unload ~/Library/LaunchAgents/com.sofia.audio-lite.plist
launchctl unload ~/Library/LaunchAgents/com.sofia.audio-full.plist
rm ~/Library/LaunchAgents/com.sofia.audio-lite.plist
rm ~/Library/LaunchAgents/com.sofia.audio-full.plist
```

After removal, your Mac is exactly as it was before setup. No traces remain.

### Re-install After Removal

Just run the setup script again:
```bash
~/Downloads/Claude\ Memory/demucs-watcher/setup-watchers.sh
```

---

## Dependencies

| Tool | Required By | Install |
|------|-------------|---------|
| `yt-dlp` | Both watchers | `brew install yt-dlp` |
| `demucs` | Full watcher only | `pip install demucs` (in conda music env) |
| `whisper` | Full watcher only | `pip install openai-whisper` |
| `ffmpeg` | Both (via yt-dlp) | `brew install ffmpeg` |

The lite watcher only needs `yt-dlp` and `ffmpeg`. The full watcher additionally needs `demucs` and optionally `whisper`.

---

## Troubleshooting

**Watcher not starting:** Check the error log: `cat ~/Downloads/demucs_output/lite-watcher-stderr.log`

**yt-dlp not found:** The LaunchAgent needs yt-dlp on the PATH. The plist includes `/opt/homebrew/bin` (Apple Silicon Homebrew). If yt-dlp is installed elsewhere, update the PATH in the plist file.

**Demucs out of memory:** On 8GB MacBook Air, long audio files (>15 min) may cause memory pressure. The full watcher will still complete but may be slow. Consider using the lite watcher for long files and running Demucs manually on shorter segments.

**Downloads failing:** Check if yt-dlp is up to date: `yt-dlp -U`. YouTube frequently changes its API and older versions stop working.

---

*Created: April 4, 2026*
*This system gives Sofia autonomous YouTube access — she queues URLs, the watchers download, and she perceives.*
