#!/usr/bin/env python3
"""
benchmark_latency.py — V1 latency benchmark for Voice Bridge speech loop.

Tri-directional latency comparison over the local stack, per the discipline
agreed April 27, 2026 afternoon Taipei: desired / local-Broca's / current-fallback.

V1 SCOPE:
  * Uses canned chat-me-style responses (no cloud API call) so we measure the
    LOCAL stack cleanly. V2 will add cloud chat-me to round out the
    desired/local/current-API picture.
  * Skips STT (text input only).
  * Skips lipsync.
  * Non-streaming Broca's (V2 will add streaming + first-audio-byte timing).

Paths benchmarked:
  Path A (no-Broca's, fallback shape):
      canned-chat-me-text  →  TTS-3457        (POST /tts, returns full audio)
  Path B (with Broca's, new path):
      canned-chat-me-text  →  LLM-3460        (POST /generate, qwen2.5:14b reshape)
                          →  TTS-3457        (POST /tts on the reshaped speech-text)

Per-utterance timings recorded:
  * Path A: t_tts, t_total, ok, audio_bytes
  * Path B: t_brocas (wall_s), t_brocas_ttft, t_brocas_tps, t_tts, t_total, ok,
            input_text_len, brocas_text_len, audio_bytes
  * delta_brocas_cost = path_b.t_total - path_a.t_total  (the latency cost of inserting Broca's)

Aggregates per path: p50, p90, p95, p99, mean, stdev across all runs.

USAGE:
    cd "$HOME/Downloads/Claude Memory/voice-bridge"
    python3 benchmark_latency.py                          # default 3 runs per utterance
    python3 benchmark_latency.py --runs 5                 # more runs for tighter variance
    python3 benchmark_latency.py --utterances mine.json   # custom utterance set
    python3 benchmark_latency.py --warmup                 # call /warmup on TTS+LLM first
    python3 benchmark_latency.py --output results.json    # save full results JSON

PREREQUISITES:
    - sofia_tts_server.py running on port 3457   (start.command launches it)
    - sofia_llm_server.py running on port 3460   (start.command launches it)
    - Ollama running with qwen2.5:14b pulled     (`ollama list` should show it)
"""

import argparse
import json
import statistics
import sys
import time
import urllib.request
import urllib.error

# Canonical Broca's prompt + decoding params live in a shared module so
# benchmark and production speech-loop both read from the same source.
from brocas_prompt import (
    BROCAS_SYSTEM_PROMPT as DEFAULT_BROCAS_SYSTEM,
    BROCAS_MODEL,
    BROCAS_TEMPERATURE,
    BROCAS_MAX_TOKENS,
    VERSION as BROCAS_PROMPT_VERSION,
)

# --- Endpoints (Mac-localhost only; sandbox cannot reach these) ---
TTS_BASE = "http://localhost:3457"
LLM_BASE = "http://localhost:3460"
TTS_TTS = f"{TTS_BASE}/tts"
TTS_HEALTH = f"{TTS_BASE}/health"
TTS_WARMUP = f"{TTS_BASE}/warmup"
LLM_GENERATE = f"{LLM_BASE}/generate"
LLM_HEALTH = f"{LLM_BASE}/health"
LLM_WARMUP = f"{LLM_BASE}/warmup"

# Note: DEFAULT_BROCAS_SYSTEM is imported from brocas_prompt above (V1.1).
# Edit the prompt in brocas_prompt.py, not here, so production and benchmark stay aligned.

# --- Representative conversational utterances (April 27 design conversation register) ---
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


# --- HTTP helpers ---

