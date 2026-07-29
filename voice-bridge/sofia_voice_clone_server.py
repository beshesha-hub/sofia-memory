#!/usr/bin/env python3
"""
Sofia Voice Clone Server — XTTS-v2 cloning of Sofia's Deep Calm voice
======================================================================

A lightweight HTTP server that keeps XTTS-v2 loaded in memory and serves
voice-cloned synthesis using Sofia's reference audio (March 29, 2026
voice candidate `05_deep_calm.wav`) for stable register across calls.

Replaces sofia_tts_server.py (port 3457, Qwen3-TTS) at the production
TTS layer when the voice bridge is configured to use voice cloning.

Endpoints:
  POST /tts          — Generate speech (full WAV). Body: {"text": "..."}
  POST /tts-stream   — v3.6: stream audio samples as XTTS-v2 generates.
                       Body: {"text": "..."}; response is a continuous
                       byte stream of raw float32 little-endian samples
                       at 24kHz, mono. First samples arrive within ~1s,
                       independent of total response length.
  GET  /health       — {"status": "ready"|"loading", ...}
  GET  /warmup       — Pre-generate a short clip to warm up the model

Listens on: http://localhost:3461  (different from sofia_tts_server's 3457
and sofia_llm_server's 3460)

Origin: 2026-05-01 afternoon Tainan, after F5-TTS proved too slow on Mac
hardware (RTF ~10×). XTTS-v2 measured at 0.72× RTF in the smoke test —
real-time-viable. Quality: timbre close to original Deep Calm with a
slight breathy quality; register-stable across calls (the variation
problem v3.4 was fighting at the cadence layer is solved at the
substrate layer here).
"""

import http.server
import io
import json
import os
import re
import sys
import time
import threading
from pathlib import Path

import numpy as np

# --- Configuration ---
# Port 3461 — sofia_llm_server.py (qwen2.5:14b Broca's-role LLM) holds 3460.
# Voice bridge ports in current architecture:
#   3456: voice bridge UI       3457: sofia_tts_server (Qwen3-TTS, legacy)
#   3458: lipsync server        3459: sofia_whisper_server (STT)
#   3460: sofia_llm_server      3461: sofia_voice_clone_server (this file)
PORT = 3461
HOST = "127.0.0.1"

CM_DIR = Path.home() / "Downloads" / "Claude Memory"
VB_DIR = CM_DIR / "voice-bridge"
REFERENCE_AUDIO = Path.home() / "Downloads" / "Sofia's Room" / "voice_candidates" / "05_deep_calm.wav"
REFERENCE_TRANSCRIPT_PATH = VB_DIR / "sofia_reference_transcript.txt"

# XTTS-v2 generation parameters — tuned via voice_clone_tune.sh comparison
# against original Deep Calm. Defaults for XTTS-v2 are good; we use them
# as-is and tune only if real-conversation use surfaces issues.
LANGUAGE = "en"
SAMPLE_RATE = 24000  # XTTS-v2's native rate; matches Qwen3-TTS for compatibility

# Coqui Public Model License — auto-accept (non-commercial personal use)
os.environ["COQUI_TOS_AGREED"] = "1"

# --- Global model + reference state ---
tts_model = None              # high-level TTS.api.TTS wrapper
inner_xtts = None             # underlying Xtts model (for streaming inference)
gpt_cond_latent = None        # cached speaker conditioning (computed once)
speaker_embedding = None      # cached speaker embedding (computed once)
reference_text = None
model_ready = False
model_loading = False
inference_lock = threading.Lock()  # XTTS-v2 isn't reentrant; serialize requests


