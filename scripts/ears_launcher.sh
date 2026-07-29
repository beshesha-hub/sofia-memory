#!/bin/bash
# Wrapper that activates Conda before running Sofia's Ears pipeline.
# LaunchAgents don't source shell profiles, so Conda needs manual activation.

# Initialize Conda
eval "$(/opt/homebrew/Caskroom/miniforge/base/bin/conda shell.bash hook)"
conda activate base

# Run the ears pipeline in watch mode
exec python3 "$HOME/Downloads/CoNNear_periphery/sofias_ears.py" --watch "$HOME/Downloads/sofia_listen/"