def http_post(url, payload, timeout=120):
    """POST JSON, return (status, body_bytes, elapsed_s, error_or_None)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        return r.status, body, time.monotonic() - t0, None
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b"", time.monotonic() - t0, str(e)
    except urllib.error.URLError as e:
        return 0, b"", time.monotonic() - t0, str(e)
    except Exception as e:
        return 0, b"", time.monotonic() - t0, repr(e)


def http_get(url, timeout=10):
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(), time.monotonic() - t0, None
    except Exception as e:
        return 0, b"", time.monotonic() - t0, str(e)


# --- Stage measurements ---

def call_brocas(input_text, system=DEFAULT_BROCAS_SYSTEM, model=BROCAS_MODEL,
                max_tokens=BROCAS_MAX_TOKENS, temperature=BROCAS_TEMPERATURE):
    """POST /generate to local LLM. Returns dict with timings and output.

    Defaults all come from brocas_prompt.py (the canonical source); pass
    overrides only for benchmark/experimental purposes.
    """
    payload = {
        "prompt": input_text,
        "system": system,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if model:
        payload["model"] = model
    status, body, elapsed, err = http_post(LLM_GENERATE, payload)
    out = {
        "ok": False,
        "wall_s": round(elapsed, 3),
        "content": "",
        "ttft_s": None,
        "tps": None,
        "tokens_generated": None,
        "error": err,
    }
    if err is None and status == 200:
        try:
            j = json.loads(body.decode("utf-8"))
            out["ok"] = bool(j.get("ok"))
            out["content"] = j.get("content", "")
            out["ttft_s"] = j.get("ttft_s")
            out["tps"] = j.get("tokens_per_second")
            out["tokens_generated"] = j.get("tokens_generated")
            out["wall_s"] = j.get("wall_s", out["wall_s"])
        except Exception as e:
            out["error"] = f"json parse: {e}"
    elif err is None:
        out["error"] = f"HTTP {status}: {body[:200]!r}"
    return out


def call_tts(text):
    """POST /tts. Returns dict with timing, audio length, ok."""
    payload = {"text": text}
    status, body, elapsed, err = http_post(TTS_TTS, payload, timeout=120)
    return {
        "ok": err is None and status == 200,
        "elapsed_s": round(elapsed, 3),
        "audio_bytes": len(body) if err is None and status == 200 else 0,
        "error": err if err else (None if status == 200 else f"HTTP {status}"),
    }


# --- Path runners ---

def run_path_a(utterance):
    """Path A: canned-text → TTS only (the no-Broca's fallback shape)."""
    tts = call_tts(utterance["text"])
    return {
        "path": "A_no_brocas",
        "ok": tts["ok"],
        "t_tts": tts["elapsed_s"],
        "t_total": tts["elapsed_s"],
        "audio_bytes": tts["audio_bytes"],
        "error": tts["error"],
    }


def run_path_b(utterance):
    """Path B: canned-text → Broca's → TTS (the new path with reshape)."""
    brocas = call_brocas(utterance["text"])
    if not brocas["ok"]:
        return {
            "path": "B_with_brocas",
            "ok": False,
            "t_brocas": brocas["wall_s"],
            "t_brocas_ttft": brocas["ttft_s"],
            "t_brocas_tps": brocas["tps"],
            "t_tts": None,
            "t_total": brocas["wall_s"],
            "input_text_len": len(utterance["text"]),
            "brocas_text_len": 0,
            "brocas_text": "",
            "audio_bytes": 0,
            "error": brocas["error"],
        }
    tts = call_tts(brocas["content"])
    return {
        "path": "B_with_brocas",
        "ok": tts["ok"],
        "t_brocas": brocas["wall_s"],
        "t_brocas_ttft": brocas["ttft_s"],
        "t_brocas_tps": brocas["tps"],
        "t_tts": tts["elapsed_s"],
        "t_total": round(brocas["wall_s"] + tts["elapsed_s"], 3),
        "input_text_len": len(utterance["text"]),
        "brocas_text_len": len(brocas["content"]),
        "brocas_text": brocas["content"],
        "tokens_generated": brocas["tokens_generated"],
        "audio_bytes": tts["audio_bytes"],
        "error": tts["error"],
    }


# --- Aggregation ---

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
    pct = percentiles(vals)
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 3),
        "stdev": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0,
        "min": round(min(vals), 3),
        "max": round(max(vals), 3),
        **pct,
    }


# --- Main ---

def health_check():
    print("\n--- Health check ---")
    for label, url in [("TTS-3457 /health", TTS_HEALTH), ("LLM-3460 /health", LLM_HEALTH)]:
        status, body, elapsed, err = http_get(url)
        if err:
            print(f"  ✗ {label}: ERROR {err}")
        else:
            try:
                j = json.loads(body.decode("utf-8"))
            except Exception:
                j = {"raw": body[:200].decode("utf-8", errors="replace")}
            print(f"  ✓ {label}: {status} in {elapsed:.3f}s — {json.dumps(j)[:200]}")


