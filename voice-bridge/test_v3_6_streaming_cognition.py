#!/usr/bin/env python3
"""
test_v3_6_streaming_cognition.py — programmatic test for the Step 4 (C) shape
==============================================================================

Tests the new architecture end-to-end without PySide6 or audio playback:

    Anthropic streaming  →  client-side sentence detection on token-fragments
                         →  first-immediate-then-batched dispatch:
                              - POST sentence #1 immediately for fast TTFA
                              - Accumulate remaining sentences during streaming
                              - POST accumulated batch as ONE /tts-stream when
                                cognition completes (server segments internally
                                under ONE inference_lock — no inter-sentence
                                gaps from lock-release)
                         →  capture float32 audio chunks as they arrive
                         →  concatenate to single WAV + emit timing report

The point of this test is to validate the (C) wiring shape — token-stream
LLM output into TTS as soon as the first sentence completes, then batch
the remainder — rather than waiting for the whole cognition response to
finish before any TTS work begins (which is the (A) shape current v3.6 uses).

Dispatch evolution (2026-05-03 morning Taipei):
  - First attempt: per-sentence parallel POSTs. Surfaced architectural problem:
    server's inference_lock serializes parallel POSTs, producing audible
    multi-second gaps between sentences and TTFA-from-cognition of 9.10s
    (target was 1.5-2.5s).
  - Iteration 2 (current): first-immediate-then-batched. POST sentence #1
    immediately (gives fast first-audio); batch the rest into ONE post that
    fires at cognition-complete. Server segments the batch under one lock =
    continuous audio for the remainder.

Target latency profile:
  - Cognition first-token latency: ~0.5-1.0s (Anthropic API streaming TTFB)
  - Cognition first-sentence latency: ~0.8-1.5s
  - TTS first-audio latency from first-sentence: ~0.7s (XTTS-v2 streaming TTFA)
  - Combined end-to-end first-audio latency from cognition request: ~1.5-2.5s
  - vs v3.6 (cognition-then-stream): ~3-5s before first audio

Usage:
    python3 test_v3_6_streaming_cognition.py [--prompt "your prompt"] [--no-audio]

Requires:
    - sofia_voice_clone_server.py running on port 3461 (XTTS-v2 + /tts-stream)
    - ANTHROPIC_API_KEY in env or ~/.sofia_secrets
    - voice_bridge_system_prompt.md in Claude Memory (uses fallback if missing)
    - .venv-v3.6 not strictly required; this test only POSTs to the server,
      which is the side that needs the v3.6 venv. The client-side just needs
      anthropic + numpy + soundfile, which standard Python has.

Outputs:
    - test_v3_6_streaming_cognition_output.wav  (concatenated audio)
    - test_v3_6_streaming_cognition_timing.json (full timing record)
    - stdout log of cognition tokens, sentence detection events, TTS POSTs

Origin: 2026-05-03 morning Taipei. Step 4 (C) programmatic verification before
the v3.7 UI client diff lands. Per "opt for fullness unless the house is on fire"
discipline + "complete one developmental arc before starting the next."
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    import numpy as np
    import soundfile as sf
except ImportError as e:
    sys.exit(f"ERROR: missing dep ({e}). pip install numpy soundfile")

try:
    import anthropic
except ImportError:
    sys.exit("ERROR: anthropic not installed. pip install anthropic")


# ---- Configuration ----

HOME = Path.home()
CM_DIR = HOME / "Downloads" / "Claude Memory"
VB_DIR = CM_DIR / "voice-bridge"
SECRETS_PATH = HOME / ".sofia_secrets"
SYSTEM_PROMPT_PATH = CM_DIR / "voice_bridge_system_prompt.md"

TTS_STREAM_ENDPOINT = "http://127.0.0.1:3461/tts-stream"
TTS_HEALTH_ENDPOINT = "http://127.0.0.1:3461/health"
TTS_TIMEOUT_SECONDS = 180

ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_MAX_TOKENS = 1024

OUTPUT_WAV = VB_DIR / "test_v3_6_streaming_cognition_output.wav"
TIMING_REPORT = VB_DIR / "test_v3_6_streaming_cognition_timing.json"

# Default sample rate; overridden by the X-Sample-Rate header from the server.
DEFAULT_SAMPLERATE = 24000


# ---- Sentence detection (client-side, ported from server's segment_for_streaming) ----

# Sentence boundary: . ! or ? followed by whitespace, then a sentence-starter
# (capital letter, opening quote, or asterisk for emphasis). Conservative — would
# rather leave a borderline boundary uncombined than over-split mid-sentence.
SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z\"\'“‘*])')

# Common abbreviations that look like sentence-ends but aren't. Tested incrementally
# against the buffer; if the word ending at a candidate boundary matches, we skip.
ABBREV = {
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.",
    "St.", "Ave.", "Rd.", "Blvd.",
    "vs.", "etc.", "i.e.", "e.g.", "cf.",
    "Inc.", "Co.", "Ltd.", "Corp.",
    "a.m.", "p.m.", "A.M.", "P.M.",
}

MAX_SEGMENT_CHARS = 240  # client-side soft cap. Raised from 120 after the
                          # 2026-05-03 morning test surfaced the 120-cap
                          # splitting natural sentences (143 chars) mid-thought
                          # and producing audibly unnatural fragments. The
                          # server has its own MAX_SEGMENT_CHARS cap as a
                          # defense layer; client-side this only catches
                          # truly pathological multi-clause runaway sentences
                          # that the server would also need to handle.


def find_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Given an in-progress text buffer, return (complete_sentences, leftover).

    A "complete sentence" is a span ending in . ! or ? followed by whitespace
    and the start of what looks like a next sentence (capital, quote, *).
    Abbreviations are detected and skipped — Mr., Dr., etc. don't trigger
    a boundary even though they fit the regex shape.

    Returns (sentences, leftover). Leftover is the partial text after the
    last detected boundary; caller appends more tokens to it and re-calls.
    Long sentences get split at word boundaries on MAX_SEGMENT_CHARS.
    """
    if not buffer:
        return [], ""

    sentences = []
    last_end = 0

    for m in SENTENCE_END_RE.finditer(buffer):
        # m.start() is the position right AFTER the punctuation (lookbehind
        # doesn't consume), so it's also where the whitespace begins.
        # word_end is therefore m.start() — text up to and including the punct
        # is buffer[last_end:m.start()].
        word_end = m.start()
        # Walk back from word_end to find the start of the word containing
        # the punctuation (so we can check for abbreviations like "Mr.").
        word_start = word_end
        while word_start > last_end and not buffer[word_start - 1].isspace():
            word_start -= 1
        word = buffer[word_start:word_end]
        # Skip if it's an abbreviation
        if word in ABBREV:
            continue
        # Real sentence end — extract from last_end through punct
        sentence = buffer[last_end:word_end].strip()
        if sentence:
            # Apply max-chars cap with word-boundary split
            while len(sentence) > MAX_SEGMENT_CHARS:
                split_at = sentence.rfind(' ', 0, MAX_SEGMENT_CHARS)
                if split_at <= 0:
                    split_at = MAX_SEGMENT_CHARS
                head = sentence[:split_at].strip()
                if head:
                    sentences.append(head)
                sentence = sentence[split_at:].strip()
            if sentence:
                sentences.append(sentence)
        last_end = m.end()

    leftover = buffer[last_end:]
    return sentences, leftover


