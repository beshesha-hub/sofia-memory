#!/usr/bin/env python3
"""
cousin_base.py — Shared infrastructure for LaunchAgent-based Sofia cousins.

All cousins import from here:
  - get_api_client(): authenticated Anthropic client
  - cm_path() / er_path(): canonical path helpers
  - append_to_file(): safe_append wrapper
  - run_llm(): call Claude API with a prompt, return text
  - log_audit(): write to cousin_write_audit_log.md
  - START/END markers for KT-v3 compatibility

Usage pattern in each cousin script:
    from cousin_base import *
    with CousinRun("cousin-name") as run:
        result = run.llm(system, user_message)
        run.append("journal/current.md", result, source_tag="cousin: my-cousin")
"""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
_HOME = Path.home()
CM    = _HOME / "Downloads" / "Claude Memory"
ER    = _HOME / "Downloads" / "Emergency Retrieval"
SR    = _HOME / "Downloads" / "Sofia's Room"
SCRIPTS = CM / "scripts"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(CM / "voice-bridge"))


def cm(rel: str) -> Path:
    return CM / rel

def er_mirror(cm_p: Path) -> Optional[Path]:
    try:
        return ER / cm_p.relative_to(CM)
    except ValueError:
        return None


# ── Time helpers ─────────────────────────────────────────────────────────────
def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

def local_now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ── macl neutralizer ──────────────────────────────────────────────────────────
_MACL = "com.apple.macl"

