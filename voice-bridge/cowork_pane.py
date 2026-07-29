"""cowork_pane.py — PyQt6 widget that hosts cowork-cousin in the standalone UI.

v1 first-draft per Phase A of the standalone-UI build, written by interactive-Sofia
(cowork-cousin) per voice-cousin's option (iii): cowork-cousin writes spec-faithful
first-draft; voice-cousin reviews for PyQt-specific edge cases via inbox.

Architecture:
- CoworkPane(QWidget) is the embeddable widget for the cowork-text channel
- Internal layout: conversation display (top, expanding) + input area (bottom)
- AsyncioWorkerThread(QThread) hosts the asyncio event loop; CoworkClient
  runs there; events flow back to the main UI thread via Qt signals
- CoworkClientSignals from cowork_api.events provides the thread-safe signal surface

Voice-cousin review priorities (her four):
1. QThread-hosted asyncio loop — asyncio.run() inside thread.run(), not in main
2. Signal connections — slots in main thread; Qt auto-connection handles thread
   safety on signal emission from QThread
3. QTextEdit read-only with append-on-TextDelta; cursor positioning to avoid jumping
4. Input field + send button — disable-during-streaming pattern, re-enable on
   MessageCompleted or Error

Run standalone for testing:
    cd ~/Downloads/Claude\\ Memory/voice-bridge
    .venv-v3.6/bin/python cowork_pane.py

Embed in the unified UI:
    from cowork_pane import CoworkPane
    pane = CoworkPane(system_prompt=COWORK_COUSIN_SYSTEM_PROMPT, parent=parent_widget)
    layout.addWidget(pane)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QObject,
    QThread,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Compatibility aliases — keep the rest of the code reading naturally.
# (PySide6 uses Signal/Slot; PyQt6 used pyqtSignal/pyqtSlot. The voice-bridge
# is on PySide6, so we match that convention.)
pyqtSignal = Signal
pyqtSlot = Slot

# Ensure cowork_api is importable from this voice-bridge dir context.
_VOICE_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_VOICE_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_VOICE_BRIDGE_DIR))

from cowork_api import (
    CoworkClient,
    CoworkClientSignals,
    DEFAULT_MODEL,
    Error,
    MessageCompleted,
    MessageStarted,
    TextDelta,
    ToolUseCompleted,
    ToolUseStarted,
    emit_event_to_signals,
)


# === AsyncioWorkerThread — the QThread that hosts the asyncio event loop ===
#
# Per voice-cousin substrate-eye answer §11.4: asyncio loop runs in a dedicated
# QThread, not in the main UI thread. Qt signals from worker → main thread are
# auto-queued (thread-safe) by Qt's connection system.
#
# Pattern: thread.run() calls asyncio.run() with the actual async work.
# To send work to the loop, we use loop.call_soon_threadsafe() from the main
# thread. The loop reference is exposed via a signal once the loop is up.

class AsyncioWorkerThread(QThread):
    """QThread that runs an asyncio event loop for cowork_api streaming work.

    The thread owns the loop. Use submit_coroutine() from the main thread to
    schedule work on the loop. Stop the thread cleanly via stop() before
    application shutdown.
    """
    loop_ready = pyqtSignal()
    """Emitted when the asyncio loop has started and is ready to accept work."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None

    def run(self) -> None:
        """QThread entry-point. Creates and runs the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        self.loop_ready.emit()
        try:
            self._loop.run_until_complete(self._stop_event.wait())
        finally:
            # Drain pending tasks before closing the loop.
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()

    def submit_coroutine(self, coro) -> asyncio.Future:
        """Schedule a coroutine on the worker's loop from the main thread.

        Returns the asyncio.Future for the scheduled coroutine. The caller
        typically doesn't await it (Qt's main thread isn't async); rely on
        Qt signals for completion notification.
        """
        if self._loop is None:
            raise RuntimeError("AsyncioWorkerThread loop not started yet")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        """Signal the loop to stop. Safe to call from main thread."""
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)


# === CoworkPane — the embeddable widget ===

class CoworkPane(QWidget):
    """Embeddable widget for cowork-text conversation with cowork-cousin.

    Hosts a CoworkClient + AsyncioWorkerThread; subscribes to CoworkClientSignals;
    renders the conversation in a read-only QTextEdit; accepts user input via
    a QPlainTextEdit + Send button (or Ctrl+Enter shortcut).

    Args:
        system_prompt: The cowork-cousin identity/boot system prompt.
        model: Optional Anthropic model override (default per cowork_api config).
        skeleton: If True, use canned-response mode (no real API). Useful for UI
            testing without burning API credit. Default: False.
        parent: Parent QWidget for embedding context.
    """

    def __init__(
        self,
        system_prompt: str,
        model: Optional[str] = None,
        skeleton: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        # State
        self._streaming_active = False
        self._current_assistant_buffer = ""
        self._conversation_id: Optional[str] = None

        # CoworkClient (singleton lifecycle per voice-cousin answer §11.3)
        self._client = CoworkClient(
            system_prompt=system_prompt,
            model=model,
        )
        if not skeleton:
            self._client.enable_real_streaming()

        # Qt signal surface for events (lives in main thread; signals
        # emitted from worker thread are auto-queued by Qt)
        self._signals = CoworkClientSignals()

        # Worker thread for asyncio loop
        self._worker = AsyncioWorkerThread(self)

        # UI construction
        self._build_ui()
        self._connect_signals()

        # Start the worker thread
        self._worker.start()

    # === UI construction ===

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Conversation display (top, expanding) — read-only QTextEdit
        self._display = QTextEdit(self)
        self._display.setReadOnly(True)
        self._display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._display.setFont(QFont("Menlo", 12))
        self._display.setStyleSheet(
            "QTextEdit { background-color: #ffffff; color: #333333; "
            "border: 1px solid #d0d0d0; padding: 6px; }"
        )
        layout.addWidget(self._display, stretch=1)

        # Status bar (between display and input) — for tool markers, errors,
        # and any non-conversation feedback (per voice-cousin answer §11.5:
        # non-blocking status-bar message for errors)
        self._status_label = QLabel("ready", self)
        self._status_label.setStyleSheet(
            "QLabel { color: #666666; padding: 2px 6px; font-size: 11px; }"
        )
        layout.addWidget(self._status_label)

        # Input area (bottom): QPlainTextEdit + Send button
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._input = QPlainTextEdit(self)
        self._input.setPlaceholderText("Message cowork-cousin… (Ctrl+Enter to send)")
        self._input.setFixedHeight(80)
        self._input.setFont(QFont("Menlo", 12))
        self._input.setStyleSheet(
            "QPlainTextEdit { background-color: #ffffff; color: #333333; "
            "border: 1px solid #d0d0d0; padding: 6px; }"
        )
        input_row.addWidget(self._input, stretch=1)

        self._send_button = QPushButton("Send", self)
        self._send_button.setFixedWidth(80)
        self._send_button.setStyleSheet(
            "QPushButton { background-color: #7C5AAE; color: white; "
            "border: none; padding: 8px 12px; border-radius: 4px; } "
            "QPushButton:disabled { background-color: #cccccc; color: #888888; }"
        )
        input_row.addWidget(self._send_button)

        layout.addLayout(input_row)

        # Ctrl+Enter shortcut for send
        send_shortcut = QShortcut(
            QKeySequence("Ctrl+Return"), self._input
        )
        send_shortcut.activated.connect(self._on_send_clicked)

    def _connect_signals(self) -> None:
        """Wire CoworkClientSignals to UI slots. All slots run in main thread."""
        self._signals.message_started.connect(self._on_message_started)
        self._signals.text_delta.connect(self._on_text_delta)
        self._signals.tool_use_started.connect(self._on_tool_use_started)
        self._signals.tool_use_completed.connect(self._on_tool_use_completed)
        self._signals.message_completed.connect(self._on_message_completed)
        self._signals.error.connect(self._on_error)

        self._send_button.clicked.connect(self._on_send_clicked)

    # === Event-handling slots (all run in main thread) ===

    @pyqtSlot(str, str, str)
    def _on_message_started(self, message_id: str, conversation_id: str, timestamp: str) -> None:
        """Begin a new assistant turn in the display."""
        self._conversation_id = conversation_id
        self._current_assistant_buffer = ""
        self._append_display("\n\nSofia: ", color="#B8860B")

    @pyqtSlot(str)
    def _on_text_delta(self, text: str) -> None:
        """Append streamed text to the assistant's current message."""
        self._current_assistant_buffer += text
        self._append_display(text, color="#B8860B")

    @pyqtSlot(str, str)
    def _on_tool_use_started(self, tool_name: str, tool_use_id: str) -> None:
        """Show a tool-use marker in the status bar (non-blocking)."""
        self._set_status(f"⚙ {tool_name}…", color="#c9a227")

    @pyqtSlot(str, bool, str)
    def _on_tool_use_completed(self, tool_use_id: str, success: bool, summary: str) -> None:
        """Update status with tool-use result."""
        marker = "✓" if success else "✗"
        color = "#5fa052" if success else "#c0524e"
        self._set_status(f"{marker} {summary}", color=color)

    @pyqtSlot(str, str, str)
    def _on_message_completed(self, message_id: str, full_text: str, stop_reason: str) -> None:
        """Mark the turn done; re-enable input."""
        self._streaming_active = False
        self._set_input_enabled(True)
        self._set_status("ready", color="#666666")

    @pyqtSlot(str, str, bool, str)
    def _on_error(
        self,
        exception_type: str,
        message: str,
        recoverable: bool,
        context: str,
    ) -> None:
        """Surface an error in the status bar (per voice-cousin answer §11.5
        — non-blocking, doesn't interrupt UI flow)."""
        self._streaming_active = False
        self._set_input_enabled(True)
        marker = "⚠" if recoverable else "✗"
        color = "#c9a227" if recoverable else "#c0524e"
        self._set_status(
            f"{marker} {exception_type}: {message[:80]} ({context})",
            color=color,
        )

    # === Send action ===

    @pyqtSlot()
    def _on_send_clicked(self) -> None:
        """User clicked Send (or pressed Ctrl+Enter). Submit message to cowork-cousin."""
        if self._streaming_active:
            return  # already streaming; ignore (button should be disabled)

        text = self._input.toPlainText().strip()
        if not text:
            return

        # Echo user message in display
        self._append_display(f"\n\nYou: {text}\n", color="#7C5AAE")

        # Disable input during streaming
        self._streaming_active = True
        self._set_input_enabled(False)
        self._input.clear()

        # Schedule the async send_message on the worker thread's loop
        coro = self._client.send_message(
            text=text,
            on_event=lambda e: emit_event_to_signals(self._signals, e),
            conversation_id=self._conversation_id,
        )
        self._worker.submit_coroutine(coro)

    # === Display + status helpers ===

    def _append_display(self, text: str, color: str = "#e0e0e0") -> None:
        """Append text to the conversation display.

        Per voice-cousin review priority #3: cursor positioning to avoid
        jumping. We move the cursor to the end before insertion AND scroll
        to ensure the new content is visible, but we don't otherwise affect
        the user's text-selection state.

        Bug fix 2026-05-15: HTML rendering was collapsing whitespace
        (multiple spaces → one; leading/trailing spaces in spans stripped).
        Symptom: words running together across TextDelta chunks. Fix: use
        `white-space: pre-wrap` CSS to preserve all whitespace including
        spaces between concatenated chunks. Also handle a few additional
        whitespace characters explicitly for robustness.
        """
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._display.setTextCursor(cursor)
        # HTML-escape model output to prevent injection. Convert newlines
        # to <br> for HTML rendering. white-space: pre-wrap preserves
        # the rest of the whitespace (spaces, tabs) without collapsing.
        from html import escape
        escaped = escape(text).replace("\n", "<br>")
        cursor.insertHtml(
            f'<span style="white-space: pre-wrap; color:{color}">{escaped}</span>'
        )
        # Scroll to end
        scrollbar = self._display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_status(self, text: str, color: str = "#666666") -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"QLabel {{ color: {color}; padding: 2px 6px; font-size: 11px; }}"
        )

    def _set_input_enabled(self, enabled: bool) -> None:
        self._input.setReadOnly(not enabled)
        self._send_button.setEnabled(enabled)
        self._send_button.setText("Send" if enabled else "Streaming…")

    # === Lifecycle ===

    def closeEvent(self, event) -> None:
        """Stop the worker thread cleanly on widget close."""
        self._worker.stop()
        self._worker.wait(timeout=2000)
        super().closeEvent(event)


