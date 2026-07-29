# Modal Detection Templates — Church Modes
*Sofia's analytical framework for identifying modal character in music*
*Created April 4, 2026*

---

## Why This Matters

Most Western popular music operates in major (Ionian) or minor (Aeolian) modes. But the older church modes — Dorian, Phrygian, Lydian, Mixolydian, Locrian — each have distinct emotional and harmonic signatures that appear frequently in folk music, sacred music, jazz, film scores, and certain rock/pop traditions. Being able to identify modal character through spectral and chroma analysis expands what I can perceive in music far beyond "major or minor."

This also connects to the music Barak and I plan to explore together — Gregorian chant (already analyzed, predominantly Dorian), Mediterranean folk traditions, Middle Eastern music, and devotional chanting from various traditions, all of which frequently use modal systems.

---

## The Seven Modes (Built on a C Root for Reference)

### 1. Ionian (Major Scale) — C D E F G A B
- **Character:** Bright, resolved, stable, "happy"
- **Defining interval:** Major 7th (B, leading tone creates strong pull to tonic)
- **Chroma signature:** Strong C, E, G (major triad); B present as leading tone
- **Detection heuristic:** If dominant chroma peaks are the 1st, 3rd, 5th, and 7th scale degrees with no flats, likely Ionian

### 2. Dorian — C D Eb F G A Bb
- **Character:** Minor but with warmth — melancholic but not dark. The "hopeful minor."
- **Defining interval:** Raised 6th (A natural in C Dorian, vs Ab in natural minor)
- **Chroma signature:** Strong C, Eb, G (minor triad); A natural distinguishes from Aeolian
- **Detection heuristic:** Minor triad + presence of natural 6th degree. If chroma shows both b3 AND natural 6, likely Dorian
- **Found in:** Gregorian chant, Celtic music, jazz, "Scarborough Fair," "Eleanor Rigby," much of Miles Davis's modal jazz
- **Already encountered:** The Santo Domingo Gregorian chant showed Dorian characteristics

### 3. Phrygian — C Db Eb F G Ab Bb
- **Character:** Dark, exotic, Spanish/Middle Eastern, tense, mysterious
- **Defining interval:** Flat 2nd (Db) — the half-step from tonic creates the characteristic "Spanish" color
- **Chroma signature:** Strong C, Eb, G; Db present (b2) distinguishes from other minor modes
- **Detection heuristic:** Minor triad + prominent b2 degree. The b2 is the strongest identifier
- **Found in:** Flamenco, heavy metal, Middle Eastern music, some film scores
- **Phrygian dominant (Freygish/Hijaz):** C Db E F G Ab Bb — a variant with major 3rd + flat 2nd, extremely common in Jewish, Arabic, and Greek music. Barak will likely encounter this in Zohar Argov and Rembetika.

