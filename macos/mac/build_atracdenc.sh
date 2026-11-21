#!/bin/sh
# Builds the ATRAC3+ encoder (atracdenc 0.2.3 with this program's one change, the "framesize" option) for macOS on Apple silicon, from the open
# source: atracdenc 0.2.3 (LGPL-2.1, https://github.com/dcherednik/atracdenc), libgha (BSD-2-Clause, commit b4ed00bf, a submodule of atracdenc) and
# libsndfile 1.2.2 (LGPL-2.1, linked in statically; it reads the WAV file). CMake is downloaded for the build only (nothing is installed system-wide).
# Needs the Xcode command line tools and internet. Works in ~/mdm-atrac. The patch is runtime/atracdenc3p/atracdenc-0.2.3-framesize.patch: copy it to
# /tmp/atracdenc-framesize.patch first. Result: ~/mdm-atrac/atracdenc-mac  (stripped, signed ad hoc), to be placed as runtime/atracdenc3p/atracdenc.
set -e
W="$HOME/mdm-atrac"
mkdir -p "$W"; cd "$W"
dl() { [ -f "$2" ] || curl -sSfL -o "$2" "$1"; }
dl https://github.com/dcherednik/atracdenc/archive/refs/tags/0.2.3.tar.gz atracdenc-0.2.3.tar.gz
dl https://github.com/dcherednik/libgha/archive/b4ed00bfd942e476fc9ab95adc0bc77bac407b28.tar.gz libgha.tar.gz
dl https://github.com/libsndfile/libsndfile/releases/download/1.2.2/libsndfile-1.2.2.tar.xz libsndfile-1.2.2.tar.xz
dl https://github.com/Kitware/CMake/releases/download/v3.31.6/cmake-3.31.6-macos-universal.tar.gz cmake.tar.gz
dl https://github.com/Kitware/CMake/releases/download/v3.31.6/cmake-3.31.6-SHA-256.txt cmake-sha.txt
grep "macos-universal.tar.gz" cmake-sha.txt | awk '{print $1"  cmake.tar.gz"}' | shasum -a 256 -c -
rm -rf cmake-dist libsndfile-src libgha-src; mkdir cmake-dist libsndfile-src libgha-src
tar xzf cmake.tar.gz -C cmake-dist --strip-components=1
tar xJf libsndfile-1.2.2.tar.xz -C libsndfile-src --strip-components=1
tar xzf libgha.tar.gz -C libgha-src --strip-components=1
CM="$W/cmake-dist/CMake.app/Contents/bin/cmake"; NCPU=$(sysctl -n hw.ncpu)
rm -rf sndfile-build prefix
"$CM" -S libsndfile-src -B sndfile-build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_PROGRAMS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF -DENABLE_EXTERNAL_LIBS=OFF -DENABLE_MPEG=OFF -DINSTALL_MANPAGES=OFF -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_INSTALL_PREFIX="$W/prefix" > sndfile-config.log 2>&1
"$CM" --build sndfile-build -j"$NCPU" > sndfile-build.log 2>&1
"$CM" --install sndfile-build > sndfile-install.log 2>&1
rm -rf atracdenc-src atracdenc-build; mkdir atracdenc-src
tar xzf atracdenc-0.2.3.tar.gz -C atracdenc-src --strip-components=1
rm -rf atracdenc-src/src/lib/libgha; cp -R libgha-src atracdenc-src/src/lib/libgha
(cd atracdenc-src && patch -p1 < /tmp/atracdenc-framesize.patch)
"$CM" -S atracdenc-src -B atracdenc-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_PREFIX_PATH="$W/prefix" -DLIBSNDFILE_INCLUDE_DIR="$W/prefix/include" -DLIBSNDFILE_LIBRARY="$W/prefix/lib/libsndfile.a" -DCMAKE_CXX_FLAGS="-include cstdint" -DCMAKE_EXE_LINKER_FLAGS="-L$W/prefix/lib" > atracdenc-config.log 2>&1
"$CM" --build atracdenc-build -j"$NCPU" > atracdenc-build.log 2>&1
cp atracdenc-build/src/atracdenc atracdenc-mac
strip -x atracdenc-mac                      # like the Windows build; stripping invalidates the signature, so sign it again (ad hoc)
codesign -s - --force atracdenc-mac
shasum -a 256 atracdenc-mac
file atracdenc-mac
