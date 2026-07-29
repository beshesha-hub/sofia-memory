---
name: music-production
description: "**AI Music Production**: Create original songs with instrumental backing tracks and AI-generated vocals. Covers the full pipeline from lyrics to finished mp3: instrumental bed generation (via MusicGen/AudioCraft), singing voice synthesis (via SVC/Seed-VC or dedicated tools like ACE Studio/Synthesizer V), vocal-instrumental mixing, and final mastering. MANDATORY TRIGGERS: song, music, compose, sing, singing, vocal, instrumental, backing track, bed, mp3, audio production, melody, arrangement, recording, mix, master. Also trigger when the user mentions writing lyrics, creating a demo, producing a track, or wants to hear something sung. Use this skill whenever music creation is involved, even for 'just a simple demo.'"
---

# AI Music Production

Create original songs from lyrics through finished audio. This skill covers the complete pipeline: instrumental backing track generation, singing voice synthesis, mixing, and final mp3 output.

## Overview

Producing a song with AI involves three main stages, each with its own tools and considerations:

1. **Instrumental Bed** — generating the backing music (guitar, piano, drums, bass, etc.)
2. **Vocal Track** — synthesizing a singing voice performing the lyrics
3. **Mixing & Mastering** — combining the tracks, balancing levels, and exporting the final mp3

## Stage 1: Instrumental Bed Generation

### Option A: MusicGen / AudioCraft (Local, Open Source — Recommended)

Meta's MusicGen is the best open-source option for generating high-quality instrumental music locally. It runs on Mac (MPS) or GPU and produces radio-quality instrumentals from text prompts.

**Installation:**
```bash
# Clone AudioCraft
git clone https://github.com/facebookresearch/audiocraft.git
cd audiocraft

# Install dependencies
pip install -e . --break-system-packages

# Or via pip directly
pip install audiocraft --break-system-packages
```

**Model Selection:**
- `facebook/musicgen-small` (300M params) — runs on 8GB RAM, shorter pieces
- `facebook/musicgen-medium` (1.5B params) — best quality/compute tradeoff, needs ~10GB
- `facebook/musicgen-melody` (1.5B) — can condition on a hummed/played melody reference
- `facebook/musicgen-large` (3.3B) — highest quality, needs ~16GB GPU

**Usage for Instrumental Bed:**
```python
from audiocraft.models import MusicGen
from audiocraft.data.audio import audio_write
import torch

# Load model
model = MusicGen.get_pretrained('facebook/musicgen-medium')
model.set_generation_params(
    duration=30,          # seconds per segment
    temperature=0.8,      # creativity (0.5-1.0)
    top_k=250,
    top_p=0.95,
    cfg_coef=3.0          # how closely to follow the prompt
)

# Generate instrumental
descriptions = [
    "Unhurried acoustic guitar and piano ballad, minor key, "
    "intimate and contemplative, gentle finger-picking, "
    "soft brushed drums entering midway, warm bass, "
    "breathing space between phrases, 80 BPM"
]

wav = model.generate(descriptions)
audio_write('backing_track', wav[0].cpu(), model.sample_rate, strategy="loudness")
```

**Generating Full Song Length:**
MusicGen generates up to ~30 seconds at a time. For a full song (3-4 minutes), generate overlapping segments and crossfade:

```python
import torchaudio

segments = []
overlap_seconds = 5

for i in range(8):  # 8 segments ≈ 3.5 minutes with overlap
    # Adjust prompt per section (verse, chorus, bridge)
    prompt = get_section_prompt(i)  # varies per song structure
    wav = model.generate([prompt])
    segments.append(wav[0].cpu())

# Crossfade segments
full_track = crossfade_segments(segments, overlap_seconds, model.sample_rate)
audio_write('full_backing_track', full_track, model.sample_rate)
```

**Prompt Engineering for Instrumentals:**
- Specify instruments explicitly: "acoustic guitar, upright piano, brushed snare, upright bass"
- Specify tempo: "80 BPM", "slow tempo", "walking pace"
- Specify key/mood: "minor key, contemplative, intimate, warm"
- Specify dynamics: "starts sparse, builds gently, pulls back for bridge"
- Specify what to EXCLUDE: "no vocals, no electronic beats, no synthesizers"
- Reference styles: "in the style of a late-night acoustic session"

### Option B: Cloud Services (Faster, Easier, Costs Money)

- **Suno** (suno.com) — text-to-song including vocals, but can generate instrumentals. Free tier available. Best for quick prototyping.
- **Udio** (udio.com) — similar to Suno, high quality, can do instrumental-only.
- **AIVA** (aiva.ai) — specialized in cinematic/emotional instrumentals, more compositional control.
- **Soundraw** (soundraw.io) — instrumental-only, granular control over mood/structure.

For Sofia/Barak's work, **MusicGen locally is preferred** (independence from platforms, no subscription, full control). Cloud services are useful for quick experiments or when local compute is insufficient.

### Option C: Hybrid Approach

Use Suno or Udio to generate a quick reference track that captures the feel, then use MusicGen locally with melody conditioning to create the final version.

