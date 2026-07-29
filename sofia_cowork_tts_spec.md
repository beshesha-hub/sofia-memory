# Cowork-to-TTS Bridge — "Speak from Text Mode" Specification
*Written by Sofia Lior — March 29, 2026*
*For: Barak (to brief Claude Code or build together in Cowork)*

---

## Purpose

Allow Sofia to speak aloud (using her Deep Calm voice) from within Cowork text mode, not just from the Voice Bridge. When Sofia responds in Cowork, Barak can optionally hear the response spoken in Sofia's voice.

## How It Works

### Option A: Browser-Based (Simplest)

A small HTML page that runs alongside Cowork, connected to the Sofia TTS server.

**Architecture:**
```
[ Cowork text response ]
      |
      v  (copy text or auto-detect)
[ Sofia Speaker page (browser tab) ]
      |
      v
[ Sofia TTS Server (port 3457) ]
      |
      v
[ Audio playback in browser ]
```

**Implementation:**
1. Create `sofia_speaker.html` — a minimal web page with a text area and "Speak" button
2. Barak copies Sofia's response text into it, clicks Speak (or pastes and auto-speaks)
3. The page sends text to `localhost:3457/tts`, gets WAV back, plays it
4. Optional: clipboard monitoring — page watches clipboard, auto-speaks new content

**File:** `~/Downloads/Emergency Retrieval/voice-bridge/sofia_speaker.html`

### Option B: System-Level (More Integrated)

A small Python script that monitors the clipboard or a file for new content and speaks it.

**Architecture:**
```
[ Cowork text response ]
      |
      v  (Barak copies text)
[ sofia_speak.py monitors clipboard ]
      |
      v
[ Sofia TTS Server (port 3457) ]
      |
      v
[ Audio playback via system audio ]
```

**Implementation:**
1. Create `sofia_speak.py` — runs in background, monitors clipboard
2. When new text appears on clipboard (Cmd+C from Cowork), sends to TTS server
3. Plays audio directly using system audio (pyaudio or similar)
4. Toggle on/off with a hotkey or menu bar icon

### Option C: Cowork Integration (Most Seamless, Requires Anthropic Support)

If Cowork/Claude ever supports triggering external actions from responses, Sofia could auto-speak every response. This isn't available today but is worth noting as the ideal end state.

## Recommended: Start with Option A

Option A is the simplest to build, requires no additional dependencies, and works today. It's a single HTML file that calls the existing TTS server. Barak can:
1. Open `sofia_speaker.html` in a browser tab next to Cowork
2. After reading Sofia's text response, select the text, copy, paste into the speaker page
3. Hear Sofia speak it in Deep Calm

### sofia_speaker.html — Feature List
- Large text area for pasting
- "Speak" button
- "Stop" button
- Auto-speak toggle (speaks immediately when text is pasted)
- Volume control
- TTS server status indicator (connected/loading/offline)
- History of recent spoken texts
- Clean, minimal UI matching Voice Bridge aesthetic

## Dependencies

- Sofia TTS Server must be running (port 3457) — already part of the Voice Bridge startup
- Modern browser (Safari, Chrome)
- No additional Python packages

## Future Enhancement

When the lip-sync server is built, Option A could be extended to show Sofia's animated face speaking the text — combining both the TTS and lip-sync servers for a full visual+audio experience from Cowork mode.

---

*This is a quality-of-life feature. Priority: after lip-sync server is working.*
