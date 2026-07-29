# voice-bridge / TOOLBOX

*Catalog of diagnostic + utility scripts in `~/Downloads/Claude Memory/voice-bridge/`. Created 2026-05-21 ~18:35 Taipei per Barak's request to keep diagnostic tools labeled and discoverable for future use (especially during the LA trip window May 27 - August 27 2026 when sessions may be shorter / less predictable / under more pressure to resolve issues quickly).*

*This file is the canonical "what's in the diagnostic drawer" reference. When something breaks in voice-bridge or Standalone UI, check here first to see if there's an existing tool for the situation. Updated whenever a new diagnostic script is added.*

---

## Quick reference table

| Tool | Purpose | When to run | Run command |
|------|---------|------------|-------------|
| `diagnose_api_key.sh` | Disambiguate Anthropic API key 401 errors — distinguish loading-path issue vs stale shell env vs .env corruption vs keychain interference vs actual key rotation | Standalone UI returns 401; OR pre-trip readiness check; OR routine monthly verification | `./diagnose_api_key.sh` |
| `list_models.py` | List currently-available Anthropic models + check whether `DEFAULT_MODEL` in cowork_api/config.py is still valid; surfaces `-latest` aliases if Anthropic ships any | When suspecting model deprecation; OR after Anthropic announces new model releases; OR pre-trip readiness check | `.venv-v3.6/bin/python list_models.py` |
| `restart_voice_bridge_stack.sh` | Clean stop + restart the 6 voice-bridge servers (TTS-3457, lipsync-3458, Whisper-3459, LLM-3460, voice-clone-3461, voiceprint-3462) | Server stack appears unhealthy; OR after voice-clone-server modifications; OR fresh boot | `./restart_voice_bridge_stack.sh` |
| `setup_v3_6_clean_venv.sh` | Bootstrap the `.venv-v3.6/` Python virtual environment with all required dependencies | First-time setup; OR after macOS migration; OR if venv gets corrupted | `./setup_v3_6_clean_venv.sh` |
| `benchmark_latency.py` | Latency benchmarking for TTS / voice path | Tuning voice-bridge performance | `.venv-v3.6/bin/python benchmark_latency.py` |
| `benchmark_streaming.py` | Streaming-mode benchmarking | Comparing streaming vs non-streaming voice paths | `.venv-v3.6/bin/python benchmark_streaming.py` |

---

## Detailed tool descriptions

### `diagnose_api_key.sh` — Standalone UI API key diagnostic

**Created**: 2026-05-21 ~18:00 Taipei, during Option A Standalone UI hardening for the LAX trip readiness check.

**Originating case**: `list_models.py` returned 401 invalid x-api-key against the Standalone UI auth surface despite Cowork-app being healthy. Multiple possible causes needed disambiguation (stale shell env override, .env corruption, keychain interference, key rotation). Script runs all checks in sequence so the actual cause is unambiguous.

**What it does** (9 steps, sanitized output — only first 10 + last 4 chars of any key shown):
1. Show `ANTHROPIC_API_KEY` value in `.env` (sanitized)
2. Hex dump of the line to catch hidden characters (BOM, CR-LF, smart quotes)
3. Show shell env value BEFORE sourcing `.env` (sanitized)
4. Show shell env value AFTER sourcing `.env` (sanitized) — if 3 ≠ 4, .env is clobbering
5. Check shell startup files (~/.zshrc, ~/.bashrc, etc.) for stray `ANTHROPIC_API_KEY=` exports
6. Find any other `.env` files in `~` that contain `ANTHROPIC_API_KEY=` (depth-limited search)
7. Check macOS keychain for entries mentioning anthropic
8. **The actual test**: call `client.models.list()` with the loaded key
9. **Bypass test**: read key directly from `.env`, pass to SDK explicitly, retry — disambiguates "key is fine, loading path is broken" vs "key really is invalid"

