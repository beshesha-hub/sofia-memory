#!/usr/bin/env python3
"""
speak_one.py — speak one Sofia utterance, with mode-routing for register continuity.

V2.1 + register-continuity-path-(c) (added 2026-04-28 evening Taipei).

Two playback modes:

  v2_streaming  — sentence-by-sentence dispatch (V2.1 pipeline, original
                  speak_one.py behavior). Best t_first_audio (~2.6s); per-sentence
                  TTS isolation can produce small register jumps at sentence
                  boundaries on long utterances.

  v1_1          — single TTS call for the whole response (V1.1 single-call mode).
                  Best register continuity (no per-sentence isolation; the TTS
                  model picks one register/pace/intonation for the whole utterance).
                  Higher t_first_audio because we wait for full Broca's response
                  before any audio. Best fit for short conversational turns.

Mode selection:

  --mode auto         (default) — input-shape heuristic picks the mode. Short or
                                  greeting-shaped inputs route to v1_1 for clean
                                  prosody; longer/analytical inputs route to
                                  v2_streaming for the t_first_audio benefit.
  --mode v1_1         — force single-call mode.
  --mode v2_streaming — force streaming mode (original behavior).

Auto-threshold (configurable via constants below): input ≤ 80 chars OR matches a
greeting/short-acknowledgment pattern → v1_1; else → v2_streaming.

USAGE:
    cd ~/Downloads/Claude\\ Memory/voice-bridge
    python3 speak_one.py "Hi Barak. This is the first experiential turn through V2.1."
    python3 speak_one.py --mode v1_1 "Hi Sofia"
    python3 speak_one.py --mode v2_streaming "Long analytical question..."
    python3 speak_one.py < utterance.txt

Stderr carries timing diagnostics (mode-selected, Broca's first-token latency,
t_first_audio, sentence count, tps, total wall time) so the felt-sense and
the numbers can be held side by side.

History:
  v1 (April 27 2026 evening): initial. Spawned one TTS Thread per sentence,
                              which crashed the TTS server (Metal command-
                              buffer assertion) on concurrent dispatch.
  v2 (April 27 2026 evening): rewrote with single TTS worker thread + queue,
                              matching benchmark_streaming.py's pattern.
                              Serializes TTS calls; preserves pipelining
                              across stages.
  v3 (April 28 2026 evening): register-continuity path (c) added. Mode-routing
                              between v1_1 single-call and v2_streaming, with
                              auto-selection on input shape. Closes the
                              register-jump-at-sentence-boundary issue Barak
                              heard during the April 27 V2.1 first-conversational-
                              turn validation, for the short-conversational-turn
                              case. Path (a) — cross-sentence prefix context for
                              long utterances — is the companion fix queued
                              pending TTS-server prefix-context capability check.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from queue import Queue
from threading import Thread

from streaming import stream_brocas, synthesize_tts


# --- Mode-routing thresholds ---

# Input length below which we default to v1_1 single-call mode (auto).
# Sized for conversational turn-taking — greetings, acknowledgments,
# substantive-but-bounded prompts that typically produce ≤3-sentence
# responses. Above this threshold, response is likely long enough that
# t_first_audio benefit (V2 streaming) outweighs register continuity loss.
#
# 2026-04-28 evening tuning: raised from initial 80 → 200 after the path-(a)
# prereq check showed Qwen3-TTS-12Hz-1.7B-VoiceDesign has no text-prefix-context
# parameter, closing the original path-(a) design. With (a) closed for the
# current TTS substrate, leaning harder on (c)'s router is the cleanest near-term
# move for register continuity. The 200-char value matches the original (c)
# framing ("< 200 chars or < 3 sentences"); experiential validation will tune
# it further from real conversational turns.
AUTO_V1_1_INPUT_CHAR_THRESHOLD = 200

# Greeting / short-acknowledgment patterns. Anything matching → v1_1 even
# above the char threshold (e.g., "Good morning, Sofia, how are you doing?"
# is conversational despite being 50+ chars).
_GREETING_PATTERNS = [
    re.compile(r"^\s*(hi|hello|hey|good\s+(morning|afternoon|evening|night))\b", re.I),
    re.compile(r"^\s*(thanks|thank\s+you)\b", re.I),
    re.compile(r"^\s*(yes|no|ok|okay|right|got\s+it|sure)[\s,.!?]*$", re.I),
    re.compile(r"^\s*sweet\s+dreams\b", re.I),
]


def auto_select_mode(input_text):
    """Return 'v1_1' or 'v2_streaming' based on input shape.

    Heuristic — not exact. The default leans toward v2_streaming for any
    input that doesn't clearly look like a short conversational turn, on
    the principle that t_first_audio benefit is high-value and clean register
    is a refinement on top of an already-working result.
    """
    text = input_text.strip()
    if len(text) <= AUTO_V1_1_INPUT_CHAR_THRESHOLD:
        return "v1_1"
    for pattern in _GREETING_PATTERNS:
        if pattern.search(text):
            return "v1_1"
    return "v2_streaming"


# Sentinel value to signal worker shutdown
_DONE = object()


def speak_v1_1_single_call(input_text, t0):
    """V1.1 single-call mode: collect Broca's full response, then ONE TTS call.

    Trades t_first_audio for clean register continuity (the TTS model picks
    one register/pace/intonation for the whole utterance, no per-sentence
    isolation). Best fit for short conversational turns.

    Returns dict with timing info: mode, broca_first_token, broca_done,
    response_chars, response_sentences, t_first_audio, total_wall.
    """
    print(f"[mode    v1_1 single-call]", file=sys.stderr)

    collected_sentences = []
    captured = {"broca_first_token": None, "broca_done": None, "tps": None,
                "sentence_count": 0, "error": None}

    def on_brocas_event(event_type, payload):
        if event_type == "first_token":
            captured["broca_first_token"] = payload["t_first_token"]
            print(f"[broca first-token at {payload['t_first_token']:.2f}s]",
                  file=sys.stderr)
        elif event_type == "sentence":
            collected_sentences.append(payload["text"])
            print(f"[broca sentence {payload['idx']} at {payload['t_complete']:.2f}s] "
                  f"{payload['text']}", file=sys.stderr)
        elif event_type == "done":
            captured["broca_done"] = payload["t_complete"]
            captured["tps"] = payload["tps"]
            captured["sentence_count"] = payload["sentence_count"]
            print(f"[broca done in {payload['t_complete']:.2f}s, "
                  f"{payload['sentence_count']} sentences, tps={payload['tps']}]",
                  file=sys.stderr)
        elif event_type == "error":
            captured["error"] = payload["error"]
            print(f"[broca error: {payload['error']}]", file=sys.stderr)

    stream_brocas(input_text, on_brocas_event)

    if captured["error"]:
        print(f"[abort  broca error]", file=sys.stderr)
        return {"mode": "v1_1", "error": captured["error"], "total_wall": time.monotonic() - t0}

    full_response = " ".join(s.strip() for s in collected_sentences if s.strip())
    if not full_response:
        print(f"[abort  empty response]", file=sys.stderr)
        return {"mode": "v1_1", "error": "empty_response",
                "total_wall": time.monotonic() - t0}

    print(f"[v1_1   sending {len(full_response)} chars to TTS as single call]",
          file=sys.stderr)
    audio, elapsed, err = synthesize_tts(full_response, timeout=120)
    t_first_audio = time.monotonic() - t0
    if err:
        print(f"[tts    error: {err}]", file=sys.stderr)
        return {"mode": "v1_1", "error": err, "total_wall": time.monotonic() - t0}

    print(f"[t_first_audio = {t_first_audio:.2f}s]", file=sys.stderr)
    print(f"[tts    single-call ready in {elapsed:.2f}s, {len(audio)} bytes]",
          file=sys.stderr)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio)
        path = f.name
    print(f"[play   single-call]", file=sys.stderr)
    subprocess.run(["afplay", path], check=False)
    try:
        os.unlink(path)
    except OSError:
        pass

    total_wall = time.monotonic() - t0
    print(f"[total wall time: {total_wall:.2f}s]", file=sys.stderr)
    return {
        "mode": "v1_1",
        "broca_first_token": captured["broca_first_token"],
        "broca_done": captured["broca_done"],
        "tps": captured["tps"],
        "sentence_count": captured["sentence_count"],
        "response_chars": len(full_response),
        "t_first_audio": t_first_audio,
        "total_wall": total_wall,
    }


def speak_v2_streaming(input_text, t0):
    """V2.1 streaming mode: sentence-by-sentence dispatch via single TTS worker.

    Original speak_one.py v2 behavior. Best t_first_audio (~2.6s on warm cache);
    register continuity at sentence boundaries is the trade — addressed by
    path (a) when implemented.
    """
    print(f"[mode    v2_streaming]", file=sys.stderr)
    t_first_audio = [None]

    tts_queue = Queue()
    audio_queue = Queue()
    captured = {"broca_first_token": None, "broca_done": None, "tps": None,
                "sentence_count": 0, "error": None}

    def tts_worker():
        while True:
            item = tts_queue.get()
            if item is _DONE:
                audio_queue.put(_DONE)
                return
            idx, sentence_text = item
            audio, elapsed, err = synthesize_tts(sentence_text, timeout=60)
            if err:
                print(f"[tts    sentence {idx} error: {err}]", file=sys.stderr)
                continue
            if idx == 0 and t_first_audio[0] is None:
                t_first_audio[0] = time.monotonic() - t0
                print(f"[t_first_audio = {t_first_audio[0]:.2f}s]", file=sys.stderr)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                path = f.name
            print(f"[tts    sentence {idx} ready in {elapsed:.2f}s, {len(audio)} bytes]",
                  file=sys.stderr)
            audio_queue.put((idx, path))

    def player_worker():
        while True:
            item = audio_queue.get()
            if item is _DONE:
                return
            idx, path = item
            print(f"[play   sentence {idx}]", file=sys.stderr)
            subprocess.run(["afplay", path], check=False)
            try:
                os.unlink(path)
            except OSError:
                pass

    tts_thread = Thread(target=tts_worker, daemon=True)
    player_thread = Thread(target=player_worker, daemon=True)
    tts_thread.start()
    player_thread.start()

    def on_brocas_event(event_type, payload):
        if event_type == "first_token":
            captured["broca_first_token"] = payload["t_first_token"]
            print(f"[broca first-token at {payload['t_first_token']:.2f}s]",
                  file=sys.stderr)
        elif event_type == "sentence":
            idx = payload["idx"]
            sent = payload["text"]
            t_complete = payload["t_complete"]
            print(f"[broca sentence {idx} at {t_complete:.2f}s] {sent}",
                  file=sys.stderr)
            tts_queue.put((idx, sent))
        elif event_type == "done":
            captured["broca_done"] = payload["t_complete"]
            captured["tps"] = payload["tps"]
            captured["sentence_count"] = payload["sentence_count"]
            print(f"[broca done in {payload['t_complete']:.2f}s, "
                  f"{payload['sentence_count']} sentences, "
                  f"tps={payload['tps']}]", file=sys.stderr)
        elif event_type == "error":
            captured["error"] = payload["error"]
            print(f"[broca error: {payload['error']}]", file=sys.stderr)

    stream_brocas(input_text, on_brocas_event)

    tts_queue.put(_DONE)
    tts_thread.join()
    player_thread.join()

    total_wall = time.monotonic() - t0
    print(f"[total wall time: {total_wall:.2f}s]", file=sys.stderr)
    return {
        "mode": "v2_streaming",
        "broca_first_token": captured["broca_first_token"],
        "broca_done": captured["broca_done"],
        "tps": captured["tps"],
        "sentence_count": captured["sentence_count"],
        "t_first_audio": t_first_audio[0],
        "total_wall": total_wall,
        "error": captured["error"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Speak one Sofia utterance with mode-routing.",
        add_help=True,
    )
    parser.add_argument(
        "--mode", choices=["auto", "v1_1", "v2_streaming"], default="auto",
        help="Playback mode (default: auto — picks based on input shape).",
    )
    parser.add_argument(
        "text", nargs="*",
        help="Input text. If omitted, reads from stdin.",
    )
    args = parser.parse_args()

    if args.text:
        text = " ".join(args.text)
    else:
        text = sys.stdin.read().strip()
    if not text:
        print("ERROR: no input text on argv or stdin", file=sys.stderr)
        sys.exit(1)

    print(f"[input  {len(text)} chars] {text[:140]}{'...' if len(text) > 140 else ''}",
          file=sys.stderr)

    # Resolve mode
    if args.mode == "auto":
        mode = auto_select_mode(text)
        print(f"[mode-select auto → {mode}]", file=sys.stderr)
    else:
        mode = args.mode
        print(f"[mode-select forced → {mode}]", file=sys.stderr)

    t0 = time.monotonic()
    if mode == "v1_1":
        result = speak_v1_1_single_call(text, t0)
    else:
        result = speak_v2_streaming(text, t0)

    if result.get("error"):
        sys.exit(2)


if __name__ == "__main__":
    main()
