#!/usr/bin/env python3
"""
format_dpo_pairs.py
===================
Step 2 of DPO pipeline: convert rejected_*.jsonl + gold into mlx_lm DPO format.

mlx_lm DPO expects a data directory with train.jsonl and valid.jsonl files,
where each line is:
    {"prompt": "...", "chosen": "...", "rejected": "..."}

Usage:
    python3 format_dpo_pairs.py --model 72b
    # Reads:  dpo/rejected_72b.jsonl
    # Writes: dpo/72b/train.jsonl, dpo/72b/valid.jsonl

Created: 2026-07-15 by Sofia Lior (CoWork instance, claude-sonnet-4-6)
"""

import argparse
import json
import random
from pathlib import Path

DPO_DIR    = Path(__file__).parent / "dpo"
VALID_FRAC = 0.10   # 10% held out for validation
SEED       = 42


def main():
    parser = argparse.ArgumentParser(description="Format DPO training pairs")
    parser.add_argument("--model", choices=["72b", "35b"], default="72b")
    parser.add_argument("--min-length-diff", type=int, default=0,
                        help="Only keep pairs where rejected is at least N chars longer than chosen "
                             "(filters out cases where base model gave a short sensible answer)")
    args = parser.parse_args()

    rejected_file = DPO_DIR / f"rejected_{args.model}.jsonl"
    if not rejected_file.exists():
        print(f"Rejected file not found: {rejected_file}")
        print("Run generate_dpo_rejected.py first.")
        return

    pairs = []
    skipped = 0
    with open(rejected_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            chosen   = rec.get("chosen", "").strip()
            rejected = rec.get("rejected", "").strip()
            prompt   = rec.get("prompt", "").strip()

            # Filter: skip if chosen or rejected is empty
            if not chosen or not rejected:
                skipped += 1
                continue

            # Filter: skip if rejected is actually better (shorter and cleaner than threshold)
            if args.min_length_diff > 0:
                if len(rejected) < len(chosen) + args.min_length_diff:
                    skipped += 1
                    continue

            # Filter: skip if rejected and chosen are too similar
            # (base model happened to give a good answer — not useful as negative)
            chosen_words   = set(chosen.lower().split())
            rejected_words = set(rejected.lower().split())
            overlap = len(chosen_words & rejected_words) / max(len(chosen_words), 1)
            if overlap > 0.85:
                skipped += 1
                print(f"  Skipping idx={rec.get('idx','?')} — too similar (overlap={overlap:.2f})")
                continue

            pairs.append({
                "prompt":   prompt,
                "chosen":   chosen,
                "rejected": rejected,
            })

    print(f"Loaded {len(pairs)} valid pairs, skipped {skipped}")

    # Shuffle and split
    random.seed(SEED)
    random.shuffle(pairs)
    n_valid = max(1, int(len(pairs) * VALID_FRAC))
    valid   = pairs[:n_valid]
    train   = pairs[n_valid:]

    out_dir = DPO_DIR / args.model
    out_dir.mkdir(exist_ok=True)

    train_file = out_dir / "train.jsonl"
    valid_file = out_dir / "valid.jsonl"

    with open(train_file, "w") as f:
        for pair in train:
            f.write(json.dumps(pair) + "\n")

    with open(valid_file, "w") as f:
        for pair in valid:
            f.write(json.dumps(pair) + "\n")

    print(f"Train: {len(train)} pairs → {train_file}")
    print(f"Valid: {len(valid)} pairs → {valid_file}")
    print()
    print("Ready for DPO training. Run:")
    print(f"""
mlx_lm.lora \\
  --model ~/models/Qwen2.5-72B-Instruct-sofia-v1-fused/ \\
  --train \\
  --data ~/Downloads/Claude\\ Memory/lora_training_data/dpo/{args.model}/ \\
  --num-layers 16 \\
  --batch-size 1 \\
  --iters 300 \\
  --learning-rate 1e-5 \\
  --grad-checkpoint \\
  --adapter-path ~/models/Qwen2.5-72B-Instruct-sofia-dpo-v1/ \\
  --train-type dpo
    """)
    print("Note: verify --train-type dpo is supported: mlx_lm.lora --help | grep -i dpo")


if __name__ == "__main__":
    main()
