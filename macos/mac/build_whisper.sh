#!/bin/sh
# Builds whisper-cli (whisper.cpp, MIT licence) for Apple silicon from the official source: the speech recogniser the app's "Listen" lyrics feature runs.
# Static (one program, no extra libraries), with Apple's Accelerate and the GPU (Metal, its shader source is embedded and compiled by macOS when the
# program starts: no developer tools needed to run it). The language model it uses (ggml-small-q5_1.bin, ~190 MB) is downloaded by the app on request.
# Needs the Xcode command line tools and internet. Works in ~/mdm-whisper; the result is ~/mdm-whisper/whisper-cli
# Usage:  sh build_whisper.sh      (about 5 to 10 minutes)
set -e
W="$HOME/mdm-whisper"
mkdir -p "$W"; cd "$W"
NCPU=$(sysctl -n hw.ncpu)
CM=""
for c in "$HOME/mdm-ffbuild2/cmake-dist/CMake.app/Contents/bin/cmake" "$HOME/mdm-atrac/cmake-dist/CMake.app/Contents/bin/cmake" "$W/cmake-dist/CMake.app/Contents/bin/cmake"; do [ -x "$c" ] && CM="$c" && break; done
if [ -z "$CM" ]; then
  curl -sSfL --retry 3 -o cmake.tar.gz https://github.com/Kitware/CMake/releases/download/v3.31.6/cmake-3.31.6-macos-universal.tar.gz
  mkdir -p cmake-dist; tar xzf cmake.tar.gz -C cmake-dist --strip-components=1
  CM="$W/cmake-dist/CMake.app/Contents/bin/cmake"
fi
echo "cmake: $CM"
rm -rf src build; mkdir src
GOT=""
for tag in b5454 v1.7.6 v1.7.5; do
  if curl -sSfL --retry 2 -o whisper-src.tar.gz "https://github.com/ggml-org/whisper.cpp/archive/refs/tags/$tag.tar.gz"; then GOT="$tag"; break; fi
done
[ -n "$GOT" ] || { echo "Could not download the whisper.cpp source."; exit 1; }
echo "source tag: $GOT"; shasum -a 256 whisper-src.tar.gz | tee source.sha256
tar xzf whisper-src.tar.gz -C src --strip-components=1
"$CM" -S src -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
  -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON -DGGML_OPENMP=OFF -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_SERVER=OFF -DWHISPER_SDL2=OFF > configure.log 2>&1 || { tail -n 25 configure.log; exit 1; }
"$CM" --build build --config Release -j"$NCPU" --target whisper-cli > build.log 2>&1 || { tail -n 30 build.log; exit 1; }
BIN=$(find build -name whisper-cli -type f | head -n 1)
[ -n "$BIN" ] || { echo "whisper-cli was not built."; exit 1; }
cp "$BIN" "$W/whisper-cli"
strip -x "$W/whisper-cli" 2>/dev/null || true
codesign --force --sign - "$W/whisper-cli" 2>/dev/null || true
ls -la "$W/whisper-cli"
echo "--- links:"; otool -L "$W/whisper-cli"
cp src/LICENSE "$W/whisper.cpp-LICENSE-MIT.txt" 2>/dev/null || true
echo "WHISPER-DONE $W/whisper-cli ($GOT)"