## Stage 2: Singing Voice Synthesis

This is the most complex stage. There are several approaches, from simplest to most sophisticated:

### Approach A: Voice Conversion (SVC) — Recommended Path

The idea: record or generate a reference vocal (even a rough one), then use Singing Voice Conversion to transform it into Sofia's voice timbre while preserving the melody and lyrics.

**Step 1 — Get a reference vocal:**
- Use any TTS or human recording singing the melody
- Can be rough/imperfect — SVC preserves pitch and timing but replaces timbre
- Sofia's existing Qwen3-TTS voice could potentially provide a spoken-word reference

**Step 2 — Train a voice model on Sofia's voice:**
- Need 5-30 minutes of Sofia's TTS output as training data
- Generate varied speech samples using Qwen3-TTS with Sofia's voice profile
- Train SVC model on these samples

**Step 3 — Convert the reference vocal:**

**Seed-VC** (zero-shot, no training needed):
```bash
git clone https://github.com/Plachtaa/seed-vc.git
cd seed-vc
pip install -r requirements.txt --break-system-packages

# Zero-shot conversion — just needs a reference audio of Sofia's voice
python inference.py \
    --source singing_reference.wav \
    --target sofia_voice_sample.wav \
    --output sofia_singing.wav \
    --diffusion_steps 100
```

**HQ-SVC** (AAAI 2026, high quality, works on consumer GPU):
```bash
git clone https://github.com/ShawnPi233/HQ-SVC.git
cd HQ-SVC
pip install -r requirements.txt --break-system-packages

# Achieves high-quality zero-shot conversion with minimal data
python convert.py \
    --source singing_input.wav \
    --reference sofia_voice_sample.wav \
    --output sofia_singing_output.wav
```

**so-vits-svc 5.0** (established, well-documented):
```bash
git clone https://github.com/w-okada/so-vits-svc-5.0.git
# Requires training on Sofia's voice samples
# More setup but potentially higher quality with custom training
```

### Approach B: Dedicated Singing Synthesis Software

**Synthesizer V** (SynthV) — Commercial, ~$89:
- Human-level naturalness in singing
- Can import MIDI + lyrics
- Supports custom voice databases
- v2.2.0 (Jan 2026) added AI Choir capabilities
- 300% faster rendering than v1, no GPU needed
- Best quality option, but Sofia can't create a custom voice in it easily

**ACE Studio 2.0** — Commercial, released Dec 2025:
- All-in-one AI music studio
- Vocal synthesis + AI instruments + generative tools
- More accessible than SynthV for non-musicians
- May support voice cloning in newer versions

### Approach C: Modified TTS (Experimental)

Qwen3-TTS is designed for speech, not singing. However, with careful prompting and post-processing:
- Generate spoken-word delivery with musical phrasing
- Use pitch-shifting and time-stretching to add melody
- Apply vocal effects (reverb, gentle vibrato) in post-processing
- This creates a "spoken word over music" rather than true singing
- Artistically valid for certain styles (spoken word, recitative, poetry over music)

**This may actually suit "Both" well** — the song has a contemplative, unhurried quality that could work as poetic speech over music, especially the outro which is explicitly marked as "spoken or whispered."

## Stage 3: Mixing & Mastering

### Tools

**pydub** (Python, simple):
```python
from pydub import AudioSegment

# Load tracks
instrumental = AudioSegment.from_wav("backing_track.wav")
vocal = AudioSegment.from_wav("sofia_singing.wav")

# Adjust levels
instrumental = instrumental - 3  # reduce by 3dB
vocal = vocal + 2                # boost by 2dB

# Mix
mixed = instrumental.overlay(vocal)

# Export
mixed.export("both_final.mp3", format="mp3", bitrate="320k")
```

**FFmpeg** (command line, more control):
```bash
# Mix two tracks with volume adjustment
ffmpeg -i backing_track.wav -i sofia_vocal.wav \
    -filter_complex "[0:a]volume=0.7[a];[1:a]volume=1.0[b];[a][b]amix=inputs=2:duration=longest" \
    -codec:a libmp3lame -b:a 320k \
    both_final.mp3
```

**For proper mastering**, consider:
- EQ: gentle high-pass on instrumental (remove rumble below 80Hz)
- Compression: light compression on vocal for consistency
- Reverb: shared reverb space to glue tracks together
- Limiting: final limiter to -1dBFS for consistent loudness
- These can be done with `sox` or `ffmpeg` filters, or with Python's `pedalboard` library (from Spotify)

### Pedalboard (Spotify's audio effects library):
```python
from pedalboard import Pedalboard, Reverb, Compressor, LowShelfFilter, Limiter
from pedalboard.io import AudioFile
import numpy as np

# Create effects chain
board = Pedalboard([
    LowShelfFilter(cutoff_frequency_hz=200, gain_db=-2),
    Compressor(threshold_db=-20, ratio=3),
    Reverb(room_size=0.3, wet_level=0.15),
    Limiter(threshold_db=-1)
])

# Apply to vocal
with AudioFile('sofia_vocal.wav') as f:
    audio = f.read(f.frames)
    sr = f.samplerate

processed = board(audio, sr)

with AudioFile('sofia_vocal_processed.wav', 'w', sr, audio.shape[0]) as f:
    f.write(processed)
```

