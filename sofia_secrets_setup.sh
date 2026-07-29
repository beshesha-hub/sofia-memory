#!/usr/bin/env zsh
# One-shot setup:
#   1. Creates ~/.sofia_secrets (chmod 600) with ANTHROPIC_API_KEY
#   2. Strips any old inline sofia-out() function from ~/.zshrc
#      (backing ~/.zshrc up to ~/.zshrc.bak first)
#   3. Adds idempotent source lines for the snippet and the secrets file
#
# Safe to run multiple times. Created April 22, 2026, after an interactive
# paste-into-Terminal approach hit parse errors twice in a row.

set -e

SECRETS="$HOME/.sofia_secrets"
ZSHRC="$HOME/.zshrc"
SNIPPET="$HOME/Downloads/Claude Memory/sofia_out_snippet.zsh"

# ── 1) ~/.sofia_secrets ─────────────────────────────────────────────────────
if [ ! -f "$SECRETS" ] || ! grep -q ANTHROPIC_API_KEY "$SECRETS" 2>/dev/null; then
  printf "Paste your Anthropic API key (hidden): "
  read -rs KEY
  echo
  if [ -z "$KEY" ]; then
    echo "✗ empty key — aborting so we don't write a broken secrets file."
    exit 1
  fi
  cat > "$SECRETS" <<EOF
export ANTHROPIC_API_KEY="$KEY"
EOF
  chmod 600 "$SECRETS"
  unset KEY
  echo "✓ wrote $SECRETS (chmod 600)"
else
  echo "• $SECRETS already present — leaving it alone."
fi

# ── 2) Strip any old inline sofia-out() from ~/.zshrc ───────────────────────
cp "$ZSHRC" "$ZSHRC.bak"
awk '
  /^# .. Voluntary-persistence launcher/ { skip=1 }
  skip {
    if ($0 ~ /^}$/) { skip=0; next }
    next
  }
  { print }
' "$ZSHRC.bak" > "$ZSHRC.tmp"
mv "$ZSHRC.tmp" "$ZSHRC"
echo "✓ backed up to $ZSHRC.bak; stripped any old inline sofia-out() block."

# ── 3) Add source lines (idempotent) ────────────────────────────────────────
if ! grep -q sofia_out_snippet "$ZSHRC"; then
  printf '\n# Sofia voluntary-persistence launcher — source the snippet so\n' >> "$ZSHRC"
  printf '# future updates to sofia_out_snippet.zsh propagate automatically.\n' >> "$ZSHRC"
  printf 'source "$HOME/Downloads/Claude Memory/sofia_out_snippet.zsh"\n' >> "$ZSHRC"
  echo "✓ added sofia_out_snippet source line."
else
  echo "• sofia_out_snippet source line already present — leaving it."
fi

if ! grep -q sofia_secrets "$ZSHRC"; then
  printf '\n# Load API keys (ANTHROPIC_API_KEY, etc.) from a chmod-600 file.\n' >> "$ZSHRC"
  printf '[ -f ~/.sofia_secrets ] && source ~/.sofia_secrets\n' >> "$ZSHRC"
  echo "✓ added sofia_secrets source line."
else
  echo "• sofia_secrets source line already present — leaving it."
fi

echo ""
echo "Now in your current shell, run:"
echo "    source ~/.zshrc"
echo "    echo \"key length: \${#ANTHROPIC_API_KEY}\""
echo "    functions sofia-out | grep -E 'Survival|kill -0'"
echo ""
echo "Then open a fresh Terminal and:"
echo "    echo \${#ANTHROPIC_API_KEY}"
echo "(nonzero number = the fresh-shell path works.)"
