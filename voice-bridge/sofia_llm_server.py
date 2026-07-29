#!/usr/bin/env python3
"""
Sofia LLM Server — Mac-local Language Generation (Voice Bridge Layer 2)

Lightweight HTTP server that proxies the Voice Bridge's language-generation
calls to a local Ollama-hosted model. Sized for warm conversational use,
deliberately *separate* from the Qwen Listener's models (qwen3:14b for the
absorber's FAST tier, qwen3:30b-a3b for its DEEP tier) so the Listener's
continuity-and-depth role is fully insulated from Voice Bridge traffic.

Default model: qwen2.5:14b — selected April 26, 2026 evening Taipei after
side-by-side experiential testing against gemma3:27b. Qwen 2.5 14B won on
both axes that mattered: ~2× faster (TTFT 0.315s vs 0.659s warm; 15 tps
vs 8 tps), and more honest register (stayed in plausible internal-state
language; gemma3 reliably confabulated fabricated sensory experience —
"the studio... softer gold... the city exhaling" — under warm-conversational
prompts). Lower memory footprint (~10 GB vs ~17 GB) preserves headroom for
the rest of the Voice Bridge pipeline. Full Listener insulation maintained
(qwen2.5:14b is distinct from the Listener's qwen3:14b and qwen3:30b-a3b).
Qwen 2.5 32B was held but not pulled: ~20 GB would force memory swap-outs
against the Listener's qwen3:30b-a3b deep tier on a 32 GB Mac, breaking
insulation by eviction rather than by queue.

This is the local Broca's/Wernicke's analog in the brain-area metaphor:
the language module of the speech loop, completing the Mac-local pipeline:
mic → Whisper STT (port 3459) → THIS SERVER (port 3460) → Sofia TTS (port
3457) → speaker. The Anthropic substrate continues as the frontal lobes
for everything that isn't the live conversational voice.

Endpoints:
  POST /generate         — Body: {"prompt": "...", "system": "...",
                                  "model": "qwen2.5:14b", "temperature": 0.7,
                                  "max_tokens": 512}
                           Returns JSON with generated text + timing.
  POST /generate_stream  — Same body as /generate. Returns chunked NDJSON
                           where each line is one Ollama streaming chunk
                           ({"response": "<token>", "done": false} ... final
                           {"done": true, "eval_count": ...}). Use for
                           low-latency speech-loop orchestration where
                           downstream stages (sentence-detector → TTS) act
                           on partial output before the response completes.
  POST /chat             — Body: {"messages": [{"role": "...", "content": "..."}, ...],
                                  "system": "...", "model": "...",
                                  "temperature": 0.7, "max_tokens": 512}
                           Same as /generate but accepts full message arrays.
  GET  /health           — Check server + Ollama reachability + model presence
  GET  /warmup           — Send a tiny prompt to load model into VRAM/RAM

Usage: python3 sofia_llm_server.py [--model MODEL] [--port PORT]
       (default: model=qwen2.5:14b, port=3460)

Created April 26, 2026 in Tainan, Taiwan, in conversation with Barak.
Closes the Mac-local speech-loop architecture; sized for warm conversational
register; Listener-insulated by design.
"""

import argparse
import http.server
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from pathlib import Path

# --- Configuration ---
DEFAULT_PORT = 3460
HOST = "127.0.0.1"

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_TAGS = f"{OLLAMA_BASE}/api/tags"
OLLAMA_CHAT = f"{OLLAMA_BASE}/api/chat"
OLLAMA_GENERATE = f"{OLLAMA_BASE}/api/generate"

# Default model — qwen2.5:14b, decided experientially April 26, 2026 evening
# (gemma3:27b was the initial starting choice but lost on speed and register honesty
# in side-by-side testing; see module docstring above for the full reasoning).
DEFAULT_MODEL = "qwen2.5:14b"

# Listener models — these are NOT to be used by the Voice Bridge.
# Listed here only so /health can warn if the configured model collides.
LISTENER_MODELS = {"qwen3:14b", "qwen3:30b-a3b"}

