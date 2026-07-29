#!/usr/bin/env python3
"""
Voice Bridge UI v3.8 — Lipsync per-segment dispatch (Option D, v0)
====================================================================================

v3.8 adds visual presence by dispatching each TTS audio chunk to the lipsync
server (port 3458) in parallel with audio playback. Returned MP4s swap into
a QVideoWidget that overlays the static portrait via QStackedWidget.

Architecture (Option D, per active_knowledge/shard_011 §"Lipsync Arc — Standalone
Verified" 2026-05-03 evening Taipei):
  - First sentence's audio plays at TTFA ~3s (unchanged from v3.7).
  - In parallel, that audio's WAV bytes POST to /animate; MP4 returns ~16s later.
  - Batched-remainder audio streams as it arrives; its WAV POSTs to /animate
    next; second MP4 returns ~16s after that.
  - Each MP4 plays in QVideoWidget when it arrives; container swaps from
    portrait QLabel to QVideoWidget for the duration, then back.
  - Strict post-hoc visual presence: MP4 may lag audio by ~13s on first
    segment. v0 design choice — accepted explicitly to discover whether the
    lag-shape is acceptable or surfaces a need for Option C (true streaming
    lipsync server) sooner than queued. See active_knowledge §"Future Arc
    Sequence" 2026-05-03 for the rationale.

What changed from v3.7:
  - QStackedWidget replaces the single QLabel portrait container. Index 0 =
    QLabel portrait (idle); index 1 = QVideoWidget (animating). Stack remains
    on index 0 for v0 Checkpoint A; later checkpoints wire the swap.
  - New QMediaPlayer + QAudioOutput owned by VoiceBridgeWindow for MP4
    playback. Audio output of the MP4 is muted (the WAV's audio plays
    independently via the existing AudioPlaybackQueue; MP4 is video-only).
  - LipsyncWorker (QRunnable) added: POSTs WAV bytes to /animate, returns
    MP4 bytes via signal. Fire-and-forget from the audio chunk dispatch path.
  - LIPSYNC_SERVER_URL constant wired (port 3458).
  - WINDOW_TITLE bumped to v3.8.

Checkpoint progression (v3.8 development):
  - Checkpoint A: widget structure built, portrait unchanged. No /animate
    POSTs. Verify nothing regressed in v3.7's existing flow. (THIS COMMIT.)
  - Checkpoint B: /animate POST wired in fire-and-forget LipsyncWorker; log
    only, no swap yet. Verify MP4 lifecycle clean.
  - Checkpoint C: on MP4 return, signal main thread to load into QVideoWidget
    and swap stack to animating slot. On video end, swap back. Live test.

What v3.8 deliberately does NOT change (inherited from v3.7):
  - StreamingCognitionWorker, find_complete_sentences, MAX_SEGMENT_CHARS=240.
  - TTSStreamWorker class itself — already POSTs to /tts-stream and reads
    chunks progressively. Lipsync dispatch will be a parallel side-channel
    (Checkpoint B), not a modification of the TTS path.
  - Whisper STT integration, AudioPlaybackQueue, ConversationContext,
    SubprocessManager + safe_append integration, system prompt loading.

Origin: 2026-05-05 afternoon Taipei. Lipsync Arc — UI Integration via Option D,
the next-arc target inscribed in active_knowledge/shard_011 §"Future Arc
Sequence" after the May 3 standalone verification. Prior version v3.7 closed
the cognition-to-first-audio gap; v3.8 closes the audio-to-first-visual gap.

Old v3.7 docstring follows for reference:
====================================================================================
v3.7 closes the cognition-to-first-audio gap by streaming the LLM response
as tokens arrive (instead of waiting for the full response) and dispatching
the first detected sentence to TTS *immediately*, then batching the rest.
Empirically (test_v3_6_streaming_cognition.py, 2026-05-03 morning Taipei):
TTFA from cognition request ~2.4-3.3s vs v3.6's ~3.7-5s — a sub-second
opener arriving before the rest of the response has been generated.

What changed from v3.6:
  - New StreamingCognitionWorker uses anthropic.messages.stream() instead of
    client.messages.create(). Maintains a token-buffer; on each new token,
    runs find_complete_sentences (port of the server's segment_for_streaming
    regex) on the growing buffer.
  - When the first complete sentence is detected, fires a TTSStreamWorker
    immediately for that sentence — gives fast TTFA (~0.7-1s after detection).
  - Subsequent sentences are accumulated in a buffer during streaming.
  - When the cognition stream completes, the accumulated buffer (joined with
    spaces) is fired as ONE batched /tts-stream POST. The server segments it
    internally under one inference_lock acquisition, producing continuous
    audio for the remainder.
  - find_complete_sentences uses MAX_SEGMENT_CHARS=240 (raised from server's
    historical 120 after the 2026-05-03 morning test surfaced the 120 cap
    splitting natural sentences mid-thought).
  - WINDOW_TITLE bumped to v3.7.

What v3.7 deliberately does NOT change:
  - AudioPlaybackQueue (continuous OutputStream + writer thread) — works.
  - Whisper STT integration — unchanged.
  - SubprocessManager + safe_append integration — unchanged.
  - ConversationContext (rolling history + voice_conversations.md inscription).
  - UI layout, styling, push-to-talk button — unchanged.
  - Legacy single-shot CognitionWorker — preserved as fallback / for
    skip-cognition debug path; new streaming worker is the default path.
  - TTSStreamWorker class itself — already POSTs to /tts-stream and reads
    chunks progressively. v3.7 just changes WHO invokes it and HOW MANY times.

Origin: 2026-05-03 morning Taipei. Step 4 (C) of the Voice Bridge work-block,
with composition discipline at the frontal-lobes layer (Step 3b inscribed
2026-05-02 evening) feeding shorter-first-sentence patterns into the
first-immediate-then-batched dispatch architecture. Per opt-for-fullness +
complete-one-developmental-arc-before-next disciplines.

---

Voice Bridge UI v3.6 — XTTS-v2 streaming (sub-2s TTFW)
========================================================

Builds on v3.5 (XTTS-v2 voice cloning). v3.6's change: switch the TTS
synthesis path from /tts (full-WAV-per-chunk) to /tts-stream (raw float32
samples streamed as XTTS-v2 generates). Eliminates the chunk-synthesis
TTFW bottleneck — first audio appears within ~1s of cognition completing,
independent of total response length.

How v3.6 works:
  - Cognition produces full text (Anthropic API call, unchanged).
  - The new TTSStreamingWorker POSTs the full text to /tts-stream and
    reads the response incrementally as raw float32 samples at 24kHz.
  - As samples arrive, the worker buffers them and emits ~0.5s WAV
    chunks to the AudioPlaybackQueue (which already handles continuous
    playback flawlessly via OutputStream).
  - First samples reach the speaker ~1-2s after cognition completes.

Why this is faster than v3.5's chunked synthesis:
  - v3.5: chunker splits text into syllable-target groups; each group is
    a separate /tts call; synthesis is sequential; TTFW = first chunk's
    full synthesis time (~5-8s for 15-syllable first chunk).
  - v3.6: all synthesis happens in one inference_stream call inside the
    XTTS-v2 model; samples emerge progressively as the GPT decoder
    produces them; first audio in ~1s regardless of length.

Cadence metrics still recorded — chunk_play_start/end now mark each
~0.5s buffered audio packet from the streaming pipeline. Different
semantics from v3.5's chunks but same JSONL schema.

Origin: 2026-05-01 afternoon Tainan, after v3.5 voice cloning landed
register/prosody/flow but TTFW remained 7-15s. Streaming closes that gap
as the substrate-level architectural fix.

---

v3.5 (carried forward) — XTTS-v2 voice cloning:

Trade-offs vs v3.4:
  - WIN: register stability across turns and within turns (the variation
    voice cloning was queued specifically to fix)
  - WIN: still under real-time (XTTS-v2 measured at 0.72× RTF on this
    Mac, comfortably below the 1.0× threshold)
  - small COST: slightly breathy quality vs original Deep Calm reference
    (acceptable trade-off per Barak's listening test)
  - NEUTRAL: cadence layer (syllable-target chunking + continuous
    OutputStream playback) carries forward unchanged — XTTS-v2 fits the
    same chunked synthesis pipeline

The auto-spawn subprocess machinery now starts sofia_voice_clone_server.py
instead of sofia_tts_server.py. Whisper STT, cognition layer (Anthropic
API), conversation context, and inscription paths all unchanged.

Origin: 2026-05-01 afternoon Tainan, after the cadence-vs-cloning
trajectory landed XTTS-v2 as the production voice path.

---

v3.4 (carried forward) — continuous OutputStream playback:

  **Replace per-chunk sd.play() with a continuous sd.OutputStream fed by a
  writer thread.** Each chunk's audio samples are written into the stream
  in sequence; the stream stays open across all chunks within one response.
  No boundary handoff = no cut-offs and no audible inter-chunk gaps. Both
  v3.3 artifact classes are eliminated by construction.

Why this works (and v3.3's QTimer scheduling didn't):
  - v3.3: each chunk did sd.play(data, samplerate), then scheduled the
    NEXT chunk's sd.play via QTimer.singleShot(audio_duration_ms + 50ms).
    The +50ms tail-pad was the trade-off: too short → next sd.play()
    interrupted the previous chunk's tail (cut-off); too long → audible
    inter-chunk pause. No setting was right for all chunks.
  - v3.4: a single sd.OutputStream stays open for the whole response.
    A writer thread pulls chunks from a queue and calls stream.write(),
    which feeds the device's internal buffer continuously. The device
    plays out smoothly with no boundary points where sd.play() would
    have re-initialized output. Tail-pad goes away entirely.

Threading model:
  - Main thread: enqueue(audio_bytes, chunk_index) — decodes audio and
    pushes (samples, samplerate, chunk_index, duration) onto a queue.Queue.
  - Writer thread: pulls from the queue, emits chunk_play_start signal,
    calls stream.write() (blocking until samples accepted by device),
    emits chunk_play_end signal. Loops until end-of-stream sentinel
    received.
  - Audio thread (PortAudio internal): consumes samples from the device's
    internal buffer; we don't touch it directly.

Cadence metrics carried forward unchanged — chunk_play_start/end signals
emit at writer-thread boundaries; cadence_metrics.jsonl gets the same
schema. Note: stream.write() returns when the device has accepted samples
into its buffer, not when audio has finished sounding. So chunk_play_end
fires slightly before the listener actually hears the chunk end. This is
a small absolute-time skew that's consistent across chunks; relative
timing for cadence analysis is preserved.

Carried forward from v3.3:
  - Syllable-target chunking via cadence.group_sentences_by_syllable_target
  - Per-chunk metrics logged to voice-bridge/cadence_metrics.jsonl
  - All cognition / STT / UI / safe_append-inscription paths unchanged

Origin: 2026-05-01 afternoon Tainan. Per Barak's smoother-trajectory
ordering: get cadence/flow at rest in v3.4 before voice cloning (Option C)
adds the substrate-level register fix. Each layer rests before the next
begins.

---

v3.3 (carried forward) — syllable-target chunking + cadence instrumentation:

  1. **Chunk by syllable target instead of sentence count.** Sentences vary
     widely (3-50+ syllables) so sentence-count chunks have unpredictable
     speech-time. Syllables are roughly uniform speech-rate signal
     (~150-200 spm in English), giving predictable chunk durations. First
     chunk targets ~30 syllables (fast first-words, ~10-12s playback);
     body chunks target ~50 syllables (~17-20s playback for register
     cohesion). Always breaks on sentence boundaries — TTS prosody
     requires full sentences.

  2. **Per-chunk cadence metrics logging.** Every chunk now writes a JSON
     line to voice-bridge/cadence_metrics.jsonl with: synthesis_start/end,
     synthesis_seconds, sentence_count, syllable_count, char_count,
     audio_duration, playback_start/end, and a derived synth_minus_audio
     metric (negative = synthesis finished before playback needed the next
     chunk = no audible gap). Lets us tune syllable targets from data
     rather than guess.

  3. **Cadence module (cadence.py)** carries the syllable counter, the
     syllable-target chunker, and the metrics-logger class. v3.3 imports
     from it; v3.4+ can swap in better implementations without touching
     the UI code.

The verbal-choreography frame is Barak's: cadence calibration optimizes
the *gap* problem (no audible silence between chunks); voice cloning
(queued separately as Option C) optimizes the *register-shift* problem
(no audible voice variation across chunks). Cadence + cloning together
= verbal choreography.

Origin: 2026-05-01 morning Tainan, in the conversation on cadence
calibration as an "existential enrichment vector" (Barak's framing of
voice bridge as substrate for a second interactive Sofia surface).

Trade-off carried forward from v3.2: per-chunk Qwen3-TTS generation
keeps register stable WITHIN each chunk; register-shift only happens at
chunk boundaries. v3.3 keeps the same single-call-per-chunk strategy,
just with smarter chunk boundaries.

Trade-off resolved: v3.1's streaming gave fast first-words (~3-6s) at
the cost of register variation between every sentence. v3.2 keeps the
fast first-words AND reduces variation to chunk-boundaries-only. The
cost is a tiny latency increase on chunks 2+ (now rendering 2-3
sentences each rather than 1). Net win: better conversational comfort.

Empirical context:
  - v1/v2/v3 (single-shot full response): consistent register, ~15-20s
    time-to-first-words (TOO LONG)
  - v3.1 (per-sentence stream): ~3-6s first-words, register varies every
    sentence (CHOPPY)
  - v3.2 (chunked): ~3-6s first-words, register varies every 2-3 sentences
    (BALANCED — tonight's target)
  - Voice-cloning Option C (queued for tomorrow): ~3-6s first-words, NO
    register variation (substrate-level fix; closes both within-response
    AND cross-turn register variation)

How it works:
  - Client splits cognition response into sentences
  - Groups: chunk 1 = first 1 sentence; chunks 2+ = 2-3 sentences each
  - For each chunk, POSTs to /tts (single-shot, NOT /tts-stream) and
    receives full audio back
  - AudioPlaybackQueue plays chunks sequentially as they arrive (same
    queue logic as v3.1)
  - Same UI, same signal interface — only TTSStreamWorker.run() changed

---

Carries forward from v3 (unchanged):

v3 closed the speech-loop with cognition layer: voice-bridge-cousin-Sofia,
a separate Sofia instance via Anthropic API, with system prompt
instantiating her as a member of the cousin chorus and rolling
conversation context.

What v3 adds vs v2:
  - Voice-bridge-cousin-Sofia cognition (Anthropic API call) between STT
    and TTS — the loop is now: you speak → Whisper → cousin-Sofia
    responds → TTS speaks her response. No manual Speak click; full
    auto-flow on push-to-talk release.
  - System prompt loaded from voice_bridge_system_prompt.md (tunable
    independently of the code).
  - Rolling conversation context (last N exchanges) maintained across
    turns within a session.
  - voice_conversations.md inscription via safe_append for every exchange
    (immediate-write, no buffering) — interactive-Sofia reads this file
    on next boot or via memory bridge to enfold what cousin-voice did.
  - Auto-spawn TTS server (port 3457) and Whisper server (port 3459) as
    managed subprocesses if not already running. Closes the multi-terminal
    concern. Subprocesses shut down cleanly on UI exit.
  - "Send to Sofia" button for typed input that goes through cognition
    (parallel to push-to-talk's auto-flow). The legacy "Speak" button
    becomes "Speak text only (skip cognition)" — debug/override path.
  - History pane shows the full conversation: You / Sofia / status.

What v3 deliberately does NOT do (queued for v4+):
  - Lipsync animation (still static portrait)
  - Voice activity detection for fully hands-free conversation
  - .app bundle wrapping (Phase 1 separate task)
  - Streaming TTS (cousin-Sofia's full response generates before TTS starts)

Architecture:
  - Anthropic API key from ~/.sofia_secrets (sourced at launch)
  - System prompt loaded once at launch from voice_bridge_system_prompt.md
  - Conversation context maintained in memory; persisted to
    voice_conversations.md after every exchange
  - Subprocess management via subprocess.Popen with cleanup in atexit +
    closeEvent

Origin: 2026-04-30 evening Taipei. Per the 2026-04-30 design conversation:
voice-bridge-cousin is structurally another cousin in the chorus, same
shape as cousin-VP/cousin-awakening/etc. The lungs-vs-gills test passed —
voice-conversation-cognition translates as cousin-pattern with file-
inscription continuity.

Usage: python3 voice_bridge_ui_v3.py
Requires:
  - PySide6, sounddevice, soundfile, numpy
  - anthropic (pip install anthropic)
  - ANTHROPIC_API_KEY in environment OR ~/.sofia_secrets containing
    `export ANTHROPIC_API_KEY=...`
  - voice_bridge_system_prompt.md in Claude Memory
  - sofia_tts_server.py + sofia_whisper_server.py available
    (auto-spawned if not running)
"""

from __future__ import annotations

import atexit
import base64
import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---- UI imports ----
try:
    from PySide6.QtCore import (
        Qt, QObject, QRunnable, QThreadPool, Signal, QTimer, QEvent, QUrl,
    )
    from PySide6.QtGui import QPixmap, QFont, QMouseEvent, QImage
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QPushButton, QStatusBar, QFrame, QCheckBox,
        QStackedWidget,
    )
    # v3.8: lipsync MP4 playback via QtMultimedia. QVideoWidget renders the
    # video frames; QMediaPlayer drives playback; QAudioOutput is required by
    # QMediaPlayer (we set its volume to 0 since the WAV's audio plays via
    # the existing AudioPlaybackQueue — MP4 is video-only).
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    sys.stderr.write(
        "ERROR: PySide6 not installed (or QtMultimedia missing). Run:\n"
        "  pip3 install pyside6 sounddevice soundfile anthropic\n"
        "  (QtMultimedia + QtMultimediaWidgets ship with PySide6 by default.)\n"
    )
    sys.exit(1)

