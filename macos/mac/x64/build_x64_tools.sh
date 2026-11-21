#!/bin/sh
# Builds the Intel (x86_64) versions of the Mac tools ON THE APPLE-SILICON MAC MINI, under Rosetta, by rewriting the arm64 build scripts in mac/ on the fly.
# Usage: sh build_x64_tools.sh <folder holding the build_*.sh scripts, atracdenc-0.2.3-framesize.patch>
# Everything works in ~/mdm-*-x64 folders; the arm64 build folders are not touched. Logs: ~/mdm-x64-logs/
set -e
S="${1:?folder with the build scripts}"
L="$HOME/mdm-x64-logs"; mkdir -p "$L" "$HOME/mdm-x64-scripts"
cp "$S/atracdenc-0.2.3-framesize.patch" /tmp/atracdenc-framesize.patch
X="$HOME/mdm-x64-scripts"
conv() {   # $1 script  $2 output
  sed -e 's/darwin-arm64/darwin-x64/g' -e 's/arm64/x86_64/g' -e 's#/-arch x86_64/d#/-arch arm64/d#' \
      -e 's#\$HOME/mdm-build"#$HOME/mdm-build-x64"#' -e 's#\$HOME/mdm-ffbuild2"#$HOME/mdm-ffbuild2-x64"#' \
      -e 's#\$HOME/mdm-whisper"#$HOME/mdm-whisper-x64"#' -e 's#\$HOME/mdm-atrac"#$HOME/mdm-atrac-x64"#' "$1" > "$2"
}
conv "$S/build_ffmpeg_full.sh" "$X/ffmpeg.sh"
sed -i '' -e 's/--arch=x86_64/--arch=x86_64 --disable-x86asm/' "$X/ffmpeg.sh"
conv "$S/build_whisper.sh" "$X/whisper.sh"
sed -i '' -e 's/-DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON/-DGGML_METAL=OFF -DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF/' "$X/whisper.sh"
conv "$S/build_atracdenc.sh" "$X/atrac.sh"
conv "$S/build_usb_module.sh" "$X/usb.sh"
grep -c x86_64 "$X"/*.sh
for t in ffmpeg whisper atrac usb; do
  ( arch -x86_64 /bin/sh "$X/$t.sh" > "$L/$t.log" 2>&1; echo "EXIT $?" >> "$L/$t.log" ) &
done
wait
tail -n 3 "$L"/*.log
