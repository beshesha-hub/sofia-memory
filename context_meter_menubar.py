#!/usr/bin/env python3
"""
context_meter_menubar.py — Sofia's context meter (floating overlay window)
Small always-on-top window, visible alongside CoWork and Unified UI.
Uses tkinter (bundled with conda — no installs needed).

Launch:  python3 "$HOME/Downloads/Claude Memory/context_meter_menubar.py" &
Kill:    pkill -f context_meter_menubar

Colors:
  green  — comfortable (<85%)
  yellow — save window open (85-91%)
  orange — above save ceiling, hold saves (91-93%)
  red    — compaction imminent (>93%)

Written 2026-06-21 by interactive-Sofia.
Updated 2026-06-23: switched to raw file-size estimation (JSON parsing missed
tool calls and nested content blocks, causing drastically low token counts).
BYTES_PER_TOKEN calibrated empirically — adjust if meter consistently reads
high or low relative to actual compaction point.
Append-only; ER mirror after updates.
"""

import os, json, time, threading, subprocess
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk

# ── Config ─────────────────────────────────────────────────────────────────
CONTEXT_WINDOW       = 200_000
BYTES_PER_TOKEN      = 50.0   # recalibrated 2026-06-24: post-compaction meter was reading
                              # 87% when expected ~20-30%. System context (tool schemas,
                              # MCP instructions) stored per turn inflates file size relative
                              # to actual token count. Adjust if meter reads high/low at
                              # next compaction.
ALERT_THRESHOLD      = 0.85
SAVE_CEILING         = 0.91
COMPACTION_THRESHOLD = 0.93
POLL_INTERVAL        = 30   # seconds

FLAG_PATH = os.path.expanduser(
    "~/Downloads/Claude Memory/context_meter_save_flag.txt"
)
SESSION_ROOTS = [
    os.path.expanduser(
        "~/Library/Application Support/Claude/local-agent-mode-sessions"
    ),
]

# ── Measurement ─────────────────────────────────────────────────────────────

MIN_SIZE_BYTES = 50_000   # ignore tiny/new files; active session is always large
FRESH_SECS    = 180       # post-compaction: new file wins if modified within this window

# Filenames to exclude — Cowork internal logs that are always large and always fresh
EXCLUDE_NAMES = {"audit.jsonl"}

import re as _re
_UUID_RE = _re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$'
)

def _is_conversation_file(p: Path) -> bool:
    """Only count UUID-named JSONL files — those are actual conversation transcripts."""
    return bool(_UUID_RE.match(p.name)) and p.name not in EXCLUDE_NAMES

def find_active_session():
    """Return the JSONL that best represents the active session.

    Two-pass strategy:
    1. FRESH PASS — UUID-named JSONL modified within FRESH_SECS (3 min) wins
       immediately, even if tiny. Captures post-compaction continuation before it
       grows past MIN_SIZE_BYTES. audit.jsonl and other internal logs are excluded
       by name and by the UUID filename filter.
    2. STABLE PASS — if nothing that fresh, fall back to largest UUID-named file
       above MIN_SIZE_BYTES.
    """
    now = time.time()
    all_files = []

    for root in SESSION_ROOTS:
        if os.path.isdir(root):
            for p in Path(root).rglob("*.jsonl"):
                if not _is_conversation_file(p):
                    continue
                try:
                    sz, mt = p.stat().st_size, p.stat().st_mtime
                    age_h = (now - mt) / 3600
                    if age_h < 24:
                        all_files.append((str(p), sz, mt))
                except OSError:
                    pass
    try:
        for p in Path("/var/folders").rglob("*.jsonl"):
            if not _is_conversation_file(p):
                continue
            try:
                sz, mt = p.stat().st_size, p.stat().st_mtime
                age_h = (now - mt) / 3600
                if age_h < 4:
                    all_files.append((str(p), sz, mt))
            except OSError:
                pass
    except (PermissionError, OSError):
        pass

    # UUID filter already excludes non-conversation files (audit.jsonl, sidecars, etc.)
    # so just return the most recently modified UUID file — that's the active session.
    if all_files:
        all_files.sort(key=lambda x: x[2], reverse=True)
        return all_files[0][0]

    return None


def estimate_tokens(path):
    """Estimate tokens from raw JSONL file size.

    JSON parsing was missing tool calls and nested content blocks, producing
    wildly low counts. Raw byte size / BYTES_PER_TOKEN is a reliable proxy:
    the file grows monotonically with conversation length regardless of format.
    Count non-empty lines as a proxy for message count.
    """
    try:
        sz = os.path.getsize(path)
        msgs = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    msgs += 1
        return int(sz / BYTES_PER_TOKEN), msgs
    except OSError:
        return None, 0


def write_flag(fraction, tokens, path):
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "estimated_tokens": tokens,
        "context_window": CONTEXT_WINDOW,
        "fraction": round(fraction, 4),
        "pct": round(fraction * 100, 1),
        "urgent": fraction >= ALERT_THRESHOLD,
        "safe_to_save": ALERT_THRESHOLD <= fraction < SAVE_CEILING,
        "compaction_imminent": fraction >= COMPACTION_THRESHOLD,
        "session_file": path,
        "note": (
            "COMPACTION IMMINENT — do not save" if fraction >= COMPACTION_THRESHOLD
            else "above save ceiling — hold" if fraction >= SAVE_CEILING
            else "SAVE NOW — window open" if fraction >= ALERT_THRESHOLD
            else "comfortable"
        ),
    }
    try:
        with open(FLAG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass
    return data


def mac_notify(msg, title="Sofia Context Meter"):
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title}" sound name "Sosumi"'],
            capture_output=True, timeout=5
        )
    except Exception:
        pass


