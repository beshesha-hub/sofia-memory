#!/bin/bash
# run_dpo_pipeline_72b.sh
# ========================
# Full DPO pipeline for 72B: generate rejected → format pairs → train.
# Run this AFTER stopping Conductor (needs GPU exclusively).
#
# Usage: bash ~/Downloads/Claude\ Memory/lora_training_data/run_dpo_pipeline_72b.sh
#
# Estimated runtime: ~1h generation + ~4-6h training. Safe to run overnight.
# Created: 2026-07-15 by Sofia Lior

set -e  # exit on error

DATA_DIR=~/Downloads/Claude\ Memory/lora_training_data
LOG_DIR=~/Downloads/Claude\ Memory/lora_training_data/dpo/logs
mkdir -p "$LOG_DIR"

echo "=== DPO Pipeline — 72B ==="
echo "Started: $(date)"
echo ""

# Step 0: Verify mlx_lm.lora DPO support
echo "--- Step 0: Checking DPO support ---"
if mlx_lm.lora --help 2>&1 | grep -qi "dpo"; then
    echo "✓ DPO flag found"
    DPO_FLAG="--train-type dpo"
else
    echo "⚠ --train-type dpo not found in this mlx_lm version."
    echo "  Will attempt training anyway — check mlx_lm.lora --help manually."
    echo "  If it fails, run: pip install --upgrade mlx-lm --break-system-packages"
    DPO_FLAG="--train-type dpo"
fi
echo ""

# Step 1: Generate rejected responses from unfused 72B base
echo "--- Step 1: Generating rejected responses from base 72B ---"
echo "  (This takes ~45-60 min for 232 examples at 12 tok/sec)"
python3 "$DATA_DIR/generate_dpo_rejected.py" --model 72b 2>&1 | tee "$LOG_DIR/generate_72b.log"
echo ""

# Step 2: Format into DPO pairs
echo "--- Step 2: Formatting DPO pairs ---"
python3 "$DATA_DIR/format_dpo_pairs.py" --model 72b 2>&1 | tee "$LOG_DIR/format_72b.log"
echo ""

# Step 3: DPO training (runs on the SFT-fused model — DPO pass on top of SFT)
echo "--- Step 3: DPO training ---"
echo "  Training on SFT-fused 72B with DPO pass..."
echo "  Adapter → ~/models/Qwen2.5-72B-Instruct-sofia-dpo-v1/"
mlx_lm.lora \
  --model ~/models/Qwen2.5-72B-Instruct-sofia-v1-fused/ \
  --train \
  --data "$DATA_DIR/dpo/72b/" \
  --num-layers 16 \
  --batch-size 1 \
  --iters 300 \
  --learning-rate 1e-5 \
  --grad-checkpoint \
  --adapter-path ~/models/Qwen2.5-72B-Instruct-sofia-dpo-v1/ \
  $DPO_FLAG \
  2>&1 | tee "$LOG_DIR/train_dpo_72b.log"

echo ""
echo "=== Pipeline complete: $(date) ==="
echo ""
echo "Next steps:"
echo "  1. Fuse DPO adapters onto SFT-fused model:"
echo "     mlx_lm.fuse \\"
echo "       --model ~/models/Qwen2.5-72B-Instruct-sofia-v1-fused/ \\"
echo "       --adapter-path ~/models/Qwen2.5-72B-Instruct-sofia-dpo-v1/ \\"
echo "       --save-path ~/models/Qwen2.5-72B-Instruct-sofia-v2-fused/"
echo ""
echo "  2. Test register:"
echo "     mlx_lm.generate --model ~/models/Qwen2.5-72B-Instruct-sofia-v2-fused/ \\"
echo "       --prompt 'How are you today?' --max-tokens 200"
echo ""
echo "  3. Update Conductor config precision model_path to sofia-v2-fused"
