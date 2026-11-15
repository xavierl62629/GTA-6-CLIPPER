"""Render picks into finished 1080x1920 Shorts with ffmpeg."""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from pathlib import Path

from . import captions, config
from .util import EXPORTS, FONTS, fmt_time, load_json, need, probe, run, save_json, slug

W, H = 1080, 1920
FACE_H = 768            # split layout: facecam band on top
GAME_H = H - FACE_H     # gameplay band below


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def _box(frac, sw: int, sh: int) -> tuple[int, int, int, int]:
    x, y, w, h = frac
    x, y = _even(x * sw), _even(y * sh)
    w, h = min(_even(w * sw), sw - x), min(_even(h * sh), sh - y)
    return x, y, w, h


def _crop_to_aspect(region: tuple[int, int, int, int], aspect: float) -> tuple[int, int, int, int]:
    """Largest centred crop of region with width/height == aspect."""
    x, y, w, h = region
    if w / h > aspect:
        nw = _even(h * aspect)
        return x + (w - nw) // 2 // 2 * 2, y, nw, h
    nh = _even(w / aspect)
    return x, y + (h - nh) // 2 // 2 * 2, w, nh


def effective_layout(cfg: dict) -> str:
    layout = cfg.get("layout", "split")
    if layout == "split" and not cfg.get("facecam"):
        return "fit"
    return layout


def video_graph(cfg: dict, sw: int, sh: int, subs: str = "captions.ass") -> str:
    layout = effective_layout(cfg)
    tail = f"fps=30,format=yuv420p,subtitles={subs}:fontsdir=fonts[v]"
    if layout == "split":
        fx, fy, fw, fh = _box(cfg["facecam"], sw, sh)
        game = _box(cfg["gameplay"], sw, sh) if cfg.get("gameplay") else (0, 0, sw, sh)
        gx, gy, gw, gh = _crop_to_aspect(game, W / GAME_H)
        return (f"[0:v]split=2[a][b];"
                f"[a]crop={fw}:{fh}:{fx}:{fy},scale={W}:{FACE_H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{FACE_H},setsar=1[face];"
                f"[b]crop={gw}:{gh}:{gx}:{gy},scale={W}:{GAME_H},setsar=1[game];"
                f"[face][game]vstack=2,{tail}")
    if layout == "crop":
        return f"[0:v]scale=-2:{H},crop={W}:{H},setsar=1,{tail}"
    # fit: blurred full-bleed background + the (slightly zoomed) frame in the middle
    cx, cy, cw, ch = _crop_to_aspect((0, 0, sw, sh), float(cfg.get("fit_aspect", 4 / 3)))
    return (f"[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,"
            f"eq=brightness=-0.10,setsar=1[bg];"
            f"[b]crop={cw}:{ch}:{cx}:{cy},scale={W}:-2,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{tail}")


def _workdir(ass_text: str) -> tempfile.TemporaryDirectory:
    """ffmpeg's subtitles filter hates special chars in paths, so run from a temp dir."""
    tmp = tempfile.TemporaryDirectory(prefix="clipper-")
    Path(tmp.name, "captions.ass").write_text(ass_text, encoding="utf-8")
    shutil.copytree(FONTS, Path(tmp.name, "fonts"))
    return tmp


def render_clip(job: Path, pick: dict, cfg: dict, out: Path) -> Path:
    need("ffmpeg")
    info = probe(job / "source.mp4")
    start = max(0.0, float(pick["start"]))
    end = min(info["duration"], float(pick["end"]))
    if end - start < 1:
        raise ValueError(f"Pick {pick.get('title')!r} is under a second long ({start}-{end})")
    words = (load_json(job / "words.json") or {}).get("words", [])
    ass = captions.build(words, start, end, cfg, effective_layout(cfg),
                         hook=pick.get("hook"), credit=config.credit_line(cfg))
    out.parent.mkdir(parents=True, exist_ok=True)
    with _workdir(ass) as tmp:
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
               "-i", str((job / "source.mp4").resolve())]
        if info["has_audio"]:
            audio = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]"
        else:
            cmd += ["-f", "lavfi", "-t", f"{end - start:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            audio = "[1:a]anull[aout]"
        graph = video_graph(cfg, info["width"], info["height"]) + ";" + audio
        cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest",
                str(out.resolve())]
        run(cmd, cwd=tmp)
    return out


