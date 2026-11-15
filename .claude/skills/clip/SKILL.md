---
name: clip
description: Turn GTA 6 streams from the streamers in streamers.yaml into captioned vertical Shorts (1080x1920) ready to post. Use when the user runs /clip, says "clip <streamer>", "make clips from <url>", "set up <streamer>'s facecam", or asks to make TikToks/Shorts/Reels from a stream.
---

# /clip — stream → captioned Shorts

You run a local pipeline (`python -m clipper`) for the mechanical work and use your own judgment
for the creative part: picking moments and writing hooks. Run every command from the repo root
with the venv's Python: `.venv/bin/python -m clipper ...` (on first use, if `.venv` is missing,
tell the user to run `./setup.sh` and stop).

Arguments: `/clip <streamer>` (a key from streamers.yaml), `/clip <url> <streamer>`, or
`/clip setup <streamer>`. With no argument, run `.venv/bin/python -m clipper streamers` and ask
which one.

## 1. Facecam setup (once per streamer)

Check `streamers` output. If the streamer's facecam is NOT set, do this before rendering
(clips still work without it — they fall back to the full-frame "fit" layout — but the
face-on-top layout is the point):

1. Fetch first (step 2) so you have a job folder with a `source.mp4`.
2. `.venv/bin/python -m clipper frame <job_dir> --at 8` → Read the `frame_grid.jpg` it prints.
   The yellow grid lines are at every 0.1 of width/height.
3. Find the webcam box. Estimate `x y w h` as fractions; err slightly inside the box edges
   so no game UI or border leaks in.
4. `.venv/bin/python -m clipper facecam <streamer> X Y W H --job <job_dir> --at 8`
   → Read the `preview.png` it prints. Face should fill the top band, centred, no borders.
   Adjust and repeat until it looks right (usually 1–3 tries).
5. If there's no webcam in this streamer's layout, leave facecam unset.

Some streamers move their camera between games or scenes; if a preview looks wrong for a
particular job, say so rather than forcing it.

## 2. Fetch + transcribe + find moments

- Twitch streamer: `.venv/bin/python -m clipper prep <streamer>`
  (top clips from the last 24h; add `--range 7d` if there aren't enough, `--limit N` for more).
- YouTube streamer (e.g. ishowspeed): same `prep` command. It finds their latest finished
  stream and downloads only the 3 most-replayed sections. If YouTube has no replay data yet
  (stream ended < ~1 day ago), ask the user for a timestamp range and use:
  `.venv/bin/python -m clipper fetch-url <url> --streamer <key> --section 1:20:00-1:50:00`
  then `transcribe <batch>` and `review <batch>`.
- A specific URL: `fetch-url <url> --streamer <key>`, then `transcribe` and `review`.

Prep prints the path of `review.md`. Transcription is the slow step (a few minutes); let it run.

## 3. Pick moments and write hooks (your job)

Read `review.md`. Each job lists candidate windows with timestamped transcripts
(times are seconds into that job's `source.mp4`). Choose the best 3–5 clips across all jobs.

Picking:
- Pick moments with a clear setup → payoff: a reaction, a fail, a fight, a hilarious line,
  a genuinely surprising game moment. Skip dead air, menus, loading screens, and chat-reading.
- Twitch clips are already short and pre-picked by viewers; mostly trim the lead-in so the
  clip starts 0–1s before the setup line, and end right after the reaction lands.
- Long-video candidates: tighten to 15–45s. Start on the first words of the setup, not
  mid-sentence; use the word timestamps.
- Skip clips that are mostly copyrighted music, someone else's video being watched, or that
  mock/target a private person, show personal info, or contain sexual content.

Hook (the white banner shown for the first 3 seconds):
- ≤ 8 words. Creates curiosity about what's about to happen, but doesn't spoil the payoff.
- Must be true to the clip. No fake claims ("GTA 6 LEAKED", invented drama).
- Good: "He did NOT expect the cops to do this" / "Kai's first 5 minutes in Vice City"
- Bad: "Funny moment" (vague), "He dies at the end" (spoiler), anything 12+ words.

Also write a short `title`, a one-line social `caption` (can use 1 emoji), and optional
`hashtags` (otherwise the streamer's defaults are used).

Write the picks to `<batch>/picks.json`:

```json
[
  {"job": "<job folder name>", "start": 12.4, "end": 38.9,
   "hook": "He did NOT see the cops coming",
   "title": "Kai vs the Vice City police",
   "caption": "bro thought he was safe 💀",
   "hashtags": ["#gta6", "#kaicenat"]}
]
```

Show the user your picks as a short table (hook, length, why it's good) before rendering.
If they're happy (or said to go ahead without checking), continue.

## 4. Render

`.venv/bin/python -m clipper render <batch>`

It writes `exports/<streamer>/<date>/NN-title.mp4` plus `posts.md` (the caption text to paste,
with credit to the streamer). Grab one frame from the first clip to sanity-check it:
`ffmpeg -v error -y -ss 2 -i <clip.mp4> -frames:v 1 -vf scale=540:-2 /tmp/check.png`
and Read it. Then tell the user where the clips are and show the posts.md contents.

## Troubleshooting

- Any download error ("Unable to extract", HTTP 403/404, "Requested format is not available"):
  run `.venv/bin/python -m pip install -U yt-dlp` and retry. Sites change constantly.
- "No clips found": the streamer didn't stream in that window; try `--range 7d`.
- Subscriber-only VODs can't be downloaded; use their public clips instead.
- Disk filling up: `.venv/bin/python -m clipper clean --days 3` (keeps exports).
- Transcription too slow: add `--model base` (faster, a bit less accurate).

Always keep the credit line; never strip a streamer's watermark or claim the content as the user's.
