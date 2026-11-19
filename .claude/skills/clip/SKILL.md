---
name: clip
description: Turn GTA 6 streams from the streamers in streamers.yaml into captioned vertical Shorts (1080x1920) ready to post. Use when the user runs /clip, says "clip <streamer>", "make clips from <url>", "set up <streamer>'s facecam", or asks to make TikToks/Shorts/Reels from a stream.
---

# /clip — stream → captioned Shorts

You run a local pipeline (`python -m clipper`) for the mechanical work and use your own judgment
for the creative part: picking moments and writing hooks. Run every command from the repo root
with the venv's Python: `.venv/bin/python -m clipper ...` (on first use, if `.venv` is missing,
tell the user to run `./setup.sh` and stop).

Arguments: `/clip <streamer>` (a key from streamers.yaml), `/clip all`, `/clip <url> <streamer>`,
or `/clip setup <streamer>`. With no argument, run `.venv/bin/python -m clipper streamers` and ask
which one.

The user often runs this **from their phone** in a cloud session. They can't open files on this
machine, so finished videos must be *sent* to them (step 5), and everything you show them should
read well on a small screen: short messages, no wide tables.

## `/clip all` — one top video per Twitch streamer

1. `.venv/bin/python -m clipper prep all --limit 4` — fetches every Twitch streamer's top clips
   (last 24h, falling back to 7 days), transcribes them, and prints a summary. YouTube streamers
   (ishowspeed) are skipped: YouTube blocks cloud downloads. Mention that in one line.
   A streamer that FAILED shouldn't stop the others; report it at the end.
2. For each streamer that's ready, read their `review.md` and pick the **single best** clip
   (step 3 rules), and write a one-item `picks.json` in their batch folder.
3. Facecams and burned-in captions: same checks as below, per streamer. Do the facecam setup
   yourself without asking (you can see the frames); the user can't easily review previews on
   a phone.
4. Show all picks in one short list (one line each: streamer — hook — length), then render with
   `.venv/bin/python -m clipper render all` unless the user wants changes.
5. Deliver every video as in step 5.

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
   "frame": [0, 0, 1, 0.88],
   "hook": "He did NOT see the cops coming",
   "title": "Kai vs the Vice City police",
   "caption": "bro thought he was safe 💀",
   "hashtags": ["#gta6", "#kaicenat"]}
]
```
(`frame` is only needed when the source has burned-in captions — see below.)

### Check every picked job for burned-in captions (do this, it's easy to miss)

Many streams show their own live captions, and Twitch clips carry them. Ours on top = two
transcripts at once, which looks broken. For each job you picked:

1. `.venv/bin/python -m clipper frame <job_dir> --at <a time mid-clip with speech>` and Read it.
2. If there are captions/subtitles burned into the video, find the highest point they reach
   (check 2-3 times, they can wrap to two lines) and add to that pick
   `"frame": [0, 0, 1, Y]` where Y is a little above their top edge (e.g. captions start at
   0.90 → use 0.88). This crops them out; our captions replace them.
3. If cropping would cut off something important, instead set `"captions": false` on the pick
   to keep theirs and skip ours.
4. If a streamer *always* has captions in the same place, put `frame: [0, 0, 1, Y]` under them
   in streamers.yaml instead of on every pick.

### Fix mis-heard words

The speech model sometimes mis-hears (crowd noise, cars, music). If you have real evidence
of the right words (the stream's own captions, the clip title, an obvious name like
"Big Smoke"), edit those entries in the job's `words.json` — keep the `s`/`e` times and split
the time span if one wrong word becomes two. Don't guess without evidence; when unsure, start
the clip after the shaky bit instead.

Show the user your picks as a short table (hook, length, why it's good) before rendering.
If they're happy (or said to go ahead without checking), continue.

## 4. Render

`.venv/bin/python -m clipper render <batch>`

It writes `exports/<streamer>/<date>/NN-title.mp4` plus `posts.md`. Grab one frame from each
clip to sanity-check it (captions present, only one set of captions, face looks right):
`ffmpeg -v error -y -ss 2 -i <clip.mp4> -frames:v 1 -vf scale=540:-2 /tmp/check.png`
and Read it. Fix and re-render anything that looks wrong before sending.

## 5. Deliver: every video + its caption and hashtags

For **each** video, in order:
1. Send the .mp4 to the user with your file-sending tool (e.g. SendUserFile), with a short
   caption like "Kai Cenat — Big Smoke's order IRL (26s)". If you have no such tool (a local
   terminal session), give the file's path instead.
2. Right after it, post that video's ready-to-paste social caption as its own code block, so
   it's one tap to copy on a phone:

```
he really said two number 9s 💀

🎥 Kai Cenat — twitch.tv/kaicenat
#gta6 #gtavi #kaicenat #bigsmoke #twitch #fyp
```

Caption rules: 1 punchy line (max ~80 chars, ≤1 emoji) that teases the moment without
spoiling it; then the credit line exactly as in posts.md; then **5–8 hashtags**: #gta6 and
#gtavi, the streamer's tag, 1–3 tags specific to the moment (e.g. #bigsmoke, #vicecity, #cops),
and 1 broad discovery tag (#fyp or #gaming). Don't invent claims or tag unrelated trends.
Every video gets its own caption — never one shared caption for a batch.

End with one line summing up (e.g. "4 clips ready. Jynxzi failed: no clips this week.").

## Troubleshooting

- Any download error ("Unable to extract", HTTP 403/404, "Requested format is not available"):
  run `.venv/bin/python -m pip install -U yt-dlp` and retry. Sites change constantly.
- "No clips found": the streamer didn't stream in that window; try `--range 7d`.
- Subscriber-only VODs can't be downloaded; use their public clips instead.
- Disk filling up: `.venv/bin/python -m clipper clean --days 3` (keeps exports).
- Transcription too slow: add `--model base` (faster, a bit less accurate).
- A download blocked by the network ("Tunnel connection failed: 403") in a cloud session means
  Twitch moved its video files to a new host. Find it with
  `.venv/bin/yt-dlp -g <clip url>` and tell the user that host needs adding to the
  GTA 6 Clipper environment's allowed hosts.

Always keep the credit line; never strip a streamer's watermark or claim the content as the user's.

## Whole video in parts with filler gameplay (e.g. Subway Surfers underneath)

When the user wants a whole video cut into reel-length parts with gameplay running below:
1. Get the video: `fetch-url <url> --streamer <key>` if it downloads; YouTube usually doesn't from
   the cloud, so ask the user to send the file, then
   `.venv/bin/python -m clipper import <file> --streamer <key> --title "<short title>" --url <original link>`.
   (Add the video's creator to streamers.yaml first so the credit line is right.)
2. The filler gameplay must be a file the user provides (their own recording). Never invent or fetch one.
3. `transcribe <batch>`, then `parts <job_dir> --max 90 --filler <filler.mp4>` writes picks.json with
   back-to-back parts cut at pauses ("Part 1 of N" hooks). Edit captions there if wanted, then `render <batch>`.