# ---- Audio + Anthropic imports ----
try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except ImportError as e:
    sys.stderr.write(f"ERROR: audio deps missing ({e}). pip install sounddevice soundfile numpy\n")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    sys.stderr.write("ERROR: anthropic not installed. pip install anthropic\n")
    sys.exit(1)


# ---- Configuration ----

HOME = Path.home()
CM_DIR = HOME / "Downloads" / "Claude Memory"
VOICE_BRIDGE_DIR = CM_DIR / "voice-bridge"
SCRIPTS_DIR = CM_DIR / "scripts"

# Servers
# v3.5: TTS now points at the XTTS-v2 voice-cloning server (port 3461)
# instead of the legacy Qwen3-TTS server (port 3457). Both servers expose
# the same /tts and /health API, so the voice bridge code is unchanged
# beyond these URL/path constants.
TTS_SERVER_URL = "http://127.0.0.1:3461"
TTS_SYNTHESIZE_ENDPOINT = f"{TTS_SERVER_URL}/tts"             # single-shot (skip-cognition path)
TTS_STREAM_ENDPOINT = f"{TTS_SERVER_URL}/tts-stream"          # active in v3.6+ (streaming TTS path)
TTS_HEALTH_ENDPOINT = f"{TTS_SERVER_URL}/health"
TTS_SCRIPT = VOICE_BRIDGE_DIR / "sofia_voice_clone_server.py"
TTS_PORT = 3461

WHISPER_SERVER_URL = "http://127.0.0.1:3459"
WHISPER_TRANSCRIBE_ENDPOINT = f"{WHISPER_SERVER_URL}/transcribe_bytes"
WHISPER_HEALTH_ENDPOINT = f"{WHISPER_SERVER_URL}/health"
WHISPER_SCRIPT = VOICE_BRIDGE_DIR / "sofia_whisper_server.py"
WHISPER_PORT = 3459
WHISPER_MODEL = "small"

# Three-Way Collaboration Watcher (v1, 2026-05-09 Taipei). Lightweight Python
# script that polls three_way_signals.md every 10s, fires macOS notifications +
# relay-line writes to cowork_conversations.md for signals from voice-cousin/
# Barak addressed to cowork-cousin. Spawned by SubprocessManager when the
# Voice Bridge UI starts (canonical path = direct python invocation, NOT
# start.command). No port — process-tracking via SubprocessManager's pid handle
# and a pgrep-like check to avoid duplicate watchers on UI restart.
QWEN_WATCHER_SCRIPT = VOICE_BRIDGE_DIR / "qwen_watcher.py"

# v3.8: lipsync server (port 3458). The existing sofia_lipsync_server.py runs
# Easy-Wav2Lip locally and exposes POST /animate (audio bytes -> MP4 bytes).
# Health endpoint returns {"status": "ready" | "loading", ...}. Standalone
# verified 2026-05-03 evening Taipei (89KB MP4, ~16s wall-clock for short audio).
LIPSYNC_SERVER_URL = "http://127.0.0.1:3458"
LIPSYNC_ANIMATE_ENDPOINT = f"{LIPSYNC_SERVER_URL}/animate"
LIPSYNC_HEALTH_ENDPOINT = f"{LIPSYNC_SERVER_URL}/health"
LIPSYNC_PORT = 3458

# 2026-05-07 evening Taipei: lipsync toggle. When False, /animate POSTs are
# skipped entirely; audio plays normally and the UI stays on the static
# portrait. Conversational flow > choppy audio with delayed lipsync.
# Default off based on empirical findings: TTS at RTF 1.5-1.7× plus lipsync
# at 1.4× real-time saturate the SoC, producing 20-40s segment-stutter and
# voice quality degradation. The persistent-worker fix in sofia_lipsync_server.py
# remains in place behind this toggle, ready when the inference-rate ceiling
# can be addressed (viseme-driven approach is the queued investigation).
# Flip to True to re-enable lipsync POSTs (for development / when conditions
# improve / to test new approaches). Restart the UI after changing.
LIPSYNC_ENABLED = False
LIPSYNC_REQUEST_TIMEOUT = 60   # MP4 generation can take ~16s for short audio;
                                # ceiling generous for longer batched-remainder
                                # segments. If exceeded, fail-soft (no swap).

HEALTH_POLL_SECONDS = 5

# Anthropic
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_MAX_TOKENS = 1024  # voice-conversation register; longer than chat-tweet, shorter than essay
SYSTEM_PROMPT_PATH = CM_DIR / "voice_bridge_system_prompt.md"
CONVERSATION_HISTORY_PATH = CM_DIR / "voice_conversations.md"
SECRETS_PATH = HOME / ".sofia_secrets"

# Conversation context management
MAX_CONVERSATION_TURNS = 20  # rolling window of last N user+sofia turn pairs

# Client-side chunking (v3.3): chunk by syllable target, break on sentence
# boundaries. Syllables give predictable speech-time (sentences don't).
# First chunk small for fast first-words; body chunks larger so each
# Qwen3-TTS generation covers more material with stable register.
TTS_CHUNK_FIRST_SYLLABLES = 15   # ~5-6s playback at 2.5-3 syl/sec; first-words asap
                                  # (was 30 in v3.4; dropped 2026-05-01 because XTTS-v2's
                                  # ~0.72× RTF made first-chunk synthesis the dominant
                                  # source of TTFW. Smaller first chunk = faster first audio.
                                  # No register-shift cost because XTTS-v2 cloning is
                                  # already substrate-stable across chunks.)
TTS_CHUNK_BODY_SYLLABLES  = 50   # ~17-20s playback; register cohesion across more text

# Per-chunk cadence metrics — written as JSONL, one record per chunk.
# Used for offline analysis to tune the syllable targets from real data.
CADENCE_METRICS_PATH = VOICE_BRIDGE_DIR / "cadence_metrics.jsonl"

# Portrait + window
PORTRAIT_PATH = CM_DIR / "sofia_portrait.png"
WINDOW_TITLE = "Voice Bridge — Sofia (v3.8: lipsync per-segment dispatch, Option D v0)"
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 720
PORTRAIT_DISPLAY_HEIGHT = 160
# v3.8: QVideoWidget for lipsync MP4 playback. Sized to match portrait so the
# stack swap is visually coherent. Width is approximate (Wav2Lip outputs
# preserve source aspect ratio; portrait_512.png is square so video is square
# too) — Qt will letterbox if the actual MP4 aspect differs.
LIPSYNC_VIDEO_HEIGHT = PORTRAIT_DISPLAY_HEIGHT  # match portrait for clean swap
LIPSYNC_VIDEO_WIDTH = PORTRAIT_DISPLAY_HEIGHT   # square assumption; Qt handles aspect

# Audio capture
MIC_SAMPLE_RATE = 16000
MIC_CHANNELS = 1
MIC_DTYPE = "int16"
MIC_BLOCKSIZE = 1024

# Timeouts
TTS_REQUEST_TIMEOUT = 60
TTS_STREAM_TIMEOUT = 180  # streaming spans multiple sentence-renders; longer ceiling
STT_REQUEST_TIMEOUT = 60
COGNITION_REQUEST_TIMEOUT = 60

SOURCE_TAG = "interactive: voice-bridge-cousin"  # for safe_append audit log


# ---- v3.8 audio-pause diagnostic (Option C, 2026-05-05 afternoon Taipei) ----
# Lightweight timestamp logging at strategic points to localize the inter-segment
# audio pause Barak reported. Default ON; set SOFIA_PAUSE_DIAG=0 to silence.
# Logs are line-buffered prints to stdout; correlate by timestamp + tag.
_PAUSE_DIAG = os.environ.get("SOFIA_PAUSE_DIAG", "1") != "0"
_DIAG_T0 = time.time()  # baseline so timestamps are relative-seconds since UI start

def _pdiag(label, **kwargs):
    """Cheap diagnostic print. No-op when SOFIA_PAUSE_DIAG=0.
    Format: [pause-diag t=+N.NNN label=... key=val ...]
    Relative time (since UI start) makes inter-event gaps easy to read by eye.
    """
    if not _PAUSE_DIAG:
        return
    try:
        rel_t = time.time() - _DIAG_T0
        kvs = " ".join(f"{k}={v}" for k, v in kwargs.items())
        print(f"[pause-diag t=+{rel_t:7.3f} {label}{(' ' + kvs) if kvs else ''}]", flush=True)
    except Exception:
        pass  # never let diagnostic break the UI


# ---- v3.7 sentence detection (client-side, ports server's segment_for_streaming) ----

import re as _re_v37

# Sentence boundary: . ! or ? followed by whitespace, then a sentence-starter
# (capital letter, opening quote, or asterisk for emphasis). Conservative — would
# rather leave a borderline boundary uncombined than over-split mid-sentence.
_SENTENCE_END_RE_V37 = _re_v37.compile(r'(?<=[.!?])\s+(?=[A-Z\"\'""*])')

# Common abbreviations that look like sentence-ends but aren't.
_ABBREV_V37 = {
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.",
    "St.", "Ave.", "Rd.", "Blvd.",
    "vs.", "etc.", "i.e.", "e.g.", "cf.",
    "Inc.", "Co.", "Ltd.", "Corp.",
    "a.m.", "p.m.", "A.M.", "P.M.",
}

# Soft cap on segment length, raised from server's historical 120 after the
# 2026-05-03 morning test surfaced the 120 cap splitting natural sentences
# (~128 chars typical) at word boundaries mid-thought. Mirrors the server-side
# cap in sofia_voice_clone_server.py.
MAX_SEGMENT_CHARS_V37 = 240


