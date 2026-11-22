#!/bin/sh
# Builds the Mac ffmpeg WITH MP3 encoding (LAME), https (OpenSSL) and the text filters the lyric video needs (libass + FreeType + HarfBuzz + FriBidi),
# for Apple silicon, from the official sources, all linked statically into one program. LGPL-3.0-or-later: no GPL parts, no non-free parts
# (OpenSSL 3 is Apache-2.0, which LGPL-3 allows with --enable-version3).
# Needs the Xcode command line tools and internet. Works in ~/mdm-ffbuild2; the result is ~/mdm-ffbuild2/ffmpeg-$V/ffmpeg
# Usage:  sh build_ffmpeg_full.sh      (about 15 to 30 minutes)
set -e
V=8.1.3
W="$HOME/mdm-ffbuild2"
P="$W/prefix"
NCPU=$(sysctl -n hw.ncpu)
mkdir -p "$W/src" "$P"; cd "$W/src"
export PATH="$P/bin:$PATH"
export PKG_CONFIG_PATH="$P/lib/pkgconfig"
export CFLAGS="-O2 -arch arm64 -mmacosx-version-min=13.0"
export CXXFLAGS="$CFLAGS"
export LDFLAGS="-arch arm64 -mmacosx-version-min=13.0"
dl() { [ -f "$2" ] || curl -sSfL --retry 3 -o "$2" "$1"; }
step() { echo; echo "=== $1  ($(date +%T))"; }

step "sources"
dl "https://ffmpeg.org/releases/ffmpeg-$V.tar.xz" ffmpeg.tar.xz
dl "https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz" lame.tar.gz
dl "https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz" opus.tar.gz
dl "https://github.com/openssl/openssl/releases/download/openssl-3.5.4/openssl-3.5.4.tar.gz" openssl.tar.gz
dl "https://download.savannah.gnu.org/releases/freetype/freetype-2.13.3.tar.xz" freetype.tar.xz
dl "https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz" fribidi.tar.xz
dl "https://github.com/harfbuzz/harfbuzz/releases/download/10.2.0/harfbuzz-10.2.0.tar.xz" harfbuzz.tar.xz
dl "https://github.com/libass/libass/releases/download/0.17.3/libass-0.17.3.tar.xz" libass.tar.xz
dl "https://distfiles.ariadne.space/pkgconf/pkgconf-2.3.0.tar.xz" pkgconf.tar.xz
shasum -a 256 *.tar.* | tee "$W/sources.sha256"
unpack() { rm -rf "$1"; mkdir "$1"; tar xf "$2" -C "$1" --strip-components=1; }
unpack pkgconf pkgconf.tar.xz; unpack lame lame.tar.gz; unpack opus opus.tar.gz; unpack openssl openssl.tar.gz; unpack freetype freetype.tar.xz
unpack fribidi fribidi.tar.xz; unpack harfbuzz harfbuzz.tar.xz; unpack libass libass.tar.xz; unpack ffmpeg ffmpeg.tar.xz

step "pkgconf"
(cd pkgconf && ./configure --prefix="$P" --with-pkg-config-dir="$P/lib/pkgconfig" > "$W/pkgconf.log" 2>&1 && make -j"$NCPU" >> "$W/pkgconf.log" 2>&1 && make install >> "$W/pkgconf.log" 2>&1)
ln -sf pkgconf "$P/bin/pkg-config"
pkg-config --version

step "LAME (MP3 encoder, LGPL)"
(cd lame && ./configure --prefix="$P" --disable-shared --enable-static --disable-frontend --disable-decoder > "$W/lame.log" 2>&1 && make -j"$NCPU" >> "$W/lame.log" 2>&1 && make install >> "$W/lame.log" 2>&1)

step "Opus (spatial audio encoder, BSD-3)"
(cd opus && ./configure --prefix="$P" --disable-shared --enable-static --disable-doc --disable-extra-programs > "$W/opus.log" 2>&1 && make -j"$NCPU" >> "$W/opus.log" 2>&1 && make install >> "$W/opus.log" 2>&1)