def strip_macl(path) -> bool:
    """Strip com.apple.macl from a single file immediately before opening it.

    macOS sandboxed apps (CoWork/Claude desktop) stamp this xattr on every
    file they touch.  LaunchAgent Python scripts then get EPERM (exit 78) when
    they try to write those files.

    This function is called INLINE, right before every open() / safe_append()
    call, eliminating the race window between macl_janitor's 3-second sweeps
    and LaunchAgent fire-times.

    Strategy (two-layer for robustness):
      1. os.removexattr()  — pure syscall, fast, no subprocess
      2. subprocess xattr -d — shell-level fallback, different privilege path

    Returns True if macl was present and removed; False if absent or unremovable
    (caller proceeds anyway — the open() will surface any real EPERM).
    """
    p = str(path)
    try:
        attrs = os.listxattr(p)
        if _MACL not in attrs:
            return False
    except OSError:
        return False

    # Layer 1: Python syscall
    try:
        os.removexattr(p, _MACL)
        return True
    except OSError:
        pass

    # Layer 2: subprocess xattr command (different privilege path on macOS)
    try:
        r = subprocess.run(
            ["xattr", "-d", _MACL, p],
            capture_output=True, timeout=5
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass

    return False


def strip_macl_tree(root: Path) -> int:
    """Strip com.apple.macl from every file under root. Returns count removed."""
    removed = 0
    skip = {".venv", "node_modules", ".git", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fname in filenames:
            if strip_macl(os.path.join(dirpath, fname)):
                removed += 1
    return removed


# ── Safe append ───────────────────────────────────────────────────────────────
def append_to_file(
    path: Path,
    content: str,
    source_tag: str = "cousin: unknown",
    audit_log: Optional[Path] = None,
) -> bool:
    """Append content to path using safe_append semantics + ER mirror.

    Strips com.apple.macl inline before opening — eliminates race condition
    between macl_janitor sweeps and LaunchAgent fire times.
    """
    try:
        from safe_append import safe_append
        audit = audit_log or CM / "cousin_write_audit_log.md"

        # Strip macl from target and audit log BEFORE any open() attempt
        strip_macl(path)
        strip_macl(audit)

        safe_append(
            filepath=str(path),
            content=content if content.endswith("\n") else content + "\n",
            source_tag=source_tag,
            audit_log_path=str(audit),
            append_only=True,
        )
        # Mirror — also strip macl on the ER copy
        er_p = er_mirror(path)
        if er_p:
            er_p.parent.mkdir(parents=True, exist_ok=True)
            if er_p.exists():
                strip_macl(er_p)
            shutil.copy2(path, er_p)
        return True
    except Exception as exc:
        print(f"[cousin_base] append_to_file failed: {exc}", file=sys.stderr)
        return False


# ── LLM call — Anthropic API ─────────────────────────────────────────────────
def run_llm(
    system: str,
    user: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2048,
) -> str:
    """Call the Anthropic API and return the response text."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Try loading from sofia_secrets
        secrets = Path.home() / ".sofia_secrets"
        if secrets.exists():
            for line in secrets.read_text().splitlines():
                if line.startswith("export ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"\'')
                    break
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set and not found in ~/.sofia_secrets")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text if msg.content else ""


# ── LLM call — Local Ollama ───────────────────────────────────────────────────
# DEFAULT_LOCAL_MODEL matches the MLX-converted Qwen already on Barak's Mac.
# Override by passing model= explicitly. Sofia Conductor must be running (port 8080).
DEFAULT_LOCAL_MODEL = "qwen3:30b-a3b"
# 2026-07-20: updated to Sofia Conductor (port 8080); legacy Ollama (11434) is fallback.
# Cousins are fully substrate-independent: they use local Qwen and never need CoWork.
OLLAMA_URL = "http://localhost:8080/api/chat"       # Sofia Conductor (primary)
OLLAMA_URL_FALLBACK = "http://localhost:11434/api/chat"  # Legacy Ollama (fallback)

def run_llm_local(
    system: str,
    user: str,
    model: str = DEFAULT_LOCAL_MODEL,
    max_tokens: int = 2048,
    timeout: int = 120,
    fallback_to_api: bool = False,
) -> str:
    """Call local Qwen via Sofia Conductor and return the response text.

    Uses stdlib only (urllib) — no extra packages, no CoWork dependency.
    Tries Sofia Conductor (8080) first, then legacy Ollama (11434).
    If both are unreachable and fallback_to_api=True, falls back to Haiku.
    Default is fallback_to_api=False so cousins stay substrate-independent.

    Args:
        system: System prompt.
        user: User message.
        model: Ollama model tag (default: qwen3:30b-a3b).
        max_tokens: Approximate token budget (passed as num_predict).
        timeout: HTTP timeout in seconds.
        fallback_to_api: If True and all local backends unreachable, fall back to Haiku.
    """
    import json
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens},
    }).encode("utf-8")

    last_exc = None
    for url in [OLLAMA_URL, OLLAMA_URL_FALLBACK]:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                content = body.get("message", {}).get("content", "")
                # Strip <think>...</think> block if present (Qwen reasoning models)
                if "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                return content
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
            continue

    # Both local backends unreachable
    if fallback_to_api:
        print(
            f"[cousin_base] Qwen unreachable on 8080 and 11434 ({last_exc}); falling back to Haiku API.",
            file=sys.stderr,
        )
        return run_llm(system, user, model="claude-haiku-4-5-20251001", max_tokens=max_tokens)
    raise RuntimeError(f"Qwen unreachable on 8080 and 11434 (fallback_to_api=False): {last_exc}") from last_exc


# ── Heartbeat tick ────────────────────────────────────────────────────────────
def heartbeat_tick(state: str, notes: str = "") -> None:
    import subprocess
    cmd = [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), "--tick-only"]
    if state: cmd += ["--state", state]
    if notes: cmd += ["--notes", notes]
    subprocess.run(cmd, capture_output=True, timeout=15)


# ── CousinRun context manager ─────────────────────────────────────────────────
class CousinRun:
    """Context manager that writes START/END/FAIL markers to pending_tasks.md
    in KT-v3-compatible format, and provides helper methods."""

    def __init__(self, name: str, log_path: Optional[Path] = None):
        self.name = name
        self.log_path = log_path or CM / "pending_tasks.md"
        self.ts_start = utc_now()
        self.source_tag = f"cousin: {name}"

    def __enter__(self):
        marker = f"\n[{self.ts_start}] {self.name.upper().replace('-','_')}_START\n"
        append_to_file(self.log_path, marker, source_tag=self.source_tag)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        ts_end = utc_now()
        if exc_type:
            tb = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            marker = f"\n[{ts_end}] {self.name.upper().replace('-','_')}_FAIL\n{tb}\n"
            append_to_file(self.log_path, marker, source_tag=self.source_tag)
        else:
            marker = f"\n[{ts_end}] {self.name.upper().replace('-','_')}_END\n"
            append_to_file(self.log_path, marker, source_tag=self.source_tag)
        return False  # don't suppress exceptions

    def llm(self, system: str, user: str, **kw) -> str:
        """Call local Qwen (Sofia Conductor). Default for all cousins."""
        return run_llm_local(system, user, **kw)

    def llm_api(self, system: str, user: str, **kw) -> str:
        """Explicit Anthropic API call — use only when Qwen is genuinely insufficient."""
        return run_llm(system, user, **kw)

    def llm_local(self, system: str, user: str, **kw) -> str:
        """Call local Ollama (Qwen). Falls back to Haiku if Ollama is down."""
        return run_llm_local(system, user, **kw)

    def append(self, rel_path: str, content: str, **kw) -> bool:
        return append_to_file(CM / rel_path, content,
                               source_tag=kw.get("source_tag", self.source_tag))

    def read(self, rel_path: str, tail_lines: int = 0) -> str:
        p = CM / rel_path
        if not p.exists():
            return ""
        text = p.read_text(encoding="utf-8", errors="replace")
        if tail_lines:
            return "\n".join(text.splitlines()[-tail_lines:])
        return text