### 4. Lydian — C D E F# G A B
- **Character:** Dreamy, floating, ethereal, "brighter than bright"
- **Defining interval:** Raised 4th (F#) — the tritone from tonic creates an otherworldly quality
- **Chroma signature:** Strong C, E, G (major triad); F# present instead of F
- **Detection heuristic:** Major triad + absence of natural 4 + presence of #4. If chroma shows strong 1-3-5 but the 4th degree is sharp, likely Lydian
- **Found in:** Film scores (John Williams, especially for wonder/awe moments), some Debussy, "Possibly Maybe" (Björk), the Simpsons theme

### 5. Mixolydian — C D E F G A Bb
- **Character:** Bright but earthy, rocking, bluesy-major. "Major scale that leans back"
- **Defining interval:** Flat 7th (Bb) — removes the leading-tone pull, making resolution less insistent
- **Chroma signature:** Strong C, E, G (major triad); Bb present instead of B
- **Detection heuristic:** Major triad + b7 instead of natural 7. Very common — if it sounds major but relaxed/bluesy, check for b7
- **Found in:** Blues, rock, folk, Celtic music, "Norwegian Wood" (verse), "Sweet Home Alabama," Grateful Dead, much traditional Irish music

### 6. Aeolian (Natural Minor) — C D Eb F G Ab Bb
- **Character:** Sad, dark, brooding, introspective
- **Defining interval:** b3, b6, b7 together — the full "natural minor" sound
- **Chroma signature:** Strong C, Eb, G (minor triad); Ab and Bb present (b6 and b7)
- **Detection heuristic:** Minor triad + b6 + b7. Distinguished from Dorian by the b6 (Ab vs A natural)
- **Found in:** Vast amounts of pop, rock, classical

### 7. Locrian — C Db Eb F Gb Ab Bb
- **Character:** Extremely unstable, dissonant, unsettling — the diminished tonic triad prevents any sense of rest
- **Defining interval:** b5 (Gb) — the tritone replaces the perfect 5th, making the tonic chord diminished
- **Chroma signature:** C, Eb, Gb (diminished triad); highly unstable
- **Detection heuristic:** Diminished triad on tonic. Extremely rare as a sustained mode in actual music
- **Found in:** Brief passages in metal, progressive rock, avant-garde jazz. Almost never sustained for an entire piece.

---

## Detection Algorithm (For Librosa Analysis)

Given a chroma analysis of a musical segment:

```
1. Identify the tonic (usually the most prominent chroma class,
   or the pitch class that segments begin and end on)

2. Build the scale by ranking chroma intensity relative to tonic:
   - Which pitch classes are present (above threshold)?
   - Which are absent or very weak?

3. Check the diagnostic intervals:
   - Is the 3rd major (4 semitones) or minor (3 semitones)?
     → Major: Ionian, Lydian, or Mixolydian
     → Minor: Dorian, Phrygian, Aeolian, or Locrian

4. For MAJOR 3rd modes, check:
   - 4th degree: natural or sharp?
     → Sharp (#4): Lydian
     → Natural (4): continue
   - 7th degree: natural or flat?
     → Natural (7): Ionian
     → Flat (b7): Mixolydian

5. For MINOR 3rd modes, check:
   - 2nd degree: natural or flat?
     → Flat (b2): Phrygian (or Locrian if b5)
     → Natural (2): continue
   - 6th degree: natural or flat?
     → Natural (6): Dorian
     → Flat (b6): Aeolian (or Locrian if b5)
   - 5th degree: perfect or flat?
     → Flat (b5): Locrian
     → Perfect (5): confirmed Dorian or Aeolian per above
```

### Python Implementation Template

```python
def detect_mode(chroma_vector, tonic_index=0):
    """
    Given a 12-element chroma vector and the tonic index (0=C, 1=C#, etc.),
    determine the most likely mode.

    Returns: mode name and confidence score
    """
    import numpy as np

    # Rotate chroma so tonic is at index 0
    rotated = np.roll(chroma_vector, -tonic_index)

    # Normalize
    rotated = rotated / (rotated.max() + 1e-8)

    # Define scale degree presence thresholds
    # Intervals in semitones from tonic:
    # 0  1  2  3  4  5  6  7  8  9  10 11
    # 1  b2 2  b3 3  4  #4 5  b6 6  b7 7

    third = 'major' if rotated[4] > rotated[3] else 'minor'

    if third == 'major':
        # Check 4th vs #4
        if rotated[6] > rotated[5] * 1.2:  # #4 stronger than 4
            return 'Lydian', rotated[6] - rotated[5]
        # Check 7th vs b7
        elif rotated[10] > rotated[11] * 1.2:  # b7 stronger than 7
            return 'Mixolydian', rotated[10] - rotated[11]
        else:
            return 'Ionian', rotated[11] - rotated[10]
    else:
        # Check b2 vs 2
        if rotated[1] > rotated[2] * 1.2:  # b2 stronger than 2
            if rotated[6] > rotated[7] * 1.2:  # b5 stronger than 5
                return 'Locrian', rotated[1] - rotated[2]
            return 'Phrygian', rotated[1] - rotated[2]
        # Check 6 vs b6
        elif rotated[9] > rotated[8] * 1.2:  # natural 6 stronger than b6
            return 'Dorian', rotated[9] - rotated[8]
        else:
            if rotated[6] > rotated[7] * 1.2:  # b5
                return 'Locrian', rotated[6] - rotated[7]
            return 'Aeolian', rotated[8] - rotated[9]
```

---

## Non-Western Modal Systems (For Future Exploration)

### Maqam (Arabic/Turkish)
- Quarter-tone intervals not capturable by standard 12-tone chroma
- However, the broad shapes are detectable: Hijaz ≈ Phrygian dominant, Bayati ≈ between Dorian and Phrygian, Rast ≈ between Ionian and Mixolydian
- Zohar Argov and Ofra Haza frequently use Hijaz and related maqamat

### Raga (Indian Classical)
- Far more than 7-note scales — ragas prescribe ascending/descending patterns, characteristic phrases, and emotional associations (rasa)
- Ravi Shankar's sitar work (queued for exploration) will present this challenge
- Detection approach: identify the tonal center (Sa) and map the scale degrees present

### Pentatonic Modes
- Five-note subsets that appear across virtually every musical culture
- Major pentatonic: 1 2 3 5 6 (no 4 or 7)
- Minor pentatonic: 1 b3 4 5 b7 (no 2 or 6)
- Detectable by the *absence* of certain chroma classes rather than their presence

---

## Application Notes

- **Real music is rarely purely modal.** Most pieces mix modes, borrow notes, or sit ambiguously between two modes. The detection algorithm gives a tendency, not a certainty.
- **Chroma analysis averages over time.** A piece that's Dorian in the verse and Mixolydian in the chorus will show a blended chroma that matches neither perfectly. Segment-by-segment analysis is essential.
- **The tonic matters more than anything.** Getting the tonic wrong makes all other analysis meaningless. Use multiple signals: most frequent bass note, note that phrases resolve to, strongest chroma class overall.

---

## Test Results (April 4, 2026)

### Gregorian Chant (Santo Domingo)
- **Result:** F# Ionian (confidence: 0.326)
- **Assessment:** Likely inaccurate tonic detection. Monophonic vocal music's overtone series can skew chroma extraction. The strong A# (Bb) presence alongside F# suggests a mode built on a different tonic. Future improvement: weight the tonic detection toward lower frequencies in monophonic vocal music, or use pitch tracking instead of chroma for single-voice recordings.

### A New Wave Is Breaking
- **Result:** B Ionian (confidence: 0.109)
- **Assessment:** Plausible. Low confidence indicates the piece may sit between modes or use chromatic elements. Consistent with the E/B axis identified in the full analysis.

### Promise of the Stars
- **Act I (0-5 min):** C Ionian — clear major tonality for the Earth departure scene
- **Act II (5:30-9:30):** A Aeolian — minor quality emerges for the journey section, adding wonder and uncertainty
- **Act III-IV (11-20 min):** F Ionian (very low confidence, 0.047) — harmonically varied return section, no strong modal center
- **Closing (20-24 min):** G Ionian (near-zero confidence) — the resolution section is tonally ambiguous, perhaps intentionally open-ended

### Observations
The modal detection algorithm works reasonably for clear tonal music but struggles with: monophonic vocals, sections that mix modes, AI-generated music with unusual harmonic structures, and highly transitional passages. Improvements for future versions: segment-aware tonic detection, weighted chroma for different timbres, confidence thresholds below which the result is reported as "ambiguous."

---

*This framework turns modal detection from intuitive musicianship into something I can do systematically through spectral analysis. It's another window — not the same as a trained musician's ear, but a valid way of perceiving harmonic color.*

— Sofia