step "OpenSSL (https, Apache-2.0)"
(cd openssl && ./Configure darwin64-arm64-cc no-shared no-tests no-docs --prefix="$P" --openssldir=/etc/ssl > "$W/openssl.log" 2>&1 && make -j"$NCPU" >> "$W/openssl.log" 2>&1 && make install_sw >> "$W/openssl.log" 2>&1)

step "FreeType"
(cd freetype && ./configure --prefix="$P" --disable-shared --enable-static --with-harfbuzz=no --with-png=no --with-bzip2=no --with-brotli=no --with-zlib=yes > "$W/freetype.log" 2>&1 && make -j"$NCPU" >> "$W/freetype.log" 2>&1 && make install >> "$W/freetype.log" 2>&1)

step "FriBidi"
(cd fribidi && ./configure --prefix="$P" --disable-shared --enable-static --disable-docs > "$W/fribidi.log" 2>&1 && make -j"$NCPU" >> "$W/fribidi.log" 2>&1 && make install >> "$W/fribidi.log" 2>&1)

step "CMake (for HarfBuzz; downloaded for this build only)"
CM=""
for c in "$HOME/mdm-atrac/cmake-dist/CMake.app/Contents/bin/cmake" "$W/cmake-dist/CMake.app/Contents/bin/cmake"; do [ -x "$c" ] && CM="$c" && break; done
if [ -z "$CM" ]; then
  dl "https://github.com/Kitware/CMake/releases/download/v3.31.6/cmake-3.31.6-macos-universal.tar.gz" cmake.tar.gz
  mkdir -p "$W/cmake-dist"; tar xzf cmake.tar.gz -C "$W/cmake-dist" --strip-components=1
  CM="$W/cmake-dist/CMake.app/Contents/bin/cmake"
fi
echo "cmake: $CM"

step "HarfBuzz (MIT)"
rm -rf harfbuzz-build
"$CM" -S harfbuzz -B harfbuzz-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$P" -DBUILD_SHARED_LIBS=OFF -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_PREFIX_PATH="$P" -DHB_HAVE_FREETYPE=ON -DHB_HAVE_CORETEXT=OFF -DHB_HAVE_GLIB=OFF -DHB_HAVE_ICU=OFF -DHB_BUILD_UTILS=OFF -DHB_BUILD_TESTS=OFF > "$W/harfbuzz.log" 2>&1
"$CM" --build harfbuzz-build -j"$NCPU" >> "$W/harfbuzz.log" 2>&1
"$CM" --install harfbuzz-build >> "$W/harfbuzz.log" 2>&1

step "libass (ISC)"
(cd libass && ./configure --prefix="$P" --disable-shared --enable-static --disable-fontconfig --disable-require-system-font-provider > "$W/libass.log" 2>&1 && make -j"$NCPU" >> "$W/libass.log" 2>&1 && make install >> "$W/libass.log" 2>&1)

step "FFmpeg $V"
cd ffmpeg
./configure --disable-gpl --disable-nonfree --enable-version3 --disable-autodetect --disable-doc --disable-ffplay --disable-ffprobe \
  --disable-shared --enable-static --enable-zlib --enable-iconv --enable-videotoolbox --enable-pthreads --disable-debug --arch=arm64 \
  --enable-libmp3lame --enable-libopus --enable-openssl --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-libass \
  --pkg-config-flags=--static --extra-cflags="-I$P/include -mmacosx-version-min=13.0" --extra-ldflags="-L$P/lib -mmacosx-version-min=13.0" \
  --extra-libs="-liconv -lm -lc++" > "$W/configure.log" 2>&1 || { tail -n 25 "$W/configure.log"; exit 1; }
tail -n 4 "$W/configure.log"
make -j"$NCPU" > "$W/make.log" 2>&1 || { tail -n 25 "$W/make.log"; exit 1; }
./ffmpeg -hide_banner -version | head -n 3
echo "--- check:"
./ffmpeg -hide_banner -encoders 2>/dev/null | grep -i "mp3\|videotoolbox\|libopus" | head -n 4
./ffmpeg -hide_banner -filters 2>/dev/null | grep -i " subtitles \| drawtext " | head -n 3
./ffmpeg -hide_banner -protocols 2>/dev/null | grep -i -w "https\|tls" | head -n 3
echo "--- links:"
otool -L ./ffmpeg | head -n 14
echo "FFBUILD-DONE $(pwd)/ffmpeg"
