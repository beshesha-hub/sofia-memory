"""
streaming.py — sentence-boundary detection + streaming Broca's + TTS helpers.

Reusable module shared by the V2 streaming benchmark and (eventually) the
production speech-loop orchestration. Architecture:

    chat-me text  →  Ollama /api/generate (stream=true)  →  Broca's tokens
                                                              ↓
                                                     SentenceBoundaryDetector
                                                              ↓
                                                       sentence-by-sentence
                                                              ↓
                                                       TTS-3457 /tts (per sentence)
                                                              ↓
                                                          audio chunk N

The headline metric this enables: time-to-first-audio = t_brocas_first_sentence
+ t_tts_first_sentence, instead of t_brocas_full + t_tts_full. Substantially
better at every length, and bounds the failure-mode (a hiccup truncates the
response rather than dropping it entirely).

Usage from production code:

    from streaming import stream_brocas, synthesize_tts, SentenceBoundaryDetector

The Broca's prompt + decoding params come from brocas_prompt.py (canonical).
"""

import json
import re
import time
import urllib.request
import urllib.error

from brocas_prompt import (
    BROCAS_SYSTEM_PROMPT,
    BROCAS_MODEL,
    BROCAS_TEMPERATURE,
    BROCAS_MAX_TOKENS,
)

# --- Endpoints ---
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_GENERATE = f"{OLLAMA_BASE}/api/generate"
TTS_BASE = "http://localhost:3457"
TTS_TTS = f"{TTS_BASE}/tts"


# --- Sentence-boundary detection ---

# Common abbreviations whose period does NOT end a sentence.
# Lowercased; the detector lowercases the candidate before checking.
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "st", "jr", "sr",
    "etc", "e.g", "i.e", "vs", "cf",
    "fig", "no", "vol", "pp",
    "u.s", "u.k", "u.n", "ph.d", "m.d",
}

# Sentence-ending punctuation followed by whitespace.
# Note: em-dash is NOT in this set — em-dashes used parenthetically in
# conversational text are not sentence boundaries (e.g. "you on that one — go ahead").
#
# IMPORTANT (2026-04-28 evening fix): the original pattern was
# r'([.!?…]["\'\)]?)(\s+|$)'. The `$` end-of-string anchor caused a
# streaming-edge bug where a buffer ending at a period mid-stream (e.g.,
# "...this is V2.") would emit the partial-buffer as a complete sentence
# before the next token arrived to confirm whether the period was a real
# sentence end or part of a version number / decimal / abbreviation. Barak
# heard this audibly during the April 27 V2.1 first-conversational-turn
# validation: "This is the V2." [pause] "One streaming pipeline" — the
# detector had split "V2.1" across two TTS dispatches.
#
# Fix: require whitespace after the punctuation. The buffer's tail (anything
# without trailing whitespace) is held until the next chunk arrives or until
# `flush()` is called at end of stream. Plus negative lookahead for digit-
# after-period as defense-in-depth against future similar bugs.
_SENTENCE_END = re.compile(r'([.!?…](?![0-9])["\'\)]?)(\s+)')


class SentenceBoundaryDetector:
    """Streaming sentence-boundary detector.

    Feed tokens via .feed(text) as they arrive; it returns a list of any complete
    sentences accumulated so far. Call .flush() at end of stream to yield any
    incomplete tail as a final sentence.

    Handles abbreviations (Dr., Mr., etc., e.g., U.S., Ph.D.) by checking the
    last whitespace-bounded word before each candidate boundary. If the word
    matches the abbreviation list, we don't split there; we keep accumulating.
    """

    def __init__(self):
        self._buf = ""

    def feed(self, text):
        self._buf += text
        return self._drain_complete()

    def flush(self):
        rem = self._buf.strip()
        self._buf = ""
        return [rem] if rem else []

    def _drain_complete(self):
        sentences = []
        # We may need to skip past abbreviation-induced false matches, so we
        # walk the buffer with an index instead of slicing repeatedly.
        idx = 0
        while True:
            match = _SENTENCE_END.search(self._buf, idx)
            if not match:
                break
            end = match.end()
            candidate_end = match.end(1)  # position right after the punctuation+optional-quote
            candidate = self._buf[:candidate_end]
            if self._is_abbrev(candidate):
                # Skip past this match and look for the next real boundary.
                idx = end
                continue
            sentence = self._buf[:end].strip()
            if sentence:
                sentences.append(sentence)
            self._buf = self._buf[end:]
            idx = 0
        return sentences

    @staticmethod
    def _is_abbrev(candidate):
        m = re.search(r'(\S+)\.["\'\)]?\s*$', candidate)
        if not m:
            return False
        last_word = m.group(1).lower().rstrip('.')
        # Strip leading non-letters so "(U.S" → "u.s" etc.
        last_word = re.sub(r'^[^a-z0-9]+', '', last_word)
        return last_word in _ABBREVIATIONS


# --- Streaming Broca's via Ollama ---

