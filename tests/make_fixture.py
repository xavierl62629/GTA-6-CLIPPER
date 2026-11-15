"""Builds a fake stream so the pipeline can be tested with no network.

Usage: python tests/make_fixture.py <work_dir>
Makes <work_dir>/teststreamer/<today>/{stream1,clip1}/ with source.mp4,
meta.json and a hand-written words.json (so no speech model is needed).
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

work = Path(sys.argv[1])
batch = work / "teststreamer" / dt.date.today().isoformat()


def make(job: str, dur: int, bursts: list[int]):
    d = batch / job
    d.mkdir(parents=True, exist_ok=True)
    # quiet noise bed, with loud tone bursts at the 'hype' moments
    vol = "+".join(f"between(t,{b},{b + 3})*0.9" for b in bursts) or "0"
    audio = f"aevalsrc='(0.03+{vol})*sin(2*PI*220*t)+0.02*(random(0)-0.5)':s=48000:d={dur}"
    video = (f"testsrc2=s=1920x1080:r=30:d={dur},"
             # 'facecam' in the top-right corner: magenta box labelled FACE
             "drawbox=x=iw*0.72:y=ih*0.03:w=iw*0.26:h=ih*0.30:color=magenta@1:t=fill,"
             "drawtext=fontfile=fonts/InterDisplay-Black.otf:text=FACE:x=w*0.80:y=h*0.13:fontsize=90:fontcolor=white")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(d / "source.mp4")], check=True)
    # fake transcript: calm talk, then hype words at each burst
    words, t = [], 1.0
    calm = "so we are just driving around vice city right now chat".split()
    hype = "YO NO WAY BRO what was that oh my god let's go".split()
    while t < dur - 2:
        near = any(b - 1 <= t <= b + 4 for b in bursts)
        for w in (hype if near else calm):
            words.append({"w": w + ("!" if near and w in ("WAY", "go") else ""), "s": round(t, 2),
                          "e": round(t + 0.32, 2), "p": 0.9})
            t += 0.42 if near else 0.38
            if t >= dur - 2:
                break
        t += 1.2  # pause between sentences
    (d / "words.json").write_text(json.dumps({"language": "en", "words": words, "segments": []}))
    (d / "meta.json").write_text(json.dumps({"streamer": "teststreamer", "kind": "vod" if dur > 90 else "clip",
                                             "url": f"https://example.invalid/{job}", "title": f"Fake {job}",
                                             "views": 12345}))


make("stream1", 180, [60, 130])
make("clip1", 30, [12])
print(batch)
