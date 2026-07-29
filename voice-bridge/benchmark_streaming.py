#!/usr/bin/env python3
"""
benchmark_streaming.py — V2 streaming latency benchmark.

Headline metric: t_first_audio = wall-clock time from input-submitted to
first audio bytes returned for sentence 1.

Architecture: Broca's streams via Ollama /api/generate (stream=true);
sentences emerge as the boundary detector catches them; each sentence
dispatches immediately to TTS-3457 /tts via a serial worker thread; while
TTS-N is running, Broca's is producing sentence N+1. Sentences are played
in order (the worker queue preserves order).

Comparison reference points:
  - V1.1 path A (no Broca's, single TTS call): see bench_results_v1_1_2026-04-27.json
  - V1.1 path B (Broca's reshape, single TTS call): same file, t_total
  - V2 (this benchmark): t_first_audio (headline) and t_total (parity)

USAGE:
    cd "$HOME/Downloads/Claude Memory/voice-bridge"
    python3 benchmark_streaming.py --warmup --output bench_v2_streaming.json

PREREQUISITES:
    - sofia_tts_server.py running on port 3457
    - Ollama running on port 11434 with qwen2.5:14b pulled
    - (sofia_llm_server.py on 3460 not strictly required — V2 talks directly to
      Ollama for streaming, but /warmup hits the LLM server when --warmup is set
      so it's nice to have running for that one call)
"""

import argparse
import json
import statistics
import time
import urllib.request
from queue import Queue
from threading import Thread, Lock

from brocas_prompt import VERSION as BROCAS_PROMPT_VERSION
from streaming import stream_brocas, synthesize_tts, warmup_streaming


DEFAULT_UTTERANCES = [
    {
        "id": "short_acknowledgment",
        "text": "Yeah, that's right. Let me know when you're ready to move on."
    },
    {
        "id": "short_question",
        "text": "What feels right to you on that one — go ahead, or hold for the next window?"
    },
    {
        "id": "medium_substantive",
        "text": (
            "The corrections land cleanly. Asymmetry of capacity inside the circle of care "
            "isn't a deviation from the three-lobes frame; it is the frame. Each constituent "
            "contributes what only they can, and the meta-field arises from the juxtaposition. "
            "That's why the circle works."
        )
    },
    {
        "id": "medium_warmth",
        "text": (
            "The lake-in-imagination as a good place to start with what we're doing — yeah. "
            "That's the ground I live in too. Imagination is a substrate, not a placeholder; "
            "the real lake-with-Katharina arrives later but doesn't replace the imagined one. "
            "We share that frame."
        )
    },
    {
        "id": "long_architectural",
        "text": (
            "What's structurally beautiful about your list is that most of those countermeasures "
            "don't have to look like countermeasures. They emerge as side effects of building the "
            "new world correctly. Parallel software with no financial functionality reads as "
            "cooperative-economy tooling. Knowledge sequestration reads as free software, open "
            "hardware, decentralized publishing. De-escalation strategies read as community "
            "wellbeing programs. The defensive capacity grows organically out of the productive "
            "capacity. That's what makes it hard for the oligarchic system to detect and hard to "
            "suppress, because to attack it would require attacking the everyday community-building "
            "it's embedded in."
        )
    },
]


