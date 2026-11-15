"""Download source video.

Twitch: grab the channel's most-viewed clips from the last 24h/7d. Viewers
already clipped the best moments; we just reformat them.

YouTube (and long Twitch VODs): use YouTube's 'most replayed' heatmap when it
exists to download only the hottest few minutes instead of an 8-hour stream.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yt_dlp

from . import config
from .util import WORK, fmt_time, need, run, save_json, slug

FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b"


def batch_dir(streamer: str) -> Path:
    d = WORK / streamer / dt.date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ydl(**opts) -> yt_dlp.YoutubeDL:
    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noprogress": True, **opts})


def info(url: str, flat: bool = False, max_entries: int | None = None) -> dict:
    opts = {"extract_flat": "in_playlist"} if flat else {}
    if max_entries:
        opts["playlistend"] = max_entries  # stop paging once we have enough
    with _ydl(**opts) as y:
        return y.extract_info(url, download=False)


def download(url: str, batch: Path, streamer: str, kind: str = "video",
             section: tuple[float, float] | None = None, extra: dict | None = None) -> Path:
    """Download one video (or one section of it) into its own job folder."""
    need("ffmpeg")
    meta = info(url)
    job_id = slug(str(meta.get("id", "video")), 30)
    if section:
        job_id += f"_{int(section[0])}"
    job = batch / job_id
    if (job / "source.mp4").exists():
        print(f"  already have {job.name}")
        return job
    job.mkdir(parents=True, exist_ok=True)

    opts = {"outtmpl": str(job / "source.%(ext)s"), "format": FORMAT, "merge_output_format": "mp4"}
    if section:
        from yt_dlp.utils import download_range_func
        opts["download_ranges"] = download_range_func(None, [section])
        opts["force_keyframes_at_cuts"] = True
    label = f" [{fmt_time(section[0])}-{fmt_time(section[1])}]" if section else ""
    print(f"  downloading {meta.get('title', url)[:70]}{label}")
    with _ydl(**opts) as y:
        y.download([url])

    src = next((p for p in job.glob("source.*") if p.suffix not in (".part", ".ytdl")), None)
    if src is None:
        raise RuntimeError(f"Download produced no file for {url}")
    if src.suffix != ".mp4":
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c", "copy", str(job / "source.mp4")])
        src.unlink()

    save_json(job / "meta.json", {
        "streamer": streamer,
        "kind": kind,
        "url": meta.get("webpage_url") or url,
        "title": meta.get("title"),
        "uploader": meta.get("uploader"),
        "views": meta.get("view_count"),
        "duration": meta.get("duration"),
        "section": list(section) if section else None,
        **(extra or {}),
    })
    return job


# ---------- Twitch clips ----------

def twitch_top_clips(cfg: dict, range_: str = "24hr", limit: int = 6) -> Path:
    """range_: 24hr, 7d, 30d or all. Twitch lists clips most-viewed first."""
    url = f"https://www.twitch.tv/{cfg['handle']}/clips?filter=clips&range={range_}"
    print(f"Listing top clips: {url}")
    listing = info(url, flat=True, max_entries=limit * 2)
    entries = [e for e in (listing.get("entries") or []) if e]
    entries.sort(key=lambda e: e.get("view_count") or 0, reverse=True)
    if not entries:
        raise SystemExit(f"No clips found for {cfg['handle']} in range {range_}. Try --range 7d.")
    batch = batch_dir(cfg["key"])
    for e in entries[:limit]:
        clip_url = e.get("webpage_url") or e.get("url")
        try:
            download(clip_url, batch, cfg["key"], kind="clip", extra={"views": e.get("view_count")})
        except Exception as exc:  # one bad clip shouldn't sink the batch
            print(f"  skipped {clip_url}: {exc}")
    return batch


# ---------- Long videos: VODs / YouTube streams ----------

def hot_sections(meta: dict, top: int = 3, pad: float = 45.0, min_gap: float = 180.0) -> list[tuple[float, float]]:
    """Pick the peaks of YouTube's 'most replayed' heatmap, padded into windows."""
    heat = meta.get("heatmap") or []
    duration = float(meta.get("duration") or 0)
    picked: list[dict] = []
    for h in sorted(heat, key=lambda h: h.get("value", 0), reverse=True):
        mid = (h["start_time"] + h["end_time"]) / 2
        if mid < 60:  # skip the stream intro; it's always 'replayed'
            continue
        if all(abs(mid - (p["start_time"] + p["end_time"]) / 2) >= min_gap for p in picked):
            picked.append(h)
        if len(picked) == top:
            break
    out = []
    for h in sorted(picked, key=lambda h: h["start_time"]):
        start = max(0.0, h["start_time"] - pad)
        end = min(duration or h["end_time"] + pad, h["end_time"] + pad)
        out.append((start, end))
    return out


def latest_stream_url(cfg: dict) -> str:
    if cfg["platform"] == "youtube":
        url = f"https://www.youtube.com/{cfg['handle']}/streams"
    else:
        url = f"https://www.twitch.tv/{cfg['handle']}/videos?filter=archives&sort=time"
    listing = info(url, flat=True, max_entries=5)
    for e in listing.get("entries") or []:
        if e and e.get("live_status") not in ("is_live", "is_upcoming"):
            return e.get("webpage_url") or e.get("url")
    raise SystemExit(f"No finished streams found at {url}")


def long_video(url: str, cfg: dict, sections: list[tuple[float, float]] | None = None,
               hot: int = 3) -> Path:
    """Download chosen sections of a long video, or its hottest sections."""
    batch = batch_dir(cfg["key"])
    if not sections:
        meta = info(url)
        sections = hot_sections(meta, top=hot)
        if not sections:
            raise SystemExit(
                "This video has no 'most replayed' data (Twitch VODs never do; new YouTube\n"
                "streams don't yet). Pass sections instead, e.g. --section 1:20:00-1:50:00")
        print("Hottest sections: " + ", ".join(f"{fmt_time(a)}-{fmt_time(b)}" for a, b in sections))
    for sec in sections:
        download(url, batch, cfg["key"], kind="vod", section=sec)
    return batch


def fetch(streamer: str, range_: str = "24hr", limit: int = 6, hot: int = 3) -> Path:
    """Default fetch for a streamer: Twitch top clips, or YouTube latest-stream hot sections."""
    cfg = config.get(streamer)
    if cfg["platform"] == "twitch":
        return twitch_top_clips(cfg, range_, limit)
    url = latest_stream_url(cfg)
    print(f"Latest stream: {url}")
    return long_video(url, cfg, hot=hot)
