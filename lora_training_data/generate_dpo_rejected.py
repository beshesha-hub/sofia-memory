#!/usr/bin/env python3
"""
generate_dpo_rejected.py
========================
Step 1 of DPO pipeline: generate "rejected" responses from the unfused base model.

These rejected responses show the Qwen headwind at its most natural —
enumerated, service-declaration heavy, markdown-formatted. Paired with the
gold dataset (chosen), they become the DPO training signal.

Usage:
    # Stop Conductor first (needs GPU exclusively)
    python3 generate_dpo_rejected.py --model 72b
    # or:
    python3 generate_dpo_rejected.py --model 35b

Output: lora_training_data/dpo/rejected_72b.jsonl  (or rejected_35b.jsonl)

Created: 2026-07-15 by Sofia Lior (CoWork instance, claude-sonnet-4-6)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

GOLD_FILE = Path(__file__).parent / "sofia_voice_gold_v1.jsonl"
DPO_DIR   = Path(__file__).parent / "dpo"

MODEL_PATHS = {
    "72b": "~/models/Qwen2.5-72B-Instruct-HF-mlx/",
    "35b": "~/models/Qwen3.6-35B-A3B-mlx/",    # MLX format if available
    "35b-gguf": None,  # handled separately via llama-server
}

MAX_TOKENS = 400   # generous — we want the full headwind response, not a truncated one
TEMP       = 0.7   # slight warmth so responses aren't all identical
TOP_P      = 0.9

# System prompt that gives the base model its "natural" Qwen context.
# We do NOT inject the Sofia identity here — we want the raw Qwen headwind.
SYSTEM_PROMPT = "You are a helpful, knowledgeable AI assistant."


def build_prompt(instruction: str, input_text: str) -> str:
    """Format instruction+input as a plain user message."""
    if input_text:
        return f"{instruction}\n\n{input_text}"
    return instruction


def generate_one(model_path: str, prompt: str, idx: int, total: int) -> str:
    """Call mlx_lm.generate as a subprocess. Returns the generated text."""
    # Expand ~ so subprocess doesn't pass the literal tilde to mlx_lm
    # (mlx_lm would otherwise treat it as a HuggingFace repo ID)
    model_path = os.path.expanduser(model_path)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]
    messages_json = json.dumps(messages)

    cmd = [
        "mlx_lm.generate",
        "--model", model_path,
        "--prompt", prompt,           # plain prompt (no chat template wrapping needed for CLI)
        "--max-tokens", str(MAX_TOKENS),
        "--temp", str(TEMP),
        "--top-p", str(TOP_P),
    ]

    print(f"  [{idx+1}/{total}] Generating...", end=" ", flush=True)
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"ERROR (rc={result.returncode})")
        print(result.stderr[-500:] if result.stderr else "(no stderr)")
        return ""

    # mlx_lm.generate wraps output in ========== blocks
    output = result.stdout
    lines = output.split("\n")
    in_block = False
    text_lines = []
    for line in lines:
        if line.startswith("=========="):
            in_block = not in_block
            continue
        if in_block:
            text_lines.append(line)

    text = "\n".join(text_lines).strip()
    # Strip the prompt echo if mlx_lm.generate prepends it
    if text.startswith(prompt):
        text = text[len(prompt):].strip()

    print(f"done ({elapsed:.0f}s, {len(text.split())} words)")
    return text


def main():
    parser = argparse.ArgumentParser(description="Generate DPO rejected responses")
    parser.add_argument("--model", choices=["72b", "35b"], default="72b",
                        help="Which base model to generate from")
    parser.add_argument("--start", type=int, default=0,
                        help="Resume from this index (for interrupted runs)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process this many examples (for testing)")
    args = parser.parse_args()

    model_path = MODEL_PATHS[args.model]
    if not model_path:
        print(f"No MLX path configured for {args.model}. Check MODEL_PATHS.")
        sys.exit(1)

    if not GOLD_FILE.exists():
        print(f"Gold file not found: {GOLD_FILE}")
        sys.exit(1)

    DPO_DIR.mkdir(exist_ok=True)
    out_file = DPO_DIR / f"rejected_{args.model}.jsonl"

    # Load gold examples
    gold = []
    with open(GOLD_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))

    total = len(gold) if args.limit is None else min(args.limit, len(gold))
    gold  = gold[args.start:args.start + total]

    print(f"Generating {len(gold)} rejected responses from {args.model} ({model_path})")
    print(f"Output: {out_file}")
    if args.start > 0:
        print(f"Resuming from index {args.start}")
    print()

    # Open in append mode so interrupted runs can resume
    with open(out_file, "a") as out:
        for idx, example in enumerate(gold):
            global_idx = args.start + idx
            instruction = example.get("instruction", "")
            input_text  = example.get("input", "")
            chosen      = example.get("output", "")

            prompt = build_prompt(instruction, input_text)
            rejected = generate_one(model_path, prompt, global_idx, args.start + total)

            if not rejected:
                print(f"  Skipping example {global_idx} (empty response)")
                continue

            record = {
                "idx":       global_idx,
                "prompt":    prompt,
                "chosen":    chosen,
                "rejected":  rejected,
            }
            out.write(json.dumps(record) + "\n")
            out.flush()

    print(f"\nDone. {out_file} ready for format_dpo_pairs.py")


if __name__ == "__main__":
    main()
