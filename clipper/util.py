"""Small shared helpers: paths, time parsing, ffprobe, subprocess."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("CLIPPER_WORK", ROOT / "work"))           # downloads + transcripts (safe to delete)
EXPORTS = Path(os.environ.get("CLIPPER_EXPORTS", ROOT / "exports"))  # finished clips you post
FONTS = ROOT / "fonts"


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise SystemExit(f"'{tool}' not found on PATH. Run ./setup.sh first.")
    return path


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a command, raising with its stderr tail on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"Command failed ({cmd[0]}):\n{tail}")
    return p


def run_bytes(cmd: list[str]) -> bytes:
    """Run a command and return raw stdout (for piping audio out of ffmpeg)."""
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.decode(errors="replace").strip().splitlines()[-15:])
        raise RuntimeError(f"Command failed ({cmd[0]}):\n{tail}")
    return p.stdout


def probe(path: Path) -> dict:
    """Width, height, duration and whether there's an audio stream."""
    need("ffprobe")
    out = run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
               "-of", "json", str(path)]).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise RuntimeError(f"No video stream in {path}")
    return {
        "width": int(v["width"]),
        "height": int(v["height"]),
        "duration": float(data["format"].get("duration") or v.get("duration") or 0),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
    }


def parse_time(t: str | float | int) -> float:
    """'1:02:03.5', '2:03', '93' or 93.0 -> seconds."""
    if isinstance(t, (int, float)):
        return float(t)
    parts = [float(p) for p in str(t).strip().split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def fmt_time(s: float) -> str:
    s = max(0.0, s)
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-")) or "clip"


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def jobs_in(path: Path) -> list[Path]:
    """A job dir holds source.mp4. Accept a job dir or a batch of them."""
    path = Path(path)
    if (path / "source.mp4").exists():
        return [path]
    return sorted(p for p in path.iterdir() if (p / "source.mp4").exists())
