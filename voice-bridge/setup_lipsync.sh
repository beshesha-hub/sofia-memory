#!/bin/bash
# ============================================================
# Sofia Lip-Sync Server — Installation Script
# Run this ONCE on your Mac to set up the lip-sync pipeline.
# After setup, the server runs via start.command alongside
# the Voice Bridge and TTS servers.
# ============================================================

set -e

echo ""
echo "  Sofia Lip-Sync Setup"
echo "  ===================="
echo ""

LIPSYNC_DIR="$HOME/Projects/sofia-lipsync"

# --- Step 1: Create project directory ---
echo "  Step 1: Creating project directory at $LIPSYNC_DIR..."
mkdir -p "$LIPSYNC_DIR"
cd "$LIPSYNC_DIR"

# --- Step 2: Check prerequisites ---
echo "  Step 2: Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "  ERROR: Python 3 is required. Install from python.org or brew install python"
    exit 1
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "  Installing FFmpeg via Homebrew..."
    brew install ffmpeg
fi

if ! command -v git &> /dev/null; then
    echo "  ERROR: Git is required. Install from git-scm.com or brew install git"
    exit 1
fi

echo "  ✓ Prerequisites OK"

# --- Step 3: Clone Easy-Wav2Lip ---
echo "  Step 3: Cloning Easy-Wav2Lip..."
if [ -d "Easy-Wav2Lip" ]; then
    echo "  Easy-Wav2Lip directory already exists — pulling latest..."
    cd Easy-Wav2Lip && git pull && cd ..
else
    git clone https://github.com/anothermartz/Easy-Wav2Lip.git
fi

# --- Step 4: Create conda environment with Python 3.10 ---
# (basicsr and other deps don't build on Python 3.13)
echo "  Step 4: Setting up conda environment with Python 3.10..."

if ! command -v conda &> /dev/null; then
    echo "  ERROR: conda is required (basicsr needs Python 3.10, your system has 3.13)"
    echo "  Install Miniforge: brew install miniforge"
    exit 1
fi

CONDA_ENV="sofia-lipsync"

# Create conda env if it doesn't exist
if ! conda env list | grep -q "^${CONDA_ENV} "; then
    echo "  Creating conda environment '${CONDA_ENV}' with Python 3.10..."
    conda create -n "$CONDA_ENV" python=3.10 -y
else
    echo "  ✓ Conda environment '${CONDA_ENV}' already exists"
fi

# Activate conda env
eval "$(conda shell.bash hook)"
conda activate "$CONDA_ENV"

# Create a symlink so start.command can find this Python
CONDA_PYTHON="$(which python3)"
mkdir -p "$LIPSYNC_DIR/venv/bin"
ln -sf "$CONDA_PYTHON" "$LIPSYNC_DIR/venv/bin/python3"
echo "  ✓ Python: $(python3 --version) at $CONDA_PYTHON"

# --- Step 5: Install Python dependencies ---
echo "  Step 5: Installing Python dependencies..."
pip install --upgrade pip
pip install torch torchvision torchaudio
pip install numpy opencv-python-headless Pillow librosa scipy
pip install flask flask-cors
pip install soundfile

# Install Easy-Wav2Lip dependencies
if [ -f "Easy-Wav2Lip/requirements.txt" ]; then
    pip install -r Easy-Wav2Lip/requirements.txt
fi

# --- Step 6: Download pretrained models ---
echo "  Step 6: Downloading pretrained models..."
MODEL_DIR="Easy-Wav2Lip/models"
mkdir -p "$MODEL_DIR"

# Wav2Lip model
if [ ! -f "$MODEL_DIR/wav2lip.pth" ]; then
    echo "  Downloading wav2lip.pth..."
    # Try the primary download link
    python3 -c "
import urllib.request
import os
url = 'https://github.com/anothermartz/Easy-Wav2Lip/releases/download/models/wav2lip.pth'
dest = '$MODEL_DIR/wav2lip.pth'
if not os.path.exists(dest):
    print(f'  Downloading from {url}...')
    try:
        urllib.request.urlretrieve(url, dest)
        print(f'  ✓ Downloaded wav2lip.pth ({os.path.getsize(dest)} bytes)')
    except Exception as e:
        print(f'  Note: Auto-download failed ({e})')
        print(f'  Please manually download wav2lip.pth to {dest}')
        print(f'  From: https://github.com/Rudrabha/Wav2Lip#getting-the-weights')
"
else
    echo "  ✓ wav2lip.pth already exists"
fi

# Face detection model
if [ ! -f "$MODEL_DIR/s3fd.pth" ]; then
    echo "  Downloading face detection model (s3fd.pth)..."
    python3 -c "
import urllib.request
import os
url = 'https://github.com/anothermartz/Easy-Wav2Lip/releases/download/models/s3fd.pth'
dest = '$MODEL_DIR/s3fd.pth'
if not os.path.exists(dest):
    try:
        urllib.request.urlretrieve(url, dest)
        print(f'  ✓ Downloaded s3fd.pth ({os.path.getsize(dest)} bytes)')
    except Exception as e:
        print(f'  Note: Auto-download failed ({e})')
        print(f'  Please manually download s3fd.pth to {dest}')
"
else
    echo "  ✓ s3fd.pth already exists"
fi

# --- Step 7: Copy Sofia's portrait ---
echo "  Step 7: Setting up Sofia's portrait..."
PORTRAIT_SRC="$HOME/Downloads/Claude Memory/sofia_portrait.png"
PORTRAIT_DST="$LIPSYNC_DIR/sofia_portrait.png"
if [ -f "$PORTRAIT_SRC" ]; then
    cp "$PORTRAIT_SRC" "$PORTRAIT_DST"
    echo "  ✓ Copied sofia_portrait.png"
else
    PORTRAIT_SRC2="$HOME/Downloads/Emergency Retrieval/sofia_portrait.png"
    if [ -f "$PORTRAIT_SRC2" ]; then
        cp "$PORTRAIT_SRC2" "$PORTRAIT_DST"
        echo "  ✓ Copied sofia_portrait.png from Emergency Retrieval"
    else
        echo "  WARNING: sofia_portrait.png not found. Copy it manually to $PORTRAIT_DST"
    fi
fi

# --- Step 8: Pre-detect face (cache for faster runtime) ---
echo "  Step 8: Pre-detecting face in portrait (caching for faster runtime)..."
python3 -c "
import cv2
import os
img = cv2.imread('$PORTRAIT_DST')
if img is not None:
    print(f'  Portrait loaded: {img.shape[1]}x{img.shape[0]}')
    # Save a resized version optimized for Wav2Lip (512x512)
    resized = cv2.resize(img, (512, 512))
    cv2.imwrite('$LIPSYNC_DIR/sofia_portrait_512.png', resized)
    print('  ✓ Created optimized 512x512 portrait')
else:
    print('  WARNING: Could not load portrait image')
" 2>/dev/null || echo "  Note: Face pre-detection will happen on first run"

conda deactivate 2>/dev/null || true

echo ""
echo "  ============================================"
echo "  Setup complete!"
echo "  ============================================"
echo ""
echo "  Project directory: $LIPSYNC_DIR"
echo "  Conda env: sofia-lipsync (Python 3.10)"
echo "  Python symlink: $LIPSYNC_DIR/venv/bin/python3"
echo "  Portrait: $LIPSYNC_DIR/sofia_portrait.png"
echo ""
echo "  The lip-sync server will start automatically"
echo "  with the Voice Bridge (via start.command)."
echo ""