def preview(job: Path, cfg: dict, at: float = 10.0) -> Path:
    """One still of the final layout, to check the facecam box looks right."""
    info = probe(job / "source.mp4")
    at = min(at, max(0.0, info["duration"] - 1))
    sample = [{"w": "SAMPLE", "s": at, "e": at + 0.5}, {"w": "CAPTION", "s": at + 0.5, "e": at + 1}]
    ass = captions.build(sample, at, at + 4, cfg, effective_layout(cfg),
                         hook="Hook text goes here", credit=config.credit_line(cfg))
    out = job / "preview.png"
    with _workdir(ass) as tmp:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str((job / "source.mp4").resolve()),
             "-filter_complex", video_graph(cfg, info["width"], info["height"]),
             "-map", "[v]", "-frames:v", "1", str(out.resolve())], cwd=tmp)
    return out


def grid_frame(job: Path, at: float = 10.0) -> Path:
    """A source frame with a labelled 10% grid, for reading off the facecam box."""
    info = probe(job / "source.mp4")
    at = min(at, max(0.0, info["duration"] - 1))
    font = (FONTS / "InterDisplay-Black.otf").resolve()
    labels = []
    for i in range(1, 10):
        f = i / 10
        labels.append(f"drawtext=fontfile='{font}':text='{f:.1f}':x=w*{f}+4:y=6:fontsize=h/36:"
                      f"fontcolor=yellow:borderw=3")
        labels.append(f"drawtext=fontfile='{font}':text='{f:.1f}':x=6:y=h*{f}+4:fontsize=h/36:"
                      f"fontcolor=yellow:borderw=3")
    vf = "drawgrid=w=iw/10:h=ih/10:t=2:c=yellow@0.7," + ",".join(labels)
    out = job / "frame_grid.jpg"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(job / "source.mp4"),
         "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out)])
    return out


def check_pick(pick: dict) -> list[str]:
    warn = []
    length = float(pick["end"]) - float(pick["start"])
    if length < 7:
        warn.append(f"only {length:.0f}s long")
    if length > 60:
        warn.append(f"{length:.0f}s is long for a Short (aim for 15-45s)")
    hook = (pick.get("hook") or "").split()
    if not hook:
        warn.append("no hook text")
    elif len(hook) > 9:
        warn.append(f"hook is {len(hook)} words; keep it under ~8 so it reads in 2 seconds")
    return warn


def render_batch(batch: Path, picks_file: Path | None = None) -> Path:
    picks_file = picks_file or batch / "picks.json"
    picks = load_json(picks_file)
    if not picks:
        raise SystemExit(f"No picks in {picks_file}. Choose clips first (see review.md).")
    streamer = batch.parent.name
    cfg = config.get(streamer)
    outdir = EXPORTS / streamer / dt.date.today().isoformat()
    lines = [f"# {cfg['name']} clips — {dt.date.today():%b %d}", "",
             f"Layout: **{effective_layout(cfg)}**  ·  Source: {config.credit_line(cfg)}", ""]
    done = []
    for n, pick in enumerate(picks, 1):
        job = batch / pick["job"]
        name = f"{n:02d}-{slug(pick.get('title') or pick.get('hook') or 'clip')}.mp4"
        out = outdir / name
        warns = check_pick(pick)
        print(f"[{n}/{len(picks)}] {name}" + (f"  (note: {'; '.join(warns)})" if warns else ""))
        try:
            render_clip(job, pick, cfg, out)
        except Exception as exc:
            print(f"   FAILED: {exc}")
            continue
        done.append(out)
        meta = load_json(job / "meta.json", {})
        tags = " ".join(pick.get("hashtags") or cfg["hashtags"])
        lines += [f"## {n}. {pick.get('title', '')}", "",
                  f"**File:** `{out.relative_to(EXPORTS.parent)}`  ",
                  f"**Length:** {float(pick['end']) - float(pick['start']):.0f}s  ",
                  f"**From:** {meta.get('url', '')} at {fmt_time(float(pick['start']))}", "",
                  "Caption to paste:", "```",
                  f"{pick.get('caption', pick.get('title', ''))}", "",
                  f"🎥 {cfg['name']} — {config.credit_line(cfg)}", tags, "```", ""]
    (outdir / "posts.md").parent.mkdir(parents=True, exist_ok=True)
    (outdir / "posts.md").write_text("\n".join(lines), encoding="utf-8")
    save_json(outdir / "picks.json", picks)
    print(f"\nRendered {len(done)}/{len(picks)} clips -> {outdir}")
    print(f"Titles + captions to paste: {outdir / 'posts.md'}")
    return outdir
