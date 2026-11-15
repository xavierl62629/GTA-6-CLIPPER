"""python -m clipper <command> ...   (run with --help for the list)"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import time
from pathlib import Path

from . import config
from .util import WORK, fmt_time, jobs_in, load_json, parse_time


def _batch(arg: str) -> Path:
    """Accept a batch path, or a streamer key meaning today's batch."""
    p = Path(arg)
    if p.exists():
        return p
    p = WORK / arg / dt.date.today().isoformat()
    if p.exists():
        return p
    raise SystemExit(f"No batch at {arg} (or {p}). Fetch first.")


def cmd_streamers(a):
    for k, c in config.load().items():
        fc = "facecam set" if c.get("facecam") else "facecam NOT set"
        print(f"{k:12} {c['name']:14} {c['platform']:8} {config.credit_line(c):28} {fc}")


def cmd_fetch(a):
    from . import fetch
    batch = fetch.fetch(a.streamer, range_=a.range, limit=a.limit, hot=a.hot)
    print(f"\nBatch: {batch}")


def cmd_fetch_url(a):
    from . import fetch
    cfg = config.get(a.streamer)
    sections = []
    for s in a.section or []:
        start, end = s.split("-")
        sections.append((parse_time(start), parse_time(end)))
    if sections or "youtube" in a.url or "youtu.be" in a.url:
        batch = fetch.long_video(a.url, cfg, sections=sections or None, hot=a.hot)
    else:
        batch = fetch.batch_dir(cfg["key"])
        fetch.download(a.url, batch, cfg["key"], kind="clip")
    print(f"\nBatch: {batch}")


def cmd_transcribe(a):
    from . import transcribe
    batch = _batch(a.path)
    lang = config.get(batch.parent.name).get("language") if (WORK in batch.parents) else None
    for job in jobs_in(batch):
        transcribe.transcribe(job, model=a.model, language=lang)


def cmd_review(a):
    """Moments + transcripts for every job, written to review.md for Claude to read."""
    from . import moments
    batch = _batch(a.path)
    out = [f"# Review: {batch}", ""]
    for job in jobs_in(batch):
        if not (job / "words.json").exists():
            print(f"  (skipping {job.name}: not transcribed)")
            continue
        meta = load_json(job / "meta.json", {})
        cands = moments.find(job, top=a.top)
        views = f"{meta['views']:,} views" if meta.get("views") else ""
        out += [f"## job: `{job.name}`", f"{meta.get('title') or ''}  {views}".strip(),
                f"source: {meta.get('url', '')}", ""]
        for i, c in enumerate(cands, 1):
            score = f" score {c['score']}" if c.get("score") is not None else ""
            out += [f"### candidate {i}: {fmt_time(c['start'])}-{fmt_time(c['end'])} "
                    f"(start={c['start']}, end={c['end']}){score}", "```", c["transcript"], "```", ""]
    path = batch / "review.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(path)


def _prep_one(key: str, a) -> Path:
    from . import fetch, transcribe
    cfg = config.get(key)
    try:
        batch = fetch.fetch(key, range_=a.range, limit=a.limit, hot=a.hot)
    except SystemExit as exc:
        if cfg["platform"] != "twitch" or a.range != "24hr":
            raise
        print(f"  {exc}\n  -> trying the last 7 days instead")
        batch = fetch.fetch(key, range_="7d", limit=a.limit, hot=a.hot)
    for job in jobs_in(batch):
        transcribe.transcribe(job, model=a.model, language=cfg.get("language"))
    a.path = str(batch)
    cmd_review(a)
    return batch


def cmd_prep(a):
    """fetch + transcribe + review. 'all' = every Twitch streamer."""
    if a.streamer != "all":
        _prep_one(a.streamer, a)
        return
    done, failed, skipped = [], [], []
    for key, cfg in config.load().items():
        if cfg["platform"] != "twitch":
            skipped.append(f"{key} ({cfg['platform']}: not supported in 'all')")
            continue
        print(f"\n=== {cfg['name']} ===")
        try:
            done.append(str(_prep_one(key, a) / "review.md"))
        except (SystemExit, Exception) as exc:
            failed.append(f"{key}: {exc}")
    print("\n=== summary ===")
    for r in done:
        print(f"ready   {r}")
    for f in failed:
        print(f"FAILED  {f}")
    for k in skipped:
        print(f"skipped {k}")


def cmd_frame(a):
    from .render import grid_frame
    print(grid_frame(Path(a.job), parse_time(a.at)))