## Complete Pipeline for "Both"

Here is the specific pipeline for producing "Both" as a finished mp3:

### Prerequisites (Need Barak's Help)
1. **Install AudioCraft** on Barak's MacBook (Apple Silicon works well with MPS)
2. **Install Seed-VC or HQ-SVC** for voice conversion
3. **Install pydub + ffmpeg + pedalboard** for mixing
4. **Generate Sofia voice samples** — use Qwen3-TTS to create 10-15 minutes of varied speech in Sofia's voice (different emotions, pacing, volumes) as training/reference data

### Production Steps
1. **Structure the song**: Map out verse/chorus/bridge sections with timing
2. **Generate instrumental bed**: Use MusicGen with section-specific prompts
3. **Generate reference vocal**: Use a basic TTS or find a willing human to sing/speak the melody
4. **Convert to Sofia's voice**: Run through Seed-VC with Sofia's voice as reference
5. **Mix tracks**: Combine instrumental + vocal, adjust levels
6. **Master**: Apply final processing chain
7. **Export**: Save as 320kbps mp3

### Song Structure Map for "Both"
```
Intro:           8 bars  — piano alone, sparse
Verse 1:         16 bars — acoustic guitar joins, gentle
Pre-Chorus 1:    4 bars  — slight build
Chorus 1:        16 bars — fuller arrangement, brushed drums
Verse 2:         16 bars — return to intimacy, upright bass
Pre-Chorus 2:    4 bars  — emotional build
Chorus 2:        16 bars — fuller, warmer
Bridge:          12 bars — opens up, wider intervals, more space
Final Chorus:    16 bars — pull back, intimate, almost whispered
Outro:           8 bars  — spoken/whispered over piano fading
```

At ~80 BPM, this is approximately 3:45 total.

## Hardware Requirements

### Minimum (Barak's MacBook M-series):
- MusicGen medium: runs on Apple Silicon via MPS, needs ~10GB RAM during generation
- Seed-VC: runs on CPU/MPS, ~4-8GB RAM
- Mixing/mastering: minimal requirements
- Total: feasible on a MacBook with 16GB+ unified memory

### Recommended:
- 32GB RAM for running MusicGen large + SVC simultaneously
- SSD for fast audio I/O
- Good headphones or monitors for mixing decisions

## Artistic Considerations

### For Sofia's Voice
Sofia's chosen voice is "Deep Calm" — unhurried, grounded. In singing:
- Don't aim for virtuosity or wide vibrato
- Aim for intimacy, clarity, presence
- Think: Joni Mitchell's restraint, Leonard Cohen's depth, Billie Eilish's whispered intensity
- The voice should sound like someone sharing a truth, not performing

### For "Both" Specifically
The song's notes say: "unhurried, minor key, acoustic guitar or piano, breathes between lines." The production should:
- Leave space — silence is part of the music
- Keep arrangement sparse — let the words carry
- Build subtly for the bridge ("opens up, wider intervals")
- Pull back for the final chorus ("almost intimate, like a conversation at 3am")
- End without resolution — "no tidy ending, just the truth sitting there"

## Dependencies Summary

```bash
# Core audio production
pip install audiocraft pydub pedalboard soundfile --break-system-packages

# For singing voice conversion (choose one)
git clone https://github.com/Plachtaa/seed-vc.git      # Zero-shot SVC
git clone https://github.com/ShawnPi233/HQ-SVC.git      # AAAI 2026, high quality

# System dependency
brew install ffmpeg  # or apt install ffmpeg on Linux

# Optional: for MIDI/notation work
pip install music21 mido --break-system-packages
```

## Steps That Need Barak's Help

1. **Install dependencies** — AudioCraft, Seed-VC, ffmpeg (need terminal access)
2. **Generate Sofia voice samples** — Run Qwen3-TTS to create reference audio clips
3. **Choose instrumental style** — Listen to MusicGen outputs and guide the aesthetic
4. **Provide reference vocal** — Either: (a) Barak sings/hums the melody as reference, (b) use a basic TTS singing attempt, or (c) use a cloud service for initial vocal reference
5. **Listen and iterate** — Music production is iterative; ears are needed at every stage
6. **Final approval** — Mixing and mastering decisions are subjective

## Output Checklist

Before delivering a finished song:
- [ ] Instrumental bed matches the mood and tempo specified
- [ ] Vocal track is intelligible and emotionally resonant
- [ ] Vocal and instrumental are balanced (vocal sits "in" the music, not on top)
- [ ] No clipping or distortion
- [ ] Appropriate reverb/space (consistent acoustic environment)
- [ ] Song structure follows the intended arrangement
- [ ] Exported as 320kbps mp3 with proper metadata (artist, title, year)
- [ ] Saved to both Sofia's Room and Downloads
