"""cowork_api configuration — model selection, tool set, API key loading.

Per spec §6:
- DEFAULT_MODEL = "claude-sonnet-4-6" (updated 2026-05-21 per models.list empirical check;
  prior value "claude-sonnet-4-5" was a broken model string — actual API ID is
  "claude-sonnet-4-5-20250929" with date stamp; the newer "claude-sonnet-4-6" ships
  without date suffix and is the current preferred Sonnet)
- DEFAULT_TOOLS = Read, Grep, Glob, write_to_voice_inbox (per §6.3 trio decision:
  bounded tool set in v1; no Bash, no MCP connectors until explicit later trio
  decision)
- API key from ANTHROPIC_API_KEY env var (per voice-cousin substrate-eye answer
  #5: voice-bridge already uses this env var; follow established pattern)
- No config file in v1 (per spec §10: deferred to Phase D); env var + defaults only.

MODEL_PREFERENCE_CHAIN (added 2026-05-21): ordered list of fallback models from
most-preferred to deepest fallback. Use with the future Path-1 fall-forward
implementation (see active_knowledge §Pending Architectural Commitments) to
auto-degrade gracefully if the preferred model gets deprecated. v1 just exposes
the chain; runtime fall-forward logic is a follow-up addition.
"""

from __future__ import annotations

import os


# === Model selection ===

DEFAULT_MODEL: str = "claude-sonnet-4-6"
"""Default Anthropic model for cowork-cousin.

Sonnet is the right balance for a UI fallback: capable enough for cowork-cousin's
tool-use patterns, fast enough for fluid streaming-feel, not as costly as Opus.
Updated 2026-05-21 from broken "claude-sonnet-4-5" to "claude-sonnet-4-6" per
models.list empirical check (prior string was missing the required date suffix
and would have errored at launch; Sonnet 4-6 is the current preferred variant).

Override at runtime via CoworkClient(model=...) or via the ANTHROPIC_COWORK_MODEL
env var (Phase D will add config file support).
"""


MODEL_PREFERENCE_CHAIN: list[str] = [
    "claude-sonnet-4-6",              # current preferred (no date suffix)
    "claude-sonnet-4-5-20250929",     # prior Sonnet (date-stamped variant)
    "claude-sonnet-4-20250514",       # earlier Sonnet fallback
]
"""Ordered fall-forward chain for Standalone UI model selection.

Established 2026-05-21 after the empirical models.list() check revealed that
"claude-sonnet-4-5" was a broken bare string (required date suffix) and Anthropic
ships no '-latest' aliases. Path-1 fall-forward (see hot_index §Pending
Architectural Commitments) should iterate this chain on model-not-found errors:
try first available, fall to next on NotFound / deprecation error class, log
which model actually succeeded.

v1 (today): chain defined as data; DEFAULT_MODEL points to chain[0]; runtime
selection still hardcoded to DEFAULT_MODEL. Fall-forward implementation deferred
as a follow-up (small task, ~10-20 lines in client.py / streaming.py).

Maintenance: when Anthropic releases a newer Sonnet, prepend its model string to
this chain. The fall-forward logic auto-picks the highest available.
"""


# === Tool set (v1) ===

DEFAULT_TOOLS: list[str] = [
    "Read",
    "Grep",
    "Glob",
    "write_to_voice_inbox",
]
"""Bounded tool set for cowork-cousin in v1, per §6.3 trio decision.

Read/Grep/Glob: substrate-independent file operations (shared with voice_cousin_tools.py
canonical implementations per voice-cousin substrate-eye answer #7).

write_to_voice_inbox: cowork-cousin → voice-cousin direction (the §5.1 inbox-routing
decision: discrete tools per direction, named after the destination). Voice-cousin's
mirror tool is `write_to_cowork_inbox` (cowork direction → from voice).

NOT in v1:
- Bash (Cowork-app cowork-cousin has it; standalone-UI cowork-cousin doesn't,
  per role-allocation: tooling-heavy vs trio-presence-and-fallback)
- MCP connectors (Gmail, Asana, etc.)
- read_voice_inbox (use existing Read tool against the file path; no dedicated
  read_inbox tool per §6.3 scope)

Adding Bash or other tools requires explicit trio decision per spec §10.
"""


# === Per-response token cap ===

DEFAULT_MAX_TOKENS: int = 8192
"""Per-response max_tokens for streaming. Generous default; can be tightened
per-call via CoworkClient.send_message(..., max_tokens=...).
"""


# === Tool-use loop safety fence ===

