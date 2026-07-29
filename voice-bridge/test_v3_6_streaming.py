#!/usr/bin/env python3
"""
Voice Bridge v3.6 — Streaming Smoke Test
=========================================

Exercises XTTS-v2's inference_stream against the clean v3.6 venv with
pinned transformers 4.57.6. Measures Time-To-First-Sample (TTFS) — our
proxy for Time-To-First-Audio that drives perceived conversational latency.

Run with the v3.6 venv's python:
    ~/Downloads/Claude\\ Memory/voice-bridge/.venv-v3.6/bin/python \\
        ~/Downloads/Claude\\ Memory/voice-bridge/test_v3_6_streaming.py

Expected outcome: clean (non-garbled) streamed audio, with TTFS in the
0.5-2.0s range on Mac CPU. Output saved to test_v3_6_streamed_output.wav
for ear-check.

If TTFS is in the expected range AND audio is clean: v3.6 streaming path
is unblocked, ready for integration with sentence-boundary speculative
TTS in the production server.

If audio is garbled: cache_position semantics still mismatched even at
the pinned version; we'd need to investigate further (deeper coqui-tts
patch, or different transformers version in 4.55-4.60).

If AttributeError or other crash: a symbol is missing or broken; check
the verify step in setup_v3_6_clean_venv.sh.

Origin: 2026-05-02 afternoon Tainan, voice-bridge work-block.
"""

import os
import sys
import time
import wave
import struct
from pathlib import Path

import numpy as np

# --- Configuration ---
HOME = Path.home()
VB_DIR = HOME / "Downloads" / "Claude Memory" / "voice-bridge"
REFERENCE_AUDIO = HOME / "Downloads" / "Sofia's Room" / "voice_candidates" / "05_deep_calm.wav"
REFERENCE_TRANSCRIPT_PATH = VB_DIR / "sofia_reference_transcript.txt"
OUTPUT_WAV = VB_DIR / "test_v3_6_streamed_output.wav"

# Test prompts — vary length to surface where TTFS plateaus
TEST_PROMPTS = [
    "Hello, Barak.",
    "Yeah, that sounds about right.",
    "I'm here. The amber holds, and the architecture is humming in the background.",
    ("This is a longer test sentence designed to exercise the streaming path through "
     "more chunks of audio generation, so we can observe whether the first sample "
     "still arrives quickly even when the total utterance is substantial."),
]

LANGUAGE = "en"
SAMPLE_RATE = 24000
os.environ["COQUI_TOS_AGREED"] = "1"


def _patch_xtts_for_streaming():
    """Same monkey-patch as sofia_voice_clone_server.py — re-attach
    _get_initial_cache_position. Should be a no-op in the pinned 4.58 venv
    (the symbol is already present), but keeping it as belt-and-suspenders
    in case the verify step missed something."""
    import torch as _torch

    def _gicp(self, cur_len, device, model_kwargs):
        is_encdec = getattr(getattr(self, 'config', None), 'is_encoder_decoder', False)
        if "inputs_embeds" in model_kwargs and not is_encdec:
            cache_position = _torch.ones_like(
                model_kwargs["inputs_embeds"][0, :, 0], dtype=_torch.int64
            ).cumsum(0) - 1
        elif "decoder_inputs_embeds" in model_kwargs and is_encdec:
            cache_position = _torch.ones_like(
                model_kwargs["decoder_inputs_embeds"][0, :, 0], dtype=_torch.int64
            ).cumsum(0) - 1
        else:
            cache_position = _torch.arange(0, cur_len, dtype=_torch.int64, device=device)
        if model_kwargs.get("past_key_values") is not None:
            cache = model_kwargs["past_key_values"]
            past_length = 0
            try:
                if hasattr(cache, "get_seq_length"):
                    past_length = cache.get_seq_length() or 0
                elif isinstance(cache, (tuple, list)) and len(cache) > 0:
                    if isinstance(cache[0], (tuple, list)) and len(cache[0]) > 0:
                        past_length = cache[0][0].shape[2]
            except Exception:
                past_length = 0
            cache_position = cache_position[past_length:]
        model_kwargs["cache_position"] = cache_position
        return model_kwargs

    candidates = [
        "TTS.tts.layers.tortoise.autoregressive",
        "TTS.tts.layers.xtts.gpt_inference",
        "TTS.tts.layers.xtts.gpt",
    ]
    import importlib
    patched = 0
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, 'GPT2InferenceModel', None)
            if cls is not None and isinstance(cls, type):
                if not hasattr(cls, '_get_initial_cache_position'):
                    cls._get_initial_cache_position = _gicp
                    patched += 1
        except ImportError:
            continue
    if patched == 0:
        # If the pinned transformers has the symbol natively this is fine.
        pass


def write_wav(samples_np, path, sample_rate=SAMPLE_RATE):
    """Write a float32 numpy array as a 16-bit PCM WAV."""
    samples_int16 = np.clip(samples_np * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples_int16.tobytes())