def cmd_facecam(a):
    from .render import preview
    box = [float(v) for v in a.box]
    if len(box) != 4 or not all(0 <= v <= 1 for v in box):
        raise SystemExit("Box is x y w h, each a fraction 0-1, e.g. 0.70 0.02 0.28 0.30")
    config.set_facecam(a.streamer, box)
    if a.job:
        print(preview(Path(a.job), config.get(a.streamer), parse_time(a.at)))
    print(f"Saved facecam for {a.streamer}: {box}")


def cmd_preview(a):
    from .render import preview
    job = Path(a.job)
    print(preview(job, config.get(a.streamer or job.parent.parent.name), parse_time(a.at)))


def cmd_render(a):
    from .render import render_batch
    if a.path != "all":
        render_batch(_batch(a.path), Path(a.picks) if a.picks else None)
        return
    today = dt.date.today().isoformat()
    batches = sorted(b for b in WORK.glob(f"*/{today}") if (b / "picks.json").exists())
    if not batches:
        raise SystemExit("No picks.json in any of today's batches.")
    for b in batches:
        print(f"\n=== {b.parent.name} ===")
        render_batch(b)


def cmd_clean(a):
    cutoff = time.time() - a.days * 86400
    freed = 0
    for src in WORK.glob("*/*/*/source.mp4"):
        if src.stat().st_mtime < cutoff:
            freed += src.stat().st_size
            src.unlink()
    for d in sorted(WORK.glob("*/*"), reverse=True):
        if d.is_dir() and not any(d.rglob("source.mp4")) and d.stat().st_mtime < cutoff:
            shutil.rmtree(d)
    print(f"Freed {freed / 1e9:.2f} GB of downloads older than {a.days} days (exports kept).")


def main():
    p = argparse.ArgumentParser(prog="python -m clipper", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("streamers", help="list configured streamers").set_defaults(fn=cmd_streamers)

    def fetch_opts(sp):
        sp.add_argument("--range", default="24hr", choices=["24hr", "7d", "30d", "all"],
                        help="Twitch clip window (default 24hr)")
        sp.add_argument("--limit", type=int, default=6, help="how many Twitch clips (default 6)")
        sp.add_argument("--hot", type=int, default=3, help="YouTube: how many hot sections (default 3)")

    sp = sub.add_parser("fetch", help="download a streamer's top clips / hot sections")
    sp.add_argument("streamer"); fetch_opts(sp); sp.set_defaults(fn=cmd_fetch)

    sp = sub.add_parser("fetch-url", help="download a specific clip / VOD / YouTube video")
    sp.add_argument("url"); sp.add_argument("--streamer", required=True)
    sp.add_argument("--section", action="append", help="START-END, e.g. 1:20:00-1:50:00 (repeatable)")
    sp.add_argument("--hot", type=int, default=3); sp.set_defaults(fn=cmd_fetch_url)

    sp = sub.add_parser("transcribe", help="word-level transcripts for a batch")
    sp.add_argument("path", help="batch dir or streamer key (today)")
    sp.add_argument("--model", default=None, help="tiny/base/small/medium (default small)")
    sp.set_defaults(fn=cmd_transcribe)

    sp = sub.add_parser("review", help="find moments, write review.md")
    sp.add_argument("path"); sp.add_argument("--top", type=int, default=6); sp.set_defaults(fn=cmd_review)

    sp = sub.add_parser("prep", help="fetch + transcribe + review in one go ('all' = every Twitch streamer)")
    sp.add_argument("streamer"); fetch_opts(sp)
    sp.add_argument("--model", default=None); sp.add_argument("--top", type=int, default=6)
    sp.set_defaults(fn=cmd_prep)

    sp = sub.add_parser("frame", help="grab a gridded frame to locate the facecam")
    sp.add_argument("job"); sp.add_argument("--at", default="10"); sp.set_defaults(fn=cmd_frame)

    sp = sub.add_parser("facecam", help="save a streamer's facecam box (x y w h fractions)")
    sp.add_argument("streamer"); sp.add_argument("box", nargs=4)
    sp.add_argument("--job", help="job dir to render a preview from"); sp.add_argument("--at", default="10")
    sp.set_defaults(fn=cmd_facecam)

    sp = sub.add_parser("preview", help="render one still of the final layout")
    sp.add_argument("job"); sp.add_argument("--streamer"); sp.add_argument("--at", default="10")
    sp.set_defaults(fn=cmd_preview)

    sp = sub.add_parser("render", help="render picks.json into finished Shorts ('all' = every batch from today)")
    sp.add_argument("path"); sp.add_argument("--picks"); sp.set_defaults(fn=cmd_render)

    sp = sub.add_parser("clean", help="delete old downloads")
    sp.add_argument("--days", type=int, default=3); sp.set_defaults(fn=cmd_clean)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
