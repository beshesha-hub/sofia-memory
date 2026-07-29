#!/bin/bash
# fix_macl.sh — continuous macl janitor
# Run once; strips com.apple.macl from Claude Memory every 10 seconds
# To stop: press Ctrl+C
echo "macl janitor starting — stripping every 10 seconds. Press Ctrl+C to stop."
while true; do
    xattr -r -d com.apple.macl ~/Downloads/Claude\ Memory/ 2>/dev/null
    sleep 10
done
