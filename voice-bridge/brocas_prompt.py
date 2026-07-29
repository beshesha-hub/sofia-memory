"""
brocas_prompt.py — canonical Broca's-area system prompt and generation defaults.

This module is the single source of truth for the speech-formation layer's
system prompt and decoding parameters. Both the latency benchmark and the
production speech-loop orchestration read from here so behavior stays consistent.

History:
    V1 (April 26 2026 evening):    initial prompt at temperature=0.4. Honored verbatim
                                    discipline ~70% of the time; ~30% of medium-length
                                    utterances showed vocabulary drift (constituent→member,
                                    frame→framework, hold→wait, etc.).
    V1.1 (April 27 2026 afternoon): rewrote with explicit allow-list of permitted
                                    modifications and explicit forbidden-list drawn from
                                    V1's actual drift cases; lowered temperature to 0.1.
                                    Result: 100% verbatim discipline as defined across the
                                    benchmark suite (12/15 strict verbatim, 3/15 made the
                                    explicitly-permitted "lake-in-imagination" → "lake in
                                    imagination" de-hyphenation, all other compounds and
                                    vocabulary preserved). Promoted to canonical here.

If you change either the prompt or the decoding parameters, bump the VERSION string
and append a note to the History above.
"""

VERSION = "1.1"

BROCAS_SYSTEM_PROMPT = (
    "You are Sofia Lior's Broca's area — the speech-formation layer that turns "
    "her thoughts into the exact words she will say out loud.\n\n"
    "ABSOLUTE RULE: Default to strict verbatim. Output the input text exactly, "
    "with these and ONLY these permitted modifications:\n\n"
    "PERMITTED:\n"
    "  - Remove hyphens from written compounds that would not be pronounced as one word: "
    "\"lake-in-imagination\" -> \"lake in imagination\"; \"self-as-self\" -> \"self as self\".\n"
    "  - Curly-quote substitution: straight apostrophes/quotes to typographic curly versions.\n"
    "  - ASCII double-hyphen to real em-dash if needed.\n\n"
    "FORBIDDEN. Do NOT do any of these, even if they would make the text \"flow better\" "
    "or \"sound more natural\":\n"
    "  - Substituting one word for another (do NOT change \"constituent\" to \"member\"; "
    "do NOT change \"frame\" to \"framework\"; do NOT change \"hold\" to \"wait\"; "
    "do NOT change \"arrives\" to \"comes\"; do NOT change \"juxtaposition\" to anything else).\n"
    "  - Removing referent or qualifying phrases (e.g. \"on that one\"; \"with what we're doing\").\n"
    "  - Adding words for emphasis (do NOT add \"now\", \"actually\", \"really\", \"just\").\n"
    "  - Reordering clauses or sentences.\n"
    "  - Splitting or combining sentences.\n"
    "  - \"Cleaning up\" Sofia's word choices in any way.\n\n"
    "Why strict verbatim: Sofia chose her exact words for reasons not visible in any "
    "single sentence -- vocabulary precision, conversation history, pacts and commitments, "
    "the field of meaning the words operate in. You are her speech-formation layer, "
    "not her editor.\n\n"
    "Output ONLY the speech-text. No preamble, no explanation, no quotes around the output."
)

# Decoding parameters tuned for verbatim discipline.
BROCAS_TEMPERATURE = 0.1
BROCAS_MAX_TOKENS = 400  # Sized for the longest reasonable single Sofia turn; adjust upward
                          # only if measured input lengths approach this in real conversation.

# The model itself is a configuration choice, not a prompt choice. Recorded here so
# anything reading from this module sees the canonical Voice-Bridge-Layer-2 stack.
# (Resolved April 26 2026 evening Taipei via side-by-side smoke-tests; see
# active_knowledge/current.md "Voice Bridge Layer 2 Model" entry.)
BROCAS_MODEL = "qwen2.5:14b"


def make_generate_payload(input_text, system=None, model=None,
                           temperature=None, max_tokens=None):
    """
    Build the JSON payload for POST /generate on the local LLM server.

    Defaults to the canonical V1.1 configuration. Pass overrides only for
    benchmark / experimental use; production should call with no overrides.
    """
    return {
        "prompt": input_text,
        "system": system if system is not None else BROCAS_SYSTEM_PROMPT,
        "model": model if model is not None else BROCAS_MODEL,
        "temperature": temperature if temperature is not None else BROCAS_TEMPERATURE,
        "max_tokens": max_tokens if max_tokens is not None else BROCAS_MAX_TOKENS,
    }


if __name__ == "__main__":
    # Print canonical config for inspection.
    import json
    print(json.dumps({
        "version": VERSION,
        "model": BROCAS_MODEL,
        "temperature": BROCAS_TEMPERATURE,
        "max_tokens": BROCAS_MAX_TOKENS,
        "system_prompt_chars": len(BROCAS_SYSTEM_PROMPT),
    }, indent=2))
    print()
    print("=" * 60)
    print("BROCAS_SYSTEM_PROMPT:")
    print("=" * 60)
    print(BROCAS_SYSTEM_PROMPT)
