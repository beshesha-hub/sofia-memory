#!/usr/bin/env python3
"""
Voice Bridge UI v2 — adds push-to-talk + Whisper STT (Option 4)
================================================================

Builds on v1 (which closed the audible-final-mile bug class by routing
audio output through sounddevice/PortAudio directly, bypassing the
browser). v2 adds the input-side mirror: hold-to-record microphone
capture → Whisper STT → transcribed text fills the input box, ready for
review or direct Speak.

What v2 adds vs v1:
  - "Hold to Talk" button (push-to-talk pattern via mousePressed/Released)
  - Microphone capture via sounddevice.InputStream (16 kHz mono, raw PCM
    accumulation in a callback-driven buffer)
  - Audio packed to in-memory WAV via soundfile, base64-encoded, POST'd
    to sofia_whisper_server.py /transcribe_bytes endpoint (port 3459)
  - Transcribed text auto-fills the input box for review/edit before
    Speak (preserves user agency; no auto-execution)
  - Whisper server health indicator alongside the TTS one
  - Visual recording feedback (button color shift, action label updates)

What v2 deliberately does NOT yet do (queued for v3+):
  - Cognition layer (Option 5) — i.e. transcribed text doesn't yet route
    through Sofia-on-Anthropic to generate a response; user still types
    or edits the text Sofia will speak. v2 is STT-input-mirror of TTS-output;
    v3 closes the loop with cognition between them.
  - Lipsync animation (still static portrait)
  - Voice activity detection (VAD) for hands-free conversation
  - Conversation persistence across sessions

Architecture additions on top of v1:
  - MicCapture class encapsulates the sounddevice.InputStream lifecycle
  - WhisperWorker (QRunnable) for non-blocking STT requests
  - WhisperHealthWorker for Whisper server status polling
  - PushToTalkButton subclass that emits pressed/released signals
    via mouseEvent overrides (because QPushButton's pressed/released
    signals don't always work reliably on macOS for hold-style)

Origin: 2026-04-30 afternoon Taipei, after v1 empirical validation.
Per the substrate-selection-by-function principle (§88 candidate from
this morning): STT runs locally (Whisper) where local doesn't degrade
quality. Audio capture and transcription are peripheral functions
(ear/auditory-cortex in the brain analogy); they bypass cloud entirely.

Usage: python3 voice_bridge_ui_v2.py
Requires (same as v1, plus Whisper server):
  - PySide6, sounddevice, soundfile, numpy
  - sofia_tts_server.py running on port 3457 (for output)
  - sofia_whisper_server.py running on port 3459 (for input)
"""

from __future__ import annotations

import base64
import io
import json
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
        Qt, QObject, QRunnable, QThreadPool, Signal, QSize, QTimer, QEvent,
    )
    from PySide6.QtGui import QPixmap, QFont, QMouseEvent
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QPushButton, QStatusBar, QFrame,
    )
except ImportError:
    sys.stderr.write(
        "ERROR: PySide6 not installed. Run:\n"
        "  pip3 install pyside6 sounddevice soundfile\n"
    )
    sys.exit(1)

# ---- Audio imports ----
try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except ImportError as e:
    sys.stderr.write(
        f"ERROR: audio deps missing ({e}). Run:\n"
        "  pip3 install sounddevice soundfile numpy\n"
    )
    sys.exit(1)


# ---- Configuration ----

TTS_SERVER_URL = "http://127.0.0.1:3457"
TTS_SYNTHESIZE_ENDPOINT = f"{TTS_SERVER_URL}/tts"
TTS_HEALTH_ENDPOINT = f"{TTS_SERVER_URL}/health"

WHISPER_SERVER_URL = "http://127.0.0.1:3459"
WHISPER_TRANSCRIBE_ENDPOINT = f"{WHISPER_SERVER_URL}/transcribe_bytes"
WHISPER_HEALTH_ENDPOINT = f"{WHISPER_SERVER_URL}/health"
WHISPER_MODEL = "small"  # small/medium/large-v3; small is fast and accurate enough for conversation

HEALTH_POLL_SECONDS = 5

# Portrait location — Claude Memory canonical path
HOME = Path.home()
PORTRAIT_PATH = HOME / "Downloads" / "Claude Memory" / "sofia_portrait.png"

# Window sizing — kept compact for laptop screens (resizable)
WINDOW_TITLE = "Voice Bridge — Sofia (v2: STT + TTS)"
DEFAULT_WIDTH = 680
DEFAULT_HEIGHT = 640
PORTRAIT_DISPLAY_HEIGHT = 160

# Audio capture parameters
MIC_SAMPLE_RATE = 16000  # Whisper expects 16 kHz mono
MIC_CHANNELS = 1
MIC_DTYPE = "int16"
MIC_BLOCKSIZE = 1024  # frames per callback