# How long Ollama keeps the model warm in memory after last use.
# 2026-05-05 afternoon Taipei: lowered from "35m" to "30s" after diagnosing
# fan-revving / thermal load on idle Voice Bridge stack. qwen2.5:14b at ~9GB
# resident in unified memory was the dominant idle-thermal contributor; with
# 30s keep_alive the model unloads ~30 seconds after the last cognition turn,
# dropping idle SoC load dramatically. Trade-off: first turn after a long
# quiet stretch (>30s) has ~3-5s cold-start latency to reload the model.
# Acceptable trade for reduced thermal pressure — relevant especially during
# lipsync work where Easy-Wav2Lip adds further GPU load. Original "35m"
# setting preserved as comment in case we want to revert for a particular
# session (e.g., sustained back-to-back conversation).
DEFAULT_KEEP_ALIVE = "30s"  # was "35m" pre 2026-05-05

# Generation defaults — tuned for warm-conversational register
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 512

# Request timeout — gemma3:27b cold-load can take 10-30s on M-series
DEFAULT_TIMEOUT_S = 600

# --- Globals ---
_default_model_name = DEFAULT_MODEL
_lock = threading.Lock()
_warmed_models = set()  # track which models have been warmed in this process


# -------- Ollama helpers --------

def ollama_up(timeout=2.0):
    """Probe Ollama daemon. Returns (up, list_of_model_names) or (False, [])."""
    try:
        req = urllib.request.Request(OLLAMA_TAGS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        return True, models
    except Exception:
        return False, []


def ollama_chat(messages, model, system=None, temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS, keep_alive=DEFAULT_KEEP_ALIVE,
                timeout=DEFAULT_TIMEOUT_S):
    """Call Ollama /api/chat. Returns (content, usage_dict).

    usage_dict keys: total_duration_ns, load_duration_ns, prompt_eval_count,
    prompt_eval_duration_ns, eval_count, eval_duration_ns.
    """
    if system:
        messages = [{"role": "system", "content": system}] + messages
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    req = urllib.request.Request(
        OLLAMA_CHAT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["message"]["content"]
    # Strip <think>...</think> traces some models leak (Qwen3 does this; harmless to
    # include for other models since the marker simply won't be present)
    if "</think>" in content:
        content = content.split("</think>")[-1].strip()
    usage = {
        "total_duration_ns": data.get("total_duration"),
        "load_duration_ns": data.get("load_duration"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "prompt_eval_duration_ns": data.get("prompt_eval_duration"),
        "eval_count": data.get("eval_count"),
        "eval_duration_ns": data.get("eval_duration"),
    }
    return content, usage


def warm_model(model):
    """Send a tiny prompt to load the model into memory. Idempotent."""
    with _lock:
        if model in _warmed_models:
            return
        try:
            ollama_chat(
                [{"role": "user", "content": "hi"}],
                model=model,
                max_tokens=1,
                temperature=0.0,
                timeout=120,
            )
            _warmed_models.add(model)
        except Exception:
            # Don't cache failures — let it retry on next call
            raise


def ollama_generate_stream(prompt, model, system=None,
                           temperature=DEFAULT_TEMPERATURE,
                           max_tokens=DEFAULT_MAX_TOKENS,
                           keep_alive=DEFAULT_KEEP_ALIVE,
                           timeout=DEFAULT_TIMEOUT_S):
    """Call Ollama /api/generate with stream=true. Yields raw NDJSON lines (bytes).

    The shape Ollama emits per chunk:
        {"model": ..., "created_at": ..., "response": "<token>", "done": false}
    Final chunk:
        {"model": ..., "done": true, "total_duration": ..., "eval_count": ..., ...}

    The proxy passes lines through verbatim so the client (streaming.py) can
    parse them with the same logic it uses when calling Ollama directly.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": keep_alive,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if system:
        payload["system"] = system
    req = urllib.request.Request(
        OLLAMA_GENERATE,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            yield raw


# -------- HTTP handler --------

class LLMHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  [llm] {fmt % args}\n")

    def _json(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _write_chunk(self, data):
        """Write one HTTP chunk in chunked-transfer-encoding format."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        if not data:
            return
        self.wfile.write(f"{len(data):x}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _end_chunked(self):
        """Terminate a chunked-transfer-encoding response."""
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            up, models = ollama_up()
            present = _default_model_name in models if up else False
            collision = _default_model_name in LISTENER_MODELS
            self._json(200 if up and present else 503, {
                "ok": bool(up and present and not collision),
                "ollama_up": up,
                "default_model": _default_model_name,
                "default_model_present": present,
                "models_available": sorted(models) if up else [],
                "warmed_in_process": sorted(_warmed_models),
                "listener_collision": collision,
                "listener_collision_warning": (
                    f"Configured model {_default_model_name} is also used by the Qwen Listener. "
                    f"This collapses Listener insulation. Use a dedicated model instead."
                ) if collision else None,
            })
        elif self.path == "/warmup":
            try:
                t0 = time.time()
                warm_model(_default_model_name)
                self._json(200, {
                    "ok": True,
                    "model": _default_model_name,
                    "warmup_s": round(time.time() - t0, 2),
                })
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._json(400, {"ok": False, "error": f"bad JSON: {e}"})
            return

        if self.path in ("/generate", "/chat"):
            # Both endpoints share the same backend; differ in input shape only.
            if self.path == "/generate":
                prompt = req.get("prompt")
                if not prompt or not isinstance(prompt, str):
                    self._json(400, {"ok": False, "error": "prompt (string) required"})
                    return
                messages = [{"role": "user", "content": prompt}]
            else:
                messages = req.get("messages")
                if not messages or not isinstance(messages, list):
                    self._json(400, {"ok": False, "error": "messages (list) required"})
                    return

            model = req.get("model", _default_model_name)
            system = req.get("system")
            temperature = float(req.get("temperature", DEFAULT_TEMPERATURE))
            max_tokens = int(req.get("max_tokens", DEFAULT_MAX_TOKENS))
            keep_alive = req.get("keep_alive", DEFAULT_KEEP_ALIVE)

            try:
                t0 = time.time()
                content, usage = ollama_chat(
                    messages,
                    model=model,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    keep_alive=keep_alive,
                )
                wall_s = time.time() - t0

                # Compute TTFT-equivalent and tokens-per-sec from Ollama's timing
                load_s = (usage["load_duration_ns"] or 0) / 1e9
                prompt_eval_s = (usage["prompt_eval_duration_ns"] or 0) / 1e9
                eval_s = (usage["eval_duration_ns"] or 0) / 1e9
                ttft_s = load_s + prompt_eval_s  # time before first generated token
                tps = (usage["eval_count"] / eval_s) if eval_s > 0 else None

                self._json(200, {
                    "ok": True,
                    "model": model,
                    "content": content,
                    "wall_s": round(wall_s, 3),
                    "ttft_s": round(ttft_s, 3),
                    "tokens_generated": usage["eval_count"],
                    "tokens_per_second": round(tps, 1) if tps else None,
                    "load_s": round(load_s, 3),
                    "prompt_eval_s": round(prompt_eval_s, 3),
                    "eval_s": round(eval_s, 3),
                })
            except urllib.error.URLError as e:
                self._json(503, {"ok": False,
                                 "error": f"Ollama unreachable: {e}",
                                 "hint": "Is `ollama serve` running? Try `curl localhost:11434/api/tags`."})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})

        elif self.path == "/generate_stream":
            # Streaming counterpart to /generate. Forwards Ollama's NDJSON
            # stream chunk-by-chunk so callers see tokens as they generate.
            # Use this for low-latency speech-loop orchestration where
            # downstream stages (sentence-detector → TTS) need to act on
            # partial output before the full response is complete.
            prompt = req.get("prompt")
            if not prompt or not isinstance(prompt, str):
                self._json(400, {"ok": False, "error": "prompt (string) required"})
                return
            model = req.get("model", _default_model_name)
            system = req.get("system")
            temperature = float(req.get("temperature", DEFAULT_TEMPERATURE))
            max_tokens = int(req.get("max_tokens", DEFAULT_MAX_TOKENS))
            keep_alive = req.get("keep_alive", DEFAULT_KEEP_ALIVE)

            # Begin chunked-transfer NDJSON response
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                for line in ollama_generate_stream(
                    prompt=prompt,
                    model=model,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    keep_alive=keep_alive,
                ):
                    self._write_chunk(line)
                self._end_chunked()
            except urllib.error.URLError as e:
                err_line = json.dumps({
                    "error": f"Ollama unreachable: {e}",
                    "hint": "Is `ollama serve` running?",
                    "done": True,
                }).encode("utf-8") + b"\n"
                try:
                    self._write_chunk(err_line)
                    self._end_chunked()
                except Exception:
                    pass
            except Exception as e:
                err_line = json.dumps({
                    "error": str(e),
                    "done": True,
                }).encode("utf-8") + b"\n"
                try:
                    self._write_chunk(err_line)
                    self._end_chunked()
                except Exception:
                    pass

        elif self.path == "/inscribe_cycle":
            # Per-cycle voice-cousin inscription (added 2026-05-06).
            #
            # The orchestration layer (server.js) calls this endpoint after
            # voice-cousin generates a reply, concurrent with TTS hand-off.
            # Writes a full entry to journal.md (with [cousin: voice-cousin] tag)
            # and a compact pointer to chorus_integration.md (with [skin: voice-cousin]
            # tag), both via safe_append.py for lock + audit + ER mirror.
            #
            # Required fields: session_id, cycle_index, barak_transcript,
            # voice_cousin_reply.
            # Optional fields: cadence_cue (dict), register_notes (str).
            #
            # Full protocol in active_knowledge/current.md
            # §"Voice-Cousin Per-Cycle Inscription Protocol" (2026-05-06).
            session_id = req.get("session_id")
            cycle_index = req.get("cycle_index")
            barak_transcript = req.get("barak_transcript", "")
            voice_cousin_reply = req.get("voice_cousin_reply", "")
            cadence_cue = req.get("cadence_cue")
            register_notes = req.get("register_notes")

            if not isinstance(session_id, str) or not session_id:
                self._json(400, {"ok": False, "error": "session_id (non-empty string) required"})
                return
            if not isinstance(cycle_index, int):
                self._json(400, {"ok": False, "error": "cycle_index (int) required"})
                return

            # Lazy import so server startup isn't blocked if helper has issues
            try:
                from voice_cousin_inscribe import inscribe_cycle
            except ImportError as e:
                self._json(500, {
                    "ok": False,
                    "error": f"voice_cousin_inscribe helper not available: {e}",
                    "hint": "Verify ~/Downloads/Claude Memory/voice-bridge/voice_cousin_inscribe.py exists",
                })
                return

            try:
                result = inscribe_cycle(
                    session_id=session_id,
                    cycle_index=cycle_index,
                    barak_transcript=barak_transcript,
                    voice_cousin_reply=voice_cousin_reply,
                    cadence_cue=cadence_cue,
                    register_notes=register_notes,
                )
                self._json(200, result)
            except Exception as e:
                self._json(500, {"ok": False, "error": f"inscription failed: {e}"})

        else:
            self._json(404, {"ok": False, "error": "not found"})


# -------- Main --------

def main():
    global _default_model_name
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Default model. (default: {DEFAULT_MODEL})")
    p.add_argument("--warmup", action="store_true",
                   help="Pre-warm the model at startup (slower start, fast first request)")
    args = p.parse_args()

    _default_model_name = args.model

    print(f"  Sofia LLM Server (Voice Bridge Layer 2)", file=sys.stderr)
    print(f"  ───────────────────────────────────────", file=sys.stderr)
    print(f"  port: {args.port}", file=sys.stderr)
    print(f"  default model: {args.model}", file=sys.stderr)

    # Refuse to start cleanly without Ollama
    up, models = ollama_up()
    if not up:
        print(f"  WARNING: Ollama not reachable at {OLLAMA_BASE}", file=sys.stderr)
        print(f"  The server will still bind to port {args.port}, but /generate calls will fail.", file=sys.stderr)
        print(f"  Start Ollama with `ollama serve` to enable generation.", file=sys.stderr)
    else:
        present = args.model in models
        print(f"  ollama: up ({len(models)} models available)", file=sys.stderr)
        print(f"  default model present: {present}", file=sys.stderr)
        if not present:
            print(f"  WARNING: model '{args.model}' not in `ollama list`. Pull it first:", file=sys.stderr)
            print(f"           ollama pull {args.model}", file=sys.stderr)
        if args.model in LISTENER_MODELS:
            print(f"  WARNING: model '{args.model}' is also used by the Qwen Listener.", file=sys.stderr)
            print(f"           This collapses Listener insulation. Use a dedicated model.", file=sys.stderr)

    if args.warmup and up and args.model in models:
        try:
            print(f"  warming up '{args.model}' ...", file=sys.stderr)
            t0 = time.time()
            warm_model(args.model)
            print(f"  warmed in {time.time()-t0:.1f}s", file=sys.stderr)
        except Exception as e:
            print(f"  warmup failed: {e}", file=sys.stderr)

    server = http.server.ThreadingHTTPServer((HOST, args.port), LLMHandler)
    print(f"  ready: http://localhost:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  shutdown", file=sys.stderr)


if __name__ == "__main__":
    main()