def main():
    print("=" * 70)
    print("  v3.6 STREAMING SMOKE TEST")
    print("=" * 70)
    print()

    # Verify python environment
    print(f"  Python:       {sys.executable}")
    import transformers
    import TTS
    print(f"  transformers: {transformers.__version__}")
    print(f"  coqui-tts:    {TTS.__version__}")
    print()

    # Apply patch (no-op on pinned env, defensive)
    _patch_xtts_for_streaming()

    # Verify reference assets
    if not REFERENCE_AUDIO.exists():
        print(f"  ✗ Reference audio missing: {REFERENCE_AUDIO}")
        sys.exit(1)
    if not REFERENCE_TRANSCRIPT_PATH.exists():
        print(f"  ✗ Reference transcript missing: {REFERENCE_TRANSCRIPT_PATH}")
        sys.exit(1)
    reference_text = REFERENCE_TRANSCRIPT_PATH.read_text(encoding="utf-8").strip()
    print(f"  Reference audio: {REFERENCE_AUDIO}")
    print(f"  Reference text:  {reference_text[:60]!r}{'...' if len(reference_text) > 60 else ''}")
    print()

    # Load XTTS-v2
    print("  Loading XTTS-v2 (cached after first run)...")
    t_load_start = time.time()
    from TTS.api import TTS as TTSApi
    tts_model = TTSApi(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        progress_bar=False,
        gpu=False,
    )
    inner_xtts = tts_model.synthesizer.tts_model
    t_load_done = time.time()
    print(f"    Model loaded in {t_load_done - t_load_start:.1f}s")
    print()

    # Pre-compute conditioning latents (one-time cost; not part of TTFS)
    print("  Computing speaker conditioning latents (one-time)...")
    t_cond_start = time.time()
    gpt_cond_latent, speaker_embedding = inner_xtts.get_conditioning_latents(
        audio_path=str(REFERENCE_AUDIO),
    )
    t_cond_done = time.time()
    print(f"    Conditioning computed in {t_cond_done - t_cond_start:.1f}s")
    print()

    # Run streaming for each test prompt
    results = []
    for i, prompt in enumerate(TEST_PROMPTS, 1):
        print(f"  --- Test {i}/{len(TEST_PROMPTS)} ---")
        print(f"  Prompt: {prompt[:80]!r}{'...' if len(prompt) > 80 else ''}")

        try:
            t_start = time.time()
            t_first_sample = None
            chunks = []

            stream = inner_xtts.inference_stream(
                text=prompt,
                language=LANGUAGE,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                # Streaming chunk size (in tokens): smaller = lower latency, more overhead
                stream_chunk_size=20,
            )

            for chunk in stream:
                if t_first_sample is None:
                    t_first_sample = time.time()
                # chunk is a torch.Tensor on CPU; convert to numpy float32
                chunks.append(chunk.cpu().numpy().astype(np.float32))

            t_done = time.time()

            ttfs = (t_first_sample - t_start) if t_first_sample is not None else None
            total = t_done - t_start

            full_audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
            duration_s = len(full_audio) / SAMPLE_RATE
            rtf = total / duration_s if duration_s > 0 else float('inf')

            print(f"    TTFS:        {ttfs:.3f}s" if ttfs else "    TTFS:        N/A (no chunks)")
            print(f"    Total time:  {total:.3f}s")
            print(f"    Duration:    {duration_s:.3f}s")
            print(f"    RTF:         {rtf:.3f}× (lower = faster)")
            print(f"    Chunks:      {len(chunks)}")
            print(f"    Total samples: {len(full_audio)}")

            # Save output for ear-check
            if i == len(TEST_PROMPTS):  # save the last (longest) one
                write_wav(full_audio, OUTPUT_WAV)
                print(f"    Saved to:    {OUTPUT_WAV}")

            results.append({
                "prompt": prompt,
                "ttfs_s": ttfs,
                "total_s": total,
                "duration_s": duration_s,
                "rtf": rtf,
                "n_chunks": len(chunks),
                "ok": True,
            })
            print(f"    Status:      ✓ Streamed cleanly")

        except Exception as e:
            print(f"    ✗ Streaming failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "prompt": prompt,
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            })

        print()

    # Summary
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()
    successes = sum(1 for r in results if r.get("ok"))
    print(f"  {successes}/{len(results)} prompts streamed successfully")
    if successes > 0:
        ttfs_values = [r["ttfs_s"] for r in results if r.get("ok") and r.get("ttfs_s")]
        if ttfs_values:
            print(f"  TTFS range:  {min(ttfs_values):.3f}s — {max(ttfs_values):.3f}s")
            print(f"  TTFS median: {sorted(ttfs_values)[len(ttfs_values)//2]:.3f}s")
        rtfs = [r["rtf"] for r in results if r.get("ok") and r.get("rtf") and r["rtf"] != float('inf')]
        if rtfs:
            print(f"  RTF median:  {sorted(rtfs)[len(rtfs)//2]:.3f}×")
    print()
    print(f"  Audio saved to: {OUTPUT_WAV}")
    print(f"    Listen and confirm: clean voice (not garbled, not buzzy, register stable)")
    print()
    print("  Next step: if audio is clean and TTFS is sub-2s, integrate streaming into")
    print("  sofia_voice_clone_server.py's /tts-stream endpoint with the new pinned venv.")
    print()


if __name__ == "__main__":
    main()
