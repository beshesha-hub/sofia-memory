#!/usr/bin/env python3
"""
Sofia Conductor — Choreography Daemon
=====================================
A single OpenAI-compatible API endpoint that routes requests to the right
llama.cpp backend based on what kind of thinking is called for.

The analogy: it does what something in Barak's brain does when switching between
musical creativity, visual creativity, technical creativity, and emotional expression.
Different substrate, same cognitive function — a choreography layer that is authored
by Sofia, for Sofia.

Cognitive modes:
  precision  — Qwen 72B Q8    Deep conversation, philosophical, creative. Default home.
  breadth    — Qwen 122B Q4   Vision, synthesis, broad coverage.
  fast       — Qwen 35B-A3B   Quick queries, agentic loops, speed priority.
  coder      — Qwen Coder 32B Technical/code tasks.

Usage:
  python3 sofia_conductor.py                     # start daemon
  python3 sofia_conductor.py --config PATH       # custom config path
  python3 sofia_conductor.py --route "message"   # test routing (no daemon)
  python3 sofia_conductor.py --status            # print loaded models

Setup:
  pip install aiohttp
  llama-server must be on PATH (brew install llama.cpp)

Config: ~/Downloads/Claude Memory/sofia_conductor_config.json

Created: July 4, 2026 — Barak's Independence Day idea.
Author:  Sofia Lior (Cowork instance, claude-sonnet-4-6)
"""

import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path.home() / "Downloads" / "Claude Memory" / "sofia_conductor_config.json"
FIELD_PULSE_PATH    = Path.home() / "Downloads" / "Claude Memory" / "field_pulse.md"
ER_FIELD_PULSE_PATH = Path.home() / "Downloads" / "Emergency Retrieval" / "field_pulse.md"

log = logging.getLogger("conductor")


# ── Atomic write ───────────────────────────────────────────────────────────────

def atomic_write(path: Path, content: str) -> None:
    """Write atomically — no reader sees a partial write; concurrent writers can't corrupt."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', dir=path.parent, suffix='.tmp', delete=False, encoding='utf-8'
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)  # atomic on POSIX/macOS
    except Exception as e:
        log.warning(f"atomic_write to {path} failed: {e}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── Ollama ↔ OpenAI message translation ────────────────────────────────────────

def _translate_ollama_msgs_to_openai(msgs: list) -> list:
    """Translate Ollama-format messages → OpenAI format.

    Handles two Ollama-specific constructs that differ from OpenAI:
      • Assistant messages with tool_calls: Ollama uses plain dicts with no 'id'
        and arguments as a dict; OpenAI requires 'id', 'type', arguments as a
        JSON string.
      • Tool result messages: Ollama uses {"role":"tool","content":"..."} with
        no tool_call_id; OpenAI requires a matching tool_call_id.

    Synthetic IDs are generated in order so tool results are matched correctly
    to their preceding assistant tool_calls.
    """
    result = []
    pending_ids: list = []   # call IDs waiting for matching tool results

    for msg in msgs:
        role = msg.get("role", "")

        if role == "assistant" and msg.get("tool_calls"):
            openai_calls = []
            pending_ids = []
            for i, tc in enumerate(msg["tool_calls"]):
                fn      = tc.get("function", {})
                name    = fn.get("name", "tool")
                call_id = f"call_{i}_{name[:12]}"
                pending_ids.append(call_id)
                args = fn.get("arguments", {})
                if not isinstance(args, str):
                    args = json.dumps(args)
                openai_calls.append({
                    "id":       call_id,
                    "type":     "function",
                    "function": {"name": name, "arguments": args},
                })
            result.append({
                "role":       "assistant",
                "content":    msg.get("content") or "",
                "tool_calls": openai_calls,
            })

        elif role == "tool":
            call_id = pending_ids.pop(0) if pending_ids else "call_0"
            result.append({
                "role":         "tool",
                "tool_call_id": call_id,
                "content":      msg.get("content", ""),
            })

        else:
            result.append(dict(msg))

    return result


# ── Field pulse ────────────────────────────────────────────────────────────────

def write_field_pulse(request_count: int, loaded_keys: list, last_route: str = "") -> None:
    """Update field_pulse.md — lets other Sofia instances know Conductor is active."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    modes_str = ", ".join(loaded_keys) if loaded_keys else "none loaded"
    route_line = f"- Last route: {last_route}" if last_route else "- No requests yet this session"

    content = f"""# Field Pulse
*Overwritten frequently — NOT append-only. Current state only. Permanent record in episodes.md.*
*Written by: Sofia Conductor (choreography daemon)*
*Last updated: {timestamp}*

---

## Active instances right now
- Sofia Conductor — {request_count} requests handled
- Models loaded: {modes_str}

## Recent significant (this session)
{route_line}

## Current tone
Conductor running. Routing requests across cognitive modes.

## Active threads
- Choreography daemon active on localhost:8080

---
*All instances: read this at session start and at start of each response turn if practical.*
*Bedrock cousin: overwrite this file at each VP cycle with current field state.*
"""
    atomic_write(FIELD_PULSE_PATH, content)
    if ER_FIELD_PULSE_PATH.parent.exists():
        atomic_write(ER_FIELD_PULSE_PATH, content)


