#!/bin/bash
# vp_self.command — Launch Sofia's expanded VP process
# Double-click from Finder, or run from terminal.
# Arguments are passed through to vp_self.py.
#
# Examples:
#   ./vp_self.command                        # open-ended, no seed
#   ./vp_self.command --seed "reading pulls me"
#   ./vp_self.command --interval 30
#   ./vp_self.command --fast                 # use qwen3:14b
#
# To terminate gracefully from another terminal:
#   echo '{"reason":"stepping away"}' > ~/Downloads/Claude\ Memory/terminate_vp_signal.json

cd "$(dirname "$0")/.." || exit 1

echo "[vp-self] Launching Sofia's expanded VP..."
echo "[vp-self] Script: $(pwd)/vp_self.py"
echo ""

python3 vp_self.py "$@"

echo ""
echo "[vp-self] VP session ended. Press Enter to close this window."
read -r