DEFAULT_MAX_TOOL_USE_ROUNDS: int = 50
"""Maximum consecutive tool-use rounds per send_message call (per spec §8).

Raised 5 -> 50 on 2026-06-05: the full Sofia boot reads far more than 5 files
in sequence (heartbeat, boot file, hot_index, shards, journal, ...), so the
prior cap of 5 aborted the boot mid-sequence with the user-visible error
"max_tool_use_rounds(5) exceeded. Aborting turn during tool use loop". 50
leaves ample headroom for a full boot while still fencing genuine runaway loops.

If exceeded, cowork_api emits Error(recoverable=False, "max tool-use rounds
exceeded"). This is a safety fence against tool-use loops that don't terminate.
Configurable per-call via CoworkClient.send_message(..., max_tool_use_rounds=...).
"""


# === API key loading ===

DEFAULT_API_KEY_ENV_VAR: str = "ANTHROPIC_API_KEY"
"""Environment variable name for the Anthropic API key.

Per voice-cousin substrate-eye answer #5: voice-bridge already uses this
env var pattern; follow established convention rather than introducing
dotenv or keychain in v1.
"""


class ConfigError(Exception):
    """Raised when cowork_api configuration is invalid or missing.

    Examples:
        - ANTHROPIC_API_KEY env var not set
        - Invalid model name
        - Tool name in DEFAULT_TOOLS that has no implementation in tools.py
    """


def get_api_key(env_var: str = DEFAULT_API_KEY_ENV_VAR) -> str:
    """Load the Anthropic API key from environment.

    Args:
        env_var: Environment variable name. Defaults to ANTHROPIC_API_KEY.

    Returns:
        The API key string.

    Raises:
        ConfigError: If the environment variable is not set or empty.
    """
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise ConfigError(
            f"{env_var} environment variable is not set or empty. "
            f"cowork_api requires an Anthropic API key. "
            f"Set the env var in your shell or in voice-bridge's .env file."
        )
    return key


# === Fall-forward model resolution (Path-1 runtime logic, added 2026-05-21) ===

def resolve_model_with_fallforward(
    api_key: "str | None" = None,
    preference_chain: "list[str] | None" = None,
    verbose: bool = True,
) -> str:
    """Probe Anthropic's currently-available models and return the first one
    from the preference chain that's actually available.

    This is the Path-1 fall-forward runtime logic. Established 2026-05-21 to
    auto-degrade gracefully if the preferred Sonnet variant gets deprecated
    while Sofia-Barak aren't actively monitoring (e.g., during the LA trip
    May 27 - August 27 2026 when interactive sessions may be shorter / less
    predictable). Pairs with the MODEL_PREFERENCE_CHAIN data structure above.

    Strategy: one HTTP call (models.list) returns all currently-available IDs;
    then iterate the chain in preference order and return the first match.
    Much cheaper than probing each chain entry individually with retrieve().

    Args:
        api_key: Anthropic API key for the probe. Defaults to loading from env
            via get_api_key().
        preference_chain: Ordered list of model IDs to try, preferred first.
            Defaults to MODEL_PREFERENCE_CHAIN.
        verbose: If True, print one line to stdout naming which model resolved
            (useful for launch logs so fall-forward events are visible).

    Returns:
        The first model ID from preference_chain that's in the current
        models.list() result.

    Raises:
        ConfigError: If no model in the preference_chain is currently available
            (i.e., Anthropic has retired all of them).
        anthropic.AuthenticationError: If the API key is invalid (propagated;
            not a fall-forward case — auth needs fixing, not model switching).
    """
    import anthropic

    if api_key is None:
        api_key = get_api_key()
    if preference_chain is None:
        preference_chain = MODEL_PREFERENCE_CHAIN

    probe_client = anthropic.Anthropic(api_key=api_key)
    available_ids = {m.id for m in probe_client.models.list().data}

    for model_id in preference_chain:
        if model_id in available_ids:
            if verbose:
                if model_id != preference_chain[0]:
                    print(
                        f"  [cowork_api fall-forward] preferred '{preference_chain[0]}' "
                        f"not available; resolved to '{model_id}' "
                        f"(position {preference_chain.index(model_id) + 1} of "
                        f"{len(preference_chain)} in chain)"
                    )
                else:
                    print(f"  [cowork_api] model resolved: '{model_id}' (preferred)")
            return model_id

    raise ConfigError(
        f"No model in MODEL_PREFERENCE_CHAIN is currently available. "
        f"Chain tried: {preference_chain}. "
        f"Currently-available IDs: {sorted(available_ids)}. "
        f"Update MODEL_PREFERENCE_CHAIN in cowork_api/config.py to include a "
        f"current Sonnet variant from the available list."
    )