**Interpretation guide is printed at the end of the diagnostic run.** Most common failure mode caught: `.env` containing a wrong-value `ANTHROPIC_API_KEY=...` that clobbers the correct `.zshrc`-loaded value when sourced. See medical_reference.md §19 .env-Value-Misassignment-Clobbering.

**Safety**: read-only diagnostic. Doesn't modify any files. Safe to run any time.

---

### `list_models.py` — Anthropic model availability check

**Created**: 2026-05-21 ~18:50 Taipei, immediately after auth was confirmed working via `diagnose_api_key.sh`.

**Originating case**: Standalone UI's `DEFAULT_MODEL` in `cowork_api/config.py` was set to `'claude-sonnet-4-5'` — but the actual API model ID is `'claude-sonnet-4-5-20250929'` (with date stamp). The bare string `'claude-sonnet-4-5'` would have errored at launch. Script lists all currently-available models so configuration can be validated against reality rather than against assumed naming patterns.

**What it does**:
1. Calls `client.models.list()` and prints all available model IDs (sorted)
2. Filters and prints Sonnet variants specifically
3. Filters and prints any `-latest` aliases (none ship as of 2026-05-21, but Anthropic could add them later)
4. Imports `cowork_api.config.DEFAULT_MODEL` and verifies it's in the currently-available list with ✓ or ✗

**Interpretation**:
- ✓ on DEFAULT_MODEL → config is current; no change needed
- ✗ on DEFAULT_MODEL → update `cowork_api/config.py §DEFAULT_MODEL` to a current Sonnet from the list
- If `-latest` aliases appear in the future → consider switching to the alias and removing the fall-forward chain (alias would auto-resolve to current)

**Safety**: read-only diagnostic. Doesn't modify any files.

---

### `restart_voice_bridge_stack.sh` — Voice Bridge server stack

**Created**: 2026-05-03 morning Taipei, after the voice-clone-server modifications required cycling all 5 voice-bridge ports together.

**What it does**: stops any process on ports 3457-3462, then starts the 5 servers in background (TTS, lipsync, Whisper STT, LLM, voice-clone) with logs landing in `~/Downloads/Claude Memory/voice-bridge/logs/`.

**Deliberately does NOT start**:
- `sofia_tts_server.py` (port 3457, legacy Qwen3-TTS, broken with mlx_audio import error — superseded by voice-clone-server on 3461)
- `voice_bridge_ui_v3_8.py` (the UI — run separately via `~/Downloads/Claude Memory/launchers/voice_sofia.command` which is the canonical wake pathway)

**Safety**: terminates processes on ports 3457-3462 (any other process on those ports gets killed); safe in normal operation since those ports are reserved for voice-bridge.

---

### `setup_v3_6_clean_venv.sh` — Python venv bootstrap

**What it does**: Creates `.venv-v3.6/` and installs all required dependencies for voice-bridge.

**When to run**: first-time setup on a new machine; OR after macOS migration that broke the venv; OR if `.venv-v3.6/` somehow gets corrupted. Not for routine use.

**Safety**: writes to `.venv-v3.6/`; doesn't touch anything outside that directory.

---

### `benchmark_latency.py` + `benchmark_streaming.py` — Voice path benchmarks

**Created**: 2026-04-27 during voice-bridge V2 streaming-mode development.

**What they do**: Time the voice-bridge pipeline end-to-end with various configurations; output to `bench_results_*.json` files.

**When to run**: When tuning voice-bridge performance or comparing configurations. Not routine.

---

## Adding new tools

When a new diagnostic or utility script is created in `voice-bridge/`:

1. Add a row to the Quick reference table above
2. Add a Detailed tool description section below
3. Include: originating case (what failure or need prompted creation), what it does, when to run, safety (read-only vs mutating), interpretation guidance
4. Mirror this file to `~/Downloads/Emergency Retrieval/voice-bridge/TOOLBOX.md`

## Pairs structurally with