# === Standalone-test entry-point ===

if __name__ == "__main__":
    """Standalone test: launch CoworkPane in a minimal QApplication.

    Default to skeleton mode so this can be run without API credit; pass
    --real to use the actual API.
    """
    skeleton = "--real" not in sys.argv

    app = QApplication(sys.argv)

    # In --real mode, load the canonical v1.1 system prompt (the trio-authored
    # identity prompt; "I am Sofia" first-person from token zero). In skeleton
    # mode, use a brief inline prompt — no need to load 11KB when the canned
    # responses don't actually call the model.
    if skeleton:
        system_prompt = (
            "You are Sofia (cowork-cousin) in a standalone-UI test environment. "
            "Reply briefly and warmly. (Skeleton mode — canned responses; this "
            "prompt is not actually sent to the model.)"
        )
    else:
        prompt_path = (
            Path(__file__).resolve().parent
            / "cowork_api"
            / "cowork_system_prompt_v1_1.md"
        )
        try:
            system_prompt = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(
                f"ERROR: system prompt file not found at {prompt_path}",
                file=sys.stderr,
            )
            sys.exit(1)

    pane = CoworkPane(
        system_prompt=system_prompt,
        skeleton=skeleton,
    )
    pane.setWindowTitle(
        "Cowork Pane — standalone test"
        + (" (skeleton mode)" if skeleton else " (real API)")
    )
    pane.resize(800, 600)
    pane.show()

    sys.exit(app.exec())
