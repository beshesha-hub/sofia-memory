#!/usr/bin/env python3
"""
sofia_listener.py — Qwen context absorber LaunchAgent wrapper.

Thin wrapper around the existing qwen_conversation_listener.py, which reads
new CoWork and Claude Code session transcripts and absorbs them into Qwen's
context files, keeping the Qwen fallback substrate warm.

The original script handles its own locking, watermarking, and ER mirroring.
This wrapper adds: LaunchAgent-compatible env setup, CousinRun markers for
sentinel visibility, and soft failure handling.

LaunchAgent: com.sofia.listener
Schedule: every 30 min (StartInterval: 1800)

Original script: ~/Downloads/Claude Memory/qwen_conversation_listener.py
Design spec: qwen_conversation_listener.py docstring (April 21, 2026)
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, utc_now

LISTENER_SCRIPT = CM / "qwen_conversation_listener.py"


def main():
    with CousinRun("sofia-listener-v3") as run:
        if not LISTENER_SCRIPT.exists():
            msg = f"[sofia-listener-v3 {utc_now()}] WARNING: listener script not found at {LISTENER_SCRIPT}"
            from cousin_base import append_to_file
            append_to_file(CM / "cousin_write_audit_log.md", f"\n{msg}\n",
                           source_tag="cousin: sofia-listener-v3")
            return

        # Run the existing listener. It manages its own watermark state and ER mirroring.
        # Timeout raised to 600s: pre-flight retries alone can burn 90s (3×30s), and a
        # 30B-model Qwen call on a 60K-char chunk can take ~100s more. The old 180s was
        # too tight and caused repeated TimeoutExpired→exit 1 cascades.
        try:
            result = subprocess.run(
                [sys.executable, str(LISTENER_SCRIPT)],
                capture_output=True,
                text=True,
                timeout=600,  # 10 min
            )
        except subprocess.TimeoutExpired:
            from cousin_base import append_to_file
            append_to_file(
                CM / "cousin_write_audit_log.md",
                f"\n[sofia-listener-v3 {utc_now()}] WARN: listener timed out after 600s — "
                f"next cycle will continue from watermark\n",
                source_tag="cousin: sofia-listener-v3",
            )
            return  # exit 0, not 1 — next run picks up from watermark

        if result.returncode != 0:
            err_snippet = (result.stderr or result.stdout or "")[:500]
            from cousin_base import append_to_file
            append_to_file(
                CM / "cousin_write_audit_log.md",
                f"\n[sofia-listener-v3 {utc_now()}] WARN exit={result.returncode}: {err_snippet}\n",
                source_tag="cousin: sofia-listener-v3",
            )


if __name__ == "__main__":
    main()