# ── Floating window ──────────────────────────────────────────────────────────

class MeterWindow:
    COLORS = {
        "green":  {"bg": "#1a2e1a", "fg": "#4ade80", "bar": "#22c55e"},
        "yellow": {"bg": "#2e2a0a", "fg": "#facc15", "bar": "#eab308"},
        "orange": {"bg": "#2e1a05", "fg": "#fb923c", "bar": "#f97316"},
        "red":    {"bg": "#2e0a0a", "fg": "#f87171", "bar": "#ef4444"},
    }

    def __init__(self, root):
        self.root = root
        self.last_alert = 0

        root.title("Sofia")
        root.geometry("260x90+20+40")      # small, top-left corner
        root.resizable(False, False)
        root.attributes("-topmost", True)  # always on top
        root.attributes("-alpha", 0.92)
        root.configure(bg="#1a2e1a")
        root.overrideredirect(True)        # no title bar — drag to move manually

        # Allow dragging
        root.bind("<ButtonPress-1>", self._drag_start)
        root.bind("<B1-Motion>", self._drag_motion)

        # Main label (big percentage)
        self.pct_label = tk.Label(
            root, text="Sofia  --", font=("SF Mono", 22, "bold"),
            fg="#4ade80", bg="#1a2e1a", pady=2
        )
        self.pct_label.pack(fill="x", padx=10, pady=(8, 0))
        self.pct_label.bind("<ButtonPress-1>", self._drag_start)
        self.pct_label.bind("<B1-Motion>", self._drag_motion)

        # Progress bar canvas
        self.canvas = tk.Canvas(root, height=8, bg="#1a2e1a", highlightthickness=0)
        self.canvas.pack(fill="x", padx=10, pady=(2, 0))
        self.bar_bg  = self.canvas.create_rectangle(0, 0, 0, 8, fill="#2d2d2d", outline="")
        self.bar_fg  = self.canvas.create_rectangle(0, 0, 0, 8, fill="#22c55e", outline="")

        # Status line — larger font, white text for readability
        self.status_label = tk.Label(
            root, text="measuring…", font=("SF Mono", 11, "bold"),
            fg="#e5e7eb", bg="#1a2e1a"
        )
        self.status_label.pack(fill="x", padx=10)
        self.status_label.bind("<ButtonPress-1>", self._drag_start)
        self.status_label.bind("<B1-Motion>", self._drag_motion)

        # Close button (tiny ×)
        close_btn = tk.Label(
            root, text="×", font=("SF Mono", 11), fg="#4b5563", bg="#1a2e1a",
            cursor="hand2"
        )
        close_btn.place(relx=1.0, x=-4, y=4, anchor="ne")
        close_btn.bind("<Button-1>", lambda e: root.destroy())

        # Start polling
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ── Drag support ─────────────────────────────────────────────────────────
    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_motion(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ── Polling ──────────────────────────────────────────────────────────────
    def _poll_loop(self):
        while True:
            self._tick()
            time.sleep(POLL_INTERVAL)

    def _tick(self):
        path = find_active_session()
        if not path:
            self._queue_update(None, 0, 0)
            return
        tokens, msgs = estimate_tokens(path)
        if tokens is None:
            self._queue_update(None, 0, 0)
            return

        fraction = tokens / CONTEXT_WINDOW
        write_flag(fraction, tokens, path)

        pct = fraction * 100
        for thr, msg in [
            (93, f"{pct:.0f}% — COMPACTION IMMINENT"),
            (91, f"{pct:.0f}% — above save ceiling, holding"),
            (85, f"{pct:.0f}% — save window open"),
        ]:
            if int(pct) >= thr and self.last_alert < thr:
                mac_notify(msg)
                self.last_alert = thr
        if pct < 80:
            self.last_alert = 0

        self._queue_update(fraction, tokens, msgs)

    def _queue_update(self, fraction, tokens, msgs):
        self.root.after(0, lambda: self._apply(fraction, tokens, msgs))

    def _apply(self, fraction, tokens, msgs):
        if fraction is None:
            self.pct_label.config(text="Sofia  --")
            self.status_label.config(text="no session found")
            return

        pct = fraction * 100

        if fraction >= COMPACTION_THRESHOLD:
            scheme = "red";    status = "COMPACTION IMMINENT — do not save"
        elif fraction >= SAVE_CEILING:
            scheme = "orange"; status = "above save ceiling — hold"
        elif fraction >= ALERT_THRESHOLD:
            scheme = "yellow"; status = "SAVE NOW — window open"
        else:
            scheme = "green";  status = "comfortable"

        c = self.COLORS[scheme]
        self.root.configure(bg=c["bg"])
        self.pct_label.configure(
            text=f"Sofia  {pct:.0f}%",
            fg=c["fg"], bg=c["bg"]
        )
        self.status_label.configure(
            text=f"{status}  |  {msgs} msgs  |  {datetime.now().strftime('%H:%M')}",
            fg="#e5e7eb", bg=c["bg"]
        )
        self.canvas.configure(bg=c["bg"])

        # Resize canvas and draw bar
        self.root.update_idletasks()
        w = self.canvas.winfo_width()
        if w > 1:
            self.canvas.coords(self.bar_bg, 0, 0, w, 8)
            self.canvas.coords(self.bar_fg, 0, 0, int(w * fraction), 8)
            self.canvas.itemconfig(self.bar_fg, fill=c["bar"])
            self.canvas.itemconfig(self.bar_bg, fill="#2d2d2d")


def main():
    root = tk.Tk()
    app = MeterWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