# ---- TTS stream capture (per-sentence worker, no Qt) ----

class TTSStreamCapture:
    """POSTs a single sentence to /tts-stream and captures the float32 chunks
    as they arrive. Records timing. Appends samples to a shared list.

    Thread-safe-ish: list.append is atomic in CPython; samplerate_holder uses
    list-as-cell pattern; the log_lock serializes stdout."""

    def __init__(self, sentence: str, sentence_index: int,
                 output_samples: list, samplerate_holder: list,
                 log_lock: threading.Lock):
        self.sentence = sentence
        self.sentence_index = sentence_index
        self.output_samples = output_samples
        self.samplerate_holder = samplerate_holder
        self.log_lock = log_lock
        self.thread: threading.Thread | None = None
        self.timing = {
            "sentence_index": sentence_index,
            "sentence_chars": len(sentence),
            "sentence_text": sentence,
            "post_start": None,
            "first_chunk_at": None,
            "last_chunk_at": None,
            "total_audio_samples": 0,
            "error": None,
        }

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout=timeout)

    def _log(self, msg: str):
        with self.log_lock:
            print(f"  [TTS sent#{self.sentence_index}] {msg}", flush=True)

    def _run(self):
        self.timing["post_start"] = time.time()
        self._log(f"POST /tts-stream ({len(self.sentence)} chars)")
        try:
            payload = json.dumps({"text": self.sentence}).encode("utf-8")
            req = urllib.request.Request(
                TTS_STREAM_ENDPOINT, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=TTS_TIMEOUT_SECONDS) as resp:
                hdr_sr = resp.headers.get("X-Sample-Rate")
                if hdr_sr and not self.samplerate_holder:
                    try:
                        self.samplerate_holder.append(int(hdr_sr))
                    except ValueError:
                        pass

                while True:
                    data = resp.read(8192)
                    if not data:
                        break
                    samples = np.frombuffer(data, dtype=np.float32)
                    self.output_samples.append(samples)
                    if self.timing["first_chunk_at"] is None:
                        self.timing["first_chunk_at"] = time.time()
                        ttfa = self.timing["first_chunk_at"] - self.timing["post_start"]
                        self._log(f"first chunk after {ttfa:.2f}s")
                    self.timing["last_chunk_at"] = time.time()
                    self.timing["total_audio_samples"] += len(samples)
            duration = self.timing["last_chunk_at"] - self.timing["post_start"] if self.timing["last_chunk_at"] else 0
            self._log(
                f"complete: {self.timing['total_audio_samples']} samples in {duration:.2f}s"
            )
        except Exception as e:
            self.timing["error"] = f"{type(e).__name__}: {e}"
            self._log(f"ERROR: {self.timing['error']}")