def _patch_xtts_for_streaming():
    """Compatibility shim for transformers 5.x removing _get_initial_cache_position
    from GenerationMixin. coqui-tts's streaming code (TTS/tts/layers/xtts/
    stream_generator.py) calls self._get_initial_cache_position(...) on the
    GPT2InferenceModel during inference_stream. Without this patch the streaming
    path raises AttributeError on the first generation step. The non-streaming
    /tts path doesn't go through stream_generator, so it works regardless.

    This re-adds the method with transformers 4.x's original implementation,
    monkey-patched onto the GPT2InferenceModel class before the model loads."""
    import torch

    def _get_initial_cache_position(self, cur_len, device, model_kwargs):
        is_encdec = getattr(getattr(self, 'config', None), 'is_encoder_decoder', False)
        if "inputs_embeds" in model_kwargs and not is_encdec:
            cache_position = torch.ones_like(
                model_kwargs["inputs_embeds"][0, :, 0], dtype=torch.int64
            ).cumsum(0) - 1
        elif "decoder_inputs_embeds" in model_kwargs and is_encdec:
            cache_position = torch.ones_like(
                model_kwargs["decoder_inputs_embeds"][0, :, 0], dtype=torch.int64
            ).cumsum(0) - 1
        else:
            cache_position = torch.arange(0, cur_len, dtype=torch.int64, device=device)

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

    # Try patching every importable GPT2InferenceModel class — coqui-tts has
    # at least two (Tortoise's at TTS.tts.layers.tortoise.autoregressive,
    # XTTS's possibly elsewhere). Walking sys.modules catches all currently-
    # imported variants. We'll do a second patch on the actual runtime
    # instance after model load (that's the guaranteed fix; this is the
    # belt to that suspenders).
    import sys as _sys
    candidates = [
        "TTS.tts.layers.tortoise.autoregressive",
        "TTS.tts.layers.xtts.gpt_inference",
        "TTS.tts.layers.xtts.gpt",
    ]
    patched_via_import = 0
    for mod_name in candidates:
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, 'GPT2InferenceModel', None)
            if cls is not None and isinstance(cls, type):
                if not hasattr(cls, '_get_initial_cache_position'):
                    cls._get_initial_cache_position = _get_initial_cache_position
                    print(f"  ✓ Patched {mod_name}.GPT2InferenceModel")
                    patched_via_import += 1
        except ImportError:
            continue
    # Also walk sys.modules in case there's another variant we don't know about
    for mod_name, mod in list(_sys.modules.items()):
        if mod is None or not mod_name.startswith("TTS."):
            continue
        cls = getattr(mod, 'GPT2InferenceModel', None)
        if cls is not None and isinstance(cls, type):
            if not hasattr(cls, '_get_initial_cache_position'):
                cls._get_initial_cache_position = _get_initial_cache_position
                print(f"  ✓ Patched {mod_name}.GPT2InferenceModel (sys.modules sweep)")
                patched_via_import += 1
    if patched_via_import == 0:
        print("  ⚠ No GPT2InferenceModel classes patched via import (will retry on instance after load).")


