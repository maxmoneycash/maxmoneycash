#!/usr/bin/env bash
# Record a 30-second demo GIF for README / launch.
#
# Output: docs/screenshots/dashboard-demo.gif (target ≤ 4 MB so GitHub
# renders inline; throttle fps / palette if larger).
#
# Dependencies:
#   brew install ffmpeg gifski
#   (gifski produces noticeably better palettes than ffmpeg's gif encoder)
#
# Usage:
#   bash docs/launch/record-gif.sh
#
# What it does:
#   1. Reminds you of the 30s storyline
#   2. Launches a clean tracker serve on :7681 with a focused window position
#   3. Records the dashboard area for 30s as h264 mp4
#   4. Converts to optimized GIF with gifski
#   5. Drops the result into docs/screenshots/dashboard-demo.gif

set -euo pipefail

OUT_DIR="docs/screenshots"
OUT_MP4="$OUT_DIR/dashboard-demo.mp4"
OUT_GIF="$OUT_DIR/dashboard-demo.gif"
DURATION=30
FPS=15
WIDTH=1280

mkdir -p "$OUT_DIR"

cat <<EOF
╭──────────────────────────────────────────────────────────────╮
│  TokenTracker README GIF — 30s storyline                     │
├──────────────────────────────────────────────────────────────┤
│  0s   Show dashboard hero (Today's cost + sparkline)         │
│  5s   Click "Models" tab — point out cache read columns      │
│  10s  Click "Projects" tab — heatmap reveal                  │
│  15s  Open menu bar app icon (top-right) for 2s              │
│  20s  Switch back, click a widget for the by-CLI breakdown   │
│  27s  Cursor hovers "Featured in 阮一峰周刊 #393" badge       │
│  30s  End on hero again                                      │
╰──────────────────────────────────────────────────────────────╯

Recording starts in 5 seconds. Position the dashboard window in the
top-left 1280x720 region of your primary screen. ffmpeg will capture
exactly that rectangle.

EOF

for i in 5 4 3 2 1; do
  printf "  %s..." "$i"
  sleep 1
done
echo
echo "RECORDING $DURATION s ..."

# macOS: device id 1 = primary screen. Use ":2" if you have an external display.
# avfoundation -list_devices true -i "" can confirm.
ffmpeg -hide_banner -loglevel error \
  -f avfoundation -framerate $FPS -capture_cursor 1 \
  -i "1:none" \
  -t $DURATION \
  -vf "crop=${WIDTH}:720:0:0,scale=${WIDTH}:-2" \
  -pix_fmt yuv420p -c:v h264 -crf 18 \
  -y "$OUT_MP4"

echo "Captured to $OUT_MP4 ($(du -h "$OUT_MP4" | cut -f1))."

if ! command -v gifski >/dev/null; then
  echo "gifski not found — falling back to ffmpeg palette GIF (larger / worse)."
  ffmpeg -hide_banner -loglevel error \
    -i "$OUT_MP4" \
    -vf "fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
    -y "$OUT_GIF"
else
  ffmpeg -hide_banner -loglevel error -i "$OUT_MP4" -vf "fps=${FPS}" -f image2pipe -vcodec ppm - \
    | gifski -o "$OUT_GIF" --width $WIDTH --fps $FPS --quality 85 -
fi

SIZE=$(du -h "$OUT_GIF" | cut -f1)
echo "Done: $OUT_GIF ($SIZE)"
echo
echo "If size > 4MB, rerun with FPS=12 or WIDTH=1024:"
echo "  FPS=12 WIDTH=1024 bash $0"
echo
echo "Then swap the README hero image:"
echo "  in README.md (+ zh-CN / ja / ko), change docs/screenshots/dashboard-dark.png"
echo "  to docs/screenshots/dashboard-demo.gif"
