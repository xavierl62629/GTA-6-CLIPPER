#!/usr/bin/env bash
# Offline end-to-end check: fake stream -> moments -> facecam preview -> render.
# Usage: ./tests/selftest.sh     (needs ./setup.sh done; no internet needed)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export CLIPPER_WORK="$T/work" CLIPPER_EXPORTS="$T/exports" CLIPPER_CONFIG="$T/streamers.yaml"
cat > "$CLIPPER_CONFIG" <<'YAML'
streamers:
  teststreamer:
    name: Test Streamer
    platform: twitch
    handle: teststreamer
    facecam: null
YAML
B="$("$PY" tests/make_fixture.py "$CLIPPER_WORK")"
"$PY" -m clipper review teststreamer >/dev/null
n=$(grep -c "^### candidate" "$B/review.md")
[ "$n" -ge 3 ] || { echo "FAIL: expected >=3 candidates, got $n"; exit 1; }
"$PY" -m clipper facecam teststreamer 0.72 0.03 0.26 0.30 --job "$B/stream1" >/dev/null
cat > "$B/picks.json" <<'JSON'
[{"job":"stream1","start":55.5,"end":76.5,"hook":"Self test","title":"selftest one"},
 {"job":"clip1","start":0,"end":30,"hook":"Wait for it","title":"selftest two"}]
JSON
"$PY" -m clipper render teststreamer >/dev/null
for f in "$CLIPPER_EXPORTS"/teststreamer/*/*.mp4; do
  dims=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$f")
  [ "$dims" = "1080,1920" ] || { echo "FAIL: $f is $dims"; exit 1; }
done
count=$(ls "$CLIPPER_EXPORTS"/teststreamer/*/*.mp4 | wc -l)
[ "$count" -eq 2 ] || { echo "FAIL: expected 2 clips, got $count"; exit 1; }
echo "PASS: moments found, facecam preview, 2 clips rendered at 1080x1920"
