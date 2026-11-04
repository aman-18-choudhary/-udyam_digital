#!/bin/sh
# Joins the two recorded segments into an MP4, makes a short preview GIF for the README,
# and cuts still screenshots at the scene markers written by record_demo.py.
#   sh make_video.sh REC_DIR OUT_DIR
set -e
REC="$1"; OUT="$2"
LIVE=$(ls "$REC"/live/*.webm | head -1)
LOCAL=$(ls "$REC"/local/*.webm | head -1)
mkdir -p "$OUT"

ffmpeg -y -loglevel error -ss 10.5 -i "$LIVE" -i "$LOCAL" -filter_complex \
  "[0:v]fps=25,scale=1280:720,setsar=1[a];[1:v]fps=25,scale=1280:720,setsar=1[b];[a][b]concat=n=2:v=1:a=0[v]" \
  -map "[v]" -c:v libx264 -preset slow -crf 25 -pix_fmt yuv420p -movflags +faststart "$OUT/udyam-demo.mp4"

# the whole 3 minutes played 8x faster, 640 px wide: a glanceable preview that loads inside a README
ffmpeg -y -loglevel error -i "$OUT/udyam-demo.mp4" \
  -vf "setpts=PTS/8,fps=8,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5" \
  "$OUT/udyam-demo-preview.gif"

python3 - "$REC" "$OUT" "$LIVE" "$LOCAL" <<'PY'
import json, subprocess, sys
rec, out, live, local = sys.argv[1:5]
ml = json.load(open(f"{rec}/markers_live.json")); mc = json.load(open(f"{rec}/markers_local.json"))
shots = [  # name, source file, seconds into that file
    ("landing", live, ml["live_landing"] + 6.6),
    ("advisor", local, mc["recommendation"] + 3.5),
    ("rules", local, mc["rule_refusal"] + 3.0),
    ("quote", local, mc["dependency"] + 2.0),
    ("kyc", local, mc["kyc_fail"] + 2.7),
    ("tracker", local, mc["live"] + 2.0),
    ("console", local, mc["console"] + 4.0),
]
for name, src, t in shots:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.1f}", "-i", src, "-frames:v", "1", "-q:v", "3",
                    f"{out}/{name}.jpg"], check=True)
print("screenshots:", ", ".join(n for n, _, _ in shots))
PY
ls -la "$OUT"