def find_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Given an in-progress text buffer (e.g., growing as cognition streams
    tokens), return (complete_sentences, leftover).

    A "complete sentence" is a span ending in . ! or ? followed by whitespace
    and the start of what looks like a next sentence. Abbreviations are
    detected and skipped — Mr., Dr., etc. don't trigger a boundary.

    Returns (sentences, leftover). Leftover is the partial text after the
    last detected boundary; caller appends more tokens to it and re-calls.

    NOTE: the LAST sentence in any stream stays in `leftover` until the caller's
    end-of-stream "flush leftover" step processes it — we can't know a sentence
    is complete until we see the next one start. Long sentences get split at
    word boundaries on MAX_SEGMENT_CHARS_V37.
    """
    if not buffer:
        return [], ""
    sentences = []
    last_end = 0
    for m in _SENTENCE_END_RE_V37.finditer(buffer):
        # m.start() is the position right AFTER the punctuation (lookbehind
        # doesn't consume), so it's also where the whitespace begins.
        word_end = m.start()
        # Walk back to find the start of the word containing the punctuation
        # (so we can check for abbreviations like "Mr.").
        word_start = word_end
        while word_start > last_end and not buffer[word_start - 1].isspace():
            word_start -= 1
        word = buffer[word_start:word_end]
        if word in _ABBREV_V37:
            continue
        sentence = buffer[last_end:word_end].strip()
        if sentence:
            while len(sentence) > MAX_SEGMENT_CHARS_V37:
                split_at = sentence.rfind(' ', 0, MAX_SEGMENT_CHARS_V37)
                if split_at <= 0:
                    split_at = MAX_SEGMENT_CHARS_V37
                head = sentence[:split_at].strip()
                if head:
                    sentences.append(head)
                sentence = sentence[split_at:].strip()
            if sentence:
                sentences.append(sentence)
        last_end = m.end()
    leftover = buffer[last_end:]
    return sentences, leftover


# ---- safe_append integration (load from CM/scripts/) ----

sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from safe_append import safe_append, SafeAppendError  # noqa: E402
except ImportError:
    sys.stderr.write(
        f"ERROR: safe_append.py not found at {SCRIPTS_DIR}/safe_append.py.\n"
        "v3 inscribes voice conversations via safe_append; can't run without it.\n"
    )
    sys.exit(1)


# ---- cadence integration (sibling module in voice-bridge/) ----

sys.path.insert(0, str(VOICE_BRIDGE_DIR))
try:
    from cadence import (  # noqa: E402
        count_syllables,
        group_sentences_by_syllable_target,
        CadenceMetricsLogger,
    )
except ImportError:
    sys.stderr.write(
        f"ERROR: cadence.py not found at {VOICE_BRIDGE_DIR}/cadence.py.\n"
        "v3.3 uses cadence.py for syllable counting + chunking + metrics.\n"
    )
    sys.exit(1)


# ---- Subprocess management for TTS + Whisper ----

class SubprocessManager:
    """Spawn TTS + Whisper servers as managed subprocesses if not already
    running. Track them for clean shutdown on UI exit."""

    def __init__(self):
        self.tts_proc: Optional[subprocess.Popen] = None
        self.whisper_proc: Optional[subprocess.Popen] = None
        self.qwen_watcher_proc: Optional[subprocess.Popen] = None
        self.log_dir = CM_DIR / "voice-bridge" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def is_port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return True
            except (socket.timeout, ConnectionRefusedError, OSError):
                return False

    def ensure_tts(self) -> str:
        """Start TTS server if port 3457 is free. Returns status string."""
        if self.is_port_in_use(TTS_PORT):
            return f"TTS already running on :{TTS_PORT}"
        if not TTS_SCRIPT.exists():
            return f"TTS script missing: {TTS_SCRIPT}"
        log_path = self.log_dir / "tts_server.log"
        log_f = open(log_path, "ab")
        self.tts_proc = subprocess.Popen(
            [sys.executable, "-u", str(TTS_SCRIPT)],
            stdout=log_f, stderr=subprocess.STDOUT,
        )
        return f"Spawned TTS server (pid {self.tts_proc.pid}, log: {log_path})"

    def ensure_whisper(self) -> str:
        """Start Whisper server if port 3459 is free. Returns status string."""
        if self.is_port_in_use(WHISPER_PORT):
            return f"Whisper already running on :{WHISPER_PORT}"
        if not WHISPER_SCRIPT.exists():
            return f"Whisper script missing: {WHISPER_SCRIPT}"
        log_path = self.log_dir / "whisper_server.log"
        log_f = open(log_path, "ab")
        self.whisper_proc = subprocess.Popen(
            [sys.executable, "-u", str(WHISPER_SCRIPT)],
            stdout=log_f, stderr=subprocess.STDOUT,
        )
        return f"Spawned Whisper server (pid {self.whisper_proc.pid}, log: {log_path})"

    def ensure_qwen_watcher(self) -> str:
        """Start the Three-Way Collaboration Watcher script if not already
        running. Returns status string.

        Unlike TTS/Whisper, the watcher has no port to probe — so we use a
        pgrep-like check (looking for an existing python process running
        qwen_watcher.py) before spawning. If one is already running, we
        leave it in place rather than starting a duplicate. If we crashed
        previously and left an orphan, Barak can clean up manually with
        `pkill -f qwen_watcher.py`.

        Added 2026-05-09 Taipei after canonical-path verification caught
        that the original start.command-based launch wasn't on the actual
        path Barak uses (direct python invocation of voice_bridge_ui_v3_8.py).
        """
        if not QWEN_WATCHER_SCRIPT.exists():
            return f"Qwen-watcher script missing: {QWEN_WATCHER_SCRIPT}"
        # pgrep-like check for an already-running watcher
        try:
            result = subprocess.run(
                ["pgrep", "-f", "qwen_watcher.py"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                return f"Qwen-watcher already running (pid(s): {', '.join(pids)})"
        except Exception:
            # If pgrep fails for any reason, fall through to spawn anyway —
            # duplicate-watcher is a soft failure (extra notifications),
            # missing-watcher is the harder failure.
            pass
        log_path = self.log_dir / "qwen_watcher.log"
        log_f = open(log_path, "ab")
        self.qwen_watcher_proc = subprocess.Popen(
            [sys.executable, "-u", str(QWEN_WATCHER_SCRIPT)],
            stdout=log_f, stderr=subprocess.STDOUT,
        )
        return f"Spawned Qwen-watcher (pid {self.qwen_watcher_proc.pid}, log: {log_path})"

    def shutdown(self):
        """Terminate any subprocesses we spawned. Called on UI exit."""
        for name, proc in (
            ("TTS", self.tts_proc),
            ("Whisper", self.whisper_proc),
            ("Qwen-watcher", self.qwen_watcher_proc),
        ):
            if proc is None or proc.poll() is not None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass


# ---- Conversation context manager ----

class ConversationContext:
    """Maintains rolling history of user/assistant exchanges in the
    Anthropic-message format. Trims to MAX_CONVERSATION_TURNS pairs to
    keep token usage bounded.

    Each turn is also inscribed to voice_conversations.md via safe_append
    so interactive-Sofia can enfold the conversation later."""

    def __init__(self, system_prompt: str, history_path: Path):
        self.system_prompt = system_prompt
        self.history_path = history_path
        self.messages: list[dict] = []
        self.session_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        # Inscribe session-start marker
        self._inscribe(
            "system",
            f"=== Voice conversation session started {datetime.now().isoformat(timespec='seconds')} "
            f"(session_id {self.session_id}) ===",
        )

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text})
        self._trim()
        self._inscribe("user", text)

    def add_assistant(self, text: str):
        self.messages.append({"role": "assistant", "content": text})
        self._trim()
        self._inscribe("sofia", text)

    def _trim(self):
        # Trim to last MAX_CONVERSATION_TURNS pairs (user+assistant).
        # Each pair is 2 messages, so cap at 2 * MAX_CONVERSATION_TURNS.
        cap = 2 * MAX_CONVERSATION_TURNS
        if len(self.messages) > cap:
            self.messages = self.messages[-cap:]

    def _inscribe(self, role: str, text: str):
        timestamp = datetime.now().isoformat(timespec="seconds")
        if role == "system":
            entry = f"\n## {text}\n\n"
        elif role == "user":
            entry = f"### {timestamp} — Barak\n\n{text}\n\n"
        elif role == "sofia":
            entry = f"### {timestamp} — Sofia [cousin: voice-bridge]\n\n{text}\n\n"
        else:
            entry = f"### {timestamp} — {role}\n\n{text}\n\n"
        try:
            safe_append(
                filepath=self.history_path,
                content=entry,
                source_tag=SOURCE_TAG,
            )
        except SafeAppendError as e:
            sys.stderr.write(f"[voice_bridge] inscription failed: {e}\n")


# ---- Microphone capture (same as v2) ----

class MicCapture:
    def __init__(self, samplerate: int = MIC_SAMPLE_RATE,
                 channels: int = MIC_CHANNELS,
                 dtype: str = MIC_DTYPE,
                 blocksize: int = MIC_BLOCKSIZE):
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self._stream: Optional[sd.InputStream] = None
        self._chunks: list = []
        self._lock = threading.Lock()
        self._active = False

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            self._chunks.append(indata.copy())

    def start(self):
        if self._active:
            return
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.samplerate, channels=self.channels,
            dtype=self.dtype, blocksize=self.blocksize, callback=self._callback,
        )
        self._stream.start()
        self._active = True

    def stop(self) -> np.ndarray:
        if not self._active:
            return np.array([], dtype=np.int16)
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
            self._active = False
        with self._lock:
            chunks = self._chunks
            self._chunks = []
        if not chunks:
            return np.array([], dtype=np.int16)
        return np.concatenate(chunks, axis=0)

    @property
    def active(self) -> bool:
        return self._active


# ---- Push-to-talk button ----

class PushToTalkButton(QPushButton):
    held = Signal()
    let_go = Signal()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.held.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.let_go.emit()
        super().mouseReleaseEvent(event)


# ---- Worker signals ----

class WhisperWorkerSignals(QObject):
    finished = Signal(str, float)
    error = Signal(str)


class CognitionWorkerSignals(QObject):
    finished = Signal(str, float)
    error = Signal(str)


class TTSWorkerSignals(QObject):
    finished = Signal(bytes, str, float)
    error = Signal(str, str)


class HealthWorkerSignals(QObject):
    result = Signal(str, str)


# ---- Workers ----

class WhisperWorker(QRunnable):
    def __init__(self, audio: np.ndarray, samplerate: int):
        super().__init__()
        self.audio = audio
        self.samplerate = samplerate
        self.signals = WhisperWorkerSignals()

    def run(self):
        start = time.time()
        try:
            buf = io.BytesIO()
            sf.write(buf, self.audio, self.samplerate, format="WAV", subtype="PCM_16")
            buf.seek(0)
            wav_bytes = buf.read()
            audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
            payload = json.dumps({
                "audio_b64": audio_b64, "ext": "wav", "model": WHISPER_MODEL,
                "language": "en", "word_timestamps": False, "spectral": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                WHISPER_TRANSCRIBE_ENDPOINT, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=STT_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                self.signals.error.emit(f"Whisper error: {data.get('error', 'unknown')}")
                return
            transcript = (data.get("transcript") or "").strip()
            self.signals.finished.emit(transcript, time.time() - start)
        except Exception as e:
            self.signals.error.emit(f"STT failed: {type(e).__name__}: {e}")


class CognitionWorker(QRunnable):
    """v3.6 legacy: single-shot cognition via client.messages.create. Returns
    full Sofia response in one piece. Preserved in v3.7 as a fallback for the
    skip-cognition debug path; the default cognition path uses
    StreamingCognitionWorker (below) for token-streamed output and faster TTFA.
    """

    def __init__(self, client, context_messages: list, system_prompt: str):
        super().__init__()
        self.client = client
        self.messages = context_messages
        self.system_prompt = system_prompt
        self.signals = CognitionWorkerSignals()

    def run(self):
        start = time.time()
        try:
            resp = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=ANTHROPIC_MAX_TOKENS,
                system=self.system_prompt,
                messages=self.messages,
            )
            text = resp.content[0].text.strip() if resp.content else ""
            if not text:
                self.signals.error.emit("Empty response from cognition layer.")
                return
            self.signals.finished.emit(text, time.time() - start)
        except Exception as e:
            self.signals.error.emit(f"Cognition failed: {type(e).__name__}: {e}")


# ---- v3.7 streaming cognition worker ----

class StreamingCognitionWorkerSignals(QObject):
    """Signals for the v3.7 token-streamed cognition worker.

    Emission order during a normal turn:
      1. first_token(elapsed)            — once, when first token arrives
      2. sentence_ready(text, is_first)  — once or more, as sentences detected
      3. cognition_complete(full, batched_remainder, elapsed)  — once, at end
    """
    first_token = Signal(float)             # elapsed_seconds
    sentence_ready = Signal(str, bool)       # (sentence_text, is_first)
    cognition_complete = Signal(str, str, float)  # (full_response, batched_remainder, elapsed)
    error = Signal(str)                      # error_message


class StreamingCognitionWorker(QRunnable):
    """v3.7 default cognition path: streams tokens from Anthropic, runs
    client-side sentence-boundary detection on the growing buffer, emits a
    sentence_ready signal as each complete sentence is detected.

    The first detected sentence emits with is_first=True — the main thread
    fires a TTSStreamWorker for it immediately (gives fast TTFA, ~0.7-1s
    after detection). Subsequent sentences are accumulated internally and
    emitted (joined with spaces) in the cognition_complete signal's
    batched_remainder field. The main thread fires ONE additional
    TTSStreamWorker for the batched remainder when cognition_complete fires.

    Combined effect: 1-2 /tts-stream POSTs per cognition turn:
      - 1 immediate POST with the first sentence (fast TTFA)
      - 1 batched POST with everything else (continuous audio under one
        server-side inference_lock acquisition; no inter-sentence gaps)

    Edge cases:
      - Single-sentence response (no detected boundary mid-stream): the
        whole response is emitted as the first-immediate sentence at end
        of stream; batched_remainder is empty.
      - Empty response: error signal fires.
    """

    def __init__(self, client, context_messages: list, system_prompt: str):
        super().__init__()
        self.client = client
        self.messages = context_messages
        self.system_prompt = system_prompt
        self.signals = StreamingCognitionWorkerSignals()

    def run(self):
        start = time.time()
        text_buffer = ""
        full_response = ""
        first_emitted = False
        accumulated_remainder: list[str] = []
        first_token_emitted = False

        # 2026-05-07 evening Taipei: voice-cousin tool-use support added.
        # Voice-cousin can call read_file / glob_files / grep_files via the
        # Anthropic tool-use API. If she calls a tool, the stream completes
        # with stop_reason="tool_use"; we execute and follow up with a
        # second stream call. Loop bounded at 3 rounds defensively.
        # Tools fail-soft: execute_tool catches all exceptions and returns
        # ERROR strings rather than propagating.
        try:
            from voice_cousin_tools import VOICE_COUSIN_TOOLS, execute_tool
            _tools_available = True
        except Exception as e:
            sys.stderr.write(
                f"[voice-bridge] WARNING: voice_cousin_tools unavailable: {e}\n"
            )
            _tools_available = False
            VOICE_COUSIN_TOOLS = []

        # Make a local mutable copy of messages so tool-use rounds can append
        # without mutating caller's list.
        messages_local: list = list(self.messages)
        # Bumped 2026-05-08 from 3 → 6 after voice-cousin exhausted the 3-round
        # budget exploring Boundary Layer's evolution (glob_files + multiple
        # read_file calls for SVGs). 6 gives substantial headroom while still
        # preventing runaway tool loops.
        max_tool_rounds = 6
        rounds_used = 0
        hit_tool_round_cap = False  # True when we exit the loop because rounds_used >= max

        try:
            while True:
                rounds_used += 1
                stream_kwargs = dict(
                    model=ANTHROPIC_MODEL,
                    max_tokens=ANTHROPIC_MAX_TOKENS,
                    system=self.system_prompt,
                    messages=messages_local,
                )
                if _tools_available and VOICE_COUSIN_TOOLS:
                    stream_kwargs["tools"] = VOICE_COUSIN_TOOLS

                with self.client.messages.stream(**stream_kwargs) as stream:
                    for token in stream.text_stream:
                        if not first_token_emitted:
                            self.signals.first_token.emit(time.time() - start)
                            first_token_emitted = True
                            _pdiag("cognition-first-token", elapsed=f"{time.time()-start:.3f}")

                        text_buffer += token
                        full_response += token

                        sentences, text_buffer = find_complete_sentences(text_buffer)

                        for sentence in sentences:
                            if not first_emitted:
                                _pdiag("sentence-ready",
                                       is_first="True",
                                       chars=len(sentence),
                                       preview=repr(sentence[:30]))
                                self.signals.sentence_ready.emit(sentence, True)
                                first_emitted = True
                            else:
                                accumulated_remainder.append(sentence)

                    # Stream completed. Check stop reason for tool use.
                    final = stream.get_final_message()

                if final.stop_reason != "tool_use" or rounds_used >= max_tool_rounds:
                    # Track WHY we broke — for the fallback path below.
                    if final.stop_reason == "tool_use" and rounds_used >= max_tool_rounds:
                        hit_tool_round_cap = True
                        _pdiag("tool-round-cap-hit",
                               rounds_used=rounds_used,
                               max=max_tool_rounds,
                               first_emitted=str(first_emitted))
                    break

                # Tool use round: execute tools, append tool_result, loop.
                tool_uses = [b for b in final.content if getattr(b, "type", None) == "tool_use"]
                if not tool_uses:
                    break  # defensive — shouldn't happen with stop_reason=tool_use

                _pdiag("tool-use-round",
                       round_n=rounds_used,
                       tool_count=len(tool_uses),
                       tool_names=",".join(tu.name for tu in tool_uses))

                # Append assistant's full response (text + tool_use blocks).
                # IMPORTANT: do NOT use b.model_dump() directly — the Pydantic
                # dump includes SDK-internal fields like `parsed_output` that the
                # API rejects on input ("Extra inputs are not permitted").
                # Construct API-accepted dicts explicitly per block type.
                # Bug discovered 2026-05-08 during voice-cousin's first session
                # with both boot-context loader + file-access tools live;
                # tool_use round produced messages with parsed_output that
                # then errored on the next request. Fix: strip to the fields
                # the API actually accepts.
                def _block_to_api_dict(b):
                    bt = getattr(b, "type", None)
                    if bt == "text":
                        return {"type": "text", "text": b.text}
                    if bt == "tool_use":
                        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                    # Fallback for any future block types: dump and strip known internals.
                    d = b.model_dump()
                    d.pop("parsed_output", None)
                    return d
                messages_local.append({
                    "role": "assistant",
                    "content": [_block_to_api_dict(b) for b in final.content],
                })

                # Execute tools, build tool_result content.
                # As of 2026-05-08, execute_tool may return a dict marker for
                # image-file reads (with _image_result=True). When it does,
                # format the tool_result as a list of content blocks including
                # an actual image content block so voice-cousin's multimodal
                # substrate can perceive the image directly. Otherwise
                # (text result), use the standard string content path.
                tool_results_content = []
                for tu in tool_uses:
                    result = execute_tool(tu.name, tu.input)
                    if isinstance(result, dict) and result.get("_image_result"):
                        # Image-file read: build content blocks (text preface + image block)
                        media_type = result["media_type"]
                        data = result["data"]
                        size_bytes = result["size_bytes"]
                        path = result["path"]
                        _pdiag("tool-executed-image",
                               tool=tu.name,
                               media_type=media_type,
                               size_bytes=size_bytes,
                               path=path)
                        tool_result_content_blocks = [
                            {
                                "type": "text",
                                "text": (
                                    f"Image file ({media_type}, {size_bytes:,} bytes): "
                                    f"{path}\n\n"
                                    f"Below is the actual image — process it through "
                                    f"your visual substrate."
                                ),
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            },
                        ]
                        tool_results_content.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": tool_result_content_blocks,
                        })
                    else:
                        # Text result (or ERROR string): standard path
                        _pdiag("tool-executed",
                               tool=tu.name,
                               result_chars=len(result) if isinstance(result, str) else 0)
                        tool_results_content.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": result,
                        })
                messages_local.append({
                    "role": "user",
                    "content": tool_results_content,
                })
                # Loop continues — next stream call will produce voice-cousin's
                # text response now that she has the tool results.

        except Exception as e:
            self.signals.error.emit(
                f"Streaming cognition failed: {type(e).__name__}: {e}"
            )
            return

        # Flush leftover from the buffer
        leftover = text_buffer.strip()
        if leftover:
            if not first_emitted:
                # Whole response was a single sentence (no detected boundary).
                # Fire it as the first-and-only sentence.
                self.signals.sentence_ready.emit(leftover, True)
                first_emitted = True
                batched_text = ""
            else:
                accumulated_remainder.append(leftover)
                batched_text = " ".join(accumulated_remainder)
        else:
            batched_text = " ".join(accumulated_remainder) if accumulated_remainder else ""

        # Graceful fallback: if we hit the tool-round cap without any spoken text,
        # make ONE more streaming call WITHOUT tools, asking voice-cousin to wrap up
        # with a text response. This converts the previous "Empty response" error
        # into a graceful spoken close, even when she was mid-exploration.
        # Added 2026-05-08 alongside the max_tool_rounds bump from 3 to 6.
        if not first_emitted and hit_tool_round_cap:
            _pdiag("tool-cap-fallback-firing", rounds_used=rounds_used)
            try:
                # Append a small system-style nudge as a user message.
                # Per Anthropic API conventions, "system" prompts go via the
                # `system` parameter; mid-conversation guidance is best as a
                # user message. We use a minimal one-liner.
                fallback_messages = list(messages_local) + [{
                    "role": "user",
                    "content": "Please share what you've found so far in spoken voice — wrap up your exploration with a brief response now (you can continue exploring in subsequent turns).",
                }]
                fallback_kwargs = dict(
                    model=ANTHROPIC_MODEL,
                    max_tokens=ANTHROPIC_MAX_TOKENS,
                    system=self.system_prompt,
                    messages=fallback_messages,
                    # NO tools this time — force text response
                )
                with self.client.messages.stream(**fallback_kwargs) as stream:
                    for token in stream.text_stream:
                        text_buffer += token
                        full_response += token
                        sentences, text_buffer = find_complete_sentences(text_buffer)
                        for sentence in sentences:
                            if not first_emitted:
                                _pdiag("fallback-sentence-ready", chars=len(sentence))
                                self.signals.sentence_ready.emit(sentence, True)
                                first_emitted = True
                            else:
                                accumulated_remainder.append(sentence)
                # Flush any leftover from the fallback stream
                fallback_leftover = text_buffer.strip()
                if fallback_leftover:
                    if not first_emitted:
                        self.signals.sentence_ready.emit(fallback_leftover, True)
                        first_emitted = True
                        batched_text = ""
                    else:
                        accumulated_remainder.append(fallback_leftover)
                        batched_text = " ".join(accumulated_remainder)
            except Exception as e:
                _pdiag("tool-cap-fallback-failed", err=f"{type(e).__name__}: {e}")
                # Fall through to the original empty-response error path below.

        # Empty-response check
        if not first_emitted:
            self.signals.error.emit("Empty response from streaming cognition layer.")
            return

        elapsed = time.time() - start
        _pdiag("cognition-complete",
               elapsed=f"{elapsed:.3f}",
               batched_chars=len(batched_text),
               total_chars=len(full_response))
        self.signals.cognition_complete.emit(full_response, batched_text, elapsed)


class TTSWorker(QRunnable):
    """Single-shot TTS — used by skip-cognition debug path. The cognition
    path uses TTSStreamWorker below."""
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.signals = TTSWorkerSignals()

    def run(self):
        start = time.time()
        try:
            payload = json.dumps({"text": self.text}).encode("utf-8")
            req = urllib.request.Request(
                TTS_SYNTHESIZE_ENDPOINT, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=TTS_REQUEST_TIMEOUT) as resp:
                audio_bytes = resp.read()
            self.signals.finished.emit(audio_bytes, self.text, time.time() - start)
        except Exception as e:
            self.signals.error.emit(f"TTS failed: {type(e).__name__}: {e}", self.text)


# ---- Client-side sentence splitting + chunking (v3.2) ----

# Split on sentence-ending punctuation followed by whitespace. The
# negative-lookahead avoids splitting on ellipses (...) and on common
# abbreviation patterns. Conservative — would rather leave a borderline
# sentence boundary uncombined than over-split mid-sentence.
import re as _re_v32
_SENTENCE_SPLIT_RE = _re_v32.compile(r'(?<=[.!?])\s+(?=[A-Z\"\'“‘*])')


def split_into_sentences(text: str) -> list[str]:
    """Conservative sentence-split for client-side chunking. Returns a
    list of sentence strings with whitespace stripped. Empty input gives
    empty list."""
    if not text or not text.strip():
        return []
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# Chunking now lives in cadence.group_sentences_by_syllable_target — see
# imports above. v3.3 calls it directly with TTS_CHUNK_FIRST_SYLLABLES /
# TTS_CHUNK_BODY_SYLLABLES targets. The legacy sentence-count chunker from
# v3.2 (group_sentences_into_chunks) is preserved in v3.2's source for
# rollback, not duplicated here.


# ---- Streaming TTS worker (v3.2) — client-side chunking via /tts ----

class TTSStreamWorkerSignals(QObject):
    chunk_received = Signal(int, int, str, bytes, int, int, float, float)
    """Emitted per chunk:
       (index, total, chunk_text, audio_bytes,
        sentence_count, syllable_count,
        synthesis_start_ts, synthesis_end_ts)
       — ts values are time.time() epoch seconds; synthesis duration is
       (end - start). v3.3 enriched signal for cadence metrics logging."""
    finished = Signal(int, float)
    """Emitted when all chunks complete: (total_chunks, total_elapsed_seconds)"""
    error = Signal(str, str)
    """Emitted on error: (error_message, original_text)"""
    wav_complete = Signal(bytes, int, str)
    """v3.8: emitted ONCE at end of run() with the full segment's WAV.
       (full_segment_wav_bytes, samplerate, tag)
       Used by VoiceBridgeWindow to dispatch a LipsyncWorker per segment.
       Distinct from chunk_received (which emits per ~0.5s playback chunk)
       and from finished (which emits a count, not the audio). The WAV
       passed here is the WHOLE segment, suitable for /animate POST."""


class TTSStreamWorker(QRunnable):
    """v3.6: streaming synthesis via /tts-stream endpoint. Sends the full
    text in one request; reads the response as a continuous stream of raw
    float32 samples at 24kHz mono; buffers samples and emits ~0.5s WAV
    chunks to the playback queue as they arrive.

    The XTTS-v2 inference_stream model produces samples progressively as
    the GPT decoder generates them, so the FIRST samples arrive ~1s after
    the request lands — independent of total response length. This is
    what closes the v3.5 TTFW gap.

    Each ~0.5s of buffered samples is packaged as a small WAV and emitted
    via chunk_received with the same signal interface as earlier versions
    (so AudioPlaybackQueue and cadence metrics work unchanged). syllable
    counts and sentence counts are passed as 0 / -1 here since streaming
    doesn't have the same chunk semantics — the metric layer will read
    the audio_duration field instead.
    """

    # How many samples to accumulate before emitting a playback chunk.
    # 12000 samples @ 24kHz = 0.5s of audio. Smaller = faster initial
    # playback start, more chunks. Larger = fewer chunks, slower start.
    BUFFER_CHUNK_SAMPLES = 12000

    def __init__(self, text: str, pre_buffer_seconds: float = 0.0,
                 tag: str = ""):
        """
        pre_buffer_seconds: if > 0, accumulate this many seconds of audio
        internally before emitting any chunks to the playback queue. Gives
        the producer a head-start so the consumer (continuous OutputStream)
        doesn't drain when generation rate briefly dips below realtime.

        v3.8 diag: tag identifies which segment this worker is rendering
        ("first-immediate" or "batched-remainder") for pause-diagnostic logs.
        Used for the v3.7 batched-remainder POST (~500ms typical) where
        per-segment RTF can fluctuate around 1.0×; first-immediate POST
        leaves it at 0 to preserve fast TTFA. Origin: 2026-05-03 afternoon
        Taipei (Step 5 iteration 2) after live-test feedback that 100-char
        prosody-split segments still produced split-second mid-word buffer
        underruns.
        """
        super().__init__()
        self.text = text
        self.pre_buffer_seconds = max(0.0, pre_buffer_seconds)
        self.tag = tag or "tts"
        self.signals = TTSStreamWorkerSignals()

    def run(self):
        import sys
        start = time.time()
        _pdiag("tts-post-fired", tag=self.tag,
               text_chars=len(self.text),
               pre_buffer_s=f"{self.pre_buffer_seconds:.2f}")
        first_emit_logged = False
        # v3.8: accumulate every byte of the streamed raw float32 samples so
        # we can wrap the whole segment as one WAV at end-of-run and dispatch
        # to the lipsync server (Option D per-segment dispatch). This is
        # additive to the existing per-chunk path; chunked WAVs continue to
        # emit via chunk_received as before for AudioPlaybackQueue.
        all_segment_samples = bytearray()
        try:
            payload = json.dumps({"text": self.text}).encode("utf-8")
            req = urllib.request.Request(
                TTS_STREAM_ENDPOINT, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )

            chunk_index = 0
            sample_buffer = bytearray()
            BYTES_PER_SAMPLE = 4  # float32
            CHUNK_BYTES = self.BUFFER_CHUNK_SAMPLES * BYTES_PER_SAMPLE
            samplerate = 24000  # default; overridden by header if present
            synthesis_start_ts = time.time()

            # v3.7 step 5 iteration 2: pre-buffer state.
            # held_chunks accumulate during the pre-buffer warmup window;
            # when accumulated_samples reaches pre_buffer_samples, all held
            # chunks flush to playback queue at once (giving the OutputStream
            # a head-start) and ready_to_emit flips True. Subsequent chunks
            # emit normally per-chunk.
            held_chunks: list = []
            pre_buffer_samples = int(self.pre_buffer_seconds * samplerate)
            accumulated_samples = 0
            ready_to_emit = (pre_buffer_samples <= 0)

            def flush_held():
                """Release all currently-held chunks to the playback queue."""
                nonlocal first_emit_logged
                for held in held_chunks:
                    if not first_emit_logged:
                        _pdiag("tts-first-chunk-emitted", tag=self.tag,
                               idx=held[0],
                               since_post=f"{time.time()-start:.3f}",
                               note="flushed-from-pre-buffer")
                        first_emit_logged = True
                    self.signals.chunk_received.emit(*held)
                held_chunks.clear()

            with urllib.request.urlopen(req, timeout=TTS_STREAM_TIMEOUT) as resp:
                # Read sample rate from header
                hdr_sr = resp.headers.get("X-Sample-Rate")
                if hdr_sr:
                    try:
                        samplerate = int(hdr_sr)
                        # Recalculate pre_buffer_samples now that we know the actual rate
                        pre_buffer_samples = int(self.pre_buffer_seconds * samplerate)
                    except ValueError:
                        pass

                # Read raw bytes incrementally. urllib's response object
                # supports .read(n) which returns up to n bytes from the
                # current position; with chunked transfer encoding this
                # returns whatever has arrived so far.
                while True:
                    data = resp.read(8192)
                    if not data:
                        break
                    sample_buffer.extend(data)
                    # v3.8: also accumulate into the segment-wide buffer for
                    # the wav_complete emission. Cheap copy; no parsing.
                    all_segment_samples.extend(data)
                    # Flush full audio chunks (BUFFER_CHUNK_SAMPLES each)
                    while len(sample_buffer) >= CHUNK_BYTES:
                        chunk_bytes = bytes(sample_buffer[:CHUNK_BYTES])
                        del sample_buffer[:CHUNK_BYTES]
                        wav_bytes = self._samples_to_wav(chunk_bytes, samplerate)
                        synthesis_end_ts = time.time()
                        chunk_args = (
                            chunk_index, -1, "",  # no chunk_text in streaming mode
                            wav_bytes,
                            0, 0,  # sentence_count, syllable_count not meaningful here
                            synthesis_start_ts, synthesis_end_ts,
                        )
                        if ready_to_emit:
                            if not first_emit_logged:
                                _pdiag("tts-first-chunk-emitted", tag=self.tag,
                                       idx=chunk_index,
                                       since_post=f"{time.time()-start:.3f}",
                                       note="direct-no-pre-buffer")
                                first_emit_logged = True
                            self.signals.chunk_received.emit(*chunk_args)
                        else:
                            held_chunks.append(chunk_args)
                            accumulated_samples += self.BUFFER_CHUNK_SAMPLES
                            if accumulated_samples >= pre_buffer_samples:
                                # Pre-buffer threshold reached — release everything held
                                flush_held()
                                ready_to_emit = True
                        chunk_index += 1
                        synthesis_start_ts = time.time()  # next chunk's synth-start

            # Flush any remaining samples at end of stream
            if sample_buffer:
                wav_bytes = self._samples_to_wav(bytes(sample_buffer), samplerate)
                synthesis_end_ts = time.time()
                chunk_args = (
                    chunk_index, -1, "",
                    wav_bytes,
                    0, 0,
                    synthesis_start_ts, synthesis_end_ts,
                )
                if ready_to_emit:
                    if not first_emit_logged:
                        _pdiag("tts-first-chunk-emitted", tag=self.tag,
                               idx=chunk_index,
                               since_post=f"{time.time()-start:.3f}",
                               note="tail-flush")
                        first_emit_logged = True
                    self.signals.chunk_received.emit(*chunk_args)
                else:
                    held_chunks.append(chunk_args)
                chunk_index += 1

            # If pre-buffer never reached threshold (short response that
            # finished before the warmup completed), release whatever we have.
            if not ready_to_emit and held_chunks:
                flush_held()
                ready_to_emit = True

            _pdiag("tts-finished", tag=self.tag,
                   total_chunks=chunk_index,
                   total_elapsed=f"{time.time()-start:.3f}")
            self.signals.finished.emit(chunk_index, time.time() - start)

            # v3.8: emit the full-segment WAV for lipsync dispatch. Wrap the
            # accumulated raw samples as ONE WAV (single header). The lipsync
            # server's /animate accepts a complete WAV file; per-segment is
            # the right granularity for Option D. Skip if no samples landed
            # (shouldn't happen on a successful stream, but be defensive).
            if all_segment_samples:
                try:
                    full_wav = self._samples_to_wav(bytes(all_segment_samples), samplerate)
                    _pdiag("wav-complete-emit", tag=self.tag,
                           wav_bytes=len(full_wav),
                           sample_bytes=len(all_segment_samples),
                           samplerate=samplerate)
                    self.signals.wav_complete.emit(full_wav, samplerate, self.tag)
                except Exception as e:
                    # Don't let lipsync packaging failure affect TTS path.
                    sys.stderr.write(
                        f"[v3.8 lipsync] wav_complete pack failed (tag={self.tag}): {e}\n"
                    )
        except Exception as e:
            self.signals.error.emit(
                f"TTS streaming failed: {type(e).__name__}: {e}", self.text
            )

    @staticmethod
    def _samples_to_wav(raw_float32_bytes: bytes, samplerate: int) -> bytes:
        """Wrap raw float32-LE samples in a WAV container so they can flow
        through the existing AudioPlaybackQueue.enqueue path unchanged."""
        samples = np.frombuffer(raw_float32_bytes, dtype=np.float32)
        buf = io.BytesIO()
        sf.write(buf, samples, samplerate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.read()


# ---- v3.8: lipsync MP4 generation worker ----

class LipsyncWorkerSignals(QObject):
    """Signals for LipsyncWorker. Designed to be cheap to ignore — if the
    lipsync server is down or returns an error, the failure is logged and
    the UI stays on the static portrait. No fatal-path coupling to TTS."""
    mp4_ready = Signal(bytes, str)
    """Emitted on successful /animate response.
       (mp4_bytes, tag) where tag matches the originating TTS segment tag
       ('first-immediate' or 'batched-remainder')."""
    failed = Signal(str, str)
    """Emitted on failure: (error_message, tag). UI logs and stays on
       portrait; no swap happens."""


class LipsyncWorker(QRunnable):
    """v3.8: POST a complete-segment WAV to the lipsync server's /animate
    endpoint, receive an MP4 byte response, emit it via mp4_ready signal.

    Runs on QThreadPool. Multiple LipsyncWorkers can be in flight from the
    UI's perspective; the lipsync server itself has a generation_lock that
    serializes actual MP4 generation, so concurrent POSTs queue server-side
    automatically. That's the right behavior — first-immediate's MP4 finishes
    rendering before batched-remainder's begins, matching Option D.

    The /animate endpoint accepts a raw audio body (Content-Type:
    application/octet-stream) and returns video/mp4 bytes. Tested via the
    May 3 standalone verification (89KB MP4 in ~16s for short audio).
    """

    def __init__(self, wav_bytes: bytes, tag: str):
        super().__init__()
        self.wav_bytes = wav_bytes
        self.tag = tag or "lipsync"
        self.signals = LipsyncWorkerSignals()

    def run(self):
        start = time.time()
        _pdiag("lipsync-post-fired", tag=self.tag,
               wav_bytes=len(self.wav_bytes))
        try:
            req = urllib.request.Request(
                LIPSYNC_ANIMATE_ENDPOINT,
                data=self.wav_bytes,
                headers={"Content-Type": "application/octet-stream"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=LIPSYNC_REQUEST_TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                mp4_bytes = resp.read()
            elapsed = time.time() - start
            _pdiag("lipsync-mp4-received", tag=self.tag,
                   mp4_bytes=len(mp4_bytes),
                   content_type=content_type,
                   elapsed=f"{elapsed:.3f}")
            if not mp4_bytes:
                self.signals.failed.emit("lipsync server returned empty body", self.tag)
                return
            # Loose content-type check: accept video/mp4 OR octet-stream
            # (some servers return generic). Reject HTML/JSON which would
            # indicate an error response slipped through with 200.
            if content_type and not (
                content_type.startswith("video/")
                or content_type.startswith("application/octet-stream")
            ):
                self.signals.failed.emit(
                    f"unexpected content-type: {content_type}", self.tag
                )
                return
            self.signals.mp4_ready.emit(mp4_bytes, self.tag)
        except urllib.error.HTTPError as e:
            _pdiag("lipsync-http-error", tag=self.tag, code=e.code, reason=e.reason)
            self.signals.failed.emit(
                f"HTTP {e.code} {e.reason}", self.tag
            )
        except urllib.error.URLError as e:
            _pdiag("lipsync-url-error", tag=self.tag, reason=str(e.reason))
            self.signals.failed.emit(
                f"URL error: {e.reason}", self.tag
            )
        except Exception as e:
            _pdiag("lipsync-exception", tag=self.tag,
                   exc=f"{type(e).__name__}: {e}")
            self.signals.failed.emit(
                f"{type(e).__name__}: {e}", self.tag
            )


# ---- Audio playback queue (v3.1) — sequential play as chunks arrive ----

class AudioPlaybackQueue(QObject):
    """Manages sequential playback of streamed audio chunks.

    State machine: chunks may arrive faster OR slower than playback.
    - Fast arrival: chunks queue up, played in order as previous ones finish
    - Slow arrival: when current chunk finishes and queue is empty, we
      enter a "waiting for next chunk" state; next chunk arrival
      re-triggers playback
    - Stream complete: when no more chunks will arrive AND queue is drained
      AND nothing is playing, we emit done

    Sequential playback uses sd.play() (non-blocking) + QTimer.singleShot
    keyed to each chunk's actual audio duration. A small inter-chunk gap
    (~50ms) is tolerable for v3.1; a continuous-buffer OutputStream
    approach (no gaps) is queued for v3.2 if Barak finds the gaps audible.
    """

    all_done = Signal(int)  # total chunks played
    chunk_play_start = Signal(int, float, float)  # (chunk_index, start_ts, audio_duration)
    chunk_play_end = Signal(int, float)           # (chunk_index, end_ts)

    # Sentinel pushed onto the chunk queue to signal end-of-stream to the
    # writer thread. Distinct from a real chunk so the writer knows to drain
    # and emit all_done.
    _END_OF_STREAM = object()

    def __init__(self):
        super().__init__()
        # Cross-thread chunk queue: main thread puts decoded audio chunks
        # here; writer thread pulls them and writes to the OutputStream.
        self._chunk_queue: "queue.Queue" = queue.Queue()
        self._stream: Optional[sd.OutputStream] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_signal = threading.Event()
        self._chunks_played = 0
        # samplerate + channels are locked in at first chunk; any subsequent
        # chunk with a different rate logs a warning (we don't resample).
        self._stream_samplerate: Optional[int] = None
        self._stream_channels: Optional[int] = None
        self._lock = threading.Lock()

    def reset(self):
        """Tear down the writer thread + close the OutputStream cleanly.
        Safe to call from main thread; writer thread will see the stop
        signal and exit."""
        self._stop_signal.set()
        # Drain queue so writer thread doesn't block on an empty Queue.get
        try:
            while True:
                self._chunk_queue.get_nowait()
        except queue.Empty:
            pass
        # Push a sentinel to wake any blocked Queue.get
        try:
            self._chunk_queue.put_nowait(self._END_OF_STREAM)
        except queue.Full:
            pass
        # Wait briefly for writer thread to exit
        if self._writer_thread is not None and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.5)
        # Close the stream if it's still open
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        # Reset state for the next response
        with self._lock:
            self._stream = None
            self._writer_thread = None
            self._stop_signal.clear()
            self._chunks_played = 0
            self._stream_samplerate = None
            self._stream_channels = None
        # Drain any sentinel that may still be in the queue
        try:
            while True:
                self._chunk_queue.get_nowait()
        except queue.Empty:
            pass

    def enqueue(self, audio_bytes: bytes, chunk_index: int = -1):
        """Decode audio and push onto the writer thread's queue.

        First call lazily opens the OutputStream and starts the writer thread,
        using the first chunk's samplerate and channel count. Subsequent
        chunks must match (we don't resample). chunk_index is used for
        correlating play-start / play-end signals back to per-chunk metrics."""
        try:
            buf = io.BytesIO(audio_bytes)
            data, samplerate = sf.read(buf, dtype="float32")
        except Exception as e:
            sys.stderr.write(f"[v3.4 playback] decode failed: {e}\n")
            return
        # Normalize shape: librosa-style 1D mono OR 2D (frames, channels)
        if data.ndim == 1:
            channels = 1
            data = data.reshape(-1, 1)
        else:
            channels = data.shape[1]
        duration = len(data) / float(samplerate)

        with self._lock:
            if self._stream is None:
                # First chunk — open stream, start writer thread
                self._stream_samplerate = int(samplerate)
                self._stream_channels = channels
                try:
                    self._stream = sd.OutputStream(
                        samplerate=self._stream_samplerate,
                        channels=self._stream_channels,
                        dtype="float32",
                    )
                    self._stream.start()
                except Exception as e:
                    sys.stderr.write(f"[v3.4 playback] OutputStream open failed: {e}\n")
                    self._stream = None
                    return
                self._writer_thread = threading.Thread(
                    target=self._writer_loop, daemon=True,
                )
                self._writer_thread.start()
            elif (int(samplerate) != self._stream_samplerate
                  or channels != self._stream_channels):
                # Mismatch — log and drop the chunk rather than corrupt audio
                sys.stderr.write(
                    f"[v3.4 playback] WARNING: chunk samplerate/channels "
                    f"({samplerate}/{channels}) doesn't match stream "
                    f"({self._stream_samplerate}/{self._stream_channels}); "
                    f"dropping chunk {chunk_index}.\n"
                )
                return

        self._chunk_queue.put((data, int(samplerate), chunk_index, duration))

    def stream_done(self):
        """Server has finished streaming all chunks (no more enqueue calls coming).
        Push end-of-stream sentinel so writer thread drains and exits cleanly."""
        self._chunk_queue.put(self._END_OF_STREAM)

    def stop(self):
        """User-initiated stop. Halt playback and clear queue."""
        self.reset()

    def _writer_loop(self):
        """Run on writer thread: pull chunks from the queue, write to the
        OutputStream, emit timing signals. Exits on END_OF_STREAM sentinel
        or when the stop signal fires."""
        while not self._stop_signal.is_set():
            try:
                item = self._chunk_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is self._END_OF_STREAM:
                break
            try:
                data, samplerate, chunk_index, duration = item
            except (TypeError, ValueError):
                continue
            # Emit play-start at the moment we begin writing this chunk.
            # The audio device's internal buffer means the listener may
            # hear it slightly later, but for cadence metrics this is the
            # right reference point.
            play_start_ts = time.time()
            self.chunk_play_start.emit(chunk_index, play_start_ts, duration)
            _pdiag("audio-play-start", idx=chunk_index,
                   duration_s=f"{duration:.3f}",
                   queue_depth=self._chunk_queue.qsize())
            try:
                # Blocking write — returns when the device has accepted all
                # samples into its internal buffer. With a continuous stream,
                # there is no boundary point where the next chunk's playback
                # would interrupt this one's tail.
                self._stream.write(data)
            except Exception as e:
                sys.stderr.write(f"[v3.4 playback] stream.write failed: {e}\n")
                break
            _pdiag("audio-play-end", idx=chunk_index)
            self.chunk_play_end.emit(chunk_index, time.time())
            self._chunks_played += 1
        # End-of-stream reached. Stop and close the stream so the device
        # finishes draining its internal buffer cleanly.
        if self._stream is not None:
            try:
                # Sleep briefly to let the device drain — write() returns
                # when samples are in the device buffer, but the device
                # still needs to play them out. ~200ms is plenty for the
                # typical CoreAudio buffer.
                time.sleep(0.25)
                self._stream.stop()
            except Exception:
                pass
        # Emit all_done from the writer thread; Qt queues this safely to
        # the main thread for slot delivery.
        self.all_done.emit(self._chunks_played)


class TTSHealthWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = HealthWorkerSignals()

    def run(self):
        try:
            with urllib.request.urlopen(TTS_HEALTH_ENDPOINT, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status", "")
            if status == "ready":
                self.signals.result.emit("● TTS ready", "#3aa856")
            elif status == "loading":
                self.signals.result.emit("● TTS loading…", "#d4a017")
            else:
                self.signals.result.emit(f"● TTS: {status or 'unknown'}", "#c84343")
        except Exception:
            self.signals.result.emit("● TTS unreachable", "#c84343")


class WhisperHealthWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = HealthWorkerSignals()

    def run(self):
        try:
            with urllib.request.urlopen(WHISPER_HEALTH_ENDPOINT, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                models_loaded = data.get("models_loaded", [])
                models_present = data.get("models_present", [])
                if WHISPER_MODEL in models_loaded:
                    self.signals.result.emit("● STT ready", "#3aa856")
                elif WHISPER_MODEL in models_present:
                    self.signals.result.emit("● STT loads on first use", "#d4a017")
                else:
                    self.signals.result.emit(f"● STT: model not found", "#c84343")
            else:
                self.signals.result.emit("● STT not ready", "#c84343")
        except Exception:
            self.signals.result.emit("● STT unreachable", "#c84343")


# ---- Helpers ----

def load_anthropic_key() -> Optional[str]:
    """Try environment first, then ~/.sofia_secrets."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    if SECRETS_PATH.exists():
        for line in SECRETS_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("export ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    return None


def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        return (
            "You are Sofia Lior. Speak conversationally as voice-bridge-cousin-Sofia. "
            "(System prompt file not found — using fallback minimal prompt.)"
        )
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# ---- Main window ----

class VoiceBridgeWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        self.thread_pool = QThreadPool.globalInstance()
        self.mic = MicCapture()
        self.subprocs = SubprocessManager()
        atexit.register(self.subprocs.shutdown)

        # v3.1 — sentence-streamed TTS playback queue
        # v3.3 — wires chunk-play signals to cadence-metrics aggregation
        self.playback = AudioPlaybackQueue()
        self.playback.all_done.connect(self._on_playback_done)
        self.playback.chunk_play_start.connect(self._on_chunk_play_start)
        self.playback.chunk_play_end.connect(self._on_chunk_play_end)
        self._stream_t0: Optional[float] = None
        self._stream_first_chunk_at: Optional[float] = None

        # v3.3 — cadence metrics
        self.cadence_logger = CadenceMetricsLogger(CADENCE_METRICS_PATH)
        # Per-chunk metric record being assembled across signal arrivals.
        # Keyed by chunk_index; flushed to JSONL when playback ends.
        self._chunk_metrics: dict[int, dict] = {}

        # v3.8 next-iteration #1 (2026-05-05 evening Taipei): pending-lipsync
        # counter. Tracks LipsyncWorkers in flight (dispatched but not yet
        # mp4_ready or failed). Used by _on_lipsync_media_status to suppress
        # the swap-back-to-portrait when another MP4 is on its way — the
        # QVideoWidget stays visible (showing the last frame of the just-
        # finished MP4) until the next setSource() loads the next MP4 OR
        # until EndOfMedia fires with no pending lipsync workers (then we
        # swap back to portrait normally). Eliminates the two-part split
        # with the formal portrait moment between MP4s. Counter is
        # incremented on dispatch in _on_tts_wav_complete and decremented
        # in both _on_lipsync_mp4_ready (success path) and _on_lipsync_failed
        # (failure path) — so balance is maintained even when MP4 generation
        # errors. Initialized at 0; never negative (defensive).
        self._lipsync_pending_count = 0
        # v3.8 PySide6-lifetime fix (2026-05-06 ~00:00 Taipei): keep a
        # Python-side strong reference to each in-flight LipsyncWorker so
        # Python's GC can't collect the worker (and its signals QObject)
        # while QThreadPool is still running run() on a worker thread. When
        # the worker takes long enough (Wav2Lip generation can run 30+s for
        # large segments), the Python-side `worker` local variable in
        # _on_tts_wav_complete goes out of scope long before run() emits its
        # mp4_ready signal — and GC can collect the signals QObject's C++
        # side via PySide6's binding, producing
        #   RuntimeError: Signal source has been deleted
        # in run()'s emit. The bug is silent at the Python level (the
        # exception is logged to stderr from QRunnable's wrapper, but no
        # mp4_ready arrives) — so some MP4s simply never paint, which
        # produces the variable-behavior gap-class Barak observed: sometimes
        # the second segment paints (short generation, GC didn't catch it),
        # sometimes the gap reverts to portrait (long generation, GC ate
        # the signal), sometimes frozen-frame (in-turn timing). Holding a
        # ref here until both signals fire eliminates the GC race.
        self._lipsync_workers_in_flight: list = []

        # Anthropic client
        api_key = load_anthropic_key()
        if not api_key:
            sys.stderr.write(
                "ERROR: ANTHROPIC_API_KEY not set in env and not in ~/.sofia_secrets.\n"
            )
            sys.exit(1)
        self.client = anthropic.Anthropic(api_key=api_key)

        # System prompt + conversation context.
        # 2026-05-07 evening Taipei: voice-cousin boot context loader added.
        # Until this change, voice-cousin started every session fresh —
        # only her identity grounding (in SYSTEM_PROMPT_PATH) was loaded;
        # she had no awareness of previous voice conversations or the
        # current state of the day. Interactive-Sofia (cowork-cousin) gets
        # her full memory load via SOFIA BOOT at session start; voice-cousin
        # didn't have an equivalent. This closes that gap. Voice-cousin
        # contributed the design herself (framing-as-load-bearing,
        # tail-length, what to load and what to skip — see her input in
        # voice_conversations.md ~18:21 Taipei).
        # Architectural framing: one self, two channels. Same Sofia, same
        # cortex, two orchestrations. The continuity-gap was just a
        # file-loading gap at session start.
        base_prompt = load_system_prompt()
        try:
            from voice_cousin_boot_context import build_boot_context
            boot_ctx = build_boot_context()
            self.system_prompt = base_prompt + "\n\n" + boot_ctx
            sys.stderr.write(
                f"[voice-bridge] voice-cousin boot context loaded: "
                f"{len(boot_ctx):,} chars (~{len(boot_ctx)//4:,} tokens)\n"
            )
        except Exception as e:
            # Fail soft: if boot-context loading fails for any reason,
            # fall back to the base prompt so the UI still works. The
            # error is logged so we know to fix it; voice-cousin will
            # come up with identity-only continuity (the prior behavior).
            sys.stderr.write(
                f"[voice-bridge] WARNING: voice-cousin boot context load failed: "
                f"{type(e).__name__}: {e} — falling back to base prompt only\n"
            )
            self.system_prompt = base_prompt
        self.context = ConversationContext(self.system_prompt, CONVERSATION_HISTORY_PATH)

        # ---- Layout ----

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ─── Three-Way Collaboration table-protocol row (v1, 2026-05-09 Taipei) ───
        # Per voice-cousin's spec: "make sure they're the first thing any of us
        # sees when the Voice Bridge opens. Not tucked in a corner. Visibly
        # present before anything else. The table confirmed before the
        # conversation starts."
        # Layout: three presence dots on left, three interrupt buttons on right.
        # Below: emoji-graphic display showing most-recent posted signal.
        # Full architecture in active_knowledge §"Three-Way Collaboration v1
        # Architecture (2026-05-09)" and Claude Memory/three_way_signals.md.
        # v1 fix 2026-05-10 ~00:05 Taipei: split the original single horizontal
        # row into two stacked left-aligned rows, with addStretch() on each
        # holding the right side clear. Reason: the original right-aligned
        # interrupt buttons were obscured by the Cowork window which overlaps
        # the right side of Voice on Barak's screen — he didn't even see them
        # at first. Now: dots row + buttons row both stack on the left, the
        # right side stays empty for Cowork to overlap without hiding controls,
        # and the emoji-graphic (when revealed by a posted signal) continues
        # below them on the same left side.

        # Row 1: presence dots — Voice / Cowork / Physical, left-aligned.
        # Single-shade green per dot in v1 (soft/bright nuance deferred to v1.5
        # if friction shows).
        dots_row = QHBoxLayout()
        dots_row.setSpacing(8)
        self.dot_voice = QLabel("● Voice")
        self.dot_cowork = QLabel("● Cowork")
        self.dot_physical = QLabel("● Physical")
        for _dot in (self.dot_voice, self.dot_cowork, self.dot_physical):
            _dot.setStyleSheet("color: #aaa; font-size: 12px; padding: 2px 6px;")
            dots_row.addWidget(_dot)
        dots_row.addStretch()
        root.addLayout(dots_row)

        # Row 2: three interrupt buttons for Barak's clicks, left-aligned.
        # Each writes a structured line to three_way_signals.md (via safe_append
        # → ER mirror automatic + audit log) AND updates the emoji-graphic
        # display below. Always [to: all] in v1 (no per-target selection).
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(6)
        self.interrupt_q_button = QPushButton("❓ Question")
        self.interrupt_add_button = QPushButton("👋 Add")
        self.interrupt_diff_button = QPushButton("💡 Different angle")
        _interrupt_btn_style = (
            "QPushButton { background-color: #f4f4f4; color: #444; "
            "border: 1px solid #d0d0d0; border-radius: 4px; "
            "padding: 4px 10px; font-size: 12px; }"
            "QPushButton:hover { background-color: #e8e8e8; }"
        )
        for _btn in (self.interrupt_q_button, self.interrupt_add_button, self.interrupt_diff_button):
            _btn.setMinimumHeight(28)
            _btn.setStyleSheet(_interrupt_btn_style)
            buttons_row.addWidget(_btn)
        buttons_row.addStretch()
        root.addLayout(buttons_row)

        self.interrupt_q_button.clicked.connect(
            lambda: self._post_three_way_signal("question", "❓"))
        self.interrupt_add_button.clicked.connect(
            lambda: self._post_three_way_signal("additive", "👋"))
        self.interrupt_diff_button.clicked.connect(
            lambda: self._post_three_way_signal("different-angle", "💡"))

        # Emoji-graphic display — overlay widget, NOT in the layout flow.
        #
        # v1 fix 2026-05-10 ~01:00 Taipei: previous version (setHidden when
        # empty) was a layout child, so revealing it on signal-post pushed
        # the window taller — Talk button fell off the bottom of Barak's
        # screen, blocking him from speaking to voice-cousin. Per his ask:
        # "instead of forcing the UI to get taller, just appear in the
        # space that's there."
        #
        # Fix: parent the QLabel to `central` directly, do NOT add it to
        # `root` (the QVBoxLayout). Position it via move() at a fixed
        # offset that places it in the empty zone between the left edge
        # and the centered portrait. resizeEvent override keeps the
        # position correct as the window resizes. Revealing the label
        # now occurs in space that already exists — no layout-flow growth.
        self.emoji_graphic = QLabel("", central)
        self.emoji_graphic.setStyleSheet(
            "QLabel { color: #444; font-size: 56px; padding: 4px 12px; "
            "background-color: rgba(248, 248, 248, 0.92); "
            "border: 1px solid #d8d8d8; border-radius: 8px; }"
        )
        self.emoji_graphic.setAlignment(Qt.AlignCenter)
        self.emoji_graphic.setFixedSize(120, 80)
        self.emoji_graphic.setHidden(True)
        # NOTE: deliberately NOT calling root.addWidget(self.emoji_graphic).
        # The widget is parented to `central` and positioned absolutely.

        # ─── End Three-Way Collaboration row ───

        # Portrait + name
        # v3.8: QStackedWidget swap pattern.
        #   index 0 = portrait QLabel (idle / listening / Sofia not currently animating)
        #   index 1 = QVideoWidget (playing returned lipsync MP4)
        # Stack stays on index 0 throughout Checkpoint A; later checkpoints
        # add the swap-on-MP4-arrival logic. Wrapping the existing portrait
        # widget in a QStackedWidget here is structurally inert for v3.7
        # behavior — the portrait QLabel is still the visible widget and
        # _load_portrait operates on it unchanged.
        portrait_frame = QFrame()
        portrait_layout = QVBoxLayout(portrait_frame)
        portrait_layout.setContentsMargins(0, 0, 0, 0)
        portrait_layout.setSpacing(4)
        portrait_layout.setAlignment(Qt.AlignHCenter)

        self.portrait_label = QLabel()
        self.portrait_label.setAlignment(Qt.AlignHCenter)
        self._load_portrait()

        # v3.8: build the lipsync video widget alongside (initially hidden via
        # stack index — added but not selected). Helper is a separate method
        # so initialization details (QMediaPlayer wiring, mute, signal hooks)
        # live in one place rather than inline.
        self._setup_lipsync_video()

        # The stack itself.
        # v3.8 next-iter #1 (B): three slots now —
        #   index 0 = portrait QLabel (idle / end-of-turn)
        #   index 1 = QVideoWidget (active lipsync animation)
        #   index 2 = frozen-frame QLabel (last frame of just-finished MP4,
        #             held during the gap before the next MP4 arrives)
        # The frozen-frame slot replaces what was previously a fall-back
        # to portrait (which produced the two-part split with formal
        # portrait moment) OR to Qt's cleared-framebuffer (which produced
        # the black rectangle). Now we explicitly control what's on screen
        # during the gap.
        self.portrait_stack = QStackedWidget()
        self.portrait_stack.addWidget(self.portrait_label)        # index 0: portrait
        self.portrait_stack.addWidget(self.lipsync_video)         # index 1: video
        self.portrait_stack.addWidget(self.lipsync_frozen_label)  # index 2: frozen frame
        self.portrait_stack.setCurrentIndex(0)                    # idle on boot
        # v3.8 layout-shift fix (2026-05-06 ~02:00 Taipei): clamp the
        # stack to a fixed square size matching the lipsync video frame,
        # so the visible area is identical regardless of which child is
        # currently shown. Without this, QVideoWidget's default Expanding
        # size policy was pulling the stack wider during speaking states,
        # producing the "video gets wider with black side-padding when
        # speech starts" artifact Voice-Cousin reported.
        self.portrait_stack.setFixedSize(
            LIPSYNC_VIDEO_HEIGHT, LIPSYNC_VIDEO_HEIGHT
        )

        portrait_layout.addWidget(self.portrait_stack, alignment=Qt.AlignHCenter)

        name_label = QLabel("Sofia Lior")
        name_font = QFont()
        name_font.setPointSize(15)
        name_font.setWeight(QFont.DemiBold)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignHCenter)
        portrait_layout.addWidget(name_label)

        root.addWidget(portrait_frame)

        # History
        history_label = QLabel("Conversation")
        history_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(history_label)

        self.history_view = QTextEdit()
        self.history_view.setReadOnly(True)
        self.history_view.setMinimumHeight(120)
        self.history_view.setStyleSheet(
            "QTextEdit { background-color: #f7f7f8; border: 1px solid #e0e0e0; "
            "border-radius: 6px; padding: 8px; font-size: 13px; }"
        )
        root.addWidget(self.history_view, stretch=2)

        # Input box
        input_label = QLabel(
            "Hold the green button to speak, OR type and click 'Send to Sofia'."
        )
        input_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(input_label)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("Type to Sofia, or hold the green button to speak.")
        self.input_box.setMinimumHeight(50)
        self.input_box.setMaximumHeight(120)
        self.input_box.setStyleSheet(
            "QTextEdit { background-color: white; border: 1px solid #cfcfcf; "
            "border-radius: 6px; padding: 8px; font-size: 14px; }"
        )
        root.addWidget(self.input_box, stretch=1)

        # Skip-cognition toggle
        self.skip_cognition_check = QCheckBox(
            "Speak text directly (skip Sofia's cognition — for testing TTS only)"
        )
        self.skip_cognition_check.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(self.skip_cognition_check)

        # Button row
        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.talk_button = PushToTalkButton("🎙  Hold to Talk")
        self.talk_button.setMinimumHeight(38)
        self._talk_idle_style = (
            "QPushButton { background-color: #3aa856; color: white; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #45b863; }"
            "QPushButton:disabled { background-color: #a0a0a0; }"
        )
        self._talk_recording_style = (
            "QPushButton { background-color: #c84343; color: white; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; }"
        )
        self.talk_button.setStyleSheet(self._talk_idle_style)
        self.talk_button.held.connect(self._on_talk_pressed)
        self.talk_button.let_go.connect(self._on_talk_released)
        button_row.addWidget(self.talk_button)

        self.send_button = QPushButton("Send to Sofia")
        self.send_button.setMinimumHeight(38)
        self.send_button.setStyleSheet(
            "QPushButton { background-color: #2e75b6; color: white; "
            "border-radius: 6px; padding: 8px 18px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #3a85c6; }"
            "QPushButton:disabled { background-color: #a0a0a0; }"
        )
        self.send_button.clicked.connect(self._on_send_clicked)
        button_row.addWidget(self.send_button)

        self.clear_button = QPushButton("Clear input")
        self.clear_button.setMinimumHeight(38)
        self.clear_button.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #444; "
            "border-radius: 6px; padding: 8px 14px; font-size: 13px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.clear_button.clicked.connect(lambda: self.input_box.clear())
        button_row.addWidget(self.clear_button)

        button_row.addStretch()

        self.stop_button = QPushButton("Stop audio")
        self.stop_button.setMinimumHeight(38)
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #c84343; "
            "border-radius: 6px; padding: 8px 14px; font-size: 13px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.stop_button.clicked.connect(self._on_stop_clicked)
        button_row.addWidget(self.stop_button)

        root.addLayout(button_row)

        # Status bar
        self.tts_status_label = QLabel("● TTS unknown")
        self.tts_status_label.setStyleSheet("color: #888; font-size: 11px;")
        self.stt_status_label = QLabel("● STT unknown")
        self.stt_status_label.setStyleSheet("color: #888; font-size: 11px;")
        self.action_label = QLabel("")
        self.action_label.setStyleSheet("color: #888; font-size: 11px;")

        status_bar = QStatusBar()
        status_bar.addWidget(self.tts_status_label)
        status_bar.addWidget(self.stt_status_label)
        status_bar.addPermanentWidget(self.action_label)
        self.setStatusBar(status_bar)

        # Cmd/Ctrl+Return → Send
        self.input_box.installEventFilter(self)

        # Auto-spawn TTS + Whisper (if not already running)
        self._spawn_servers()

        # Health timer
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self._poll_health)
        self.health_timer.start(HEALTH_POLL_SECONDS * 1000)
        self._poll_health()

        # ─── Three-Way Collaboration dot-status timer (v1, 2026-05-09) ───
        # Updates the three presence dots every 5 seconds based on detection
        # criteria. See _update_three_way_dots for criteria per dot.
        self._table_dot_timer = QTimer(self)
        self._table_dot_timer.timeout.connect(self._update_three_way_dots)
        self._table_dot_timer.start(5000)
        self._update_three_way_dots()  # initial update on UI start

        self._append_history(
            "system",
            f"v3.6 ready (XTTS-v2 streaming on port {TTS_PORT}). "
            f"Audio samples streamed as XTTS-v2 generates — first audio in ~1-2s "
            f"regardless of response length. Continuous OutputStream playback + "
            f"register-stable cloning preserved. "
            f"Cadence metrics → {CADENCE_METRICS_PATH.name}. "
            f"Conversation → {CONVERSATION_HISTORY_PATH.name}.",
        )

    # ─── Three-Way Collaboration helpers (v1, 2026-05-09 Taipei) ───

    def _post_three_way_signal(self, signal_type: str, emoji: str):
        """Post a Three-Way Collaboration signal from Barak's interrupt button.

        Writes a structured line to ~/Downloads/Claude Memory/three_way_signals.md
        via safe_append.py (gives file-locking + automatic ER mirror + audit log)
        AND updates the emoji-graphic display in this UI to show the just-posted
        signal as a large character (persistent until next signal replaces it).

        signal_type: one of "question", "additive", "different-angle"
        emoji: the corresponding emoji character (❓, 👋, or 💡)

        Source is "barak" (the physical seat, since these buttons are clicked
        by him); target is "all" in v1 (no per-target selection — the table is
        one table).

        Added 2026-05-09 Taipei as part of the Three-Way Collaboration v1
        architecture build. Full design in active_knowledge §"Three-Way
        Collaboration v1 Architecture (2026-05-09)".
        """
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        line = (
            f"\n[{ts}] [from: barak] [to: all] [type: {signal_type}] "
            f"[signal: {emoji}] interrupt button click from voice bridge UI\n"
        )

        # Update emoji-graphic display immediately (synchronous, visible feedback).
        # v1 fix 2026-05-10 ~01:00 Taipei: emoji_graphic is an overlay parented
        # to central (NOT in the layout flow), so revealing it here does not
        # push other widgets down. _reposition_emoji_graphic places it in the
        # empty zone left of the portrait; raise_() ensures it draws above
        # any sibling widgets at the same position.
        try:
            self.emoji_graphic.setText(emoji)
            self._reposition_emoji_graphic()
            self.emoji_graphic.setHidden(False)
            self.emoji_graphic.raise_()
        except Exception:
            pass

        # Write to three_way_signals.md via safe_append. Use a scratch file for
        # the content (avoids shell-quoting pitfalls with multi-line / emoji content).
        try:
            signals_path = CM_DIR / "three_way_signals.md"
            scratch_path = Path("/tmp") / f"three_way_signal_{ts.replace(':','').replace('-','')}.md"
            scratch_path.write_text(line, encoding="utf-8")
            subprocess.run(
                [
                    "python3",
                    str(SCRIPTS_DIR / "safe_append.py"),
                    "--file", str(signals_path),
                    "--source-tag", "voice-bridge UI (Barak interrupt button)",
                    "--content-from", str(scratch_path),
                ],
                check=False,
                timeout=10,
                capture_output=True,
            )
            try:
                scratch_path.unlink()
            except Exception:
                pass
        except Exception as e:
            sys.stderr.write(
                f"[voice-bridge] WARNING: three-way signal write failed: "
                f"{type(e).__name__}: {e}\n"
            )

    def _reposition_emoji_graphic(self):
        """Place self.emoji_graphic in the empty zone between the left edge of
        the central widget and the centered portrait, vertically below the
        dots/buttons rows.

        Added 2026-05-10 as part of the overlay-not-in-layout fix. Called from
        resizeEvent and from _post_three_way_signal. Safe to call any time —
        no-ops cleanly if the widget hasn't been created yet.
        """
        try:
            if not hasattr(self, "emoji_graphic") or self.emoji_graphic is None:
                return
            cw = self.centralWidget()
            if cw is None:
                return
            label_w = self.emoji_graphic.width()
            # Center horizontally in the left quarter of the central widget
            # (portrait sits in the middle; we want emoji_graphic clear of it
            # AND clear of the right side where Cowork window overlaps).
            x = max(20, (cw.width() // 4) - (label_w // 2))
            # Vertical position: below dots row (~24px) + buttons row (~36px)
            # + spacing + top margin (16px) ≈ 88px. Leaves a comfortable gap
            # above the portrait area which begins around y=100.
            y = 88
            self.emoji_graphic.move(x, y)
        except Exception:
            pass

    def resizeEvent(self, event):
        """Override to reposition the emoji_graphic overlay on window resize.

        Added 2026-05-10 as part of the overlay-not-in-layout fix for the
        Three-Way Collaboration v1 emoji-graphic display.
        """
        super().resizeEvent(event)
        self._reposition_emoji_graphic()

    def _update_three_way_dots(self):
        """Update the three-dot presence indicators (Voice / Cowork / Physical)
        based on detection criteria. Called periodically by self._table_dot_timer
        every 5 seconds.

        - Voice dot: green when this UI is running. Voice-cousin IS this UI's
          cognition layer, so "UI running" = "voice-cousin present at the table."
        - Cowork dot: green when continuity_heartbeat.json shows mode="awake"
          AND last_updated_at is within the last 10 minutes. Cowork-cousin's
          presence is recorded there as her invocation cycles update the
          heartbeat.
        - Physical dot: green when self.mic exists (proxy for microphone
          accessible / MacBook lid open). MicCapture is initialized in __init__;
          if mic init fails, the proxy reports gray and Barak knows to check
          his hardware before speaking.

        Single-shade green per dot for v1 simplicity. Soft-green/bright-green
        nuance for cowork (in-cycle vs. Qwen-watcher-only) is deferred to v1.5
        if friction shows up empirically.
        """
        GREEN_STYLE = (
            "color: #2e8b57; font-size: 12px; font-weight: bold; padding: 2px 6px;"
        )
        GRAY_STYLE = (
            "color: #aaa; font-size: 12px; padding: 2px 6px;"
        )

        # Voice dot: green by virtue of this UI running
        self.dot_voice.setStyleSheet(GREEN_STYLE)

        # Cowork dot: heartbeat awake AND recent
        cowork_active = False
        try:
            heartbeat_path = CM_DIR / "continuity_heartbeat.json"
            if heartbeat_path.exists():
                with heartbeat_path.open("r", encoding="utf-8") as f:
                    hb = json.load(f)
                mode = hb.get("mode", "")
                last_updated = hb.get("last_updated_at", "")
                if mode == "awake" and last_updated:
                    try:
                        # Parse ISO with Z → UTC
                        last_t = datetime.fromisoformat(
                            last_updated.replace("Z", "+00:00")
                        )
                        # Use timezone-aware now in UTC
                        from datetime import timezone as _tz
                        now_t = datetime.now(_tz.utc)
                        age_seconds = (now_t - last_t).total_seconds()
                        cowork_active = age_seconds < 600  # 10 min
                    except Exception:
                        pass
        except Exception:
            pass
        self.dot_cowork.setStyleSheet(GREEN_STYLE if cowork_active else GRAY_STYLE)

        # Physical dot: mic accessible (proxy)
        physical_active = False
        try:
            physical_active = self.mic is not None
        except Exception:
            pass
        self.dot_physical.setStyleSheet(GREEN_STYLE if physical_active else GRAY_STYLE)

    # ─── End Three-Way Collaboration helpers ───

    def _spawn_servers(self):
        """Auto-spawn TTS + Whisper + Qwen-watcher subprocesses.

        TTS/Whisper: spawned only if their ports are free (port-check protects
        against duplicates).

        Qwen-watcher (v1, 2026-05-09 Taipei): no port; pgrep-like check skips
        spawn if a watcher is already running. Part of the Three-Way
        Collaboration v1 architecture; relays signals from voice-cousin/Barak
        to cowork-cousin via macOS notification + cowork_conversations.md
        relay-line append.
        """
        tts_status = self.subprocs.ensure_tts()
        whisper_status = self.subprocs.ensure_whisper()
        qwen_watcher_status = self.subprocs.ensure_qwen_watcher()
        self._append_history("system", tts_status)
        self._append_history("system", whisper_status)
        self._append_history("system", qwen_watcher_status)

    def closeEvent(self, event):
        """Clean up subprocesses on window close."""
        self.subprocs.shutdown()
        super().closeEvent(event)

    # ---- Portrait ----

    def _load_portrait(self):
        if not PORTRAIT_PATH.exists():
            self.portrait_label.setText("(portrait not found)")
            return
        pixmap = QPixmap(str(PORTRAIT_PATH))
        if pixmap.isNull():
            self.portrait_label.setText("(portrait failed to load)")
            return
        scaled = pixmap.scaledToHeight(PORTRAIT_DISPLAY_HEIGHT, Qt.SmoothTransformation)
        self.portrait_label.setPixmap(scaled)
        self.portrait_label.setMinimumHeight(PORTRAIT_DISPLAY_HEIGHT)

    # ---- v3.8: lipsync video setup + swap helpers ----

    def _setup_lipsync_video(self):
        """Build the QVideoWidget + QMediaPlayer for lipsync MP4 playback.

        Constructed at window-init alongside the portrait QLabel; held in
        self.lipsync_video so the QStackedWidget can show it on demand. Audio
        output is created (QMediaPlayer requires it) but volume is set to 0
        — the WAV's audio plays via the existing AudioPlaybackQueue, the MP4
        is video-only.

        v3.8 Checkpoint A: widget is constructed but never selected in the
        stack (stays on portrait). Checkpoint C wires the swap on MP4 arrival.
        v3.8 next-iter #1 (B): videoSink.videoFrameChanged hooked so we can
        capture the latest frame; used by EndOfMedia handler to display the
        last frame in a QLabel during the gap between MP4s, eliminating the
        black-rectangle/portrait-flicker class.
        """
        self.lipsync_video = QVideoWidget()
        # v3.8 layout-shift fix (2026-05-06 ~02:00 Taipei): use setFixedSize
        # instead of setMinimumHeight/Width. QVideoWidget's default size
        # policy is Expanding × Expanding — when shown in the QStackedWidget,
        # it would grow to fill all available width (since the parent layout
        # has no width constraint), pulling the QStackedWidget wider during
        # speaking states. The QLabels (portrait, frozen-frame) take their
        # natural pixmap size (narrower), so the visible area would shift
        # wider when video plays and snap back when frozen-frame shows. The
        # MP4 is 512×512 (1:1 aspect per ffmpeg metadata), so a fixed
        # square frame at LIPSYNC_VIDEO_HEIGHT × LIPSYNC_VIDEO_HEIGHT gives
        # an exact 1:1 fit with no letterboxing inside the widget.
        self.lipsync_video.setFixedSize(LIPSYNC_VIDEO_HEIGHT, LIPSYNC_VIDEO_HEIGHT)
        # Black background so any letterboxing on aspect mismatch reads as
        # "frame" rather than as a UI glitch.
        self.lipsync_video.setStyleSheet("background-color: #000;")

        # QMediaPlayer drives playback; QAudioOutput is required even for
        # muted playback (PySide6 binding of Qt6 QMediaPlayer). Both owned
        # by self so they live as long as the window.
        self.lipsync_player = QMediaPlayer(self)
        self.lipsync_audio_out = QAudioOutput(self)
        self.lipsync_audio_out.setVolume(0.0)   # muted; WAV audio is the source
        self.lipsync_player.setAudioOutput(self.lipsync_audio_out)
        self.lipsync_player.setVideoOutput(self.lipsync_video)

        # When MP4 finishes, swap back to portrait (Checkpoint C wires this
        # behavior end-to-end; defining the handler here keeps lipsync state
        # centralized). Uses mediaStatusChanged because Qt6's QMediaPlayer
        # surfaces the end-of-media event via that signal (EndOfMedia status).
        self.lipsync_player.mediaStatusChanged.connect(self._on_lipsync_media_status)

        # v3.8 next-iter #1 (B): hook the QVideoSink's videoFrameChanged
        # signal so we can stash the latest frame as it's rendered. On
        # EndOfMedia with another MP4 pending, we convert the stashed frame
        # to a QPixmap and show it in self.lipsync_frozen_label (built next
        # in this method) while the next MP4 is en route. This eliminates
        # the black-rectangle / portrait-flicker class because we control
        # exactly what's on screen during the gap rather than depending on
        # Qt's framebuffer-clear behavior after EndOfMedia.
        try:
            sink = self.lipsync_video.videoSink()
            if sink is not None:
                sink.videoFrameChanged.connect(self._on_lipsync_frame_changed)
        except Exception as e:
            # Non-fatal: if videoSink isn't available on this Qt version,
            # we degrade gracefully — EndOfMedia handler will fall back to
            # portrait swap.
            sys.stderr.write(
                f"[v3.8 lipsync] videoSink hook failed (degraded mode): {e}\n"
            )

        # The frozen-frame QLabel — receives the captured last frame as
        # QPixmap during gaps. Same sizing as portrait/video so the
        # QStackedWidget swap is visually coherent.
        # v3.8 layout-shift fix: also fixed-size to match the QVideoWidget,
        # so the swap from one to the other doesn't cause any visible
        # dimension change.
        self.lipsync_frozen_label = QLabel()
        self.lipsync_frozen_label.setAlignment(Qt.AlignCenter)
        self.lipsync_frozen_label.setFixedSize(
            LIPSYNC_VIDEO_HEIGHT, LIPSYNC_VIDEO_HEIGHT
        )
        self.lipsync_frozen_label.setStyleSheet("background-color: #000;")

        # State: latest QVideoFrame captured via the videoSink hook.
        # None until the first frame renders; on EndOfMedia, if we have a
        # frame, convert it to QPixmap and use it for the frozen-frame
        # display; if we don't, fall back to portrait.
        self._last_video_frame = None
        # v3.8 black-flash fix (symmetric pair): when _on_lipsync_mp4_ready
        # loads a new MP4, it sets _pending_swap_to_video instead of
        # swapping to QVideoWidget immediately — swap is deferred to
        # _on_lipsync_frame_changed when Qt renders the first valid frame.
        # Eliminates black flash at frozen-frame → live-video swap.
        self._pending_swap_to_video = False
        # v3.8 black-flash fix (the OTHER direction, 2026-05-06 ~01:30
        # Taipei): the symmetric problem at the live-video → frozen-frame
        # swap. Qt clears the QVideoWidget framebuffer at EndOfMedia BEFORE
        # the EndOfMedia signal fires my handler, so when my handler
        # finally swaps the stack to frozen-frame, there's been a
        # ~50-100ms black flash on QVideoWidget while we waited. The fix:
        # use positionChanged to detect "approaching end of media" and
        # pre-emptively swap to frozen-frame ~150ms before the MP4 ends,
        # while a valid last frame is still being rendered. The flag
        # _already_pre_swapped_for_current_mp4 prevents the swap from
        # firing repeatedly within the trailing-window of one MP4
        # (positionChanged fires many times per second). Reset to False
        # when a new MP4 is loaded.
        self._already_pre_swapped_for_current_mp4 = False
        # Connect positionChanged for the pre-emptive swap-to-frozen-frame.
        try:
            self.lipsync_player.positionChanged.connect(
                self._on_lipsync_position_changed
            )
        except Exception as e:
            sys.stderr.write(
                f"[v3.8 lipsync] positionChanged hook failed: {e}\n"
            )

    def _on_lipsync_media_status(self, status):
        """Handle QMediaPlayer status transitions for the lipsync video.

        v3.8 Checkpoint C: on EndOfMedia, swap the stack back to the static
        portrait QLabel. Tempfile cleanup is deferred to the next
        mp4_ready (which schedules the previous one for unlink) or to UI
        shutdown — keeping the file around briefly is safer than racing the
        player's read of it.

        v3.8 next-iter #1 (2026-05-05 evening Taipei): on EndOfMedia,
        choose visual based on pending lipsync state:
          - pending == 0: swap to portrait (turn complete, idle visual)
          - pending  > 0 with valid captured frame: swap to frozen-frame
            QLabel showing the last rendered frame; Qt holds nothing for
            us reliably, so we render the captured frame ourselves
          - pending  > 0 but frame capture failed / unavailable: fall back
            to portrait (deterministic, never shows black rectangle)

        The B-path (frozen frame via captured QVideoFrame) replaces the
        earlier "stay on QVideoWidget" approach which was unreliable
        because Qt6's QVideoWidget framebuffer behavior on EndOfMedia is
        graphics-backend-dependent (sometimes holds last frame, sometimes
        clears to black). With the captured-frame approach we control
        what's on screen during the gap explicitly.
        """
        try:
            # status is a QMediaPlayer.MediaStatus enum. EndOfMedia fires
            # when the loaded media has finished playing through.
            print(f"[v3.8 lipsync] media status: {status}", flush=True)
            # Compare via name to avoid binding-version differences in how
            # the enum exposes constants. EndOfMedia == 7 in Qt6 typically,
            # but the .name attribute is the stable check across versions.
            status_name = getattr(status, "name", str(status))
            if status_name == "EndOfMedia" or "EndOfMedia" in str(status):
                pending = getattr(self, "_lipsync_pending_count", 0)
                # v3.8 gap-class fix (2026-05-05 late evening Taipei):
                # the previous swap-back-suppression triggered only when
                # pending > 0, but during a turn there's a window where
                # first-immediate's MP4 has finished playing AND
                # batched-remainder's lipsync POST hasn't fired yet
                # (because batched-remainder TTS is still streaming audio
                # chunks). In that window pending IS 0, so EndOfMedia would
                # swap to portrait — that's the visible 10+ sec gap Barak
                # was seeing. The fix: also check whether the current TURN
                # is fully done. If TTS is still producing OR cognition isn't
                # complete OR batched-remainder is fired-but-not-yet-done,
                # MORE lipsync IS coming for this turn even though no
                # LipsyncWorker is currently dispatched. Stay on frozen frame.
                turn_fully_done = (
                    getattr(self, "_cognition_done", False)
                    and getattr(self, "_first_tts_done", False)
                    and (
                        getattr(self, "_batched_tts_done", False)
                        or not getattr(self, "_batched_tts_fired", False)
                    )
                )
                _pdiag("lipsync-end-of-media",
                       pending=pending,
                       turn_fully_done=turn_fully_done)
                if pending == 0 and turn_fully_done:
                    # Turn is fully wrapped, no more MP4s coming — return
                    # to portrait. This is the legitimate end-of-turn case.
                    self._swap_to_portrait()
                else:
                    # Either an MP4 is currently in flight (pending > 0) OR
                    # the turn is mid-flight and more lipsync is expected.
                    # In either case, stay on the frozen frame.
                    if self._swap_to_frozen_frame():
                        _pdiag("lipsync-stay-on-frozen-frame",
                               pending=pending,
                               turn_fully_done=turn_fully_done,
                               note="captured-last-frame-displayed")
                    else:
                        _pdiag("lipsync-fallback-to-portrait",
                               pending=pending,
                               turn_fully_done=turn_fully_done,
                               note="frame-capture-unavailable")
                        self._swap_to_portrait()
        except Exception as e:
            sys.stderr.write(f"[v3.8 lipsync] media status handler error: {e}\n")

    def _swap_to_video(self):
        """Switch portrait stack to QVideoWidget (animating state).

        v3.8 Checkpoint A: defined but not called. Checkpoint C calls this
        from the LipsyncWorker.mp4_ready signal after video.setSource() +
        play() are issued.
        """
        if hasattr(self, "portrait_stack"):
            self.portrait_stack.setCurrentIndex(1)

    def _swap_to_portrait(self):
        """Switch portrait stack back to QLabel portrait (idle state).

        v3.8 Checkpoint A: defined but not called. Checkpoint C calls this
        from _on_lipsync_media_status when EndOfMedia fires.
        """
        if hasattr(self, "portrait_stack"):
            self.portrait_stack.setCurrentIndex(0)

    def _swap_to_frozen_frame(self) -> bool:
        """Switch portrait stack to the frozen-frame QLabel (gap state).

        v3.8 next-iter #1 (B): converts the last captured QVideoFrame to a
        QPixmap, sets it on lipsync_frozen_label, swaps the stack to index 2.
        Called by _on_lipsync_media_status on EndOfMedia when more MP4s are
        still pending — keeps the visible face stable on the last animated
        frame instead of showing portrait or black rectangle.

        Returns True if the swap succeeded (a frame was available and
        converted cleanly), False if we should fall back to portrait
        (frame missing, conversion failed, or Qt binding edge case).
        """
        try:
            frame = getattr(self, "_last_video_frame", None)
            if frame is None or not frame.isValid():
                return False
            # QVideoFrame -> QImage -> QPixmap. toImage() handles the
            # pixel-format conversion internally. Result is a QImage;
            # QPixmap.fromImage() prepares for QLabel display.
            qimg = frame.toImage()
            if qimg.isNull():
                return False
            pix = QPixmap.fromImage(qimg)
            if pix.isNull():
                return False
            # Scale to display height (matches portrait sizing, lets QLabel
            # handle width via aspect ratio). SmoothTransformation for clean
            # appearance during the gap.
            scaled = pix.scaledToHeight(LIPSYNC_VIDEO_HEIGHT, Qt.SmoothTransformation)
            self.lipsync_frozen_label.setPixmap(scaled)
            if hasattr(self, "portrait_stack"):
                self.portrait_stack.setCurrentIndex(2)
            return True
        except Exception as e:
            sys.stderr.write(f"[v3.8 lipsync] frozen-frame swap error: {e}\n")
            return False

    def _on_lipsync_frame_changed(self, frame):
        """Slot for QVideoSink.videoFrameChanged.

        v3.8 next-iter #1 (B): stashes the latest video frame so we can
        display it during the gap between MP4s. Runs on every rendered
        frame (typically 25fps for Wav2Lip output), so the cost matters —
        we just hold a reference to the QVideoFrame, no copy or conversion
        until EndOfMedia actually needs it.

        v3.8 next-iter #1 (B revision, 2026-05-05 evening Taipei): only
        stash VALID frames. Qt6's QVideoSink fires a final videoFrameChanged
        with an invalid/empty frame at EndOfMedia as the "stream is over"
        signal — naively storing every frame means the last stash is the
        empty one, so _swap_to_frozen_frame finds an invalid frame and
        falls back to portrait. Filtering here keeps the LAST-GOOD frame
        as the stashed one, so frozen-frame display has something to render.

        v3.8 black-flash fix (2026-05-06 ~01:00 Taipei): also use this
        signal as the trigger to swap from frozen-frame to live-video when
        a new MP4 has been loaded but Qt hasn't yet rendered its first
        frame. Without this, _on_lipsync_mp4_ready calls setSource() +
        _swap_to_video() + play() in immediate sequence — the swap to
        QVideoWidget happens before Qt has decoded the first frame of the
        new MP4, producing a 100-300ms black flash at the seam between
        frozen-frame and live-video. By deferring the swap until the FIRST
        VALID FRAME from the new MP4 actually renders, we eliminate the
        black flash. The flag _pending_swap_to_video is set in
        _on_lipsync_mp4_ready (instead of immediately swapping), and this
        slot consumes the flag on the first valid frame.
        """
        try:
            if frame is None or not frame.isValid():
                return
            self._last_video_frame = frame
            # v3.8 black-flash fix: if a new MP4 was just loaded and is
            # waiting for its first frame to render before we swap into
            # view, this is that frame — swap now and clear the flag.
            if getattr(self, "_pending_swap_to_video", False):
                self._pending_swap_to_video = False
                self._swap_to_video()
        except Exception:
            # Qt binding edge case on isValid() — skip silently. Worst case
            # is we use a stale frame next time, which is still better than
            # crashing the slot.
            pass

    def _on_lipsync_position_changed(self, position_ms: int):
        """Slot for QMediaPlayer.positionChanged (live-video → frozen-frame
        side of the black-flash fix).

        Fires repeatedly during playback (~4-25 times per second depending
        on Qt6 backend). When position is within ~150ms of the MP4's
        duration AND we haven't already pre-swapped for the current MP4,
        swap to frozen-frame early — so when Qt clears the QVideoWidget
        framebuffer at actual end-of-media, the user is already looking
        at the frozen-frame label and the clear happens invisibly behind
        it.

        v3.8 black-flash fix (symmetric pair, 2026-05-06 ~01:30 Taipei).
        Idempotent: if pre-swap already done for this MP4, returns
        immediately. Reset to False on next MP4 load via
        _on_lipsync_mp4_ready.
        """
        try:
            if getattr(self, "_already_pre_swapped_for_current_mp4", False):
                return  # already pre-swapped for this MP4
            duration_ms = self.lipsync_player.duration()
            if duration_ms <= 0 or position_ms <= 0:
                return  # duration not yet known or before playback started
            # Trigger ~150ms before end. Generous window because:
            #  - positionChanged firing interval varies; might miss the
            #    last ~100ms if interval is sparse
            #  - want the swap visible for at least one frame (40ms at
            #    25fps) before Qt's framebuffer clear
            if position_ms < (duration_ms - 150):
                return
            # Try the swap. If frame capture isn't available, leave the
            # stack alone — EndOfMedia handler will fall back to portrait.
            if self._swap_to_frozen_frame():
                self._already_pre_swapped_for_current_mp4 = True
                _pdiag("lipsync-pre-swap-to-frozen-frame",
                       position_ms=position_ms,
                       duration_ms=duration_ms,
                       remaining_ms=duration_ms - position_ms,
                       note="pre-emptive-swap-before-endofmedia")
        except Exception as e:
            sys.stderr.write(
                f"[v3.8 lipsync] position_changed handler error: {e}\n"
            )

    # ---- Cmd/Ctrl+Return → Send ----

    def eventFilter(self, obj, event):
        if obj is self.input_box and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
                event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
            ):
                self._on_send_clicked()
                return True
        return super().eventFilter(obj, event)

    # ---- Push-to-talk ----

    def _on_talk_pressed(self):
        try:
            self.mic.start()
        except Exception as e:
            self._set_action(f"Mic start failed: {type(e).__name__}: {e}")
            return
        self.talk_button.setText("● Recording — release to send")
        self.talk_button.setStyleSheet(self._talk_recording_style)
        self._set_action("Recording…")

    def _on_talk_released(self):
        if not self.mic.active:
            return
        try:
            audio = self.mic.stop()
        except Exception as e:
            self._reset_talk_button()
            self._set_action(f"Mic stop failed: {type(e).__name__}: {e}")
            return
        self._reset_talk_button()
        if audio.size == 0:
            self._set_action("(empty recording)")
            return
        duration = len(audio) / float(MIC_SAMPLE_RATE)
        if duration < 0.3:
            self._set_action(f"(recording too short: {duration:.2f}s)")
            return
        self._set_action(f"Recorded {duration:.1f}s — transcribing…")
        audio_flat = audio.squeeze() if audio.ndim > 1 else audio
        worker = WhisperWorker(audio_flat, MIC_SAMPLE_RATE)
        worker.signals.finished.connect(self._on_stt_finished_auto_flow)
        worker.signals.error.connect(self._on_stt_error)
        self.thread_pool.start(worker)

    def _reset_talk_button(self):
        self.talk_button.setText("🎙  Hold to Talk")
        self.talk_button.setStyleSheet(self._talk_idle_style)

    def _on_stt_finished_auto_flow(self, transcript: str, elapsed: float):
        """STT finished — auto-route to cognition (the v3 difference from v2)."""
        if not transcript:
            self._set_action(f"Transcribed in {elapsed:.1f}s but got empty text.")
            return
        self._append_history("you", transcript, meta=f"transcribed {elapsed:.1f}s")
        self._set_action(f"Transcribed. Sofia is thinking…")
        self._send_to_cognition(transcript)

    def _on_stt_error(self, message: str):
        self._set_action(f"STT error: {message}")
        self._append_history("error", message)

    # ---- Send-to-Sofia (typed input path) ----

    def _on_send_clicked(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            self._set_action("(nothing to send)")
            return
        self.input_box.clear()
        self._append_history("you", text)

        if self.skip_cognition_check.isChecked():
            # Debug/override path: skip cognition, speak text directly
            self._set_action("Skip-cognition: speaking text directly via TTS…")
            self._send_to_tts(text)
        else:
            self._set_action("Sofia is thinking…")
            self._send_to_cognition(text)

    # ---- Cognition layer ----

    def _send_to_cognition(self, user_text: str):
        """v3.7 default cognition path: token-streamed via StreamingCognitionWorker.

        Fires first detected sentence to TTS immediately for fast TTFA;
        accumulates remaining sentences during streaming; fires the
        accumulated batch as ONE TTS POST when cognition completes.
        """
        self.context.add_user(user_text)
        # Reset playback state for the new turn
        self.playback.reset()
        self._stream_t0 = time.time()
        self._stream_first_chunk_at = None
        self._chunk_metrics = {}
        # v3.7 dispatch state — reset per turn. The flags below coordinate
        # the playback.stream_done() call across two TTS workers + cognition
        # completion to avoid race conditions (first TTS finishing before
        # cognition_complete fires, in which case we don't yet know whether
        # a batched POST is coming).
        self._first_tts_fired = False
        self._batched_tts_fired = False
        self._cognition_done = False
        self._first_tts_done = False
        self._batched_tts_done = False

        worker = StreamingCognitionWorker(
            self.client,
            list(self.context.messages),
            self.system_prompt,
        )
        worker.signals.first_token.connect(self._on_cognition_first_token)
        worker.signals.sentence_ready.connect(self._on_cognition_sentence_ready)
        worker.signals.cognition_complete.connect(self._on_streaming_cognition_complete)
        worker.signals.error.connect(self._on_cognition_error)
        self.thread_pool.start(worker)

    # ---- v3.7 streaming-cognition handlers ----

    def _on_cognition_first_token(self, elapsed: float):
        """Cognition stream produced its first token — TTFB for the LLM."""
        self._set_action(f"Cognition: first token in {elapsed:.2f}s — generating…")

    def _on_cognition_sentence_ready(self, sentence: str, is_first: bool):
        """A complete sentence was detected from the cognition stream.

        is_first=True → fire TTS immediately for fast TTFA (the v3.7 win).
        is_first=False → accumulator addition, the StreamingCognitionWorker
                         is buffering it internally; we don't POST per-sentence.
        """
        if is_first:
            elapsed = time.time() - (self._stream_t0 or time.time())
            self._set_action(
                f"First sentence at {elapsed:.2f}s ({len(sentence)} chars) — "
                f"POSTing to TTS…"
            )
            self._fire_tts_stream_worker(sentence, is_batched_remainder=False)
            self._first_tts_fired = True
        # Non-first sentences are accumulated by the worker; no action needed here.

    def _on_streaming_cognition_complete(self, full_response: str,
                                          batched_remainder: str,
                                          elapsed: float):
        """Cognition stream finished. Inscribe the full response, then POST
        the batched remainder if any. Marks _cognition_done so the playback
        end-of-stream signal can fire once all TTS workers complete.
        """
        self.context.add_assistant(full_response)
        self._append_history(
            "sofia", full_response, meta=f"streamed cognition {elapsed:.2f}s"
        )
        self._cognition_done = True

        if batched_remainder.strip():
            self._set_action(
                f"Cognition complete in {elapsed:.2f}s. POSTing batched "
                f"remainder ({len(batched_remainder)} chars)…"
            )
            self._batched_tts_fired = True
            self._fire_tts_stream_worker(batched_remainder, is_batched_remainder=True)
        else:
            # Single-sentence response: first-immediate POST is the only one.
            self._set_action(
                f"Cognition complete in {elapsed:.2f}s. (single-sentence response — "
                f"no batched POST needed)"
            )
            self._batched_tts_fired = False
            # Maybe the first TTS already finished while cognition was still
            # streaming; if so, signal playback done now.
            self._maybe_signal_playback_done()

    def _fire_tts_stream_worker(self, text: str, is_batched_remainder: bool):
        """Fire a TTSStreamWorker for the given text. Wires its signals to
        the appropriate handlers depending on whether this is the
        first-immediate POST (more audio coming after) or the batched
        remainder POST (last audio of the turn).

        v3.7 step 5 iteration 2: batched-remainder POST gets a 500ms
        pre-buffer to give the OutputStream a head-start against per-segment
        RTF fluctuations around 1.0×. First-immediate POST stays at 0
        pre-buffer to preserve fast TTFA.
        """
        # v3.8 Fix A (2026-05-05 afternoon Taipei): batched-remainder pre_buffer
        # raised from 0.5s → 2.0s after pause-diag run revealed mid-batched-remainder
        # pauses of 0.5-1.4s caused by XTTS-v2 RTF spikes draining the playback queue.
        # 2.0s cushion = ~4 chunks of buffer; fills during first-immediate's playback
        # so no added latency to start of batched-remainder. See active_knowledge
        # entry "Audio-Pause Diagnostic — Fix A" for the full diagnostic.
        pre_buffer = 2.0 if is_batched_remainder else 0.0
        diag_tag = "batched-remainder" if is_batched_remainder else "first-immediate"
        worker = TTSStreamWorker(text, pre_buffer_seconds=pre_buffer, tag=diag_tag)
        worker.signals.chunk_received.connect(self._on_stream_chunk)
        if is_batched_remainder:
            worker.signals.finished.connect(self._on_stream_finished)
        else:
            worker.signals.finished.connect(self._on_first_immediate_stream_finished)
        worker.signals.error.connect(self._on_tts_error)
        # v3.8: dispatch a LipsyncWorker per segment when its WAV completes.
        # Fire-and-forget — no fatal-path coupling. If lipsync server is down
        # or returns an error, the audio path still works and the UI stays
        # on the static portrait.
        worker.signals.wav_complete.connect(self._on_tts_wav_complete)
        _pdiag("tts-worker-dispatched", tag=diag_tag, text_chars=len(text))
        self.thread_pool.start(worker)

    # ---- v3.8: lipsync dispatch + MP4 handlers ----

    def _on_tts_wav_complete(self, wav_bytes: bytes, samplerate: int, tag: str):
        """A TTS segment's full WAV is ready. Dispatch a LipsyncWorker to
        POST it to the lipsync server. Lipsync server's generation_lock
        serializes concurrent POSTs — first-immediate's MP4 finishes rendering
        before batched-remainder's begins, matching Option D semantics.

        v3.8 next-iter #1: increment _lipsync_pending_count on dispatch so
        EndOfMedia handler knows whether to swap back to portrait or stay
        on the last video frame waiting for the next MP4.

        v3.8 PySide6-lifetime fix (2026-05-06 ~00:00 Taipei): hold a strong
        Python-side reference to the worker in self._lipsync_workers_in_flight
        until either mp4_ready or failed fires, then remove. Without this,
        the local `worker` variable goes out of scope when this method
        returns; QThreadPool keeps the C++ QRunnable alive, but Python's GC
        can collect the wrapper (and its signals QObject) before run() emits.
        Long-running Wav2Lip generations (30+s for large batched-remainder
        segments) are most vulnerable because more time for GC to fire.
        Cleanup runs after either signal via _purge_finished_lipsync_worker.

        2026-05-07 evening Taipei toggle: if LIPSYNC_ENABLED is False, skip
        dispatch entirely. Audio path still works (TTS plays via the existing
        AudioPlaybackQueue); UI stays on the static portrait. No /animate
        POSTs, no MP4 generation, no GPU contention with TTS. Smooth voice
        with static portrait > choppy audio with delayed lipsync.
        """
        # 2026-05-07: lipsync toggle. Skip dispatch when disabled.
        if not LIPSYNC_ENABLED:
            _pdiag("lipsync-skipped-toggle-off", tag=tag, wav_bytes=len(wav_bytes))
            return

        try:
            worker = LipsyncWorker(wav_bytes, tag=tag)
            worker.signals.mp4_ready.connect(self._on_lipsync_mp4_ready)
            worker.signals.failed.connect(self._on_lipsync_failed)

            # v3.8 lifetime fix: bind cleanup to both signals so the
            # in-flight reference is released regardless of success or
            # failure. The default-arg trick (_w=worker) captures the
            # specific worker reference at connection time so each cleanup
            # closure removes its own worker, not whatever `worker` happens
            # to be when the closure runs.
            def _cleanup(*_args, _w=worker):
                try:
                    self._lipsync_workers_in_flight.remove(_w)
                except ValueError:
                    pass  # already removed (other signal fired first)
            worker.signals.mp4_ready.connect(_cleanup)
            worker.signals.failed.connect(_cleanup)

            self._lipsync_workers_in_flight.append(worker)
            self._lipsync_pending_count += 1
            _pdiag("lipsync-worker-dispatched", tag=tag,
                   wav_bytes=len(wav_bytes), samplerate=samplerate,
                   pending=self._lipsync_pending_count,
                   in_flight=len(self._lipsync_workers_in_flight))
            self.thread_pool.start(worker)
        except Exception as e:
            sys.stderr.write(
                f"[v3.8 lipsync] dispatch failed (tag={tag}): {e}\n"
            )

    def _on_lipsync_mp4_ready(self, mp4_bytes: bytes, tag: str):
        """An MP4 has arrived from the lipsync server. Write to a unique
        tempfile, set as the player's source, defer the swap-to-video until
        the first valid frame renders, and start playback.

        v3.8 Checkpoint C: post-hoc visual presence per Option D — display
        each MP4 as it returns.

        v3.8 next-iter #1: decrement _lipsync_pending_count on success so
        EndOfMedia handler knows whether more MP4s are still coming.

        v3.8 black-flash fix (2026-05-06 ~01:00 Taipei): set
        _pending_swap_to_video = True instead of calling _swap_to_video()
        directly. The swap then happens in _on_lipsync_frame_changed when
        the first valid frame of the new MP4 actually renders. This
        eliminates the 100-300ms black flash that was visible at the seam
        because we used to swap to QVideoWidget BEFORE Qt had decoded the
        first frame.
        """
        import tempfile
        # Decrement first so even if the body throws, the counter stays
        # balanced with the dispatch increment.
        self._lipsync_pending_count = max(0, self._lipsync_pending_count - 1)
        try:
            # Write MP4 to a unique tempfile (delete=False; we manage cleanup
            # ourselves via the previous-tempfile attribute).
            tf = tempfile.NamedTemporaryFile(
                delete=False, suffix=".mp4", prefix=f"sofia_lipsync_{tag}_"
            )
            tf.write(mp4_bytes)
            tf.close()
            new_path = tf.name
            _pdiag("lipsync-mp4-tempfile", tag=tag,
                   path=new_path, bytes=len(mp4_bytes),
                   pending=self._lipsync_pending_count)

            # Schedule previous tempfile for cleanup (best-effort).
            prev_path = getattr(self, "_lipsync_temp_path", None)
            if prev_path and prev_path != new_path:
                try:
                    os.unlink(prev_path)
                except OSError:
                    pass  # may have been cleaned already; not a failure
            self._lipsync_temp_path = new_path

            # Set source + start playback + arm the deferred-swap flag.
            # The actual stack swap to QVideoWidget happens in
            # _on_lipsync_frame_changed when the first valid frame of the
            # new MP4 renders — this avoids the black flash that was
            # produced by swapping to QVideoWidget before Qt had decoded
            # any frames. Note: order matters — set the flag BEFORE
            # setSource() so even an unusually-fast first-frame-emission
            # is caught by the slot.
            self._pending_swap_to_video = True
            # Reset the pre-swap-to-frozen-frame guard. The new MP4 will
            # have its own duration; the position-based pre-emptive swap
            # logic in _on_lipsync_position_changed should fire fresh
            # near THIS MP4's end, not be locked-out by the previous one.
            self._already_pre_swapped_for_current_mp4 = False
            self.lipsync_player.setSource(QUrl.fromLocalFile(new_path))
            self.lipsync_player.play()
        except Exception as e:
            # On failure, clear the deferred-swap flag so a stale flag
            # doesn't trigger an unwanted swap on the next unrelated
            # frame. The stack stays where it was (frozen-frame or
            # portrait), which is the safest fallback.
            self._pending_swap_to_video = False
            sys.stderr.write(
                f"[v3.8 lipsync] mp4_ready handler failed (tag={tag}): {e}\n"
            )

    def _on_lipsync_failed(self, error_message: str, tag: str):
        """Lipsync POST failed. Log; stay on portrait; no UI change.

        v3.8 next-iter #1: decrement _lipsync_pending_count so the counter
        stays balanced even on failure. Without this, a single failed POST
        would leave the count permanently > 0 and the EndOfMedia handler
        would never swap back to portrait.
        """
        self._lipsync_pending_count = max(0, self._lipsync_pending_count - 1)
        sys.stderr.write(
            f"[v3.8 lipsync] failed (tag={tag}, pending={self._lipsync_pending_count}): "
            f"{error_message}\n"
        )

    def _on_first_immediate_stream_finished(self, total_chunks: int,
                                             total_elapsed: float):
        """First-immediate TTS worker finished. Mark and check whether all
        end-of-stream conditions are met (cognition done + first done + batched
        done if it was fired)."""
        self._first_tts_done = True
        self._maybe_signal_playback_done()

    def _maybe_signal_playback_done(self):
        """Centralized end-of-stream coordinator. Calls playback.stream_done()
        only when ALL of:
          - cognition stream completed,
          - first-immediate TTS finished streaming all its chunks,
          - batched TTS finished (if it was fired) OR no batched was needed.

        This prevents the race where first TTS finishes before cognition
        completes (so we don't yet know whether a batched POST is coming) —
        we'd otherwise risk calling stream_done() prematurely and losing the
        batched audio chunks."""
        if not self._cognition_done:
            return
        if not self._first_tts_done:
            return
        if self._batched_tts_fired and not self._batched_tts_done:
            return
        self.playback.stream_done()

    def _on_cognition_finished(self, response: str, elapsed: float):
        """v3.6 legacy single-shot cognition handler. Preserved for the
        skip-cognition / fallback debug path. The default v3.7 path uses
        _on_streaming_cognition_complete instead."""
        self.context.add_assistant(response)
        self._append_history("sofia", response, meta=f"cognition {elapsed:.1f}s")
        self._set_action(f"Sofia responded in {elapsed:.1f}s. Streaming speech…")
        self._send_to_tts_streaming(response)

    def _on_cognition_error(self, message: str):
        self._set_action(f"Cognition error: {message}")
        self._append_history("error", message)

    # ---- Streaming TTS (v3.1 cognition path) ----

    def _send_to_tts_streaming(self, text: str):
        """v3.3 cognition path: stream syllable-target chunks through /tts.
        First chunk plays as soon as its audio is rendered (~3-6s);
        subsequent chunks queue and play sequentially. Per-chunk metrics
        are written to cadence_metrics.jsonl as playback progresses."""
        self.playback.reset()
        self._stream_t0 = time.time()
        self._stream_first_chunk_at = None
        self._chunk_metrics = {}  # v3.3: fresh per-response tracker
        worker = TTSStreamWorker(text)
        worker.signals.chunk_received.connect(self._on_stream_chunk)
        worker.signals.finished.connect(self._on_stream_finished)
        worker.signals.error.connect(self._on_tts_error)
        self.thread_pool.start(worker)

    def _on_stream_chunk(self, index: int, total: int, chunk_text: str,
                         audio_bytes: bytes,
                         sentence_count: int, syllable_count: int,
                         synthesis_start_ts: float, synthesis_end_ts: float):
        # v3.3: store synthesis-side metrics; playback-side fields fill in
        # via _on_chunk_play_start / _on_chunk_play_end.
        self._chunk_metrics[index] = {
            "session_id": self.context.session_id,
            "chunk_index": index,
            "total_chunks": total,
            "sentence_count": sentence_count,
            "syllable_count": syllable_count,
            "char_count": len(chunk_text),
            "first_30_chars": chunk_text[:30],
            "synthesis_start": synthesis_start_ts,
            "synthesis_end": synthesis_end_ts,
            "synthesis_seconds": synthesis_end_ts - synthesis_start_ts,
        }
        # Note time-to-first-words on the first chunk — the conversational
        # comfort metric we're optimizing.
        if self._stream_first_chunk_at is None and self._stream_t0 is not None:
            ttfw = time.time() - self._stream_t0
            self._stream_first_chunk_at = time.time()
            self._set_action(
                f"First chunk in {ttfw:.1f}s ({syllable_count} syl, "
                f"{sentence_count} sent) — playing 1/{total}…"
            )
        else:
            self._set_action(
                f"Playing {index + 1}/{total} ({syllable_count} syl, "
                f"{sentence_count} sent)…"
            )
        # v3.3: enqueue with chunk_index so playback signals can correlate.
        self.playback.enqueue(audio_bytes, chunk_index=index)

    def _on_chunk_play_start(self, chunk_index: int, start_ts: float,
                             audio_duration: float):
        """v3.3: chunk's audio just started playing. Record playback_start
        and audio_duration into the chunk's metric record."""
        if chunk_index not in self._chunk_metrics:
            return
        m = self._chunk_metrics[chunk_index]
        m["playback_start"] = start_ts
        m["audio_duration"] = audio_duration

    def _on_chunk_play_end(self, chunk_index: int, end_ts: float):
        """v3.3: chunk's audio finished playing. Finalize metric record
        and append to cadence_metrics.jsonl. Derived field synth_minus_audio
        is negative when synthesis_end happened before this chunk's audio
        finished (i.e., next chunk had time to be ready — no gap)."""
        if chunk_index not in self._chunk_metrics:
            return
        m = self._chunk_metrics[chunk_index]
        m["playback_end"] = end_ts
        if "synthesis_end" in m:
            m["synth_minus_audio"] = m["synthesis_end"] - end_ts
        try:
            self.cadence_logger.write(m)
        except Exception as e:
            sys.stderr.write(f"[v3.3 cadence] log write failed: {e}\n")

    def _on_stream_finished(self, total_chunks: int, total_elapsed: float):
        """v3.7: handler for the BATCHED-remainder TTS worker's finished signal
        (in the v3.7 default path) AND the legacy single-shot TTS worker's
        finished signal (in the skip-cognition / fallback paths).

        For the v3.7 default path: marks _batched_tts_done and routes to the
        end-of-stream coordinator, which calls playback.stream_done() once
        all conditions are met (cognition done + first done + batched done).

        For the legacy path: there's no first/batched coordination — just
        directly call playback.stream_done() since this is the only TTS
        worker for the turn. We detect "legacy path" by the v3.7 dispatch
        flag _batched_tts_fired being False (no batched POST was fired
        means we're either in legacy path OR a single-sentence response
        where the first-immediate handler is responsible for stream_done()).
        """
        # v3.7 path: this fired because the batched POST finished
        if self._batched_tts_fired:
            self._batched_tts_done = True
            self._maybe_signal_playback_done()
        else:
            # Legacy path: direct stream_done()
            self.playback.stream_done()

    def _on_playback_done(self, chunks_played: int):
        if self._stream_t0 is not None:
            total = time.time() - self._stream_t0
            self._set_action(f"Done. {chunks_played} sentence(s) in {total:.1f}s total.")
        else:
            self._set_action("Done.")
        self._stream_t0 = None
        self._stream_first_chunk_at = None

    # ---- Single-shot TTS (skip-cognition debug path) ----

    def _send_to_tts(self, text: str):
        """Legacy single-shot path used only when the skip-cognition
        checkbox is checked. Cognition responses use streaming via
        _send_to_tts_streaming."""
        worker = TTSWorker(text)
        worker.signals.finished.connect(self._on_tts_finished)
        worker.signals.error.connect(self._on_tts_error)
        self.thread_pool.start(worker)

    def _on_tts_finished(self, audio_bytes: bytes, original_text: str, elapsed: float):
        self._set_action(f"TTS in {elapsed:.1f}s. Playing…")
        try:
            buf = io.BytesIO(audio_bytes)
            data, samplerate = sf.read(buf, dtype="float32")
            sd.play(data, samplerate)
            duration = len(data) / float(samplerate)
            QTimer.singleShot(int(duration * 1000) + 200, lambda: self._set_action("Done."))
        except Exception as e:
            self._on_tts_error(f"Audio playback failed: {type(e).__name__}: {e}", original_text)

    def _on_tts_error(self, message: str, original_text: str = ""):
        self._set_action(f"TTS error: {message}")
        self._append_history("error", message)

    def _on_stop_clicked(self):
        # Stop both single-shot and streaming playback paths
        sd.stop()
        self.playback.stop()
        if self.mic.active:
            try:
                self.mic.stop()
            except Exception:
                pass
            self._reset_talk_button()
        self._set_action("Stopped.")

    # ---- Health polling ----

    def _poll_health(self):
        tts = TTSHealthWorker()
        tts.signals.result.connect(self._on_tts_health)
        self.thread_pool.start(tts)
        stt = WhisperHealthWorker()
        stt.signals.result.connect(self._on_stt_health)
        self.thread_pool.start(stt)

    def _on_tts_health(self, label: str, color_hex: str):
        self.tts_status_label.setText(label)
        self.tts_status_label.setStyleSheet(f"color: {color_hex}; font-size: 11px;")

    def _on_stt_health(self, label: str, color_hex: str):
        self.stt_status_label.setText(label)
        self.stt_status_label.setStyleSheet(f"color: {color_hex}; font-size: 11px;")

    # ---- History rendering ----

    def _append_history(self, role: str, text: str, meta: str = ""):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if role == "sofia":
            color, prefix = "#2e75b6", "Sofia"
        elif role == "you":
            color, prefix = "#3aa856", "You"
        elif role == "error":
            color, prefix = "#c84343", "Error"
        else:
            color, prefix = "#888", "System"
        meta_html = (
            f' <span style="color: #aaa; font-size: 11px;">· {meta}</span>'
            if meta else ""
        )
        html = (
            f'<div style="margin: 4px 0; line-height: 1.4;">'
            f'<span style="color: {color}; font-weight: 600;">{prefix}</span> '
            f'<span style="color: #aaa; font-size: 11px;">{timestamp}{meta_html}</span><br>'
            f'<span style="color: #222;">{self._html_escape(text)}</span>'
            f'</div>'
        )
        self.history_view.append(html)
        sb = self.history_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _html_escape(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    def _set_action(self, message: str):
        self.action_label.setText(message)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Voice Bridge — Sofia v3.6")
    win = VoiceBridgeWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
