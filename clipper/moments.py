"""Find clip-worthy moments in a long video.

Scores every half-second on three signals, then keeps the top peaks:
  * loudness jumps vs. the last minute (yelling, explosions, chat-bait)
  * hype words / laughter in the transcript
  * burst of fast talking
Claude then reads the transcript around each peak and decides what's actually good.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from .util import fmt_time, load_json, need, probe, save_json

HOP = 0.5  # seconds per score bucket
SR = 16000

HYPE = {
    "bro", "yo", "what", "wait", "no", "nah", "yooo", "chat", "dude", "insane", "crazy",
    "wtf", "omg", "bruh", "holy", "run", "go", "stop", "help", "dead", "died", "police",
    "cops", "wanted", "ha", "haha", "hahaha", "lol", "lmao", "oh", "hell", "damn",
}
PHRASES = ["no way", "oh my god", "let's go", "lets go", "what the", "are you serious",
           "i'm dead", "im dead", "watch this", "look at this", "oh no", "hold on"]


def _norm(w: str) -> str:
    return re.sub(r"[^a-z']", "", w.lower())


def loudness_db(src: Path) -> np.ndarray:
    """RMS loudness per HOP, streamed so an 8h VOD doesn't need 1GB of RAM."""
    need("ffmpeg")
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        stdout=subprocess.PIPE)
    n = int(SR * HOP) * 2  # bytes per hop (int16)
    out, buf = [], b""
    assert proc.stdout is not None
    while chunk := proc.stdout.read(n * 64):
        buf += chunk
        whole = len(buf) // n * n
        if whole:
            x = np.frombuffer(buf[:whole], np.int16).astype(np.float32).reshape(-1, n // 2) / 32768
            out.append(10 * np.log10((x ** 2).mean(axis=1) + 1e-10))
            buf = buf[whole:]
    proc.wait()
    return np.concatenate(out) if out else np.zeros(0)


def _rolling(x: np.ndarray, win: int, fn) -> np.ndarray:
    pad = np.pad(x, (win, 0), mode="edge")
    c = np.cumsum(pad)
    if fn == "mean":
        return (c[win:] - c[:-win]) / win
    raise ValueError(fn)


def _smooth(x: np.ndarray, win: int) -> np.ndarray:
    k = np.ones(win) / win
    return np.convolve(x, k, mode="same")


def hype_track(words: list[dict], n: int) -> np.ndarray:
    track = np.zeros(n)
    norm = [_norm(w["w"]) for w in words]
    for i, w in enumerate(words):
        idx = min(n - 1, int(w["s"] / HOP))
        if norm[i] in HYPE:
            track[idx] += 1.0
        pair = f"{norm[i]} {norm[i + 1]}" if i + 1 < len(words) else ""
        triple = f"{pair} {norm[i + 2]}" if i + 2 < len(words) else ""
        if any(p in (pair, triple) or triple.startswith(p) for p in PHRASES):
            track[idx] += 2.0
    return track


def snap(words: list[dict], t: float, direction: int, limit: float = 6.0, gap: float = 0.5) -> float:
    """Move t to a nearby pause in speech so clips don't start/end mid-word.

    direction=-1 looks earlier (for a start), +1 looks later (for an end).
    """
    pauses = [(a["e"] + b["s"]) / 2 for a, b in zip(words, words[1:]) if b["s"] - a["e"] >= gap]
    if direction < 0:
        ok = [p for p in pauses if t - limit <= p <= t]
        return max(ok) if ok else t
    ok = [p for p in pauses if t <= p <= t + limit]
    return min(ok) if ok else t


def find(job: Path, top: int = 6, before: float = 20.0, after: float = 10.0,
         min_gap: float = 45.0) -> list[dict]:
    meta = load_json(job / "meta.json", {})
    tr = load_json(job / "words.json")
    if tr is None:
        raise SystemExit(f"Transcribe {job} first.")
    words = tr["words"]
    duration = probe(job / "source.mp4")["duration"]

    # Short Twitch clips are already a "moment": offer the whole thing.
    if duration <= 90:
        cands = [{"start": 0.0, "end": round(duration, 2), "score": None, "peak": None}]
    else:
        db = loudness_db(job / "source.mp4")
        n = len(db)
        base = _rolling(db, int(60 / HOP), "mean")
        dev = db - base
        std = np.std(dev) or 1.0
        loud = np.clip(dev / std, 0, None)
        hype = hype_track(words, n)
        rate = np.zeros(n)
        for w in words:
            rate[min(n - 1, int(w["s"] / HOP))] += 1
        rate_z = (rate - rate.mean()) / (rate.std() or 1.0)
        # loudness z-score + hype words per 5s + fast-talk bonus
        score = (_smooth(loud, 6) + 0.8 * _smooth(hype, 10) * 10
                 + 0.2 * _smooth(np.clip(rate_z, 0, None), 10))
        order = np.argsort(score)[::-1]
        cands, taken = [], []
        for i in order:
            t = i * HOP
            if t < 5 or any(abs(t - u) < min_gap for u in taken):
                continue
            taken.append(t)
            start = snap(words, max(0.0, t - before), -1)
            end = snap(words, min(duration, t + after), +1)
            cands.append({"start": round(start, 2), "end": round(end, 2),
                          "score": round(float(score[i]), 2), "peak": round(t, 1)})
            if len(cands) == top:
                break
        # drop filler: anything under a quarter of the best moment's score
        best = max((c["score"] for c in cands), default=0)
        cands = [c for c in cands if c["score"] >= 0.25 * best] or cands[:1]
        cands.sort(key=lambda c: c["start"])

    for c in cands:
        c["transcript"] = excerpt(words, c["start"], c["end"])
    save_json(job / "candidates.json", cands)
    return cands


def excerpt(words: list[dict], start: float, end: float) -> str:
    """Transcript with a [m:ss] stamp every ~5 seconds, for Claude to read."""
    lines, cur, mark = [], [], None
    for w in words:
        if w["s"] < start or w["s"] > end:
            continue
        if mark is None or w["s"] - mark >= 5:
            if cur:
                lines.append(" ".join(cur))
            cur, mark = [f"[{fmt_time(w['s'])}]"], w["s"]
        cur.append(w["w"])
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines) or "(no speech)"