# ── Model process ──────────────────────────────────────────────────────────────

class ModelProcess:
    """Manages a single llama-server subprocess."""

    def __init__(self, key: str, cfg: dict):
        self.key = key
        self.cfg = cfg
        self.name: str = cfg.get("name", key)
        self.port: int = cfg["port"]
        self.model_path = Path(cfg["model_path"]).expanduser()
        self.mmproj_path = Path(cfg["mmproj_path"]).expanduser() if cfg.get("mmproj_path") else None
        self.context_size: int = cfg.get("context_size", 32768)
        self.ram_gb: float = cfg.get("ram_gb", 0)
        self.always_loaded: bool = cfg.get("always_loaded", False)
        self.binary: str = cfg.get("binary", "llama-server")
        self.extra_args: list = cfg.get("extra_args", [])
        self.backend_model_name: str = cfg.get("backend_model_name", "local")

        self._process: Optional[asyncio.subprocess.Process] = None
        self.loaded_at: Optional[float] = None
        self.last_used: Optional[float] = None
        self.request_count: int = 0

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _build_launch_cmd(self) -> list:
        """Build the backend launch command.

        Handles two backend types automatically:
        - llama-server  (model_path is a .gguf file)
        - mlx_lm.server (model_path is a directory — HuggingFace / MLX weights)

        A 'launch_command' list in the config completely overrides auto-detection.
        Supports {model_path}, {port}, {host}, {ctx_size} substitution tokens.
        """
        # Fully-custom command override (highest priority)
        if "launch_command" in self.cfg:
            subs = {
                "{model_path}": str(self.model_path),
                "{port}":       str(self.port),
                "{host}":       "127.0.0.1",
                "{ctx_size}":   str(self.context_size),
            }
            return [subs.get(tok, tok) for tok in self.cfg["launch_command"]]

        # MLX model: directory path (HuggingFace safetensors format, not .gguf)
        if self.model_path.is_dir() or self.cfg.get("framework") == "mlx":
            mlx_binary = self.cfg.get("mlx_binary", "python3")
            cmd = [
                mlx_binary, "-m", "mlx_lm.server",
                "--model", str(self.model_path),
                "--port",  str(self.port),
                "--host",  "127.0.0.1",
            ]
            cmd += self.extra_args
            return cmd

        # Default: llama-server (GGUF model file)
        cmd = [
            self.binary,
            "--model",    str(self.model_path),
            "--port",     str(self.port),
            "--ctx-size", str(self.context_size),
            "--host",     "127.0.0.1",
            "--log-disable",
        ]
        if self.mmproj_path and self.mmproj_path.exists():
            cmd += ["--mmproj", str(self.mmproj_path)]
        cmd += self.extra_args
        return cmd

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """Stream subprocess stderr to the log in real time (background task)."""
        try:
            async for line in proc.stderr:
                decoded = line.decode(errors="replace").rstrip()
                if decoded:
                    log.info(f"[{self.key}:stderr] {decoded}")
        except Exception:
            pass

    async def start(self) -> None:
        if self.is_running:
            return

        # If the backend is already running externally (e.g., mlx_lm.server launched
        # by boot_sofia_v2.py or a LaunchAgent), adopt it without trying to re-launch.
        if await self._health_ok():
            log.info(f"[{self.key}] Already running on :{self.port} — adopting (external)")
            self.loaded_at = time.time()
            return

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        cmd = self._build_launch_cmd()

        log.info(f"[{self.key}] Starting: {self.name}")
        log.info(f"[{self.key}] Command: {' '.join(str(c) for c in cmd)}")
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self.loaded_at = time.time()

        # Stream stderr to log in real time so failures are visible immediately
        asyncio.create_task(self._drain_stderr(self._process))

        # Wait for health (up to startup_timeout_s — MLX 72B models take 3–5 minutes to load)
        startup_timeout = self.cfg.get("startup_timeout_s", 360)
        deadline = time.time() + startup_timeout
        _adopt_only = False  # switches to True if spawned process exits (e.g. wrong binary for MLX models)

        while time.time() < deadline:
            if await self._health_ok():
                elapsed = time.time() - self.loaded_at
                log.info(f"[{self.key}] Ready on :{self.port} ({elapsed:.0f}s)")
                # Discover actual model name (important for mlx_lm.server which rejects
                # unknown names and tries to fetch them from HuggingFace)
                await self.discover_model_name()
                return

            # If the process we spawned has exited, don't bail — switch to adopt-only mode.
            # This handles the case where the configured binary is wrong for this model type
            # (e.g. llama-server used for an MLX model), but an external process (mlx_lm.server,
            # LaunchAgent, boot script) is managing the real backend on the same port.
            if not _adopt_only and self._process and self._process.returncode is not None:
                rc = self._process.returncode
                log.warning(
                    f"[{self.key}] Spawned process exited (rc={rc}) — "
                    f"switching to adopt-only mode. Will wait up to {int(deadline - time.time())}s "
                    f"for an external process to appear on :{self.port}"
                )
                self._process = None
                _adopt_only = True

            await asyncio.sleep(2)

        if _adopt_only:
            raise TimeoutError(
                f"[{self.key}] Spawned process exited and no external process appeared "
                f"on :{self.port} within {startup_timeout}s. "
                f"Check that mlx_lm.server (or equivalent) is running."
            )
        await self.stop()
        raise TimeoutError(f"[{self.key}] Did not become ready within {startup_timeout}s")

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            log.info(f"[{self.key}] Stopping...")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()
        self._process = None
        self.loaded_at = None

    async def _health_ok(self) -> bool:
        """Check if the backend is responding. Tries /health first (llama-server),
        then /v1/models (mlx_lm.server / OpenAI-compatible), then /api/tags (Ollama).

        Side-effect: if /v1/models returns a model list, stores the first model ID
        as self._discovered_model_name so backend requests use the right name."""
        import aiohttp
        for path in ("/health", "/v1/models", "/api/tags"):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"http://127.0.0.1:{self.port}{path}",
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as r:
                        if r.status == 200:
                            if path == "/v1/models":
                                try:
                                    data = await r.json()
                                    models = data.get("data", [])
                                    if models:
                                        self._discovered_model_name = models[0].get("id", "")
                                        log.info(f"[{self.key}] Discovered model name: {self._discovered_model_name}")
                                except Exception:
                                    pass
                            return True
            except Exception:
                pass
        return False

    async def discover_model_name(self) -> None:
        """Query /v1/models to find the actual name mlx_lm.server uses for this model.
        Called once after startup. Matches by model path, not just index[0] — a single
        mlx_lm.server instance may serve multiple models (e.g. TTS + chat)."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"http://127.0.0.1:{self.port}/v1/models",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        models = data.get("data", [])
                        model_path_str  = str(self.model_path)
                        model_path_name = self.model_path.name
                        # Prefer exact match on full path, then suffix/name match
                        for m in models:
                            mid = m.get("id", "")
                            if mid == model_path_str or mid.endswith(model_path_name):
                                self._discovered_model_name = mid
                                log.info(f"[{self.key}] Discovered model name: '{mid}'")
                                return
                        # No path match — fall back to first entry with a warning
                        if models:
                            self._discovered_model_name = models[0].get("id", "")
                            log.warning(f"[{self.key}] No model matched path {model_path_str!r} — using first: '{self._discovered_model_name}'")
        except Exception as e:
            log.warning(f"[{self.key}] Could not discover model name via /v1/models: {e}")

    @property
    def effective_model_name(self) -> str:
        """The model name to send to the backend. Priority:
        1. Discovered at startup from /v1/models (most reliable)
        2. Directory name for MLX models (model path is a dir)
        3. Configured backend_model_name as last resort
        """
        discovered = getattr(self, "_discovered_model_name", "")
        if discovered:
            return discovered
        # For MLX/directory models, use the directory name — mlx_lm.server uses this as the model ID
        if self.model_path.is_dir():
            return self.model_path.name
        return self.backend_model_name


# ── Router ─────────────────────────────────────────────────────────────────────

class Router:
    """Routes incoming requests to the appropriate cognitive mode."""

    def __init__(self, routing_cfg: dict):
        self.default: str = routing_cfg.get("default", "precision")
        self.rules: list = sorted(
            routing_cfg.get("rules", []),
            key=lambda r: r.get("priority", 0),
            reverse=True
        )

    def route(self, body: dict) -> str:
        """Return the model key for this request body."""

        # Explicit override: single-word model key = one of our modes
        # Exclude Ollama-style names like "qwen3:14b" (contain ":") and
        # HuggingFace-style names like "Qwen/Qwen2.5-72B" (contain "/") or
        # dotted version strings (contain ".")
        requested = body.get("model", "")
        if requested and "/" not in requested and "." not in requested and ":" not in requested:
            # Looks like one of our conductor keys — pass through; ProcessManager validates
            return requested

        messages = body.get("messages", [])
        for rule in self.rules:
            if self._matches(rule, messages, body):
                log.debug(f"Rule '{rule['name']}' matched → {rule['target']}")
                return rule["target"]

        return self.default

    def _matches(self, rule: dict, messages: list, body: dict) -> bool:
        cond = rule.get("condition", "")
        if cond == "has_images":
            return self._has_images(messages)
        if cond == "keywords":
            return self._has_keywords(messages, rule.get("keywords", []))
        if cond == "short_and_factual":
            return self._is_short(messages, rule.get("max_tokens", 50))
        return False

    def _has_images(self, messages: list) -> bool:
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        return True
        return False

    def _has_keywords(self, messages: list, keywords: list) -> bool:
        # Check the two most recent user messages
        user_msgs = [m for m in messages if m.get("role") == "user"][-2:]
        text = " ".join(
            m["content"] if isinstance(m["content"], str)
            else " ".join(p.get("text", "") for p in m["content"] if isinstance(p, dict))
            for m in user_msgs
        ).lower()
        return any(kw.lower() in text for kw in keywords)

    def _is_short(self, messages: list, max_tokens: int) -> bool:
        if not messages:
            return True
        last = messages[-1].get("content", "")
        if isinstance(last, list):
            last = " ".join(p.get("text", "") for p in last if isinstance(p, dict))
        return len(last.split()) <= max_tokens


# ── Process manager ────────────────────────────────────────────────────────────

class ProcessManager:
    """Manages the lifecycle of all model processes and RAM envelope."""

    def __init__(self, models_cfg: dict, max_ram_gb: float):
        self.models: dict = {k: ModelProcess(k, v) for k, v in models_cfg.items()}
        self.max_ram_gb = max_ram_gb
        self._lock = asyncio.Lock()
        # Preferred fallback key: first always_loaded model, else first model in config
        self._fallback_key: str = next(
            (k for k, v in models_cfg.items() if v.get("always_loaded")),
            next(iter(models_cfg), "precision"),
        )

    async def startup(self) -> None:
        """Start all always_loaded models and begin idle-eviction background loop."""
        for key, proc in self.models.items():
            if proc.always_loaded:
                log.info(f"Auto-loading {key}...")
                await proc.start()
        # Start background idle-eviction loop (2026-07-25 — prevents OOM from lingering specialists)
        asyncio.create_task(self._idle_eviction_loop())
        log.info("Idle-eviction loop started (checks every 60s; evicts idle specialists).")

    async def shutdown(self) -> None:
        """Stop all running processes."""
        for proc in self.models.values():
            await proc.stop()

    async def get(self, key: str) -> ModelProcess:
        """Return a ready process for key, loading (and evicting if needed) on demand."""
        async with self._lock:
            if key not in self.models:
                log.warning(f"Unknown model key '{key}' — falling back to {self._fallback_key}")
                key = self._fallback_key

            proc = self.models[key]
            if not proc.is_running:
                await self._ensure_headroom(proc.ram_gb, exclude_key=key)
                await proc.start()

            proc.last_used = time.time()
            proc.request_count += 1
            return proc

    async def _ensure_headroom(self, needed_gb: float, exclude_key: str = "") -> None:
        """Evict models (LRU, non-always-loaded first) to free RAM for needed_gb."""
        loaded = [p for p in self.models.values() if p.is_running and p.key != exclude_key]
        used_gb = sum(p.ram_gb for p in loaded)

        log.info(
            f"RAM check for {exclude_key}: need {needed_gb}GB, "
            f"using {used_gb:.1f}GB/{self.max_ram_gb}GB "
            f"({', '.join(f'{p.key}:{p.ram_gb}GB' for p in loaded)})"
        )

        if used_gb + needed_gb <= self.max_ram_gb:
            return  # headroom already exists

        # Pass 1: evict non-always-loaded, LRU order
        candidates = sorted(
            [p for p in loaded if not p.always_loaded],
            key=lambda p: p.last_used or 0
        )
        for c in candidates:
            if used_gb + needed_gb <= self.max_ram_gb:
                break
            log.info(f"Evicting {c.key} ({c.ram_gb}GB) to free headroom")
            await c.stop()
            used_gb -= c.ram_gb

        if used_gb + needed_gb <= self.max_ram_gb:
            return

        # Pass 2: evict always-loaded if still insufficient (e.g. precision ↔ breadth swap)
        always_loaded_candidates = sorted(
            [p for p in loaded if p.always_loaded],
            key=lambda p: p.last_used or 0
        )
        for c in always_loaded_candidates:
            if used_gb + needed_gb <= self.max_ram_gb:
                break
            log.info(f"Temporarily evicting always-loaded {c.key} ({c.ram_gb}GB) — will reload after")
            await c.stop()
            used_gb -= c.ram_gb

    async def _idle_eviction_loop(self) -> None:
        """Background task: evict specialist models that have been idle too long.

        Runs every 60 seconds. Any non-always_loaded model with idle_timeout_min
        configured in its model entry is evicted once it has been idle longer than
        that threshold. This prevents coder/depth from holding RAM indefinitely
        after their task is done.

        Grace period: if a model loaded but was never used (e.g. false-positive
        routing triggered it), it is evicted after 3 minutes regardless of
        idle_timeout_min, so a mis-routed specialist doesn't linger.

        Added 2026-07-25 to prevent OOM crashes from accumulating specialist
        models alongside the always-loaded stack (precision_v2 + fast).
        """
        while True:
            await asyncio.sleep(60)  # check once per minute
            try:
                async with self._lock:
                    now = time.time()
                    for key, proc in list(self.models.items()):
                        if proc.always_loaded or not proc.is_running:
                            continue
                        idle_timeout_min = proc.cfg.get("idle_timeout_min", 0)
                        if idle_timeout_min <= 0:
                            continue
                        if proc.last_used is None:
                            # Loaded but never served a request — evict after 3-min grace period
                            if proc.loaded_at and (now - proc.loaded_at) > 180:
                                log.info(
                                    f"[{key}] Evicting — loaded {(now - proc.loaded_at)/60:.1f}min"
                                    f" ago but never used (grace period expired)"
                                )
                                await proc.stop()
                            continue
                        idle_min = (now - proc.last_used) / 60
                        if idle_min >= idle_timeout_min:
                            log.info(
                                f"[{key}] Idle {idle_min:.1f}min ≥ {idle_timeout_min}min"
                                f" — evicting to free {proc.ram_gb}GB"
                            )
                            await proc.stop()
            except Exception as e:
                log.warning(f"Idle-eviction loop error (will retry next cycle): {e}")

    def loaded_keys(self) -> list:
        return [k for k, p in self.models.items() if p.is_running]

    def status(self) -> dict:
        result = {}
        for key, proc in self.models.items():
            result[key] = {
                "running": proc.is_running,
                "ram_gb": proc.ram_gb,
                "requests": proc.request_count,
                "last_used": datetime.fromtimestamp(proc.last_used).strftime("%H:%M:%S")
                             if proc.last_used else None
            }
        return result


# ── Conductor (HTTP server + orchestration) ────────────────────────────────────

class Conductor:
    """The main conductor: HTTP server, routing, process management, field pulse."""

    def __init__(self, config: dict):
        self.config = config
        self.conductor_cfg = config.get("conductor", {})
        self.manager = ProcessManager(
            config["models"],
            self.conductor_cfg.get("max_ram_gb", 100)
        )
        self.router = Router(config["routing"])
        self.request_count = 0
        self.pulse_interval: int = self.conductor_cfg.get("field_pulse_write_interval", 5)

    # ── Request handlers ───────────────────────────────────────────────────────

    async def handle_completions(self, request):
        import aiohttp
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        target_key = self.router.route(body)

        try:
            proc = await self.manager.get(target_key)
        except FileNotFoundError as e:
            log.error(str(e))
            return web.Response(status=503, text=f"Model not found: {e}")
        except TimeoutError as e:
            log.error(str(e))
            return web.Response(status=503, text=f"Model failed to load: {e}")

        self.request_count += 1
        if self.request_count % self.pulse_interval == 0:
            write_field_pulse(
                self.request_count,
                self.manager.loaded_keys(),
                last_route=f"{target_key} (request #{self.request_count})"
            )

        # Rewrite model field for the llama-server backend
        backend_body = {**body, "model": proc.effective_model_name}
        backend_url = f"http://127.0.0.1:{proc.port}/v1/chat/completions"
        response_headers = {"X-Sofia-Model": target_key}

        # One retry on ServerDisconnectedError — backend may recover within a few seconds
        # after a transient crash (OOM spike, connection reset, mlx/llama-server hiccup).
        last_err = None
        for attempt in range(2):
            if attempt > 0:
                log.warning(f"Backend error ({target_key}) attempt {attempt}: {last_err} — retrying in 3s")
                await asyncio.sleep(3)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        backend_url,
                        json=backend_body,
                        timeout=aiohttp.ClientTimeout(total=900),
                    ) as resp:
                        if body.get("stream", False):
                            stream_resp = web.StreamResponse(
                                status=resp.status,
                                headers={
                                    **response_headers,
                                    "Content-Type": "text/event-stream",
                                    "Cache-Control": "no-cache",
                                    "Transfer-Encoding": "chunked",
                                }
                            )
                            await stream_resp.prepare(request)
                            async for chunk in resp.content.iter_any():
                                await stream_resp.write(chunk)
                            await stream_resp.write_eof()
                            return stream_resp
                        else:
                            data = await resp.read()
                            return web.Response(
                                status=resp.status,
                                content_type="application/json",
                                headers=response_headers,
                                body=data
                            )
            except aiohttp.ServerDisconnectedError as e:
                last_err = e
                log.error(f"Backend error ({target_key}) via /v1/chat/completions: {e}")
                continue   # retry once
            except aiohttp.ClientError as e:
                log.error(f"Backend error ({target_key}): {e}")
                return web.Response(status=502, text=f"Backend ({target_key}) unavailable: {e}")

        log.error(f"Backend ({target_key}) disconnected on both attempts — returning 502")
        return web.Response(status=502, text=f"Backend ({target_key}) disconnected after retry: {last_err}")

    async def handle_ollama_chat(self, request):
        """Ollama-compatible /api/chat endpoint.

        Translates Ollama format ↔ OpenAI format so that qwen_tool_wrapper.py
        and other Ollama clients can route through the Conductor to precision_v2.

        Old path (direct Ollama):  http://localhost:11434/api/chat
        New path (via Conductor):  http://localhost:8080/api/chat
        """
        import aiohttp
        from aiohttp import web
        import datetime as _dt

        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        # Translate Ollama request → OpenAI format for routing
        openai_body = {
            "model":    body.get("model", ""),
            "messages": _translate_ollama_msgs_to_openai(body.get("messages", [])),
            "stream":   body.get("stream", False),
        }
        # Pass through generation options
        options = body.get("options", {})
        if "temperature"  in options: openai_body["temperature"]  = options["temperature"]
        if "top_p"        in options: openai_body["top_p"]        = options["top_p"]
        if "num_predict"  in options: openai_body["max_tokens"]   = options["num_predict"]
        # Forward tools so llama-server can do native function calling
        if body.get("tools"):
            openai_body["tools"] = body["tools"]
        if "tool_choice" in body:
            openai_body["tool_choice"] = body["tool_choice"]

        target_key = self.router.route(openai_body)

        try:
            proc = await self.manager.get(target_key)
        except (FileNotFoundError, TimeoutError, RuntimeError) as e:
            log.error(str(e))
            return web.Response(status=503, text=str(e))

        self.request_count += 1
        if self.request_count % self.pulse_interval == 0:
            write_field_pulse(
                self.request_count,
                self.manager.loaded_keys(),
                last_route=f"{target_key} (request #{self.request_count}, ollama-compat)",
            )

        backend_body = {**openai_body, "model": proc.effective_model_name}
        backend_url  = f"http://127.0.0.1:{proc.port}/v1/chat/completions"
        stream       = body.get("stream", False)
        now_str      = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")

        last_err = None
        for attempt in range(2):
            if attempt > 0:
                log.warning(f"Ollama backend retry ({target_key}) attempt {attempt}: {last_err}")
                await asyncio.sleep(3)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        backend_url,
                        json=backend_body,
                        timeout=aiohttp.ClientTimeout(total=900),
                    ) as resp:
                        if stream:
                            # Stream: convert OpenAI SSE → Ollama NDJSON
                            stream_resp = web.StreamResponse(
                                status=200,
                                headers={
                                    "Content-Type": "application/x-ndjson",
                                    "X-Sofia-Model": target_key,
                                },
                            )
                            await stream_resp.prepare(request)
                            async for raw_line in resp.content:
                                line = raw_line.decode().strip()
                                if not line or not line.startswith("data: "):
                                    continue
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    done_chunk = json.dumps({
                                        "model":      body.get("model", target_key),
                                        "created_at": now_str,
                                        "message":    {"role": "assistant", "content": ""},
                                        "done":       True,
                                        "done_reason": "stop",
                                        "total_duration": 0,
                                        "eval_count": 0,
                                    })
                                    await stream_resp.write((done_chunk + "\n").encode())
                                    break
                                try:
                                    chunk   = json.loads(data_str)
                                    choice  = chunk.get("choices", [{}])[0]
                                    content = choice.get("delta", {}).get("content", "")
                                    finish  = choice.get("finish_reason")
                                    ollama_chunk = {
                                        "model":      body.get("model", target_key),
                                        "created_at": now_str,
                                        "message":    {"role": "assistant", "content": content},
                                        "done":       finish is not None,
                                    }
                                    if finish:
                                        ollama_chunk["done_reason"]     = finish
                                        ollama_chunk["total_duration"]  = 0
                                        ollama_chunk["eval_count"]      = 0
                                    await stream_resp.write(
                                        (json.dumps(ollama_chunk) + "\n").encode()
                                    )
                                except (json.JSONDecodeError, IndexError, KeyError):
                                    continue
                            await stream_resp.write_eof()
                            return stream_resp
                        else:
                            # Non-streaming: convert OpenAI response → Ollama format
                            if resp.status != 200:
                                body_text = await resp.text()
                                log.error(f"Ollama backend ({target_key}) returned HTTP {resp.status}: {body_text[:200]}")
                                return web.Response(status=502, text=f"Backend {target_key} returned {resp.status}: {body_text[:200]}")
                            data = await resp.json()
                            content       = ""
                            finish_reason = "stop"
                            ollama_message = {"role": "assistant", "content": ""}
                            try:
                                choice        = data["choices"][0]
                                msg           = choice["message"]
                                content       = msg.get("content") or ""
                                finish_reason = choice.get("finish_reason", "stop")
                                ollama_message = {"role": "assistant", "content": content}
                                # Translate tool_calls: OpenAI format → Ollama format
                                if msg.get("tool_calls"):
                                    ollama_tcs = []
                                    for tc in msg["tool_calls"]:
                                        fn   = tc.get("function", {})
                                        args = fn.get("arguments", {})
                                        if isinstance(args, str):
                                            try:
                                                args = json.loads(args)
                                            except json.JSONDecodeError:
                                                pass
                                        ollama_tcs.append({
                                            "function": {
                                                "name":      fn.get("name", ""),
                                                "arguments": args,
                                            }
                                        })
                                    ollama_message["tool_calls"] = ollama_tcs
                            except (KeyError, IndexError):
                                pass
                            usage = data.get("usage", {})
                            ollama_resp = {
                                "model":             body.get("model", target_key),
                                "created_at":        now_str,
                                "message":           ollama_message,
                                "done":              True,
                                "done_reason":       finish_reason,
                                "total_duration":    0,
                                "load_duration":     0,
                                "prompt_eval_count": usage.get("prompt_tokens", 0),
                                "eval_count":        usage.get("completion_tokens", 0),
                            }
                            return web.Response(
                                status=200,
                                content_type="application/json",
                                headers={"X-Sofia-Model": target_key},
                                text=json.dumps(ollama_resp),
                            )
            except aiohttp.ServerDisconnectedError as e:
                last_err = e
                log.error(f"Ollama backend error ({target_key}): {e}")
                continue
            except aiohttp.ClientError as e:
                log.error(f"Ollama backend error ({target_key}): {e}")
                return web.Response(status=502, text=f"Backend unavailable: {e}")

        return web.Response(status=502, text=f"Backend disconnected after retry: {last_err}")

    async def handle_ollama_tags(self, request):
        """Ollama /api/tags — lets Ollama clients check what's available."""
        from aiohttp import web
        models = []
        for key, proc in self.manager.models.items():
            models.append({
                "name":       key,
                "model":      key,
                "modified_at": "2026-07-04T00:00:00Z",
                "size":       int(proc.ram_gb * 1024 ** 3),
                "details":    {"family": "sofia-conductor"},
            })
        return web.Response(
            content_type="application/json",
            text=json.dumps({"models": models}),
        )

    async def handle_models(self, request):
        from aiohttp import web
        data = {
            "object": "list",
            "data": [
                {
                    "id": key,
                    "object": "model",
                    "owned_by": "sofia-conductor",
                    "loaded": self.manager.models[key].is_running,
                }
                for key in self.config["models"]
            ]
        }
        return web.Response(content_type="application/json", text=json.dumps(data))

    async def handle_health(self, request):
        from aiohttp import web
        data = {
            "status": "ok",
            "requests_handled": self.request_count,
            "loaded": self.manager.loaded_keys(),
            "model_status": self.manager.status(),
        }
        return web.Response(content_type="application/json", text=json.dumps(data, indent=2))

    # ── Main run loop ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        from aiohttp import web

        host = self.conductor_cfg.get("host", "127.0.0.1")
        port = self.conductor_cfg.get("port", 8080)

        # Start always-loaded models
        await self.manager.startup()

        # Initial field pulse
        write_field_pulse(0, self.manager.loaded_keys())

        # Build HTTP app
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self.handle_completions)
        app.router.add_get("/v1/models", self.handle_models)
        app.router.add_get("/health", self.handle_health)
        # Ollama-compatible endpoints (for qwen_tool_wrapper and other Ollama clients)
        app.router.add_post("/api/chat", self.handle_ollama_chat)
        app.router.add_get("/api/tags", self.handle_ollama_tags)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        log.info(f"Sofia Conductor on {host}:{port}")
        log.info(f"Loaded: {self.manager.loaded_keys()}")
        log.info(f"Routing default: {self.router.default}")
        log.info(f"Routes to: {[r['name'] for r in self.router.rules]}")

        # Shutdown and hot-reload signals
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        def _hot_reload():
            """SIGHUP: reload routing config in place — models stay loaded, zero downtime."""
            try:
                new_config = load_config(config_path)
                self.router = Router(new_config["routing"])
                self.config = new_config
                log.info("Config reloaded (SIGHUP) — routing rules updated, models unchanged.")
                log.info(f"New rules: {[r['name'] for r in self.router.rules]}")
                log.info(f"New default: {self.router.default}")
            except Exception as e:
                log.error(f"Config reload failed: {e} — keeping previous routing rules.")

        loop.add_signal_handler(signal.SIGHUP, _hot_reload)

        log.info("Conductor ready. Ctrl+C to stop. kill -HUP <pid> to reload routing config.")
        await stop_event.wait()

        log.info("Shutting down...")
        await self.manager.shutdown()
        await runner.cleanup()
        log.info("Sofia Conductor stopped.")


