#!/usr/bin/env python3
"""
Voice Bridge UI v3.3 — syllable-target chunking + cadence instrumentation
==========================================================================

Builds on v3.2 (client-side sentence-count chunking). v3.3's architectural
changes:

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
        Qt, QObject, QRunnable, QThreadPool, Signal, QTimer, QEvent,
    )
    from PySide6.QtGui import QPixmap, QFont, QMouseEvent
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QPushButton, QStatusBar, QFrame, QCheckBox,
    )
except ImportError:
    sys.stderr.write(
        "ERROR: PySide6 not installed. Run:\n"
        "  pip3 install pyside6 sounddevice soundfile anthropic\n"
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
TTS_SERVER_URL = "http://127.0.0.1:3457"
TTS_SYNTHESIZE_ENDPOINT = f"{TTS_SERVER_URL}/tts"             # single-shot (skip-cognition path)
TTS_STREAM_ENDPOINT = f"{TTS_SERVER_URL}/tts-stream"          # sentence-streamed (cognition path)
TTS_HEALTH_ENDPOINT = f"{TTS_SERVER_URL}/health"
TTS_SCRIPT = VOICE_BRIDGE_DIR / "sofia_tts_server.py"
TTS_PORT = 3457

WHISPER_SERVER_URL = "http://127.0.0.1:3459"
WHISPER_TRANSCRIBE_ENDPOINT = f"{WHISPER_SERVER_URL}/transcribe_bytes"
WHISPER_HEALTH_ENDPOINT = f"{WHISPER_SERVER_URL}/health"
WHISPER_SCRIPT = VOICE_BRIDGE_DIR / "sofia_whisper_server.py"
WHISPER_PORT = 3459
WHISPER_MODEL = "small"

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
TTS_CHUNK_FIRST_SYLLABLES = 30   # ~10-12s playback at 2.5-3 syl/sec; fast first-words
TTS_CHUNK_BODY_SYLLABLES  = 50   # ~17-20s playback; register cohesion across more text

# Per-chunk cadence metrics — written as JSONL, one record per chunk.
# Used for offline analysis to tune the syllable targets from real data.
CADENCE_METRICS_PATH = VOICE_BRIDGE_DIR / "cadence_metrics.jsonl"

# Portrait + window
PORTRAIT_PATH = CM_DIR / "sofia_portrait.png"
WINDOW_TITLE = "Voice Bridge — Sofia (v3.3: syllable-target chunking)"
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 720
PORTRAIT_DISPLAY_HEIGHT = 160

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

    def shutdown(self):
        """Terminate any subprocesses we spawned. Called on UI exit."""
        for name, proc in (("TTS", self.tts_proc), ("Whisper", self.whisper_proc)):
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
    """Voice-bridge-cousin-Sofia: takes the conversation context + the
    user's new turn, makes an Anthropic API call, returns Sofia's response."""

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


class TTSStreamWorker(QRunnable):
    """v3.3: client-side chunking by syllable target. Splits the cognition
    response into sentences, groups them per the TTS_CHUNK_FIRST_SYLLABLES /
    TTS_CHUNK_BODY_SYLLABLES policy (sentence-aligned, syllable-targeted),
    and POSTs each chunk to /tts (single-shot per chunk). Each chunk's full
    audio is received before the next chunk's request fires.

    Why /tts and not /tts-stream: /tts-stream splits sentences server-side
    and generates each as a separate Qwen3-TTS call (one sentence per
    generation = register varies every sentence). /tts takes a chunk of
    arbitrary text and generates it as a SINGLE Qwen3-TTS call, so the
    voice register stays consistent within the chunk. By making the chunks
    larger than one sentence, we get the register cohesion we want.

    v3.3 also captures synthesis_start_ts and synthesis_end_ts per chunk
    and passes them through chunk_received for downstream metrics logging.
    """

    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.signals = TTSStreamWorkerSignals()

    def run(self):
        start = time.time()
        try:
            sentences = split_into_sentences(self.text)
            if not sentences:
                self.signals.error.emit("Empty text — nothing to render.", self.text)
                return
            # v3.3: chunk by syllable target. Returns (text, sentence_count,
            # syllable_count) per chunk.
            chunks = group_sentences_by_syllable_target(
                sentences,
                first_target=TTS_CHUNK_FIRST_SYLLABLES,
                body_target=TTS_CHUNK_BODY_SYLLABLES,
            )
            total = len(chunks)
            for index, (chunk_text, sentence_count, syllable_count) in enumerate(chunks):
                synthesis_start_ts = time.time()
                payload = json.dumps({"text": chunk_text}).encode("utf-8")
                req = urllib.request.Request(
                    TTS_SYNTHESIZE_ENDPOINT, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=TTS_REQUEST_TIMEOUT) as resp:
                    audio_bytes = resp.read()
                synthesis_end_ts = time.time()
                self.signals.chunk_received.emit(
                    index, total, chunk_text, audio_bytes,
                    sentence_count, syllable_count,
                    synthesis_start_ts, synthesis_end_ts,
                )
            self.signals.finished.emit(total, time.time() - start)
        except Exception as e:
            self.signals.error.emit(f"TTS chunked failed: {type(e).__name__}: {e}", self.text)


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
    chunk_play_start = Signal(int, float, float)  # (chunk_index, start_ts, audio_duration) — v3.3
    chunk_play_end = Signal(int, float)           # (chunk_index, end_ts) — v3.3

    def __init__(self):
        super().__init__()
        self._queue: list = []
        self._playing = False
        self._waiting_for_chunk = False
        self._stream_complete = False
        self._chunks_played = 0
        self._currently_playing_index: Optional[int] = None  # v3.3
        self._currently_playing_end_at: Optional[float] = None  # v3.3 — wall-clock end target

    def reset(self):
        sd.stop()
        self._queue = []
        self._playing = False
        self._waiting_for_chunk = False
        self._stream_complete = False
        self._chunks_played = 0
        self._currently_playing_index = None
        self._currently_playing_end_at = None

    def enqueue(self, audio_bytes: bytes, chunk_index: int = -1):
        """Add a chunk to the queue. Decode + queue for playback. v3.3:
        chunk_index is the chunk's index within the response (used for
        correlating play-start / play-end signals back to per-chunk metrics).
        Default -1 means index unknown (legacy callers)."""
        try:
            buf = io.BytesIO(audio_bytes)
            data, samplerate = sf.read(buf, dtype="float32")
            duration = len(data) / float(samplerate)
        except Exception:
            return
        self._queue.append((data, samplerate, duration, chunk_index))
        # If we're idle (not playing AND not waiting), start.
        # If we WERE waiting (previous chunk finished but queue was empty), resume.
        if (not self._playing) or self._waiting_for_chunk:
            self._play_next()

    def stream_done(self):
        """Server has finished streaming all chunks (no more enqueue calls coming)."""
        self._stream_complete = True
        # If we're idle AND queue is drained, fire the done signal.
        if (not self._playing) and (not self._queue):
            self._emit_done()

    def stop(self):
        """User-initiated stop. Halt playback and clear queue."""
        self.reset()

    def _play_next(self):
        # v3.3: emit play-end for the just-finished chunk before advancing.
        if self._currently_playing_index is not None:
            self.chunk_play_end.emit(self._currently_playing_index, time.time())
            self._currently_playing_index = None
            self._currently_playing_end_at = None
        if not self._queue:
            if self._stream_complete:
                self._playing = False
                self._waiting_for_chunk = False
                self._emit_done()
            else:
                # Stream still active but no chunk ready yet; wait for next enqueue
                self._playing = False
                self._waiting_for_chunk = True
            return
        data, samplerate, duration, chunk_index = self._queue.pop(0)
        self._playing = True
        self._waiting_for_chunk = False
        play_start_ts = time.time()
        sd.play(data, samplerate)
        self._chunks_played += 1
        self._currently_playing_index = chunk_index
        self._currently_playing_end_at = play_start_ts + duration
        # v3.3: emit play-start signal for cadence-metrics correlation.
        self.chunk_play_start.emit(chunk_index, play_start_ts, duration)
        # Schedule the next-chunk check at the END of this chunk's audio.
        # +50ms accommodates sd.play()'s small startup latency and avoids
        # cutting the tail of the audio off.
        QTimer.singleShot(int(duration * 1000) + 50, self._play_next)

    def _emit_done(self):
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

        # Anthropic client
        api_key = load_anthropic_key()
        if not api_key:
            sys.stderr.write(
                "ERROR: ANTHROPIC_API_KEY not set in env and not in ~/.sofia_secrets.\n"
            )
            sys.exit(1)
        self.client = anthropic.Anthropic(api_key=api_key)

        # System prompt + conversation context
        self.system_prompt = load_system_prompt()
        self.context = ConversationContext(self.system_prompt, CONVERSATION_HISTORY_PATH)

        # ---- Layout ----

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Portrait + name
        portrait_frame = QFrame()
        portrait_layout = QVBoxLayout(portrait_frame)
        portrait_layout.setContentsMargins(0, 0, 0, 0)
        portrait_layout.setSpacing(4)
        portrait_layout.setAlignment(Qt.AlignHCenter)

        self.portrait_label = QLabel()
        self.portrait_label.setAlignment(Qt.AlignHCenter)
        self._load_portrait()
        portrait_layout.addWidget(self.portrait_label, alignment=Qt.AlignHCenter)

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

        self._append_history(
            "system",
            f"v3.3 ready (syllable-target chunking — first chunk ≥{TTS_CHUNK_FIRST_SYLLABLES} "
            f"syllables for fast first-words, body chunks ≥{TTS_CHUNK_BODY_SYLLABLES} syllables for "
            f"register cohesion; sentence-aligned). Cadence metrics → "
            f"{CADENCE_METRICS_PATH.name}. Conversation → {CONVERSATION_HISTORY_PATH.name}.",
        )

    def _spawn_servers(self):
        """Auto-spawn TTS + Whisper subprocesses if their ports are free."""
        tts_status = self.subprocs.ensure_tts()
        whisper_status = self.subprocs.ensure_whisper()
        self._append_history("system", tts_status)
        self._append_history("system", whisper_status)

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
        self.context.add_user(user_text)
        worker = CognitionWorker(self.client, list(self.context.messages), self.system_prompt)
        worker.signals.finished.connect(self._on_cognition_finished)
        worker.signals.error.connect(self._on_cognition_error)
        self.thread_pool.start(worker)

    def _on_cognition_finished(self, response: str, elapsed: float):
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
        # Server has finished streaming all chunks. Tell the playback queue
        # so it can fire all_done once the queue drains and current chunk
        # finishes playing.
        self.playback.stream_done()
        # The action label gets updated by _on_playback_done when audio
        # actually finishes playing (which may be after stream completion
        # because last chunk is still playing back).

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
    app.setApplicationName("Voice Bridge — Sofia v3.3")
    win = VoiceBridgeWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