- `procedural_knowledge.md §Date-Source-Linking SOP / §Pre-Inscription Date-Check Protocol / §Deeper-Dive-Default Discipline / §Associational-Layer Discipline` — sibling procedural disciplines
- `medical_reference.md §18 Independent-Auth-Surface Drift` (the failure class `diagnose_api_key.sh` catches)
- `medical_reference.md §19 .env-Value-Misassignment-Clobbering` (the specific drift mechanism)
- `~/Downloads/Claude Memory/launchers/voice_sofia.command` — sibling named-launcher discipline (same principle: named tool > memorized command string)

---

*Maintained by interactive-Sofia per Barak's 2026-05-21 ~18:35 Taipei request to keep diagnostic scripts handy and labeled. Future tool additions per the maintenance procedure above.*


---

### `sofia_voiceprint_server.py` + `sofia_voiceprint_lib.py` + `enroll_speakers.py` — Speaker Recognition Pipeline

**Created**: 2026-05-22 in Tainan, Taiwan, during the pre-LAX-trip build. Pairs with `sofia_whisper_server.py` (port 3459) to give each utterance both a transcript AND a speaker tag — so Voice-Cousin knows whether Barak or Kay is speaking without either of them having to announce "this is Barak" / "this is Kay" at every turn.

**Originating case**: Pre-LAX-trip preparation. With Barak and Kay both expected to interact with Voice-Cousin during the LA window (May 27 - August 27), having Voice-Cousin distinguish speakers automatically removes per-turn friction. Per Barak's request 2026-05-22 morning Taipei.

**Architecture**:
- `sofia_voiceprint_lib.py` — shared library with `enroll_speaker()`, `identify_speaker()`, `audio_to_embedding()`, `load_voiceprints()`, `cosine_similarity()`. Uses Resemblyzer (256-d d-vector embeddings, ~70MB model, CPU-runnable, local-only). Storage in `voice-bridge/voiceprints/{speaker}.npz` files.
- `enroll_speakers.py` — one-shot script that enrolls Barak and Kay from canonical `voice-bridge/enrollment_audio/{barak,kay}/` audio. Prints pairwise diagnostic (cosine_similarity between centroids) as the empirical readout on enrollment quality.
- `sofia_voiceprint_server.py` — HTTP server on port **3462** (NOT 3461 — 3461 is voice-clone TTS in v3_8). Endpoints: `/enroll`, `/identify` (audio path), `/identify_bytes` (base64-encoded audio), `/list`, `/health`, `/warmup`. Matches the convention pattern of `sofia_whisper_server.py` (3459), `sofia_tts_server.py` (3457), `sofia_lipsync_server.py` (3458), `sofia_llm_server.py` (3460), `sofia_voice_clone_server.py` (3461).

**Mac-side setup (one-time, ~1-2 minutes)**:
```bash
cd "$HOME/Downloads/Claude Memory/voice-bridge"
.venv-v3.6/bin/pip install resemblyzer
# (Resemblyzer downloads ~70MB pretrained model on first import)
```

**Enroll Barak and Kay (one-time, ~10-20 seconds)**:
```bash
cd "$HOME/Downloads/Claude Memory/voice-bridge"
.venv-v3.6/bin/python enroll_speakers.py
```
Expected output: enrollment status for both speakers + the **pairwise diagnostic** (cosine_similarity between Barak's and Kay's centroids). Interpretation:
- **< 0.50** very well-separated (ideal)
- **0.50-0.65** well-separated (typical for distinct speakers)
- **0.65-0.75** moderately separable (watch threshold tuning)
- **> 0.75** poorly separated — fresh enrollment sample recommended

**Quick smoke-test (after enrollment)**:
```bash
# CLI mode
.venv-v3.6/bin/python sofia_voiceprint_lib.py list
.venv-v3.6/bin/python sofia_voiceprint_lib.py identify path/to/test_audio.mp3

# OR via server
.venv-v3.6/bin/python sofia_voiceprint_server.py &
curl http://127.0.0.1:3462/health
curl -X POST http://127.0.0.1:3462/identify \
     -H "Content-Type: application/json" \
     -d '{"audio_path":"/absolute/path/to/test.mp3"}'
```

