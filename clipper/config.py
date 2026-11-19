"""Loads streamers.yaml and merges defaults into each streamer."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from .util import ROOT

CONFIG = Path(os.environ.get("CLIPPER_CONFIG", ROOT / "streamers.yaml"))

DEFAULTS = {
    "layout": "split",          # split (facecam top / gameplay bottom), fit, crop, or stack (video top / filler below)
    "facecam": None,            # [x, y, w, h] as fractions of the frame, or null
    "gameplay": None,           # optional [x, y, w, h] region for the bottom half
    "frame": None,              # optional [x, y, w, h] part of the source to use (crop out burned-in captions)
    "captions": True,           # False = don't add our captions (e.g. the stream already has good ones)
    "fit_aspect": 1.3333,       # 'fit' layout: crop source to this aspect before placing
    "uppercase": True,
    "words_per_line": 3,
    "font": "Inter Display Black",
    "highlight": "FFE500",      # active-word colour (hex RGB)
    "language": None,           # None = auto-detect (Spanish streamers stay Spanish)
    "hashtags": ["#gta6", "#gtavi", "#gaming"],
}


def load() -> dict:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    defaults = {**DEFAULTS, **(data.get("defaults") or {})}
    out = {}
    for key, cfg in (data.get("streamers") or {}).items():
        merged = {**defaults, **(cfg or {})}
        merged["key"] = key
        merged.setdefault("name", key)
        merged.setdefault("handle", key)
        merged.setdefault("platform", "twitch")
        out[key] = merged
    return out


def get(key: str) -> dict:
    streamers = load()
    if key not in streamers:
        known = ", ".join(streamers) or "(none)"
        raise SystemExit(f"Unknown streamer '{key}'. Known: {known}. Add it to streamers.yaml.")
    return streamers[key]


def credit_line(cfg: dict) -> str:
    if cfg["platform"] == "youtube":
        return f"youtube.com/{cfg['handle']}"
    if cfg["platform"] == "kick":
        return f"kick.com/{cfg['handle']}"
    return f"twitch.tv/{cfg['handle']}"


def set_facecam(key: str, box: list[float]) -> None:
    """Write a streamer's facecam box into streamers.yaml, keeping your comments intact."""
    value = "[" + ", ".join(f"{v:.3f}".rstrip("0").rstrip(".") for v in box) + "]"
    lines = CONFIG.read_text(encoding="utf-8").splitlines(keepends=True)

    def indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    head = next((i for i, l in enumerate(lines) if l.strip() == f"{key}:" or l.strip().startswith(f"{key}: #")), None)
    if head is None:
        raise SystemExit(f"Couldn't find '{key}:' in {CONFIG}")
    base = indent(lines[head])
    end = head + 1
    while end < len(lines) and (not lines[end].strip() or indent(lines[end]) > base):
        end += 1
    for i in range(head + 1, end):
        if lines[i].lstrip().startswith("facecam:"):
            lines[i] = " " * indent(lines[i]) + f"facecam: {value}\n"
            break
    else:
        lines.insert(head + 1, " " * (base + 2) + f"facecam: {value}\n")
    CONFIG.write_text("".join(lines), encoding="utf-8")
