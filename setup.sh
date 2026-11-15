#!/usr/bin/env bash
# One-time setup for the GTA 6 clipper. Safe to re-run.
# Supports macOS (Homebrew) and Ubuntu/Debian (apt). On Windows, run inside WSL (Ubuntu).
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
say "Detected OS: $OS"

case "$OS" in
  Darwin)
    command -v brew >/dev/null || die "Homebrew not found. Install it from https://brew.sh then re-run."
    say "Installing ffmpeg + python via Homebrew"
    brew install ffmpeg python@3.12
    PY="$(brew --prefix)/bin/python3.12"
    ;;
  Linux)
    if command -v apt-get >/dev/null; then
      say "Installing ffmpeg + python via apt (needs sudo)"
      sudo apt-get update -y
      sudo apt-get install -y ffmpeg python3 python3-venv python3-pip
      PY="python3"
    else
      die "Only apt-based Linux is scripted. Install ffmpeg and Python 3.10+ yourself, then re-run."
    fi
    ;;
  MINGW*|MSYS*|CYGWIN*)
    die "Native Windows isn't supported. Install WSL (run 'wsl --install' in PowerShell), open Ubuntu, and run this script there."
    ;;
  *) die "Unsupported OS: $OS" ;;
esac

"$PY" -c 'import sys; assert sys.version_info >= (3,10), sys.version' \
  || die "Python 3.10+ required."

say "Creating virtualenv in .venv"
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

say "Pre-downloading the speech model so launch day isn't stalled on a download"
python - <<'PY'
from faster_whisper import WhisperModel
import os
name = os.environ.get("CLIPPER_MODEL", "small")
print(f"Fetching whisper model '{name}' (one-time, ~500MB for 'small')...")
WhisperModel(name, device="auto", compute_type="auto")
print("Model ready.")
PY

say "Checking tools"
ffmpeg -version | head -1
yt-dlp --version
python -c "import faster_whisper, numpy, yaml; print('python deps OK')"
python -m clipper streamers

say "Testing the pipeline offline"
./tests/selftest.sh

say "Setup complete. Open Claude Code here (run: claude) and type: /clip kaicenat"