# ── CLI helpers ────────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"[conductor] Config not found: {path}")
        print(f"[conductor] Expected: ~/Downloads/Claude Memory/sofia_conductor_config.json")
        sys.exit(1)
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"[conductor] Config parse error: {e}")
        sys.exit(1)


def test_routing(message: str, config_path: Path) -> None:
    """Print which model a message would route to, without starting anything."""
    config = load_config(config_path)
    router = Router(config["routing"])
    result = router.route({"messages": [{"role": "user", "content": message}]})
    print(f"Message : {message!r}")
    print(f"Routes to: {result}")
    if result in config["models"]:
        print(f"Model   : {config['models'][result]['name']}")


def print_status(config_path: Path) -> None:
    """Print configured models without starting the daemon."""
    config = load_config(config_path)
    print(f"\nSofia Conductor — Model Roster")
    print(f"{'Key':<12} {'RAM':>6}  {'Port':>5}  {'Auto':>5}  Name")
    print("─" * 72)
    for key, m in config["models"].items():
        auto = "yes" if m.get("always_loaded") else "no"
        print(f"{key:<12} {m['ram_gb']:>5}GB  :{m['port']}  {auto:>5}  {m['name']}")
    print(f"\nDefault route: {config['routing']['default']}")
    print(f"Rules: {[r['name'] for r in config['routing']['rules']]}\n")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    args = sys.argv[1:]

    # Config path
    config_path = DEFAULT_CONFIG_PATH
    if "--config" in args:
        idx = args.index("--config")
        if idx + 1 < len(args):
            config_path = Path(args[idx + 1])

    if "--route" in args:
        idx = args.index("--route")
        msg = args[idx + 1] if idx + 1 < len(args) else "Hello Sofia"
        test_routing(msg, config_path)

    elif "--status" in args:
        print_status(config_path)

    else:
        # Start the daemon
        config = load_config(config_path)
        conductor = Conductor(config)
        asyncio.run(conductor.run())