**When the empirical signal says fresh enrollment is needed for Kay**: see `enrollment_audio/kay/PROVENANCE.md` for the two-substrate caveat (her sample was extracted from a video playback through the MacBook speakers + mic, not recorded directly) and the two cleaner alternatives (Kay records directly on the MacBook, OR Kay sends iPhone audio file directly without the video-playback loop).

**Coherence-of-Source-Conditions Principle anchor**: see `~/Downloads/Claude Memory/semantic_knowledge/current.md §Coherence-of-Source-Conditions Discipline` (2026-05-22) for the structural principle that governs enrollment-condition matching to inference-condition. Barak's audio-engineering domain (sixty-plus years of music recording) is the originating empirical anchor.

**Safety: unknown-speaker discipline**. The `/identify` endpoint returns `speaker: "unknown"` when the best-match cosine similarity is below the threshold (default 0.75). Voice-Cousin should treat `unknown` as "I don't know who's speaking, please confirm" rather than force-classifying — important when a third party (Chenhao, Linda calling, etc.) speaks.

**Integration with Voice-Cousin pipeline (next phase, after enrollment verified)**: voice_bridge_ui_v3_*.py currently calls `sofia_whisper_server` per utterance. Adding a parallel call to `sofia_voiceprint_server.POST /identify` (or `/identify_bytes` for in-memory audio) gives each transcript an attached `speaker` field. Phase-2 work after empirical signal from enrollment.

**Files**:
- `voice-bridge/sofia_voiceprint_lib.py`
- `voice-bridge/sofia_voiceprint_server.py`
- `voice-bridge/enroll_speakers.py`
- `voice-bridge/enrollment_audio/barak/barak_enrollment_2026-05-22.mp3` (66.6s, mono, 44.1kHz, direct MacBook mic recording)
- `voice-bridge/enrollment_audio/kay/kay_enrollment_2026-05-22.mp3` (80.7s, mono, 44.1kHz, two-substrate; see PROVENANCE.md)
- `voice-bridge/enrollment_audio/kay/PROVENANCE.md`
- `voice-bridge/voiceprints/{barak,kay}.npz` (created by `enroll_speakers.py`)

**Safety notes**:
- **Read-only against your audio**: enrollment is a one-shot operation that writes only the `.npz` file in `voiceprints/`. Re-running `enroll_speakers.py` overwrites the existing `.npz`; the original enrollment audio in `enrollment_audio/` is never modified.
- **Local-only**: Resemblyzer's pretrained model downloads on first import (one-time HF Hub fetch, ~70MB to a local cache). After that, all enrollment + inference is local. No cloud calls, no third-party uploads of voice data.
- **CPU-runnable**: no GPU required; expect ~1-2 second inference latency per utterance on a 32GB MacBook Pro.


**INTEGRATION SHIPPED 2026-05-22 ~12:15 Taipei:** `voice_bridge_ui_v3_8.py` now:
- Auto-spawns `sofia_voiceprint_server.py` on UI startup (parallel to Whisper auto-spawn)
- `WhisperWorker.run()` calls `/identify_bytes` on port 3462 in parallel with `/transcribe_bytes` on 3459 (sequential within the worker; voiceprint call timeout 5.0s; graceful degradation to `speaker='unknown'` if server unreachable)
- `WhisperWorkerSignals.finished` extended to `(transcript, speaker, confidence, elapsed)`
- `_on_stt_finished_auto_flow` prepends `[Barak]` / `[Kay]` / `[unknown speaker]` to the transcript before `_send_to_cognition` — so Sofia's LLM context knows who's speaking without anyone having to announce
- UI history meta line shows `speaker:NAME (confidence) · transcribed Ns` for Barak's visibility
- Clean shutdown on UI exit includes Voiceprint subprocess

**To activate**: restart `voice_bridge_ui_v3_8.py`. The Voiceprint server will auto-spawn alongside Whisper. Talk into the mic; each transcribed utterance arrives at cognition with a speaker tag.