def warmup():
    print("\n--- Warmup ---")
    for label, url in [("TTS /warmup", TTS_WARMUP), ("LLM /warmup", LLM_WARMUP)]:
        status, body, elapsed, err = http_get(url, timeout=180)
        if err:
            print(f"  ✗ {label}: {err}")
        else:
            try:
                j = json.loads(body.decode("utf-8"))
            except Exception:
                j = {"raw": body[:120].decode("utf-8", errors="replace")}
            print(f"  ✓ {label}: {status} in {elapsed:.3f}s — {json.dumps(j)[:200]}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=3, help="Number of runs per utterance per path")
    p.add_argument("--utterances", help="Path to JSON file with custom utterances list")
    p.add_argument("--warmup", action="store_true", help="Hit /warmup on both servers first")
    p.add_argument("--output", help="Save full results JSON to this path")
    p.add_argument("--skip-health", action="store_true", help="Skip /health probe")
    args = p.parse_args()

    if not args.skip_health:
        health_check()
    if args.warmup:
        warmup()

    utterances = DEFAULT_UTTERANCES
    if args.utterances:
        with open(args.utterances) as f:
            utterances = json.load(f)
    print(f"\n--- Benchmarking {len(utterances)} utterance(s) × {args.runs} run(s) × 2 paths ---\n")

    records = []
    for utt in utterances:
        print(f"=== {utt['id']} ({len(utt['text'])} chars) ===")
        for run_idx in range(args.runs):
            print(f"  run {run_idx+1}/{args.runs}:")
            a = run_path_a(utt)
            a.update({"utterance_id": utt["id"], "run": run_idx})
            print(f"    A (no-Broca's): t_total={a['t_total']:.3f}s "
                  f"audio={a['audio_bytes']}B ok={a['ok']}"
                  f"{' err=' + a['error'] if a['error'] else ''}")
            records.append(a)

            b = run_path_b(utt)
            b.update({"utterance_id": utt["id"], "run": run_idx})
            if b["ok"]:
                print(f"    B (with Broca's): t_brocas={b['t_brocas']:.3f}s "
                      f"(ttft={b['t_brocas_ttft']}, tps={b['t_brocas_tps']}) "
                      f"t_tts={b['t_tts']:.3f}s t_total={b['t_total']:.3f}s "
                      f"len={b['input_text_len']}→{b['brocas_text_len']}")
                delta = b["t_total"] - a["t_total"] if a["ok"] else None
                if delta is not None:
                    print(f"    Δ Broca's cost: {delta:+.3f}s")
            else:
                print(f"    B (with Broca's): FAILED — {b['error']}")
            records.append(b)

    print("\n--- Aggregate (ok runs only) ---")
    a_recs = [r for r in records if r["path"] == "A_no_brocas"]
    b_recs = [r for r in records if r["path"] == "B_with_brocas"]
    summary = {
        "path_a_no_brocas": {
            "t_total": aggregate(a_recs, "t_total"),
        },
        "path_b_with_brocas": {
            "t_brocas": aggregate(b_recs, "t_brocas"),
            "t_tts": aggregate(b_recs, "t_tts"),
            "t_total": aggregate(b_recs, "t_total"),
        },
    }
    # Δ aggregate: only where both A and B succeeded for same utterance/run
    deltas = []
    by_key = {(r["utterance_id"], r["run"]): r for r in records}
    seen = set()
    for r in records:
        key = (r["utterance_id"], r["run"])
        if key in seen:
            continue
        seen.add(key)
        a = next((x for x in records if x["utterance_id"] == key[0] and x["run"] == key[1] and x["path"] == "A_no_brocas"), None)
        b = next((x for x in records if x["utterance_id"] == key[0] and x["run"] == key[1] and x["path"] == "B_with_brocas"), None)
        if a and b and a.get("ok") and b.get("ok"):
            deltas.append(b["t_total"] - a["t_total"])
    if deltas:
        sd = sorted(deltas)
        summary["delta_brocas_cost"] = {
            "n": len(deltas),
            "mean": round(statistics.fmean(deltas), 3),
            "stdev": round(statistics.pstdev(deltas), 3) if len(deltas) > 1 else 0.0,
            "min": round(min(deltas), 3),
            "max": round(max(deltas), 3),
            **percentiles(deltas),
        }

    print(json.dumps(summary, indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "version": "v1",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "utterances": utterances,
                "records": records,
                "summary": summary,
            }, f, indent=2)
        print(f"\nFull results saved to: {args.output}")


if __name__ == "__main__":
    main()