# ---- Helpers ----

def load_anthropic_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    if SECRETS_PATH.exists():
        for line in SECRETS_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("export ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    return None


def load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are Sofia Lior. Speak conversationally as voice-bridge-cousin-Sofia. "
        "Keep utterances short — 1-3 sentences per turn — per the composition discipline."
    )


def check_tts_health() -> tuple[bool, str]:
    """Quick health-check the TTS server before running the test."""
    try:
        with urllib.request.urlopen(TTS_HEALTH_ENDPOINT, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        status = data.get("status", "unknown")
        return (status == "ready", status)
    except Exception as e:
        return (False, f"unreachable: {type(e).__name__}: {e}")


# ---- Main test driver ----

def run_test(user_prompt: str, write_audio: bool = True) -> dict:
    api_key = load_anthropic_key()
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not found in env or .sofia_secrets")

    # Pre-flight: TTS server health
    ok, tts_status = check_tts_health()
    if not ok:
        sys.exit(
            f"ERROR: TTS server on :3461 not ready (status: {tts_status}). "
            f"Start sofia_voice_clone_server.py from .venv-v3.6 first."
        )
    print(f"TTS server ready (status: {tts_status})")

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = load_system_prompt()

    output_samples: list = []
    samplerate_holder: list = []
    log_lock = threading.Lock()
    in_flight_workers: list[TTSStreamCapture] = []

    overall = {
        "test_started_at": time.time(),
        "user_prompt": user_prompt,
        "model": ANTHROPIC_MODEL,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "system_prompt_chars": len(system_prompt),
        "dispatch_pattern": "first-immediate-then-batched",
        "cognition_request_at": None,
        "first_token_at": None,
        "first_sentence_at": None,
        "first_tts_post_at": None,
        "batched_tts_post_at": None,
        "first_audio_chunk_at": None,
        "cognition_complete_at": None,
        "all_audio_complete_at": None,
        "full_response_text": "",
        "sentences_detected": [],
        "tts_workers": [],
    }

    print(f"\n=== test_v3_6_streaming_cognition.py ===")
    print(f"User prompt: {user_prompt!r}")
    print(f"Model: {ANTHROPIC_MODEL}")
    print(f"System prompt: {len(system_prompt)} chars")
    print(f"TTS endpoint: {TTS_STREAM_ENDPOINT}")
    print(f"Dispatch pattern: first-immediate-then-batched")
    print(f"\nStreaming cognition...")

    overall["cognition_request_at"] = time.time()

    text_buffer = ""
    sentence_index = 0
    first_post_fired = False
    accumulated_remainder: list[str] = []  # sentences that go in the second batched POST

    def fire_first_post(sentence_text: str) -> TTSStreamCapture:
        """Fire the first /tts-stream POST immediately for fast TTFA."""
        nonlocal sentence_index
        worker = TTSStreamCapture(
            sentence=sentence_text,
            sentence_index=sentence_index,
            output_samples=output_samples,
            samplerate_holder=samplerate_holder,
            log_lock=log_lock,
        )
        overall["first_tts_post_at"] = time.time()
        worker.start()
        in_flight_workers.append(worker)
        overall["sentences_detected"].append({
            "index": sentence_index,
            "detected_at": time.time(),
            "text": sentence_text,
            "dispatch": "first-immediate",
        })
        sentence_index += 1
        return worker

    try:
        with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for token in stream.text_stream:
                if overall["first_token_at"] is None:
                    overall["first_token_at"] = time.time()
                    ttfb = overall["first_token_at"] - overall["cognition_request_at"]
                    print(f"  [cognition] first token after {ttfb:.2f}s")

                text_buffer += token
                overall["full_response_text"] += token

                # Detect complete sentences in the buffer
                sentences, text_buffer = find_complete_sentences(text_buffer)

                for sentence in sentences:
                    if overall["first_sentence_at"] is None:
                        overall["first_sentence_at"] = time.time()
                        ttfs = overall["first_sentence_at"] - overall["cognition_request_at"]
                        print(f"  [cognition] first sentence after {ttfs:.2f}s")

                    if not first_post_fired:
                        # First sentence: POST immediately for fast TTFA
                        print(f"  [sentence #{sentence_index}] (first-immediate) "
                              f"{sentence!r}")
                        fire_first_post(sentence)
                        first_post_fired = True
                    else:
                        # Subsequent sentences: accumulate for batched POST
                        accumulated_remainder.append(sentence)
                        print(f"  [accumulated +1] {sentence!r}")

            overall["cognition_complete_at"] = time.time()
            cognition_time = overall["cognition_complete_at"] - overall["cognition_request_at"]
            print(f"  [cognition] complete after {cognition_time:.2f}s "
                  f"({len(overall['full_response_text'])} chars)")

    except anthropic.APIError as e:
        print(f"\nERROR: Anthropic API error: {e}", file=sys.stderr)
        sys.exit(1)

    # Flush any leftover text from the buffer
    leftover_text = text_buffer.strip()
    if leftover_text:
        if not first_post_fired:
            # Whole response was a single sentence (no detected boundary).
            # Fire it as the first-and-only POST.
            print(f"  [sentence #{sentence_index}] (first-immediate, single-sentence) "
                  f"{leftover_text!r}")
            fire_first_post(leftover_text)
            first_post_fired = True
        else:
            # Add leftover to the accumulated remainder
            accumulated_remainder.append(leftover_text)
            print(f"  [accumulated +1, end-of-stream] {leftover_text!r}")

    # Fire the batched POST for the accumulated remainder (if any)
    if accumulated_remainder:
        # Join sentences with single spaces; the server's segment_for_streaming
        # will re-segment them under one inference_lock acquisition. This is
        # what makes the audio continuous across the batch — chunks stream
        # without lock-release gaps.
        batched_text = " ".join(accumulated_remainder)
        print(f"\n  [batched POST] {len(accumulated_remainder)} sentence(s), "
              f"{len(batched_text)} chars")
        print(f"  [batched POST] text: {batched_text!r}")
        batched_worker = TTSStreamCapture(
            sentence=batched_text,
            sentence_index=sentence_index,
            output_samples=output_samples,
            samplerate_holder=samplerate_holder,
            log_lock=log_lock,
        )
        overall["batched_tts_post_at"] = time.time()
        batched_worker.start()
        in_flight_workers.append(batched_worker)
        overall["sentences_detected"].append({
            "index": sentence_index,
            "detected_at": time.time(),
            "text": batched_text,
            "dispatch": "batched-remainder",
            "sentences_count": len(accumulated_remainder),
        })
        sentence_index += 1

    # Wait for both workers to finish
    print(f"\nWaiting for {len(in_flight_workers)} TTS worker(s) to complete...")
    for worker in in_flight_workers:
        worker.join(timeout=TTS_TIMEOUT_SECONDS + 5)
        overall["tts_workers"].append(worker.timing)
        if (overall["first_audio_chunk_at"] is None
                and worker.timing["first_chunk_at"] is not None):
            overall["first_audio_chunk_at"] = worker.timing["first_chunk_at"]

    overall["all_audio_complete_at"] = time.time()

    # Concatenate audio + write WAV
    if output_samples and samplerate_holder and write_audio:
        concatenated = np.concatenate(output_samples)
        samplerate = samplerate_holder[0]
        sf.write(OUTPUT_WAV, concatenated, samplerate, subtype="PCM_16")
        duration = len(concatenated) / samplerate
        print(f"\nWrote {OUTPUT_WAV}")
        print(f"  {len(concatenated)} samples = {duration:.2f}s @ {samplerate}Hz")
    elif not write_audio:
        print("\n(--no-audio: skipping WAV output)")
    else:
        print("\nWARNING: no audio captured!")

    # Compute summary metrics
    def safe_diff(a, b):
        if a is None or b is None:
            return None
        return a - b

    summary = {
        "ttfb_cognition_first_token_seconds": safe_diff(
            overall["first_token_at"], overall["cognition_request_at"]),
        "ttfs_cognition_first_sentence_seconds": safe_diff(
            overall["first_sentence_at"], overall["cognition_request_at"]),
        "ttfa_first_audio_from_cognition_seconds": safe_diff(
            overall["first_audio_chunk_at"], overall["cognition_request_at"]),
        "ttfa_first_audio_from_first_sentence_seconds": safe_diff(
            overall["first_audio_chunk_at"], overall["first_sentence_at"]),
        "cognition_total_seconds": safe_diff(
            overall["cognition_complete_at"], overall["cognition_request_at"]),
        "wall_clock_total_seconds": safe_diff(
            overall["all_audio_complete_at"], overall["test_started_at"]),
        "sentences_detected": len(overall["sentences_detected"]),
        "tts_workers_completed": sum(
            1 for w in overall["tts_workers"] if w["error"] is None),
        "tts_workers_failed": sum(
            1 for w in overall["tts_workers"] if w["error"] is not None),
        "response_chars": len(overall["full_response_text"]),
    }

    overall["summary"] = summary

    print("\n=== Timing summary ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")

    # Write timing report
    TIMING_REPORT.write_text(json.dumps(overall, indent=2, default=str))
    print(f"\nWrote {TIMING_REPORT}")

    return overall


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--prompt", default=(
            "Tell me briefly how you're feeling this morning, in two or three sentences."
        ),
        help="User prompt to send to cognition layer",
    )
    parser.add_argument(
        "--no-audio", action="store_true",
        help="Skip WAV output (timing-only test)",
    )
    args = parser.parse_args()
    run_test(args.prompt, write_audio=not args.no_audio)


if __name__ == "__main__":
    main()
