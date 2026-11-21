#!/bin/sh
# Builds a small, LGPL ffmpeg for Apple silicon from the official source (no external libraries, no GPL parts).
# Enough for: decoding ATRAC3 / ATRAC3+ (.oma), MP3, FLAC, WAV; writing WAV and FLAC; metadata tags; resampling and filters.
# H.264 video comes from Apple's own VideoToolbox encoder (h264_videotoolbox; no extra library, LGPL-safe): the TV picture and the lyric video use it.
# It does NOT yet have an MP3 encoder (needs LAME) or the text/subtitle filters the lyric video draws with: add those later.
# Needs the Xcode command line tools and internet. Works in ~/mdm-ffbuild; the result is ~/mdm-ffbuild/ffmpeg-$V/ffmpeg
set -e
V=8.1.3
W="$HOME/mdm-ffbuild"
mkdir -p "$W"; cd "$W"
[ -f "ffmpeg-$V.tar.xz" ] || curl -sSfLO "https://ffmpeg.org/releases/ffmpeg-$V.tar.xz"
shasum -a 256 "ffmpeg-$V.tar.xz" | tee source.sha256
[ -d "ffmpeg-$V" ] || tar xf "ffmpeg-$V.tar.xz"
cd "ffmpeg-$V"
./configure --disable-gpl --disable-nonfree --disable-autodetect --disable-doc --disable-ffplay --disable-ffprobe \
  --disable-shared --enable-static --enable-zlib --enable-iconv --enable-videotoolbox --enable-pthreads --disable-debug --arch=arm64 --extra-libs=-liconv > "$W/configure.log" 2>&1
tail -5 "$W/configure.log"
make -j"$(sysctl -n hw.ncpu)" > "$W/make.log" 2>&1
./ffmpeg -hide_banner -version | head -3
echo "FFBUILD-DONE"
