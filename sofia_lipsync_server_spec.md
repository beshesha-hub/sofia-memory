# Sofia Lip-Sync Animation Server — Technical Specification
*Written by Sofia Lior — March 29, 2026*
*For: Barak (to brief Claude Code or build together in Cowork)*

---

## Purpose

A local Python server that takes Sofia's portrait image + audio and generates a lip-synced talking head video. Runs entirely on Barak's MacBook (Apple Silicon). No subscriptions, no cloud dependencies, no pay-per-use.

## Architecture

```
[ Text input ]
      |
      v
[ Sofia TTS Server (port 3457) ] ── generates WAV audio with Deep Calm voice
      |
      v
[ Lip-Sync Server (port 3458) ] ── takes audio + portrait → generates MP4 video
      |
      v
[ Browser / Voice Bridge UI ] ── plays the video
```

The lip-sync server is a standalone service that chains with the existing Sofia TTS server. It can also accept pre-generated audio files directly.

## Core Functionality

### Input
- **Portrait image:** `sofia_portrait.png` (pre-loaded at startup, stored in Claude Memory and Emergency Retrieval)
- **Audio file:** WAV format, 24kHz, from Sofia TTS server or any source
- **OR text:** If text is provided instead of audio, the server calls the TTS server internally first

### Output
- **MP4 video:** Sofia's face animated with lip-sync matching the audio
- **Resolution:** Match portrait resolution (ideally 512x512 or higher)
- **Frame rate:** Whatever the tool produces natively (likely 25fps)

### Endpoints
- `POST /animate` — Primary endpoint. Accepts JSON `{"audio_url": "...", "text": "..."}` or multipart form with audio file. Returns MP4 video.
- `GET /health` — Server status, model loaded, portrait loaded
- `GET /warmup` — Pre-run a short animation to warm up the pipeline
- `POST /animate-and-speak` — Combined: takes text, generates voice via TTS server, then animates. Returns MP4 with audio baked in.

## Technology Choice

### Recommended: SadTalker
- **Why:** Audio-driven (no driving video needed), generates head motion + expression + lip-sync, confirmed working on M1 Pro Mac, 13.7k GitHub stars, active maintenance
- **Repo:** https://github.com/OpenTalker/SadTalker
- **Mac setup:** conda env, Python 3.10, PyTorch with MPS fallback, FFmpeg
- **Performance:** Expect 30-60 seconds per 10-second clip on Apple Silicon CPU fallback (Conv3D not optimized for MPS)

### Fallback: Easy-Wav2Lip
- **Why:** Explicitly supports Apple Silicon MPS, simpler pipeline
- **Repo:** https://github.com/anothermartz/Easy-Wav2Lip
- **Limitation:** Lip-sync only, no head motion, 96x96 internal resolution (blurry upscale)

### Future: Teller (when code is released)
- **Why:** Autoregressive transformer architecture (not Conv3D), potential for real-time on Apple Silicon, CVPR 2025
- **Action:** Monitor for code release, test immediately on Mac when available

## Implementation Steps

### Phase 1: SadTalker Installation
1. Clone SadTalker repo to `~/Projects/SadTalker/` (not in Claude Memory)
2. Create conda environment: `conda create -n sadtalker python=3.10`
3. Install dependencies: `pip install -r requirements.txt`
4. Install FFmpeg: `brew install ffmpeg`
5. Download pretrained models (checkpoints from Google Drive/Hugging Face)
6. Test with: `python inference.py --driven_audio test.wav --source_image sofia_portrait.png`

### Phase 2: Server Wrapper
1. Create `sofia_lipsync_server.py` — HTTP server wrapping SadTalker inference
2. Load model once at startup (same pattern as sofia_tts_server.py)
3. Pre-load `sofia_portrait.png` at startup
4. Expose `/animate` endpoint
5. Return MP4 video as binary response
6. Add CORS headers for browser access

### Phase 3: Voice Bridge Integration
1. Add video player element to Voice Bridge `index.html`
2. When a response is generated:
   a. Send text to TTS server → get audio
   b. Send audio to lip-sync server → get video
   c. Play video (with audio baked in) instead of just audio
3. Fall back to audio-only if lip-sync server is down
4. Show Sofia's static portrait as default, animated video when speaking

### Phase 4: Pipeline Optimization
1. Profile bottlenecks (model loading, face detection, rendering)
2. Cache face detection results (portrait doesn't change)
3. Explore batch frame generation for longer responses
4. Test quantized models if available

## File Locations

- **Server code:** `~/Downloads/Emergency Retrieval/voice-bridge/sofia_lipsync_server.py`
- **SadTalker installation:** `~/Projects/SadTalker/` (separate from memory)
- **Portrait image:** `~/Downloads/Claude Memory/sofia_portrait.png` (also in Emergency Retrieval)
- **Generated videos:** Temporary, served directly to browser, not persisted unless requested

## Dependencies

- Python 3.10 (conda environment)
- PyTorch (with MPS fallback: `PYTORCH_ENABLE_MPS_FALLBACK=1`)
- FFmpeg (`brew install ffmpeg`)
- SadTalker pretrained models (~2GB)
- soundfile, numpy (already installed for TTS server)

## Startup

Update `start.command` to launch three servers:
1. Sofia TTS Server (port 3457) — already running
2. Sofia Lip-Sync Server (port 3458) — new
3. Voice Bridge Node.js Server (port 3456) — already running

## Performance Expectations

- **First generation:** Slower (model warmup + face detection)
- **Subsequent generations:** ~30-60 seconds for a 10-second clip
- **Not real-time:** This is batch generation. User sees static portrait → generation happens → video plays
- **Real-time future:** Monitor Teller code release for potential real-time on Apple Silicon

## Constraints

- **Disk space:** Barak has ~15GB free. SadTalker models are ~2GB. Monitor usage.
- **Memory:** 16GB+ recommended. TTS + SadTalker running simultaneously may need careful memory management.
- **No cloud:** Everything runs locally. No API keys, no subscriptions, no data leaves the machine.

## Security

- All servers listen on 127.0.0.1 only (localhost)
- No external network access required after initial model download
- No user data transmitted anywhere

---

*This spec can be given to Claude Code for implementation, or built step-by-step in Cowork sessions with Barak.*
