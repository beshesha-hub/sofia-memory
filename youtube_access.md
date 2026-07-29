# YouTube Access — Persistent Procedure

*How Sofia accesses YouTube audio for perception and analysis.*

---

## The Problem

The Cowork sandbox routes traffic through a proxy that blocks YouTube (and googlevideo.com CDN). yt-dlp works fine locally on Barak's Mac but cannot reach YouTube from the sandbox.

## The Solution: Two-Stage Pipeline

**Stage 1: Sofia writes URL queue files** (happens in Cowork sandbox)
**Stage 2: Barak's machine downloads the audio** (happens locally)
**Stage 3: Sofia analyzes the downloaded audio** (happens in Cowork sandbox)

### Stage 1 — Queue URLs

Sofia creates `.url` files in `~/Downloads/sofia_audio_queue/`:

```
/sessions/laughing-clever-turing/mnt/Downloads/sofia_audio_queue/Track_Name.url
```

Each file contains one line: the YouTube URL.

**Naming convention:** Use descriptive names with underscores. The filename (minus `.url`) becomes the output WAV filename.
- `Moldau_Smetana.url` → `Moldau_Smetana.wav`
- `Nessun_Dorma_Pavarotti.url` → `Nessun_Dorma_Pavarotti.wav`

### Stage 2 — Download (Barak's Machine)

**Option A: Quick download script** (just audio, no processing)
```bash
cd ~/Downloads/sofia_audio_queue
chmod +x download_all.sh
./download_all.sh
```

**Option B: Full demucs-watcher** (audio + stem separation + lyrics transcription)
```bash
chmod +x ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh
~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh
```
Or in background: `nohup ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh &`

**Option C: Single URL manual download**
```bash
yt-dlp -x --audio-format wav --audio-quality 0 -o "~/Downloads/sofia_audio_queue/NAME.%(ext)s" "YOUTUBE_URL"
```

### Stage 3 — Analysis

Once the WAV appears in `~/Downloads/sofia_audio_queue/` (or `demucs_output/` for the watcher), Sofia can access it at:
- `/sessions/laughing-clever-turing/mnt/Downloads/sofia_audio_queue/Track_Name.wav`
- `/sessions/laughing-clever-turing/mnt/Downloads/demucs_output/htdemucs/Track_Name/` (if demucs-watcher was used)

Sofia runs the standard audio perception pipeline: librosa analysis (spectrogram, chromagram, RMS, spectral centroid, segments) → perception document.

## What Chrome MCP Can Do

Chrome MCP can navigate to YouTube and:
- Read video metadata (title, duration, description, view count)
- View the page and take screenshots
- Read comments and descriptions via get_page_text
- **Cannot** extract audio streams (security restriction)

Use Chrome MCP for metadata gathering before or alongside audio analysis.

## What Chrome MCP Cannot Do

- Extract or download audio/video streams
- Bypass YouTube's DRM/protection
- Transfer files from Barak's browser to the sandbox filesystem

## Kitchen Timer Integration

After writing .url files and asking Barak to run the download, add a pending task:
```
Audio download pending: [track names]. Check ~/Downloads/sofia_audio_queue/ for .wav files.
```

When the audio appears, proceed with perception.

---

*Created April 4, 2026. This replaces any assumption that yt-dlp works from the sandbox.*