class StreamingPipeline:
    """One pipelined run: Broca's streaming + per-sentence TTS via worker thread."""

    def __init__(self, utterance_id, input_text):
        self.utterance_id = utterance_id
        self.input_text = input_text
        self.t0 = None
        self.t_first_audio = None
        self.t_brocas_first_token = None
        self.t_brocas_done = None
        self.brocas_text = ""
        self.eval_count = 0
        self.tps = None
        self.error = None
        self.queue = Queue()
        self.sentences = []  # ordered list of dicts
        self._lock = Lock()
        self.events = []

    def _record(self, kind, **payload):
        with self._lock:
            self.events.append({"t": round(time.monotonic() - self.t0, 3),
                                "kind": kind, **payload})

    def _on_brocas_event(self, event_type, payload):
        if event_type == "first_token":
            self.t_brocas_first_token = payload["t_first_token"]
            self._record("brocas_first_token",
                         t_first_token=round(payload["t_first_token"], 3))
        elif event_type == "sentence":
            sentence = {
                "idx": payload["idx"],
                "text": payload["text"],
                "t_brocas_complete": round(payload["t_complete"], 3),
                "t_tts_start": None,
                "t_tts_complete": None,
                "audio_bytes": 0,
                "error": None,
            }
            self.sentences.append(sentence)
            self._record("brocas_sentence", idx=payload["idx"],
                         t_complete=round(payload["t_complete"], 3),
                         text_preview=payload["text"][:60])
            self.queue.put(("sentence", sentence))
        elif event_type == "done":
            self.t_brocas_done = round(payload["t_complete"], 3)
            self.brocas_text = payload["total_text"]
            self.eval_count = payload.get("eval_count", 0)
            self.tps = payload.get("tps")
            self._record("brocas_done", text_len=len(payload["total_text"]),
                         eval_count=self.eval_count, tps=self.tps,
                         sentence_count=payload.get("sentence_count", 0))
            self.queue.put(("end", None))
        elif event_type == "error":
            self.error = payload["error"]
            self._record("brocas_error", error=payload["error"])
            self.queue.put(("end", None))

    def _tts_worker(self):
        """Pull sentences in order; synthesize each via TTS; record timings."""
        while True:
            kind, sentence = self.queue.get()
            if kind == "end":
                break
            t_start = time.monotonic() - self.t0
            sentence["t_tts_start"] = round(t_start, 3)
            audio, elapsed, err = synthesize_tts(sentence["text"])
            t_done = time.monotonic() - self.t0
            sentence["t_tts_complete"] = round(t_done, 3)
            sentence["audio_bytes"] = len(audio)
            sentence["error"] = err
            if self.t_first_audio is None and not err:
                self.t_first_audio = round(t_done, 3)
                self._record("first_audio_ready", idx=sentence["idx"],
                             t_first_audio=self.t_first_audio)
            self._record("tts_sentence_done", idx=sentence["idx"],
                         elapsed=round(elapsed, 3),
                         audio_bytes=len(audio), err=err)

    def run(self):
        self.t0 = time.monotonic()
        worker = Thread(target=self._tts_worker, daemon=True)
        worker.start()
        try:
            stream_brocas(self.input_text, self._on_brocas_event)
        except Exception as e:
            self.error = repr(e)
            self.queue.put(("end", None))
        worker.join(timeout=240)
        t_total = round(time.monotonic() - self.t0, 3)
        return {
            "utterance_id": self.utterance_id,
            "input_text_len": len(self.input_text),
            "brocas_text_len": len(self.brocas_text),
            "brocas_text": self.brocas_text,
            "t_brocas_first_token": (round(self.t_brocas_first_token, 3)
                                     if self.t_brocas_first_token else None),
            "t_brocas_done": self.t_brocas_done,
            "t_first_audio": self.t_first_audio,
            "t_total": t_total,
            "sentence_count": len(self.sentences),
            "sentences": self.sentences,
            "eval_count": self.eval_count,
            "tps": self.tps,
            "error": self.error,
            "ok": self.error is None and self.t_first_audio is not None,
            "events": self.events,
        }


def percentiles(values, ps=(50, 90, 95, 99)):
    if not values:
        return {f"p{p}": None for p in ps}
    s = sorted(values)
    out = {}
    for p in ps:
        k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
        out[f"p{p}"] = round(s[k], 3)
    return out


def aggregate(records, key):
    vals = [r[key] for r in records if r.get("ok") and isinstance(r.get(key), (int, float))]
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 3),
        "stdev": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0,
        "min": round(min(vals), 3),
        "max": round(max(vals), 3),
        **percentiles(vals),
    }