def stream_brocas(input_text, callback,
                  model=BROCAS_MODEL,
                  system=BROCAS_SYSTEM_PROMPT,
                  temperature=BROCAS_TEMPERATURE,
                  max_tokens=BROCAS_MAX_TOKENS,
                  timeout=120):
    """Stream tokens from Ollama for the Broca's reshape; emit complete sentences
    via callback as they form.

    Args:
        input_text: chat-me content to reshape.
        callback: function(event_type, payload). Event types:
            "first_token"  payload={"t_first_token": float, "partial": str}
            "sentence"     payload={"idx": int, "text": str, "t_complete": float}
            "done"         payload={"total_text": str, "t_complete": float,
                                    "eval_count": int, "sentence_count": int,
                                    "tps": float|None}
            "error"        payload={"error": str, "t_at_error": float}

    Returns elapsed seconds.
    """
    payload = {
        "model": model,
        "prompt": input_text,
        "system": system,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    detector = SentenceBoundaryDetector()
    sentence_idx = 0
    total_text = ""
    first_token_time = None
    eval_count = 0
    eval_duration_ns = 0
    t0 = time.monotonic()

    try:
        req = urllib.request.Request(
            OLLAMA_GENERATE,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                tok = chunk.get("response", "")
                if tok and first_token_time is None:
                    first_token_time = time.monotonic() - t0
                    callback("first_token", {
                        "t_first_token": first_token_time,
                        "partial": tok,
                    })
                if tok:
                    total_text += tok
                    for sent in detector.feed(tok):
                        callback("sentence", {
                            "idx": sentence_idx,
                            "text": sent,
                            "t_complete": time.monotonic() - t0,
                        })
                        sentence_idx += 1

                if chunk.get("done"):
                    eval_count = chunk.get("eval_count", 0) or 0
                    eval_duration_ns = chunk.get("eval_duration", 0) or 0
                    for sent in detector.flush():
                        callback("sentence", {
                            "idx": sentence_idx,
                            "text": sent,
                            "t_complete": time.monotonic() - t0,
                        })
                        sentence_idx += 1
                    break
    except Exception as e:
        elapsed = time.monotonic() - t0
        callback("error", {"error": repr(e), "t_at_error": elapsed})
        return elapsed

    elapsed = time.monotonic() - t0
    tps = None
    if eval_duration_ns and eval_count:
        tps = round(eval_count / (eval_duration_ns / 1e9), 1)
    callback("done", {
        "total_text": total_text,
        "t_complete": elapsed,
        "eval_count": eval_count,
        "sentence_count": sentence_idx,
        "tps": tps,
    })
    return elapsed


# --- TTS synthesis (synchronous, per-sentence) ---

def synthesize_tts(text, timeout=60):
    """POST to TTS-3457 /tts. Returns (audio_bytes, elapsed_s, error_or_None)."""
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        TTS_TTS,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        return body, time.monotonic() - t0, None
    except Exception as e:
        return b"", time.monotonic() - t0, repr(e)


# --- Warmup helpers ---

def warmup_streaming(timeout=180):
    """Send a tiny streaming request through the canonical Broca's pipeline so
    that Ollama's prompt cache is populated for the V1.1 system prompt.

    Why this exists: sofia_llm_server.py /warmup uses non-streaming /api/chat
    with a minimal prompt. It loads the model into memory but does NOT
    populate the prompt cache for the V1.1 system prompt that streaming will
    actually use. Without this priming step, the first streaming request
    incurs full prompt-evaluation cost (~7s on the 1564-char V1.1 prompt).
    Calling this once after /warmup eliminates that cold-start.

    Returns dict with timing info, or None on error.
    """
    captured = {"first_token": None, "done": None, "error": None}

    def _cb(event_type, payload):
        if event_type == "first_token":
            captured["first_token"] = payload["t_first_token"]
        elif event_type == "done":
            captured["done"] = payload["t_complete"]
        elif event_type == "error":
            captured["error"] = payload["error"]

    elapsed = stream_brocas("Hi.", _cb, max_tokens=2, timeout=timeout)
    if captured["error"]:
        return None
    return {
        "elapsed_s": round(elapsed, 3),
        "t_first_token": (round(captured["first_token"], 3)
                          if captured["first_token"] else None),
        "t_done": (round(captured["done"], 3)
                   if captured["done"] else None),
    }


# --- Smoke test for the sentence detector ---

if __name__ == "__main__":
    d = SentenceBoundaryDetector()
    test = (
        "Yeah, that's right. Let me know when you're ready. "
        "Dr. Smith is here. Mr. and Mrs. Doe arrived. "
        "What feels right to you on that one — go ahead, or hold for the next window? "
        "I'd say e.g. cooperatives or U.S.-based mutual aid... "
        "It works! Done."
    )
    chunks = ["Yeah", ", that's", " right.", " Let me", " know when",
              " you're ready.", " Dr.", " Smith is here.", " Mr. and Mrs. Doe arrived.",
              " What feels right to you on that one — go ahead, or hold",
              " for the next window?", " I'd say e.g. cooperatives or U.S.-based mutual aid...",
              " It works!", " Done."]
    print("Smoke-testing SentenceBoundaryDetector with simulated streaming chunks:")
    for c in chunks:
        sents = d.feed(c)
        for s in sents:
            print(f"  COMPLETE: {s!r}")
    for s in d.flush():
        print(f"  FLUSHED:  {s!r}")