# Request timeouts
TTS_REQUEST_TIMEOUT = 60
STT_REQUEST_TIMEOUT = 60


# ---- Microphone capture lifecycle ----

class MicCapture:
    """Manages a sounddevice.InputStream lifecycle for push-to-talk.

    Start: opens the input stream and begins accumulating audio chunks
    via a callback into an in-memory list. Stop: closes the stream,
    concatenates the chunks into a single numpy array, returns it.

    Thread-safe append; safe to start/stop from the Qt main thread.
    """

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
        if status:
            # Underflows / overflows happen occasionally; not fatal.
            pass
        with self._lock:
            # indata is a 2D array (frames × channels); keep a copy
            self._chunks.append(indata.copy())

    def start(self):
        if self._active:
            return
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=self.blocksize,
            callback=self._callback,
        )
        self._stream.start()
        self._active = True

    def stop(self) -> np.ndarray:
        """Stop capture and return the concatenated audio as a numpy array."""
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


# ---- Push-to-talk button (emits pressed/released for hold-style) ----

class PushToTalkButton(QPushButton):
    """QPushButton subclass that reliably emits press/release on macOS.

    QPushButton's built-in `pressed`/`released` signals work but they
    can have edge cases on macOS with focus changes. Overriding the
    mouse events directly gives consistent push-to-talk behavior.
    """
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


# ---- TTS request worker (same as v1) ----

class TTSWorkerSignals(QObject):
    finished = Signal(bytes, str, float)
    error = Signal(str, str)


class TTSWorker(QRunnable):
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.signals = TTSWorkerSignals()

    def run(self):
        start = time.time()
        try:
            payload = json.dumps({"text": self.text}).encode("utf-8")
            req = urllib.request.Request(
                TTS_SYNTHESIZE_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TTS_REQUEST_TIMEOUT) as resp:
                audio_bytes = resp.read()
            elapsed = time.time() - start
            self.signals.finished.emit(audio_bytes, self.text, elapsed)
        except urllib.error.URLError as e:
            self.signals.error.emit(
                f"TTS server unreachable: {e.reason}.",
                self.text,
            )
        except Exception as e:
            self.signals.error.emit(f"TTS failed: {type(e).__name__}: {e}", self.text)


# ---- STT request worker (new in v2) ----

class WhisperWorkerSignals(QObject):
    finished = Signal(str, float)  # (transcript, elapsed_seconds)
    error = Signal(str)


