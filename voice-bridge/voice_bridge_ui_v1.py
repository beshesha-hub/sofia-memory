#!/usr/bin/env python3
"""
Voice Bridge UI v1 — Custom PySide6 desktop app
================================================

Minimal first-iteration desktop UI for the Voice Bridge. Replaces the
browser-mediated UI (port 3456 + Safari Web Audio API) with a native
PySide6 window that plays audio directly via sounddevice. Closes the
audible-final-mile bug class that browser audio routing produced on
2026-04-29 evening (byte-level LLM-to-TTS pipe was clean; the audio-
element-to-ear last meter failed inside the browser).

What this v1 does:
  - Shows Sofia's portrait at the top (face visible, no lipsync yet)
  - Text area for input
  - "Speak" button → POST text to TTS server (port 3457) → play WAV via
    sounddevice (direct PortAudio binding, no Web Audio API)
  - Conversation history pane showing what was said and when
  - Status indicator showing TTS server health (green/amber/red)
  - All audio output is in-process; the browser is gone from the path

What this v1 deliberately does NOT do (queued for v2+):
  - Lipsync animation (face is static portrait)
  - Chat with Sofia (this is speak-text-back; the LLM-server hook is v2)
  - STT / voice input (Whisper integration is v3 or so)
  - Multiple voices / voice switching
  - Conversation persistence across sessions

Architecture:
  - PySide6 for native cross-platform widgets
  - sounddevice + soundfile for direct audio output (no browser)
  - QThread (via QRunnable + QThreadPool) for non-blocking TTS requests
  - urllib.request for HTTP calls to local TTS server (no extra deps)

Origin: 2026-04-30 afternoon Taipei. Per the 2026-04-30 design conversation
with Barak: substrate-selection-by-function principle (§88 candidate) —
peripheral functions run locally where local doesn't degrade quality.
Audio output is peripheral; runs locally; bypasses browser entirely.

Usage: python3 voice_bridge_ui_v1.py
Requires:
  - PySide6 (pip install pyside6)
  - sounddevice (pip install sounddevice)
  - soundfile (pip install soundfile)
  - numpy (already a dep of the existing voice-bridge stack)
  - sofia_tts_server.py running on port 3457
"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---- UI imports ----
try:
    from PySide6.QtCore import (
        Qt, QObject, QRunnable, QThreadPool, Signal, QSize, QTimer,
    )
    from PySide6.QtGui import QPixmap, QFont, QColor, QPalette
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QPushButton, QStatusBar, QFrame, QSplitter,
        QSizePolicy,
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
HEALTH_POLL_SECONDS = 5  # how often to ping /health to refresh status

# Portrait location — Claude Memory canonical path
HOME = Path.home()
PORTRAIT_PATH = HOME / "Downloads" / "Claude Memory" / "sofia_portrait.png"

# Window sizing — kept small enough to fit a 13" MacBook Pro screen
# (effective ~800px tall after menu bar + dock); user can resize larger.
WINDOW_TITLE = "Voice Bridge — Sofia"
DEFAULT_WIDTH = 680
DEFAULT_HEIGHT = 600
PORTRAIT_DISPLAY_HEIGHT = 160  # px

# TTS request timeout (seconds) — long-utterance generation can take a while
TTS_REQUEST_TIMEOUT = 60


# ---- TTS request worker (runs in QThreadPool, doesn't block UI) ----

class TTSWorkerSignals(QObject):
    """Signals emitted by the TTS worker on completion or error.

    Defined as a separate QObject because QRunnable can't directly emit
    Qt signals (it's not a QObject subclass). Standard Qt pattern.
    """
    finished = Signal(bytes, str, float)  # (audio_bytes, original_text, elapsed_seconds)
    error = Signal(str, str)              # (error_message, original_text)


class TTSWorker(QRunnable):
    """Send text to the TTS server, receive WAV bytes, emit on completion.

    Runs in QThreadPool so the UI remains responsive during synthesis.
    Audio playback happens on the UI thread after the worker finishes —
    sounddevice's play() is non-blocking by default.
    """

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
                f"TTS server unreachable: {e.reason}. "
                f"Is sofia_tts_server.py running on port 3457?",
                self.text,
            )
        except Exception as e:
            self.signals.error.emit(
                f"TTS failed: {type(e).__name__}: {e}",
                self.text,
            )


# ---- Health check worker (lightweight, runs on a timer) ----

class HealthWorkerSignals(QObject):
    result = Signal(str, str)  # (status_label, color_hex)


class HealthWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = HealthWorkerSignals()

    def run(self):
        try:
            with urllib.request.urlopen(TTS_HEALTH_ENDPOINT, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # The TTS server returns status="ready" | "loading" (not the
            # model_ready / model_loading shape my v1 originally assumed).
            status = data.get("status", "")
            if status == "ready":
                self.signals.result.emit("● TTS ready", "#3aa856")  # green
            elif status == "loading":
                self.signals.result.emit("● TTS loading model…", "#d4a017")  # amber
            else:
                self.signals.result.emit(f"● TTS status: {status or 'unknown'}", "#c84343")  # red
        except Exception:
            self.signals.result.emit("● TTS unreachable", "#c84343")  # red


# ---- Main window ----

class VoiceBridgeWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        self.thread_pool = QThreadPool.globalInstance()

        # ---- Build layout ----

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Portrait + name banner at the top
        portrait_frame = QFrame()
        portrait_frame.setFrameShape(QFrame.NoFrame)
        portrait_layout = QVBoxLayout(portrait_frame)
        portrait_layout.setContentsMargins(0, 0, 0, 0)
        portrait_layout.setSpacing(6)
        portrait_layout.setAlignment(Qt.AlignHCenter)

        self.portrait_label = QLabel()
        self.portrait_label.setAlignment(Qt.AlignHCenter)
        self._load_portrait()
        portrait_layout.addWidget(self.portrait_label, alignment=Qt.AlignHCenter)

        name_label = QLabel("Sofia Lior")
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setWeight(QFont.DemiBold)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignHCenter)
        portrait_layout.addWidget(name_label)

        root.addWidget(portrait_frame)

        # Conversation history (read-only, scrollable)
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

        # Input area
        input_label = QLabel("Type what Sofia should say")
        input_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(input_label)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText(
            "Type a sentence or paragraph here, then click Speak (or Cmd+Return)."
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

        self.speak_button = QPushButton("Speak")
        self.speak_button.setMinimumHeight(36)
        self.speak_button.setStyleSheet(
            "QPushButton { background-color: #2e75b6; color: white; "
            "border-radius: 6px; padding: 8px 18px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #3a85c6; }"
            "QPushButton:disabled { background-color: #a0a0a0; }"
        )
        self.speak_button.clicked.connect(self._on_speak_clicked)
        button_row.addWidget(self.speak_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setMinimumHeight(36)
        self.clear_button.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #444; "
            "border-radius: 6px; padding: 8px 18px; font-size: 14px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.clear_button.clicked.connect(lambda: self.input_box.clear())
        button_row.addWidget(self.clear_button)

        button_row.addStretch()

        self.stop_button = QPushButton("Stop")
        self.stop_button.setMinimumHeight(36)
        self.stop_button.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #c84343; "
            "border-radius: 6px; padding: 8px 18px; font-size: 14px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.stop_button.clicked.connect(self._on_stop_clicked)
        button_row.addWidget(self.stop_button)

        root.addLayout(button_row)

        # Status bar (TTS server health + last action)
        self.status_label = QLabel("● TTS unknown")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        status_bar = QStatusBar()
        status_bar.addWidget(self.status_label, 1)
        self.action_label = QLabel("")
        self.action_label.setStyleSheet("color: #888; font-size: 11px;")
        status_bar.addPermanentWidget(self.action_label)
        self.setStatusBar(status_bar)

        # Cmd+Return / Ctrl+Return shortcut to Speak
        self.input_box.installEventFilter(self)

        # Health-check timer
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self._poll_health)
        self.health_timer.start(HEALTH_POLL_SECONDS * 1000)
        self._poll_health()  # initial check

        self._append_history("system", "Voice Bridge ready. Audio out via sounddevice — no browser in the path.")

    # ---- Portrait loading ----

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
        scaled = pixmap.scaledToHeight(
            PORTRAIT_DISPLAY_HEIGHT,
            Qt.SmoothTransformation,
        )
        self.portrait_label.setPixmap(scaled)
        self.portrait_label.setMinimumHeight(PORTRAIT_DISPLAY_HEIGHT)

    # ---- Event filter for Cmd/Ctrl+Return ----

    def eventFilter(self, obj, event):
        if obj is self.input_box and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
                event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
            ):
                self._on_speak_clicked()
                return True
        return super().eventFilter(obj, event)

    # ---- Speak action ----

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
        # Decode WAV → numpy array → play via sounddevice (non-blocking)
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
            # Re-enable Speak when audio finishes (approximate via timer)
            QTimer.singleShot(int(duration * 1000) + 200, self._on_audio_done)
        except Exception as e:
            self._on_tts_error(f"Audio playback failed: {type(e).__name__}: {e}", original_text)

    def _on_tts_error(self, message: str, original_text: str):
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
        self._set_action("Stopped.")
        self.speak_button.setEnabled(True)
        self.speak_button.setText("Speak")

    # ---- Health poll ----

    def _poll_health(self):
        worker = HealthWorker()
        worker.signals.result.connect(self._on_health_result)
        self.thread_pool.start(worker)

    def _on_health_result(self, label: str, color_hex: str):
        self.status_label.setText(label)
        self.status_label.setStyleSheet(f"color: {color_hex}; font-size: 11px;")

    # ---- History rendering ----

    def _append_history(self, role: str, text: str, meta: str = ""):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if role == "sofia":
            color = "#2e75b6"
            prefix = "Sofia"
        elif role == "user":
            color = "#444"
            prefix = "You"
        elif role == "error":
            color = "#c84343"
            prefix = "Error"
        else:  # system
            color = "#888"
            prefix = "System"

        meta_html = f' <span style="color: #aaa; font-size: 11px;">· {meta}</span>' if meta else ""
        html = (
            f'<div style="margin: 4px 0; line-height: 1.4;">'
            f'<span style="color: {color}; font-weight: 600;">{prefix}</span> '
            f'<span style="color: #aaa; font-size: 11px;">{timestamp}{meta_html}</span><br>'
            f'<span style="color: #222;">{self._html_escape(text)}</span>'
            f'</div>'
        )
        self.history_view.append(html)
        # Auto-scroll to bottom
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
    app.setApplicationName("Voice Bridge — Sofia")
    win = VoiceBridgeWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
