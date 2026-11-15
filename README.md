# GTA 6 Clipper

A learning project: turn GTA 6 streams into captioned vertical Shorts (TikTok / YouTube Shorts / Reels)
using Claude Code. Free, runs on your own computer.

```
Twitch top clips / YouTube "most replayed" ──► transcript (word-level) ──► Claude picks moments
        + writes hooks ──► ffmpeg renders 1080×1920: facecam on top, gameplay below,
        word-by-word captions, hook banner, streamer credit ──► you post them
```

## One-time setup

Needs macOS (with [Homebrew](https://brew.sh)) or Ubuntu/Debian. On Windows, run `wsl --install`
in PowerShell first and do everything inside Ubuntu.

```bash
git clone https://github.com/xavierl62629/GTA-6-CLIPPER.git
cd GTA-6-CLIPPER
./setup.sh          # installs ffmpeg, yt-dlp, the speech model (~20 min, mostly downloading)
```

## Making clips

Open Claude Code in this folder (`claude`), then:

```
/clip kaicenat
```

The first time for each streamer, Claude also sets up where their webcam sits (it looks at a frame
and shows you a preview). After that it's: fetch → transcribe → Claude picks 3–5 moments and writes
hooks → you OK them → rendered clips land in `exports/<streamer>/<date>/` with a `posts.md` of
captions to paste.

Other things to try: `/clip https://www.twitch.tv/videos/123 xqc`, `/clip setup jynxzi`.

Streamers live in [`streamers.yaml`](streamers.yaml) — add or remove them there.

## Running it by hand (no Claude)

```bash
source .venv/bin/activate
python -m clipper streamers                 # list streamers + facecam status
python -m clipper prep kaicenat             # fetch top clips, transcribe, write review.md
# ...write work/kaicenat/<date>/picks.json (see .claude/skills/clip/SKILL.md for the format)
python -m clipper render kaicenat           # -> exports/kaicenat/<date>/
python -m clipper clean --days 3            # delete old downloads
```

## Layouts

| `layout` in streamers.yaml | Look |
|---|---|
| `split` (default) | Facecam band on top, gameplay below. Needs `facecam` set. |
| `fit` | Whole frame in the middle, blurred copy filling top/bottom. Used automatically when no facecam. |
| `crop` | Centre of the frame, zoomed to fill the screen. |

If a stream has its own captions burned in, set `frame: [0, 0, 1, 0.88]` (on the streamer or a single
pick) to crop them off the bottom, or `captions: false` to keep theirs instead of ours.

## Be a good clipper

These are other people's streams. Credit is added to every clip and `posts.md` automatically; keep it.
Platforms can take down unauthorised clips, so check whether a streamer welcomes clippers
(many say so in their Twitch panels or Discord) before posting a lot of them.

## Pieces

| File | What it does |
|---|---|
| `clipper/fetch.py` | yt-dlp: Twitch top clips, YouTube most-replayed sections, any URL |
| `clipper/transcribe.py` | faster-whisper word-level transcript |
| `clipper/moments.py` | scores loudness spikes + hype words to find moments in long videos |
| `clipper/captions.py` | builds word-by-word pop captions (.ass subtitles) |
| `clipper/render.py` | ffmpeg layouts, loudness normalisation, `posts.md` |
| `.claude/skills/clip/SKILL.md` | the `/clip` workflow Claude follows |
| `tests/make_fixture.py` | fake stream for testing without the internet |

Caption font: Inter Display Black (SIL Open Font License, see `fonts/LICENSE-Inter.txt`).