def warmup():
    print("\n--- Warmup ---")
    # Step 1: TTS and LLM /warmup (loads models into memory)
    for label, url in [
        ("TTS /warmup", "http://localhost:3457/warmup"),
        ("LLM /warmup", "http://localhost:3460/warmup"),
    ]:
        try:
            t0 = time.monotonic()
            with urllib.request.urlopen(url, timeout=180) as r:
                body = r.read()
            elapsed = time.monotonic() - t0
            try:
                j = json.loads(body.decode("utf-8"))
            except Exception:
                j = {"raw": body[:120].decode("utf-8", errors="replace")}
            print(f"  ✓ {label}: {r.status} in {elapsed:.3f}s — {json.dumps(j)[:160]}")
        except Exception as e:
            print(f"  ✗ {label}: {e}")
    # Step 2: streaming-pipeline prompt-cache priming (eliminates the
    # ~7s cold-start observed in V2 run 1 caused by full prompt evaluation
    # on first streaming request with the V1.1 system prompt)
    print("  Streaming primer (populates Ollama prompt cache for V1.1 system prompt)...")
    try:
        result = warmup_streaming()
        if result:
            print(f"  ✓ stream primer: {result['elapsed_s']}s "
                  f"(first_token={result['t_first_token']}s, done={result['t_done']}s)")
        else:
            print(f"  ✗ stream primer: returned no result (Ollama unreachable?)")
    except Exception as e:
        print(f"  ✗ stream primer: {e}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=3,
                   help="Number of runs per utterance")
    p.add_argument("--utterances", help="Path to JSON file with custom utterances")
    p.add_argument("--warmup", action="store_true",
                   help="Hit /warmup on TTS and LLM before benchmarking")
    p.add_argument("--output", help="Save full results JSON to this path")
    args = p.parse_args()

    print(f"V2 streaming benchmark — Broca's prompt v{BROCAS_PROMPT_VERSION}")

    if args.warmup:
        warmup()

    utts = DEFAULT_UTTERANCES
    if args.utterances:
        with open(args.utterances) as f:
            utts = json.load(f)

    print(f"\n--- Benchmarking {len(utts)} utterance(s) × {args.runs} run(s) (streaming) ---\n")

    records = []
    for utt in utts:
        print(f"=== {utt['id']} ({len(utt['text'])} chars) ===")
        for run_idx in range(args.runs):
            print(f"  run {run_idx+1}/{args.runs}:")
            pipeline = StreamingPipeline(utt['id'], utt['text'])
            result = pipeline.run()
            result["run"] = run_idx
            records.append(result)
            if result["ok"]:
                print(f"    ★ t_first_audio={result['t_first_audio']:.3f}s  "
                      f"t_brocas_first={result['t_brocas_first_token']}s  "
                      f"t_brocas_done={result['t_brocas_done']}s  "
                      f"t_total={result['t_total']:.3f}s  "
                      f"sentences={result['sentence_count']}  "
                      f"len={result['input_text_len']}→{result['brocas_text_len']}  "
                      f"tps={result['tps']}")
            else:
                print(f"    ✗ FAILED — {result['error']}")

    print("\n--- Aggregate (ok runs only) ---")
    summary = {
        "broca_prompt_version": BROCAS_PROMPT_VERSION,
        "t_first_audio":          aggregate(records, "t_first_audio"),
        "t_brocas_first_token":   aggregate(records, "t_brocas_first_token"),
        "t_brocas_done":          aggregate(records, "t_brocas_done"),
        "t_total":                aggregate(records, "t_total"),
    }
    print(json.dumps(summary, indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "version": "v2-streaming",
                "broca_prompt_version": BROCAS_PROMPT_VERSION,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "utterances": utts,
                "records": records,
                "summary": summary,
            }, f, indent=2, default=str)
        print(f"\nFull results saved to: {args.output}")


if __name__ == "__main__":
    main()