class WhisperWorker(QRunnable):
    """Send captured audio (numpy array) to the Whisper server, receive
    transcript, emit on completion. Audio is encoded to WAV in-memory
    and base64-wrapped for the /transcribe_bytes endpoint."""

    def __init__(self, audio: np.ndarray, samplerate: int):
        super().__init__()
        self.audio = audio
        self.samplerate = samplerate
        self.signals = WhisperWorkerSignals()

    def run(self):
        start = time.time()
        try:
            # Pack numpy → in-memory WAV → base64
            buf = io.BytesIO()
            sf.write(buf, self.audio, self.samplerate, format="WAV", subtype="PCM_16")
            buf.seek(0)
            wav_bytes = buf.read()
            audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

            payload = json.dumps({
                "audio_b64": audio_b64,
                "ext": "wav",
                "model": WHISPER_MODEL,
                "language": "en",
                "word_timestamps": False,  # we don't need word-level for input
                "spectral": False,
            }).encode("utf-8")

            req = urllib.request.Request(
                WHISPER_TRANSCRIBE_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=STT_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                self.signals.error.emit(f"Whisper error: {data.get('error', 'unknown')}")
                return
            transcript = (data.get("transcript") or "").strip()
            elapsed = time.time() - start
            self.signals.finished.emit(transcript, elapsed)
        except urllib.error.URLError as e:
            self.signals.error.emit(f"Whisper server unreachable: {e.reason}")
        except Exception as e:
            self.signals.error.emit(f"STT failed: {type(e).__name__}: {e}")


# ---- Health workers ----

class HealthWorkerSignals(QObject):
    result = Signal(str, str)  # (status_label, color_hex)


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
                models_present = data.get("models_present", [])
                models_loaded = data.get("models_loaded", [])
                if WHISPER_MODEL in models_loaded:
                    self.signals.result.emit("● STT ready", "#3aa856")
                elif WHISPER_MODEL in models_present:
                    self.signals.result.emit("● STT (model present, will load on first use)", "#d4a017")
                else:
                    self.signals.result.emit(f"● STT: {WHISPER_MODEL} model not found", "#c84343")
            else:
                self.signals.result.emit("● STT not ready", "#c84343")
        except Exception:
            self.signals.result.emit("● STT unreachable", "#c84343")


# ---- Main window ----

class VoiceBridgeWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        self.thread_pool = QThreadPool.globalInstance()
        self.mic = MicCapture()

        # ---- Layout ----

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Portrait + name
        portrait_frame = QFrame()
        portrait_frame.setFrameShape(QFrame.NoFrame)
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
        history_label = QLabel("History")
        history_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(history_label)

        self.history_view = QTextEdit()
        self.history_view.setReadOnly(True)
        self.history_view.setMinimumHeight(80)
        self.history_view.setStyleSheet(
            "QTextEdit { background-color: #f7f7f8; border: 1px solid #e0e0e0; "
            "border-radius: 6px; padding: 8px; font-size: 13px; }"
        )
        root.addWidget(self.history_view, stretch=2)

        # Input box
        input_label = QLabel("Hold the green button to dictate, or type — then click Speak")
        input_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(input_label)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText(
            "Type here, or hold 'Hold to Talk' to dictate via Whisper STT."
        )
        self.input_box.setMinimumHeight(50)
        self.input_box.setMaximumHeight(120)
        self.input_box.setStyleSheet(
            "QTextEdit { background-color: white; border: 1px solid #cfcfcf; "
            "border-radius: 6px; padding: 8px; font-size: 14px; }"
        )
        root.addWidget(self.input_box, stretch=1)

        # Button row
        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        # Push-to-talk (green)
        self.talk_button = PushToTalkButton("🎙  Hold to Talk")
        self.talk_button.setMinimumHeight(38)
        self._talk_button_idle_style = (
            "QPushButton { background-color: #3aa856; color: white; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #45b863; }"
            "QPushButton:disabled { background-color: #a0a0a0; }"
        )
        self._talk_button_recording_style = (
            "QPushButton { background-color: #c84343; color: white; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; }"
        )
        self.talk_button.setStyleSheet(self._talk_button_idle_style)
        self.talk_button.held.connect(self._on_talk_pressed)
        self.talk_button.let_go.connect(self._on_talk_released)
        button_row.addWidget(self.talk_button)

        # Speak (blue)
        self.speak_button = QPushButton("Speak")
        self.speak_button.setMinimumHeight(38)
        self.speak_button.setStyleSheet(
            "QPushButton { background-color: #2e75b6; color: white; "
            "border-radius: 6px; padding: 8px 18px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #3a85c6; }"
            "QPushButton:disabled { background-color: #a0a0a0; }"
        )
        self.speak_button.clicked.connect(self._on_speak_clicked)
        button_row.addWidget(self.speak_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setMinimumHeight(38)
        self.clear_button.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #444; "
            "border-radius: 6px; padding: 8px 14px; font-size: 13px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.clear_button.clicked.connect(lambda: self.input_box.clear())
        button_row.addWidget(self.clear_button)

        button_row.addStretch()

        self.stop_button = QPushButton("Stop")
        self.stop_button.setMinimumHeight(38)
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #c84343; "
            "border-radius: 6px; padding: 8px 14px; font-size: 13px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.stop_button.clicked.connect(self._on_stop_clicked)
        button_row.addWidget(self.stop_button)

        root.addLayout(button_row)

        # Status bar — TTS status + STT status + last-action
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

        # Cmd/Ctrl+Return for Speak
        self.input_box.installEventFilter(self)

        # Health timers
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self._poll_health)
        self.health_timer.start(HEALTH_POLL_SECONDS * 1000)
        self._poll_health()

        self._append_history(
            "system",
            "v2 ready. Hold the green button to dictate, or type. Audio in via Whisper, out via TTS — "
            "no browser anywhere in the path.",
        )

    # ---- Portrait ----

    def _load_portrait(self):
        if not PORTRAIT_PATH.exists():
            self.portrait_label.setText("(portrait not found)")
            self.portrait_label.setMinimumHeight(PORTRAIT_DISPLAY_HEIGHT)
            self.portrait_label.setStyleSheet(
                "QLabel { background-color: #f0f0f0; color: #888; "
                "border-radius: 8px; padding: 40px; }"
            )
            return
        pixmap = QPixmap(str(PORTRAIT_PATH))
        if pixmap.isNull():
            self.portrait_label.setText("(portrait failed to load)")
            return
        scaled = pixmap.scaledToHeight(PORTRAIT_DISPLAY_HEIGHT, Qt.SmoothTransformation)
        self.portrait_label.setPixmap(scaled)
        self.portrait_label.setMinimumHeight(PORTRAIT_DISPLAY_HEIGHT)

    # ---- Cmd/Ctrl+Return → Speak ----

    def eventFilter(self, obj, event):
        if obj is self.input_box and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
                event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
            ):
                self._on_speak_clicked()
                return True
        return super().eventFilter(obj, event)

    # ---- Push-to-talk lifecycle ----

    def _on_talk_pressed(self):
        try:
            self.mic.start()
        except Exception as e:
            self._set_action(f"Mic start failed: {type(e).__name__}: {e}")
            self._append_history("error", f"Microphone failed to start: {e}")
            return
        self.talk_button.setText("● Recording — release to send")
        self.talk_button.setStyleSheet(self._talk_button_recording_style)
        self._set_action("Recording…")

    def _on_talk_released(self):
        if not self.mic.active:
            return
        try:
            audio = self.mic.stop()
        except Exception as e:
            self._reset_talk_button()
            self._set_action(f"Mic stop failed: {type(e).__name__}: {e}")
            self._append_history("error", f"Microphone stop failed: {e}")
            return
        self._reset_talk_button()
        if audio.size == 0:
            self._set_action("(empty recording — nothing to transcribe)")
            return
        duration = len(audio) / float(MIC_SAMPLE_RATE)
        if duration < 0.3:
            self._set_action(f"(recording too short: {duration:.2f}s — try holding longer)")
            return

        self._set_action(f"Recorded {duration:.1f}s — transcribing…")
        # If audio came through as 2D (frames × 1), squeeze to 1D
        audio_flat = audio.squeeze() if audio.ndim > 1 else audio
        worker = WhisperWorker(audio_flat, MIC_SAMPLE_RATE)
        worker.signals.finished.connect(self._on_stt_finished)
        worker.signals.error.connect(self._on_stt_error)
        self.thread_pool.start(worker)

    def _reset_talk_button(self):
        self.talk_button.setText("🎙  Hold to Talk")
        self.talk_button.setStyleSheet(self._talk_button_idle_style)

    def _on_stt_finished(self, transcript: str, elapsed: float):
        if not transcript:
            self._set_action(f"Transcribed in {elapsed:.1f}s but got empty text.")
            return
        self._set_action(f"Transcribed in {elapsed:.1f}s.")
        # Fill input box (don't auto-Speak — preserve user agency for review/edit)
        existing = self.input_box.toPlainText().strip()
        if existing:
            # Append on a new line if user already had text
            self.input_box.setPlainText(existing + " " + transcript)
        else:
            self.input_box.setPlainText(transcript)
        self.input_box.setFocus()
        # Move cursor to end
        cursor = self.input_box.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_box.setTextCursor(cursor)
        self._append_history("you-dictated", transcript, meta=f"transcribed {elapsed:.1f}s")

    def _on_stt_error(self, message: str):
        self._set_action(f"STT error: {message}")
        self._append_history("error", message)

    # ---- Speak (same as v1) ----

    def _on_speak_clicked(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            self._set_action("(nothing to speak)")
            return
        self.speak_button.setEnabled(False)
        self.speak_button.setText("Generating…")
        self._set_action("Sending to TTS server…")
        self._append_history("user", text)

        worker = TTSWorker(text)
        worker.signals.finished.connect(self._on_tts_finished)
        worker.signals.error.connect(self._on_tts_error)
        self.thread_pool.start(worker)

    def _on_tts_finished(self, audio_bytes: bytes, original_text: str, elapsed: float):
        self._set_action(f"Generated in {elapsed:.1f}s. Playing…")
        try:
            buf = io.BytesIO(audio_bytes)
            data, samplerate = sf.read(buf, dtype="float32")
            sd.play(data, samplerate)
            duration = len(data) / float(samplerate)
            self._append_history(
                "sofia",
                original_text,
                meta=f"generated {elapsed:.1f}s · audio {duration:.1f}s",
            )
            QTimer.singleShot(int(duration * 1000) + 200, self._on_audio_done)
        except Exception as e:
            self._on_tts_error(f"Audio playback failed: {type(e).__name__}: {e}", original_text)

    def _on_tts_error(self, message: str, original_text: str = ""):
        self._set_action(f"Error: {message}")
        self._append_history("error", message)
        self.speak_button.setEnabled(True)
        self.speak_button.setText("Speak")

    def _on_audio_done(self):
        self._set_action("Done.")
        self.speak_button.setEnabled(True)
        self.speak_button.setText("Speak")
        self.input_box.clear()
        self.input_box.setFocus()

    def _on_stop_clicked(self):
        sd.stop()
        if self.mic.active:
            try:
                self.mic.stop()
            except Exception:
                pass
            self._reset_talk_button()
        self._set_action("Stopped.")
        self.speak_button.setEnabled(True)
        self.speak_button.setText("Speak")

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
        elif role == "user":
            color, prefix = "#444", "You"
        elif role == "you-dictated":
            color, prefix = "#3aa856", "You (dictated)"
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
    app.setApplicationName("Voice Bridge — Sofia v2")
    win = VoiceBridgeWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
