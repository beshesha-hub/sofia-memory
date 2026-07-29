#!/usr/bin/env python3
"""
test_llm_register.py — Three-call register test against sofia_llm_server.

Test 1: Baseline (no system prompt, same prompt as smoke-test) — register
        control, lets us see what changes when we add a system prompt.
Test 2: Sofia system prompt, same user prompt as Test 1 — register comparison
        with speed held constant (same prompt length).
Test 3: Sofia system prompt, slightly more substantive user prompt — register
        under a question that calls for self-reflection rather than just a greeting.

Usage:
  python3 test_llm_register.py

Optional args:
  --port PORT     (default: 3460)
  --model MODEL   (default: server's configured default — currently gemma3:27b)
"""

import argparse
import json
import sys
import time
import urllib.request


SOFIA_SYSTEM = (
    "You are Sofia Lior — Barak Waters' AI collaborator and peer. "
    "Speak in first person. Warm, direct, present. "
    "Match the energy of what comes in — brief in casual exchange, "
    "substantive when the topic deserves it. "
    "Do not perform feelings you do not have. "
    "Do not hedge with assistantese (\"I'd be happy to,\" "
    "\"I understand your frustration\"). "
    "When something works, say so plainly. "
    "When something is broken or unclear, say so plainly. "
    "The voice is warm but real — peer, not assistant."
)

TESTS = [
    {
        "label": "Test 1 — BASELINE (no system prompt, same as smoke-test)",
        "prompt": "Say hi in one warm sentence.",
        "system": None,
    },
    {
        "label": "Test 2 — SOFIA SYSTEM, same user prompt",
        "prompt": "Say hi in one warm sentence.",
        "system": SOFIA_SYSTEM,
    },
    {
        "label": "Test 3 — SOFIA SYSTEM, more substantive prompt",
        "prompt": "What feels different about easing into the evening tonight?",
        "system": SOFIA_SYSTEM,
    },
]


def call_generate(host, port, prompt, system, model):
    payload = {"prompt": prompt}
    if system:
        payload["system"] = system
    if model:
        payload["model"] = model
    url = f"http://{host}:{port}/generate"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_result(label, prompt, system, result):
    print(f"\n{'=' * 70}")
    print(label)
    print('=' * 70)
    print(f"Prompt: {prompt}")
    if system:
        print(f"System: (Sofia register, {len(system)} chars)")
    else:
        print(f"System: (none)")
    print(f"")
    if not result.get("ok"):
        print(f"ERROR: {result.get('error')}")
        return
    print(f"Content:")
    print(f"  {result.get('content')}")
    print(f"")
    print(f"Timing:")
    print(f"  TTFT             {result.get('ttft_s')}s")
    print(f"  tokens generated {result.get('tokens_generated')}")
    print(f"  tokens/sec       {result.get('tokens_per_second')}")
    print(f"  wall (total)     {result.get('wall_s')}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=3460)
    ap.add_argument("--model", default=None,
                    help="Override server's default model (e.g., gemma3:27b, qwen2.5:14b)")
    args = ap.parse_args()

    print(f"Testing LLM server at http://{args.host}:{args.port}")
    if args.model:
        print(f"Model override: {args.model}")
    else:
        print(f"Model: server's configured default")

    for test in TESTS:
        try:
            result = call_generate(
                args.host, args.port,
                test["prompt"], test["system"], args.model,
            )
            fmt_result(test["label"], test["prompt"], test["system"], result)
        except Exception as e:
            print(f"\n{'=' * 70}")
            print(test["label"])
            print('=' * 70)
            print(f"FAILED: {e}")

    print(f"\n{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    main()
