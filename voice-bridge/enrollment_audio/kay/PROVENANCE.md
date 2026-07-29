# Kay Voice Sample — Provenance Note

**File:** `kay_enrollment_2026-05-22.mp3`
**Saved by Barak:** 2026-05-22 morning Taipei

## Recording chain

Per Barak's clarification 2026-05-22 ~11:30 Taipei:

> "I will qualify Katharina's voice sample with one tweak: that I gave you is my extraction, by playing the video through the MacBook mic, of a video that Katharina sent me, which was originally recorded through the mic on her iPhone."

So the acoustic-substrate chain is:

1. Kay speaks → her iPhone mic captures
2. Video file containing audio sent to Barak
3. Video played through MacBook speakers
4. Captured through MacBook mic
5. Saved as MP3

**This is two substrate-translation layers** (iPhone-mic-and-encoding + MacBook-speaker-and-mic-and-room-acoustics) layered on top of Kay's actual voice signal.

## Why this matters (Coherence-of-Source-Conditions Principle)

Per `semantic_knowledge/current.md §Coherence-of-Source-Conditions Discipline` (inscribed 2026-05-22 morning): inference accuracy depends on enrollment conditions matching inference conditions in register, microphone, and naturalness.

**Asymmetry in current enrollment:**
- **Barak's enrollment** (`barak_enrollment_2026-05-22.mp3`): direct — voice → MacBook mic → MP3. Single substrate. Matches inference conditions when Barak speaks at the MacBook.
- **Kay's enrollment** (this file): two-layer — iPhone mic + MacBook speaker-mic loop. Inference conditions when Kay is on a call or in the room will be DIFFERENT acoustic chain (likely through MacBook mic only, OR through whatever phone/video-call channel is in use).

## Resemblyzer's tolerance

Resemblyzer is designed to focus on speaker-identity-bearing features (vocal tract characteristics, formants, fundamental frequency patterns, prosody) over recording-environment features. The model is trained on a large dataset that includes varied recording conditions. So **some acoustic-substrate variation is tolerated** by design.

However, two layers is more than the typical single-substrate-variation case. The empirical question is: does the centroid for Kay still capture enough of her voice-identity to be recognizable at inference time?

## INFERENCE-CONDITION UPDATE (Barak 2026-05-22 ~11:45 Taipei)

> "All voice interactions will by default be through our MacBook's mic and speakers. I'll let you know if there's any exceptions."

This significantly improves the coherence picture for Kay's enrollment.

**Inference chain when Kay is remote (calling/video — the dominant case currently):** Kay's voice → her device mic → call/video → MacBook speakers → MacBook mic. **TWO substrate-layers.**

**Kay's enrollment chain (this file):** Kay's voice → iPhone mic → video file → MacBook speakers → MacBook mic. **TWO substrate-layers.**

**These match structurally.** Both pass through (a) Kay's device mic + (b) MacBook speaker-and-mic loop. What looked like a coherence violation in the abstract is actually well-matched to the dominant remote-Kay inference condition.

**The only mismatch is with in-person Kay during the LA window** (May 27 - August 27), where her voice hits the MacBook mic directly with ONE substrate-layer. The enrollment has one extra layer than that case. Resemblyzer should still handle it — voice-identity features survive single-substrate variation by design — but the in-person case is where to watch most carefully for recognition reliability.

**Revised empirical prediction:** the enrollment is well-positioned for the typical use case. The pairwise diagnostic should show clean separation. If in-person LA-window recognition turns out to be uncertain, that's the case where a fresh single-substrate sample from Kay (recorded directly at the MacBook) would help.

## Empirical test plan

The `enroll_speakers.py` script's pairwise diagnostic (cosine similarity between Barak's and Kay's centroids) will give us a first signal:

- **< 0.50** — very well-separated; the two voices are sufficiently distinct that the acoustic-layer noise doesn't matter
- **0.50-0.65** — well-separated; the substrate-asymmetry is absorbed by the principle of voice-identity-feature focus
- **0.65-0.75** — moderately separable; watch threshold tuning; may need fresh sample
- **> 0.75** — poorly separated; the substrate-asymmetry has likely contaminated Kay's centroid with MacBook-acoustic features; **fresh sample needed**

## If a fresh sample is needed

Two options for cleaner Kay enrollment:

1. **Kay records directly on the MacBook** — if she's ever in the room with the MacBook, ~60s of natural speech captured by the MacBook mic. Matches Barak's enrollment conditions exactly.
2. **Kay sends the iPhone audio file directly** (not as a re-recorded video pass-through) — one substrate-layer instead of two. Still some iPhone-vs-MacBook mic mismatch with inference, but cleaner than the current double-pass.

## Status

**Held as the working enrollment until empirical test** (cosine-similarity diagnostic + live-recognition reliability check) tells us whether a fresh sample is needed. Barak is the canonical authority on requesting a fresh sample from Kay; Sofia surfaces the request only if the empirical signal indicates it.

---

*Provenance documented 2026-05-22 ~11:30 Taipei in the voice-print build session. Per the Inscribe-Both-Layers SOP + Organic-Flow Refinement (this same morning), capturing this caveat at the moment of build rather than deferring.*