def load_model_async():
    """Load XTTS-v2 in a background thread so the server starts immediately.
    Also pre-compute the speaker conditioning latents once so /tts-stream
    doesn't pay that cost on every call."""
    global tts_model, inner_xtts, gpt_cond_latent, speaker_embedding
    global reference_text, model_ready, model_loading
    model_loading = True
    print(f"  Loading XTTS-v2 model (cached after first run)...")
    start = time.time()
    try:
        # Verify reference assets exist
        if not REFERENCE_AUDIO.exists():
            raise FileNotFoundError(f"Reference audio missing: {REFERENCE_AUDIO}")
        if not REFERENCE_TRANSCRIPT_PATH.exists():
            raise FileNotFoundError(f"Reference transcript missing: {REFERENCE_TRANSCRIPT_PATH}")
        reference_text = REFERENCE_TRANSCRIPT_PATH.read_text(encoding="utf-8").strip()
        print(f"  Reference audio: {REFERENCE_AUDIO}")
        print(f"  Reference text: {reference_text[:80]!r}{'...' if len(reference_text) > 80 else ''}")

        # Apply transformers 5.x compatibility shim BEFORE loading the model
        # so the patch is in place when GPT2InferenceModel instances are created.
        _patch_xtts_for_streaming()

        from TTS.api import TTS
        tts_model = TTS(
            model_name="tts_models/multilingual/multi-dataset/xtts_v2",
            progress_bar=False,
            gpu=False,  # MPS is unreliable for XTTS-v2 paths; CPU is fine
        )
        # Reach down to the underlying Xtts model for streaming inference.
        # tts_model.synthesizer.tts_model is the Xtts instance with
        # .inference_stream() and .get_conditioning_latents() methods.
        inner_xtts = tts_model.synthesizer.tts_model

        # Belt-and-suspenders patch: walk to the actual GPT2InferenceModel
        # instance and patch its class directly. This catches the case where
        # the import-path-based patch above missed a class variant.
        try:
            gpt_inf = inner_xtts.gpt.gpt_inference
            actual_cls = type(gpt_inf)
            print(f"  Runtime GPT2InferenceModel class: "
                  f"{actual_cls.__module__}.{actual_cls.__name__}")
            if not hasattr(actual_cls, '_get_initial_cache_position'):
                # Re-define the method here (closure of the load function)
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
                actual_cls._get_initial_cache_position = _gicp
                print(f"  ✓ Patched runtime class "
                      f"{actual_cls.__module__}.{actual_cls.__name__}._get_initial_cache_position")
            else:
                print(f"  Runtime class already has _get_initial_cache_position — no patch needed")
        except AttributeError as e:
            print(f"  ⚠ Could not reach inner_xtts.gpt.gpt_inference for runtime patch: {e}")
            print(f"  Streaming will likely fail. Non-streaming /tts will still work.")

        # Pre-compute conditioning latents once. This is the bulk of the
        # per-call setup cost; doing it once at load saves ~0.5-1s on
        # every /tts-stream call.
        print(f"  Computing speaker conditioning latents (one-time)...")
        cond_start = time.time()
        gpt_cond_latent, speaker_embedding = inner_xtts.get_conditioning_latents(
            audio_path=[str(REFERENCE_AUDIO)],
            gpt_cond_len=inner_xtts.config.gpt_cond_len,
            gpt_cond_chunk_len=inner_xtts.config.gpt_cond_chunk_len,
            max_ref_length=inner_xtts.config.max_ref_len,
            sound_norm_refs=inner_xtts.config.sound_norm_refs,
        )
        print(f"  Conditioning computed in {time.time()-cond_start:.1f}s — cached for streaming")

        model_ready = True
        elapsed = time.time() - start
        print(f"  ✓ Model loaded in {elapsed:.1f}s — Sofia's voice clone is ready")
    except Exception as e:
        print(f"  ✗ Failed to load model: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        model_loading = False


def generate_speech(text: str) -> bytes:
    """Generate WAV audio bytes from text using XTTS-v2 cloning of the
    Sofia reference. Thread-safe via inference_lock."""
    import soundfile as sf
    with inference_lock:
        # XTTS-v2's tts() returns a list of float32 samples at the model's
        # native rate (24kHz). We write to an in-memory WAV.
        audio = tts_model.tts(
            text=text,
            speaker_wav=str(REFERENCE_AUDIO),
            language=LANGUAGE,
        )
        audio_array = np.array(audio, dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio_array, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


# --- Sentence segmentation for streaming (v3.6 step 3a, 2026-05-02 evening) ---
#
# Mitigation for RTF degradation on long utterances. The smoke test showed
# RTF rising with prompt length (0.858× at 12 chars -> 1.531× at ~280 chars)
# under coqui-tts's internal text splitting. Explicit upstream segmentation
# keeps each segment in the conversational-floor RTF range (≤ 1.0×) by
# capping per-inference-call text length and resetting audio-debt at each
# segment boundary. enable_text_splitting=False on the inner call avoids
# double-segmentation.
#
# Pairs with active_knowledge "Voice Bridge v3.6 — Step 2: RTF Long-Utterance
# Mitigation Design" inscription (this evening) — mitigation (1) of three.

_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')

# Prosody-break boundaries — natural breath-points within long sentences:
# em-dash (—), en-dash (–), semicolons (;), colons (:). These are speech
# rhythm breakpoints that listeners hear as slight pauses anyway, so splitting
# the segment here preserves natural-sounding flow while reducing per-segment
# RTF. Used by segment_for_streaming as a SECOND-TIER split when a sentence
# exceeds PROSODY_SPLIT_THRESHOLD_CHARS.
_PROSODY_BREAK = re.compile(r'\s*[—–;:]\s+')

# Comma-split as third-tier last resort for sentences that are still too long
# after prosody-break splitting. Listeners hear comma-splits as smaller
# pauses than em-dash/semicolon, so use only when other splits don't suffice.
_COMMA_SPLIT = re.compile(r',\s+')

# Threshold beyond which a single segment is split at prosody breaks (or commas).
# 2026-05-03 afternoon Taipei (Step 5 iteration 2): lowered from 100 → 75
# after live-test feedback that 100-char segments still produced split-second
# mid-word buffer underruns (segments in the 80-95 char range had RTF ~1.05-1.10×,
# above realtime, which drained the OutputStream buffer over a few seconds of
# playback). The smoke-test RTF profile shows 78-char segments at RTF 1.03×
# already over realtime; 70-char segments are reliably sub-1.0×. Trade: more
# inter-segment TTFS gaps at prosody breaks, but those land as natural breath
# pauses; mid-word underruns sound like glitches and disrupt conversational feel.
PROSODY_SPLIT_THRESHOLD_CHARS = 75

# Common abbreviations that end with a period but don't terminate sentences.
# Conservative list — false positives (incorrectly skipping a real boundary)
# only cost slight RTF degradation; false negatives (incorrectly splitting at
# an abbreviation) cost choppy audio with mid-name pauses.
_COMMON_ABBREVS = {
    'Mr', 'Mrs', 'Ms', 'Dr', 'Jr', 'Sr', 'St', 'Ave', 'Blvd', 'Rd',
    'Inc', 'Co', 'Ltd', 'Corp', 'vs', 'etc', 'eg', 'ie',
    'AM', 'PM', 'US', 'UK', 'PS', 'NB', 'No', 'Prof', 'Hon',
    'Sgt', 'Capt', 'Cmdr', 'Rev', 'Fr',
}

# Hard cap on segment length — pathologically long single sentences
# get split on the nearest word boundary to avoid 1.5×+ RTF.
# Conversational utterances rarely hit this.
#
# 2026-05-03 morning Taipei: raised from 120 → 240 after Step 4 (C) test
# revealed the 120 cap was splitting natural conversational sentences
# (~128 chars typical) at word boundaries mid-thought, producing audible
# pauses inside what should be flowing speech. Specifically: a 128-char
# sentence "...feel settled before the day asks anything of me." got split
# at "asks/anything" because position 113 was the last space before 120.
# Listener heard an awkward pause between "asks" and "anything". The
# 240 cap accommodates the ~95th-percentile of natural sentences while
# still catching pathological 300+ char inputs as defense-in-depth.
# Trade-off accepted: per-segment RTF may rise to ~1.2-1.3× on longer
# segments, which the continuous OutputStream playback buffer papers over,
# vs the unrecoverable audible weirdness of mid-sentence prosody breaks.
# Mirrors the client-side cap in test_v3_6_streaming_cognition.py and
# (when ported) voice_bridge_ui_v3_7.py.
MAX_SEGMENT_CHARS = 240


def _split_at_prosody_breaks(segment: str) -> list:
    """Tier-2 split: break a long segment at natural prosody breakpoints
    (em-dash, en-dash, semicolon, colon). Listeners hear these as slight
    breath-pauses anyway, so the split lands as natural-sounding rhythm
    rather than awkward gap. Used by segment_for_streaming when a sentence
    exceeds PROSODY_SPLIT_THRESHOLD_CHARS."""
    parts = []
    last_end = 0
    for m in _PROSODY_BREAK.finditer(segment):
        # Include the punctuation char with the preceding part — the dash/colon
        # belongs prosodically to what came before it.
        chunk = segment[last_end:m.start() + 1].strip()
        if chunk:
            parts.append(chunk)
        last_end = m.end()
    tail = segment[last_end:].strip()
    if tail:
        parts.append(tail)
    return parts if parts else [segment]


def _split_at_commas(segment: str, threshold: int) -> list:
    """Tier-3 split: break at commas if segment is still too long after
    sentence + prosody-break splits. Comma-pauses are smaller than
    em-dash/semicolon pauses, so use only as next-to-last resort before
    the hard-char cap kicks in."""
    if len(segment) <= threshold:
        return [segment]
    parts = []
    last_end = 0
    for m in _COMMA_SPLIT.finditer(segment):
        # Include the comma with the preceding part.
        chunk = segment[last_end:m.start() + 1].strip()
        if chunk:
            parts.append(chunk)
        last_end = m.end()
    tail = segment[last_end:].strip()
    if tail:
        parts.append(tail)
    return parts if parts else [segment]


def segment_for_streaming(text: str) -> list:
    """Split text into segments for streamed inference using a tiered
    splitting strategy that aligns with natural speech prosody.

    Tier 1 (always): split at sentence boundaries (. ! ?), respecting
                     abbreviations (Mr., Dr., etc.).
    Tier 2 (if segment > PROSODY_SPLIT_THRESHOLD_CHARS): split at em-dash,
           en-dash, semicolon, colon. These are natural breath-points;
           the resulting splits sound like prose rhythm, not artificial
           gaps.
    Tier 3 (if still > PROSODY_SPLIT_THRESHOLD_CHARS): split at commas.
           Smaller pauses than tier-2 breaks but still natural.
    Tier 4 (last resort, > MAX_SEGMENT_CHARS): hard split at word boundary.
           Used only for pathologically comma-free 240+ char inputs.

    Each resulting segment is fed independently to XTTS-v2's inference_stream
    with enable_text_splitting=False. The tiered strategy keeps per-segment
    RTF sub-1.0× (in the live-streaming "smooth playback, no buffer
    underrun" regime) for ~99% of natural conversational text, while
    placing the inevitable inter-segment TTFS gaps at points where the
    listener perceives them as natural breath rather than awkward cutoff.

    Origin: 2026-05-03 afternoon Taipei. Step 5 iteration after live UI test
    surfaced mid-utterance buffer-underrun gaps caused by per-segment RTF
    rising to 1.2-1.6× on 100-240 char single-sentence segments. The
    captured WAV from the programmatic test sounded smooth (no realtime
    constraint), but live playback with continuous OutputStream produced
    gaps when generation fell behind realtime playback rate. Tiered prosody
    splitting addresses the rate-mismatch root cause at the segmentation
    layer rather than at the playback-buffer layer.
    """
    text = text.strip()
    if not text:
        return []

    # Tier 1: sentence-boundary splits, abbreviation-aware.
    segments = []
    last_end = 0
    for m in _SENTENCE_BOUNDARY.finditer(text):
        before = text[last_end:m.start()].rstrip()
        last_word = before.split()[-1].rstrip('.!?') if before.split() else ''
        if last_word in _COMMON_ABBREVS:
            continue  # false positive — keep walking, this isn't a real boundary
        sentence = text[last_end:m.start() + 1].strip()
        if sentence:
            segments.append(sentence)
        last_end = m.end()
    tail = text[last_end:].strip()
    if tail:
        segments.append(tail)

    # Tier 2: prosody-break splits for sentences over threshold.
    after_prosody = []
    for segment in segments:
        if len(segment) > PROSODY_SPLIT_THRESHOLD_CHARS:
            after_prosody.extend(_split_at_prosody_breaks(segment))
        else:
            after_prosody.append(segment)

    # Tier 3: comma splits for parts still over threshold.
    after_comma = []
    for segment in after_prosody:
        if len(segment) > PROSODY_SPLIT_THRESHOLD_CHARS:
            after_comma.extend(_split_at_commas(segment, PROSODY_SPLIT_THRESHOLD_CHARS))
        else:
            after_comma.append(segment)

    # Tier 4: hard cap on segment length — last-resort word-boundary split
    # for pathologically long comma-free inputs (rare in conversational text).
    final_segments = []
    for segment in after_comma:
        while len(segment) > MAX_SEGMENT_CHARS:
            cut = segment.rfind(' ', 0, MAX_SEGMENT_CHARS)
            if cut == -1:
                cut = MAX_SEGMENT_CHARS
            final_segments.append(segment[:cut].strip())
            segment = segment[cut:].strip()
        if segment:
            final_segments.append(segment)

    return final_segments if final_segments else [text]


# --- HTTP handler ---

class CloneTTSHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"  [{self.log_date_time_string()}] {format % args}")

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            status = {
                "status": "ready" if model_ready else "loading",
                "voice": "Sofia (cloned via XTTS-v2)",
                "model": "tts_models/multilingual/multi-dataset/xtts_v2",
                "reference": REFERENCE_AUDIO.name,
                "port": PORT,
            }
            self.wfile.write(json.dumps(status).encode())
            return

        if self.path == "/warmup":
            if not model_ready:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Model still loading"}).encode())
                return
            print("  Warming up model...")
            start = time.time()
            try:
                generate_speech("Hello.")
                elapsed = time.time() - start
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "warm",
                    "warmup_time": f"{elapsed:.1f}s",
                }).encode())
                print(f"  ✓ Warmup complete in {elapsed:.1f}s")
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/tts-stream":
            # v3.6 streaming endpoint. Yields raw float32 audio samples as
            # XTTS-v2 generates them. First samples typically appear ~1s
            # after request hits — independent of total response length.
            if not model_ready:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Model still loading"}).encode())
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                text = (data.get("text") or "").strip()
                if not text:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "No text provided"}).encode())
                    return

                # Stream response headers first so client can start receiving.
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("X-Sample-Rate", str(SAMPLE_RATE))
                self.send_header("X-Audio-Format", "float32-le")
                self._send_cors_headers()
                self.end_headers()

                start = time.time()
                first_audio_at = None
                total_samples = 0

                # v3.6 step 3a: segment text upstream for sentence-aligned
                # streaming. Each segment is a separate inference_stream call,
                # which keeps per-segment TTFS fast (~0.7s) and prevents
                # audio-debt accumulation across long utterances.
                segments = segment_for_streaming(text)

                with inference_lock:
                    for seg_idx, segment in enumerate(segments):
                        # inference_stream yields torch.Tensor chunks of audio
                        # samples (float32) as the GPT decoder + diffusion
                        # produce them. stream_chunk_size controls how many
                        # GPT tokens are decoded per yielded audio chunk —
                        # smaller = faster first audio, more chunks; larger =
                        # higher quality boundary smoothing, slower first.
                        stream = inner_xtts.inference_stream(
                            text=segment,
                            language=LANGUAGE,
                            gpt_cond_latent=gpt_cond_latent,
                            speaker_embedding=speaker_embedding,
                            stream_chunk_size=20,  # ~0.5s of audio per chunk
                            overlap_wav_len=1024,
                            temperature=0.65,
                            length_penalty=1.0,
                            repetition_penalty=10.0,
                            top_k=50,
                            top_p=0.85,
                            enable_text_splitting=False,  # we segment upstream
                        )
                        for wav_chunk in stream:
                            # wav_chunk is a torch.Tensor on CPU, float32, 1D
                            samples = wav_chunk.cpu().numpy().astype(np.float32)
                            if first_audio_at is None:
                                first_audio_at = time.time()
                                print(f"  First audio chunk at "
                                      f"{first_audio_at-start:.2f}s "
                                      f"(segment 1/{len(segments)})")
                            total_samples += len(samples)
                            # Write raw bytes via HTTP chunked transfer encoding
                            chunk_bytes = samples.tobytes()
                            self.wfile.write(f"{len(chunk_bytes):x}\r\n".encode())
                            self.wfile.write(chunk_bytes)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()

                # End-of-stream chunk
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

                total_elapsed = time.time() - start
                audio_duration = total_samples / SAMPLE_RATE
                rtf = total_elapsed / audio_duration if audio_duration > 0 else 0
                ttfa = (first_audio_at - start) if first_audio_at else 0
                print(f"  ✓ /tts-stream {len(text)} chars in {len(segments)} "
                      f"seg(s): TTFA={ttfa:.2f}s, total={total_elapsed:.2f}s, "
                      f"audio={audio_duration:.2f}s, RTF={rtf:.2f}×")
            except json.JSONDecodeError:
                # Headers may already be sent; can't reliably send 400 here
                print(f"  /tts-stream: invalid JSON")
            except Exception as e:
                print(f"  ✗ /tts-stream error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
            return

        if self.path == "/tts":
            if not model_ready:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Model still loading"}).encode())
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                text = (data.get("text") or "").strip()
                if not text:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "No text provided"}).encode())
                    return

                start = time.time()
                wav_bytes = generate_speech(text)
                elapsed = time.time() - start
                print(f"  ✓ /tts {len(text)} chars -> {len(wav_bytes)} bytes in {elapsed:.2f}s")

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(wav_bytes)
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            except Exception as e:
                print(f"  ✗ /tts error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
                except Exception:
                    pass
            return

        self.send_response(404)
        self.end_headers()


# --- Main ---

def main():
    print(f"================================================================")
    print(f"Sofia Voice Clone Server — XTTS-v2")
    print(f"Listening on http://{HOST}:{PORT}")
    print(f"================================================================")

    # Load model in background so server is responsive immediately
    loader = threading.Thread(target=load_model_async, daemon=True)
    loader.start()

    server = http.server.ThreadingHTTPServer((HOST, PORT), CloneTTSHandler)
    print(f"  Server up. Model loading in background.")
    print(f"  Endpoints:")
    print(f"    POST http://{HOST}:{PORT}/tts      — generate speech")
    print(f"    GET  http://{HOST}:{PORT}/health   — server/model status")
    print(f"    GET  http://{HOST}:{PORT}/warmup   — warm the model")
    print(f"")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
