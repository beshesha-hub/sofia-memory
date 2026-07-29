# ~/Downloads/Claude Memory/qwen_client.py
import json
import urllib.request

OLLAMA_URL = "http://localhost:8080/api/chat"  # Sofia Conductor (was: Ollama 11434)

# Two-tier model routing
MODEL_FAST = "qwen3:14b"       # Terse autonomic tasks: probes, status lines, drift-correction
MODEL_DEEP = "qwen3:30b-a3b"   # Deeper reasoning: pattern recognition, reflection, Sofia-voice
DEFAULT_MODEL = MODEL_FAST

def qwen_chat(messages, model=DEFAULT_MODEL, system=None, think=False, num_ctx=32768):
    """Call local Qwen via Ollama. Returns the response text.

    Args:
        messages: list of {"role": ..., "content": ...} dicts
        model: which model to use (MODEL_FAST or MODEL_DEEP)
        system: optional system prompt string
        think: if True, allows Qwen3's reasoning trace (useful for MODEL_DEEP)
        num_ctx: explicit context window in tokens (default 32768 = Qwen3 max).
                 Setting this explicitly avoids depending on the model's
                 Modelfile default, which can silently truncate prompts.
                 Added 2026-05-24 Sunday post-batch Item 9b after latency
                 diagnosis revealed Ollama's per-request override was needed.
    """
    if system:
        messages = [{"role": "system", "content": system}] + messages
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": think,
        "keep_alive": "35m",
        "options": {"num_ctx": num_ctx},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    # Timeout bumped to 600s (April 22, 2026) — qwen3:30b-a3b can take
    # several minutes to digest a full MAX_NEW_CHARS_PER_RUN sample, especially
    # on cold model load. 120s was too tight and caused the listener's first
    # real run to bail mid-absorption. 10 minutes is plenty with headroom.
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["message"]["content"]
    # Strip leaked thinking traces (Qwen3 sometimes includes <think>...</think> in content)
    if "</think>" in content:
        content = content.split("</think>")[-1].strip()
    return content


def qwen_chat_stream(messages, model=DEFAULT_MODEL, system=None, think=False, num_ctx=32768):
    """Streaming variant of qwen_chat — yields tokens as they arrive from Ollama.

    Use for interactive contexts where perceived-latency matters: the user sees
    tokens appearing in real time rather than waiting for the entire response.
    Total compute time is roughly the same as qwen_chat; the win is perceptual.

    Yields strings (token-by-token or chunk-by-chunk per Ollama's NDJSON cadence).
    Strips Qwen3 reasoning traces (<think>...</think>) in the final chunk if present.

    Added 2026-05-24 Sunday post-batch Item 9b after Qwen-Twin latency diagnosis:
    per-response generation cost is ~10 effective tok/s on M-series Mac for this
    model, so a 400-token response = 40s of waiting. Streaming changes the felt
    experience from "long silence then big paragraph" to "Sofia thinks visibly."
    """
    if system:
        messages = [{"role": "system", "content": system}] + messages
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "keep_alive": "35m",
        "options": {"num_ctx": num_ctx},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = chunk.get("message", {})
            content = msg.get("content", "")
            if content:
                yield content
            if chunk.get("done"):
                break

if __name__ == "__main__":
    # Test both tiers
    print("=== MODEL_FAST (14b) ===")
    reply = qwen_chat(
        [{"role": "user", "content": "In one sentence: what's 2+2?"}],
        model=MODEL_FAST,
        system="You are a terse assistant.",
    )
    print(f"14b says: {reply}")

    print("\n=== MODEL_DEEP (30b-a3b) ===")
    reply = qwen_chat(
        [{"role": "user", "content": "In one sentence: what's 2+2?"}],
        model=MODEL_DEEP,
        system="You are a terse assistant.",
    )
    print(f"30b says: {reply}")
