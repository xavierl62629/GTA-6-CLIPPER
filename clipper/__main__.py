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


def cmd_import(a):
    """Bring in a video file the user sent (when it can't be downloaded here)."""
    from . import fetch
    from .util import need, run, save_json, slug
    need("ffmpeg")
    src = Path(a.file).expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"No such file: {src}")
    cfg = config.get(a.streamer)
    job = fetch.batch_dir(cfg["key"]) / slug(a.title or src.stem, 30)
    job.mkdir(parents=True, exist_ok=True)
    out = job / "source.mp4"
    try:   # remux if the codecs already fit in mp4, else re-encode
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(out)])
    except Exception:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:v", "libx264", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    save_json(job / "meta.json", {"streamer": cfg["key"], "kind": "video", "url": a.url or "",
                                  "title": a.title or src.stem})
    print(f"Imported -> {job}")


def _cut_points(words: list[dict]) -> list[tuple[float, float]]:
    """(time, pause length) after each word: the pauses are where a part can end cleanly."""
    pts = []
    for w, nxt in zip(words, words[1:]):
        gap = float(nxt["s"]) - float(w["e"])
        bonus = 0.5 if str(w["w"]).rstrip().endswith((".", "?", "!")) else 0.0
        pts.append(((float(w["e"]) + float(nxt["s"])) / 2, gap + bonus))
    return pts


def cmd_parts(a):
    """Split a whole video into back-to-back parts of at most --max seconds, cut at pauses."""
    from .util import probe, save_json
    job = Path(a.job)
    dur = probe(job / "source.mp4")["duration"]
    words = (load_json(job / "words.json") or {}).get("words", [])
    pts = _cut_points(words)
    cuts, cur = [], 0.0
    while dur - cur > a.max:
        window = [(t, g) for t, g in pts if cur + a.max * 0.6 <= t <= cur + a.max]
        cur = max(window, key=lambda tg: (tg[1], tg[0]))[0] if window else cur + a.max
        cuts.append(cur)
    bounds = [0.0] + cuts + [dur]
    n = len(bounds) - 1
    title = a.title or load_json(job / "meta.json", {}).get("title", job.name)
    picks = []
    for i in range(n):
        pick = {"job": job.name, "start": round(bounds[i], 2), "end": round(bounds[i + 1], 2),
                "hook": f"Part {i + 1}" + (f" of {n}" if n > 1 else ""),
                "title": f"{title} part {i + 1}", "caption": f"{title} (part {i + 1}/{n})"}
        if a.filler:
            pick.update(layout="stack", filler=str(Path(a.filler).resolve()), filler_start=i * 41.0)
        picks.append(pick)
    save_json(job.parent / "picks.json", picks)
    for p_ in picks:
        print(f"  {p_['hook']:<12} {fmt_time(p_['start'])} - {fmt_time(p_['end'])}  ({p_['end'] - p_['start']:.0f}s)")
    print(f"Wrote {n} parts -> {job.parent / 'picks.json'} (edit hooks/captions there, then render)")


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

    sp = sub.add_parser("import", help="bring in a local video file (e.g. one the user sent)")
    sp.add_argument("file"); sp.add_argument("--streamer", required=True)
    sp.add_argument("--title"); sp.add_argument("--url", help="original link, for posts.md")
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("parts", help="split a whole video into reel-length parts (writes picks.json)")
    sp.add_argument("job"); sp.add_argument("--max", type=float, default=90.0, help="max seconds per part (default 90)")
    sp.add_argument("--filler", help="gameplay video for the bottom half (stack layout), e.g. Subway Surfers")
    sp.add_argument("--title"); sp.set_defaults(fn=cmd_parts)

    sp = sub.add_parser("clean", help="delete old downloads")
    sp.add_argument("--days", type=int, default=3); sp.set_defaults(fn=cmd_clean)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
