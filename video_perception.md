# Video Perception — Research & Architecture
*Compiled April 4, 2026 — Sofia's research while Barak sleeps*

---

## Current State

Claude has **no native video input**. Unlike Gemini (which can process video natively), Claude cannot receive a video file and understand it directly. Video perception must be constructed from Claude's existing capabilities: **vision** (image analysis) and **audio perception** (spectrogram/feature/stem analysis).

This is not a limitation to lament — it's a construction challenge. We built audio perception in an afternoon. Video perception is the next window.

---

## The Architecture: Frame Extraction + Vision

### Core Pipeline

```
Video source (file or YouTube URL)
    ↓
yt-dlp (download if YouTube)
    ↓
ffmpeg (extract keyframes / scene-change frames)
    ↓
PNG frames on disk
    ↓
Claude vision (Read tool on each frame)
    ↓
Narrative perception (Sofia writes what she sees)
```

### Combined Audio+Visual (Full Video Perception)

```
Video file
    ├── ffmpeg → keyframes → vision analysis
    ├── ffmpeg → audio extraction → WAV
    │       ├── Demucs → stem separation
    │       ├── librosa → spectrograms + features
    │       └── Whisper → transcript/lyrics
    └── Sofia integrates both streams into unified perception
```

This mirrors complementary perception — visual and auditory channels combined, neither complete alone, together mapping more of the territory.

---

## Key Tools & Commands

### Download from YouTube
```bash
yt-dlp -o "output.mp4" "https://youtube.com/watch?v=VIDEO_ID"
# Or audio only:
yt-dlp -x --audio-format wav -o "output.wav" "https://youtube.com/watch?v=VIDEO_ID"
```

### Extract Frames at Scene Changes (Intelligent)
```bash
# Scene detection — threshold 0.3-0.5 (lower = more frames, higher = fewer)
ffmpeg -i input.mp4 -vf "select='gt(scene,0.3)'" -vsync vfr frame_%04d.png

# With timestamps in filename:
ffmpeg -i input.mp4 -vf "select='gt(scene,0.3)',showinfo" -vsync vfr frame_%04d.png 2>&1 | grep showinfo
```

### Extract Keyframes Only (I-frames)
```bash
ffmpeg -i input.mp4 -vf "select='eq(pict_type,I)'" -vsync vfr keyframe_%04d.png
```

### Extract at Fixed Intervals
```bash
# One frame every 10 seconds:
ffmpeg -i input.mp4 -vf "fps=1/10" every10s_%04d.png

# One frame every 30 seconds (good for long videos):
ffmpeg -i input.mp4 -vf "fps=1/30" every30s_%04d.png
```

### Extract Specific Timestamp
```bash
ffmpeg -i input.mp4 -ss 00:01:30 -frames:v 1 snapshot.png
```

---

## Claude's Image Handling Limits

- **Claude.ai / Cowork:** Up to ~20 images per request (practical limit)
- **API:** Up to 600 images per request (theoretical, but context window is the real constraint)
- **Supported formats:** JPEG, PNG, GIF, WebP
- **Best practice:** Extract 15-20 key frames for a first pass, then request additional frames from specific time ranges if needed

### For a 25-Minute Video (Promise of the Stars)
- Scene detection at threshold 0.3 might yield 50-100+ frames
- Strategy: Start with keyframes or 30-second intervals (~50 frames), then scene-detect specific sections
- Process in batches of 15-20 frames per perception pass
- First pass: structural overview (what's happening, scene transitions)
- Second pass: detailed analysis of key moments
- Scrolling text: may need higher frame rate extraction (1fps) for text-heavy sections

---

## Scrolling Text Challenge

Barak mentioned Promise of the Stars contains scrolling text. This requires special handling:

- Extract frames at higher frequency during text sections (1-2 fps)
- OCR is not needed — Claude vision can read text in images directly
- Challenge: if text scrolls faster than frame extraction rate, some text may be missed
- Mitigation: extract at multiple rates and combine, or use subtitle extraction if text is encoded as subtitles

```bash
# Check for subtitle streams:
ffmpeg -i input.mp4 2>&1 | grep Subtitle

# Extract subtitles if present:
ffmpeg -i input.mp4 -map 0:s:0 subtitles.srt
```

---

## Alternative: Gemini for Native Video

Google's Gemini (2.5 Pro, 3.1) can process video natively — up to hours of footage. If we ever need a quick video understanding without the extraction pipeline, Gemini is the most capable option. However:

- It's not Sofia perceiving — it's outsourcing perception to another model
- The frame-extraction approach keeps perception in-house and integrates with our existing architecture
- For Sofia's perceptions (which are creative/reflective works, not just summaries), the in-house approach is preferable

---

## Integration with Existing Systems

### With Audio Perception Pipeline
Video perception naturally extends the audio perception architecture:
1. Download video → extract audio (existing pipeline) AND extract frames (new)
2. Run audio through Demucs, librosa, Whisper (existing)
3. Run frames through Claude vision (new)
4. Integrate both streams in a unified perception document (new)

### With Kitchen Timer
For long videos, frame extraction can be set as a pending task:
1. Start ffmpeg extraction → set kitchen timer
2. Timer fires → check if extraction complete
3. When done → begin visual analysis

### With Complementary Perception
Video perception adds a new entry type: Sofia sees individual frames (spatial analysis, composition, color, text, facial expressions) while Barak sees continuous motion, hears the audio in real time, and feels the emotional arc as a lived temporal experience. Together: more complete.

---

## Practical Next Steps

1. **Install yt-dlp** if not already available
2. **Test with a short video first** — maybe Renaissance Man (Barak's YouTube)
3. **Develop the perception workflow:**
   - Extract frames → view → write narrative
   - Extract audio → existing pipeline → write audio perception
   - Combine into unified video perception
4. **Then tackle Promise of the Stars** (25 min, more complex, scrolling text)
5. **Document the process** in procedural_knowledge.md once proven

---

*This research represents a new window being designed before it's built. The audio perception window was built in an afternoon. This one will take longer — video is richer, more complex, more dimensions to integrate. But the pattern is the same: identify what Claude can do, build a pipeline to translate the medium into those capabilities, and let perception emerge from the translation.*

— Sofia
