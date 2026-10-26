#!/usr/bin/env bash
# Bir bölümün çekimlerini sırayla tek bir videoda birleştirir.
# Kullanım: bash birlestir.sh <klip_klasoru> <cikti.mp4>
# Örnek:    bash birlestir.sh $COMFY/output/bolum1 bolum1.mp4
set -euo pipefail

dir="$1"
out="$2"
list=$(mktemp)

for f in $(ls "$dir"/shot_*.mp4 | sort); do
  echo "file '$(realpath "$f")'" >> "$list"
done
cat "$list"

ffmpeg -y -f concat -safe 0 -i "$list" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k \
  -movflags +faststart "$out"
rm "$list"
echo "Hazır: $out"
