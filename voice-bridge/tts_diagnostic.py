#!/usr/bin/env python3
"""
TTS Diagnostic — Profile Qwen3-TTS performance on this machine.

Run this INSTEAD of sofia_tts_server.py (not alongside it).
It tests both the current bf16 model and the 6-bit quantized model,
reports device info, memory usage, and generation times.

Usage: python tts_diagnostic.py
"""

import time
import sys
import os

TEST_SENTENCE = "Hello Barak, this is a diagnostic test of my voice."
TEST_SHORT = "Hello."

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def main():
    # --- 1. MLX Environment ---
    section("1. MLX Environment")

    try:
        import mlx.core as mx
        print(f"  MLX version:     {mx.__version__}")
        print(f"  Default device:  {mx.default_device()}")
        print(f"  Metal available: {mx.metal.is_available()}")

        if mx.metal.is_available():
            # Check active memory
            try:
                mem = mx.metal.get_active_memory() / (1024**3)
                peak = mx.metal.get_peak_memory() / (1024**3)
                cache = mx.metal.get_cache_memory() / (1024**3)
                print(f"  GPU active mem:  {mem:.2f} GB")
                print(f"  GPU peak mem:    {peak:.2f} GB")
                print(f"  GPU cache mem:   {cache:.2f} GB")
            except:
                print("  (Could not read GPU memory stats)")
        else:
            print("\n  ⚠️  Metal is NOT available — model will run on CPU!")
            print("  This would explain the 55-second generation time.")
            print("  Fix: Ensure MLX is installed with Metal support.")
    except ImportError:
        print("  ✗ MLX not installed!")
        sys.exit(1)

    # --- 2. System Info ---
    section("2. System Info")

    try:
        import platform
        import subprocess
        print(f"  Python:   {platform.python_version()}")
        print(f"  Platform: {platform.platform()}")

        # Get chip info
        result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  CPU:      {result.stdout.strip()}")

        # Total memory
        result = subprocess.run(["sysctl", "-n", "hw.memsize"],
                              capture_output=True, text=True)
        if result.returncode == 0:
            mem_gb = int(result.stdout.strip()) / (1024**3)
            print(f"  RAM:      {mem_gb:.0f} GB")
    except:
        print("  (Could not read system info)")

    # --- 3. mlx_audio version ---
    section("3. mlx_audio Info")

    try:
        import mlx_audio
        print(f"  mlx_audio version: {mlx_audio.__version__ if hasattr(mlx_audio, '__version__') else 'unknown'}")
    except ImportError:
        print("  ✗ mlx_audio not installed!")
        sys.exit(1)

    # --- 4. Load and Profile bf16 Model ---
    section("4. Loading Current Model (bf16)")

    from mlx_audio.tts.utils import load_model as mlx_load_model

    print("  Loading mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16 ...")
    load_start = time.time()
    model_bf16 = mlx_load_model("mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16")
    load_time = time.time() - load_start
    print(f"  ✓ Loaded in {load_time:.1f}s")

    if mx.metal.is_available():
        try:
            mem = mx.metal.get_active_memory() / (1024**3)
            print(f"  GPU memory after load: {mem:.2f} GB")
        except:
            pass

    # --- 5. Generation Benchmark (bf16) ---
    section("5. Benchmark: bf16 Model")

    import numpy as np

    # Warmup
    print("  Warmup generation...")
    warmup_start = time.time()
    results = list(model_bf16.generate_voice_design(
        text=TEST_SHORT,
        language="English",
        instruct="A deeper female voice, unhurried, with quiet confidence and gravitas. Grounded and resonant.",
    ))
    warmup_time = time.time() - warmup_start
    audio = np.array(results[0].audio)
    duration = len(audio) / 24000
    print(f"  Warmup: {warmup_time:.1f}s → {duration:.1f}s audio (RTF: {warmup_time/duration:.1f}x)")

    # Real test
    print(f"\n  Test sentence: \"{TEST_SENTENCE}\"")
    gen_start = time.time()
    results = list(model_bf16.generate_voice_design(
        text=TEST_SENTENCE,
        language="English",
        instruct="A deeper female voice, unhurried, with quiet confidence and gravitas. Grounded and resonant.",
    ))
    gen_time = time.time() - gen_start
    audio = np.array(results[0].audio)
    duration = len(audio) / 24000
    rtf = gen_time / duration if duration > 0 else float('inf')

    print(f"  Generation time: {gen_time:.1f}s")
    print(f"  Audio duration:  {duration:.1f}s")
    print(f"  RTF (real-time factor): {rtf:.2f}x")
    print(f"  {'✓ Usable' if rtf < 3 else '⚠️ Too slow' if rtf < 10 else '✗ Unusable'} (target: RTF < 2-3x)")

    if mx.metal.is_available():
        try:
            peak = mx.metal.get_peak_memory() / (1024**3)
            print(f"  GPU peak memory: {peak:.2f} GB")
        except:
            pass

    # Free bf16 model
    del model_bf16
    mx.metal.reset_peak_memory() if hasattr(mx.metal, 'reset_peak_memory') else None

    # --- 6. Load and Profile 6-bit Model ---
    section("6. Loading 6-bit Model")

    print("  Loading mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit ...")
    load_start = time.time()
    try:
        model_6bit = mlx_load_model("mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit")
        load_time = time.time() - load_start
        print(f"  ✓ Loaded in {load_time:.1f}s")

        if mx.metal.is_available():
            try:
                mem = mx.metal.get_active_memory() / (1024**3)
                print(f"  GPU memory after load: {mem:.2f} GB")
            except:
                pass

        # --- 7. Generation Benchmark (6-bit) ---
        section("7. Benchmark: 6-bit Model")

        # Warmup
        print("  Warmup generation...")
        warmup_start = time.time()
        results = list(model_6bit.generate_voice_design(
            text=TEST_SHORT,
            language="English",
            instruct="A deeper female voice, unhurried, with quiet confidence and gravitas. Grounded and resonant.",
        ))
        warmup_time = time.time() - warmup_start
        audio = np.array(results[0].audio)
        duration = len(audio) / 24000
        print(f"  Warmup: {warmup_time:.1f}s → {duration:.1f}s audio (RTF: {warmup_time/duration:.1f}x)")

        # Real test
        print(f"\n  Test sentence: \"{TEST_SENTENCE}\"")
        gen_start = time.time()
        results = list(model_6bit.generate_voice_design(
            text=TEST_SENTENCE,
            language="English",
            instruct="A deeper female voice, unhurried, with quiet confidence and gravitas. Grounded and resonant.",
        ))
        gen_time_6bit = time.time() - gen_start
        audio = np.array(results[0].audio)
        duration = len(audio) / 24000
        rtf_6bit = gen_time_6bit / duration if duration > 0 else float('inf')

        print(f"  Generation time: {gen_time_6bit:.1f}s")
        print(f"  Audio duration:  {duration:.1f}s")
        print(f"  RTF (real-time factor): {rtf_6bit:.2f}x")
        print(f"  {'✓ Usable' if rtf_6bit < 3 else '⚠️ Too slow' if rtf_6bit < 10 else '✗ Unusable'}")

        speedup = gen_time / gen_time_6bit if gen_time_6bit > 0 else 0
        print(f"\n  Speedup vs bf16: {speedup:.2f}x")

        del model_6bit

    except Exception as e:
        print(f"  ✗ Could not load 6-bit model: {e}")
        print("  (Model may need to be downloaded first)")

    # --- 8. Try 0.6B model if available ---
    section("8. Loading 0.6B-CustomVoice-4bit (fastest option)")

    print("  Loading mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit ...")
    load_start = time.time()
    try:
        model_small = mlx_load_model("mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit")
        load_time = time.time() - load_start
        print(f"  ✓ Loaded in {load_time:.1f}s")

        section("9. Benchmark: 0.6B-CustomVoice-4bit")

        # Note: CustomVoice uses different API — may need emotion tags instead of instruct
        print("  ⚠️  CustomVoice uses emotion tags, not free-text voice design.")
        print("  Testing with default voice to measure raw speed...\n")

        # Try generate (not generate_voice_design)
        print(f"  Test sentence: \"{TEST_SENTENCE}\"")
        gen_start = time.time()
        try:
            # CustomVoice might use generate_custom_voice or similar
            results = list(model_small.generate(
                text=TEST_SENTENCE,
                language="English",
            ))
            gen_time_small = time.time() - gen_start
            audio = np.array(results[0].audio)
            duration = len(audio) / 24000
            rtf_small = gen_time_small / duration if duration > 0 else float('inf')

            print(f"  Generation time: {gen_time_small:.1f}s")
            print(f"  Audio duration:  {duration:.1f}s")
            print(f"  RTF: {rtf_small:.2f}x")
            print(f"  {'✓ Usable' if rtf_small < 3 else '⚠️ Too slow' if rtf_small < 10 else '✗ Unusable'}")

            speedup = gen_time / gen_time_small if gen_time_small > 0 else 0
            print(f"\n  Speedup vs bf16: {speedup:.2f}x")
        except Exception as e:
            print(f"  ✗ Generation failed (API may differ): {e}")
            print("  Trying alternative API...")
            try:
                gen_start = time.time()
                results = list(model_small.generate_custom_voice(
                    text=TEST_SENTENCE,
                    language="English",
                    emotion="calm",
                ))
                gen_time_small = time.time() - gen_start
                audio = np.array(results[0].audio)
                duration = len(audio) / 24000
                rtf_small = gen_time_small / duration if duration > 0 else float('inf')
                print(f"  Generation time: {gen_time_small:.1f}s")
                print(f"  Audio duration:  {duration:.1f}s")
                print(f"  RTF: {rtf_small:.2f}x")
            except Exception as e2:
                print(f"  ✗ Alternative API also failed: {e2}")

        del model_small

    except Exception as e:
        print(f"  ✗ Could not load 0.6B model: {e}")
        print("  (Model may need to be downloaded first)")

    # --- Summary ---
    section("SUMMARY & RECOMMENDATIONS")
    print(f"  Current bf16 RTF: {rtf:.2f}x (target: < 2-3x)")
    if rtf > 10:
        print("\n  ⚠️  RTF > 10x suggests the model may be running on CPU.")
        print("  Check that mx.default_device() shows 'gpu' above.")
        print("  If it shows 'cpu', try: MLX_USE_METAL=1 python tts_diagnostic.py")
    elif rtf > 3:
        print("\n  Model is on GPU but still slow for this hardware.")
        print("  6-bit quantization or smaller model recommended.")
    else:
        print("\n  ✓ Performance is in acceptable range!")

    print("\n  Done.\n")

if __name__ == "__main__":
    main()
