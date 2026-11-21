#!/bin/sh
# Builds the Node "usb" module 2.13.0 for macOS on Apple silicon against libusb 1.0.30 (the npm package ships libusb 1.0.27 and a C++14 build
# setting that current Node cannot compile). Needs the Xcode command line tools and internet. Works in ~/mdm-build and changes nothing else.
# The result, ~/mdm-build/package/build/Release/usb_bindings.node, goes to runtime/node_modules/usb/build/Release/ (node-gyp-build prefers it).
set -e
W="$HOME/mdm-build"
NODEV=v24.22.0
rm -rf "$W"; mkdir -p "$W"; cd "$W"
curl -sSfLO "https://nodejs.org/dist/$NODEV/node-$NODEV-darwin-arm64.tar.gz"
curl -sSfLO "https://nodejs.org/dist/$NODEV/SHASUMS256.txt"
grep "node-$NODEV-darwin-arm64.tar.gz" SHASUMS256.txt | shasum -a 256 -c -
tar xzf "node-$NODEV-darwin-arm64.tar.gz"
NODEDIR="$W/node-$NODEV-darwin-arm64"
export PATH="$NODEDIR/bin:$PATH"
curl -sSfLo usb.tgz https://registry.npmjs.org/usb/-/usb-2.13.0.tgz
echo "521d11244cbe991a3f247c770821635abdcc9c7f  usb.tgz" | shasum -a 1 -c -
tar xzf usb.tgz
curl -sSfLo libusb.tar.bz2 https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2
tar xjf libusb.tar.bz2
rm -rf package/libusb
mv libusb-1.0.30 package/libusb
cd package
npm install --omit=dev --ignore-scripts --no-audit --no-fund 2>&1 | tail -3
# current Node headers need C++20; build for this Mac (arm64) only
sed -i '' -e "s/-std=c++14/-std=c++20/" -e "s/-std=c++1y/-std=c++20/" -e "/-arch x86_64/d" -e "s/MACOSX_DEPLOYMENT_TARGET': '10.7'/MACOSX_DEPLOYMENT_TARGET': '12.0'/" binding.gyp
node "$NODEDIR/lib/node_modules/npm/node_modules/node-gyp/bin/node-gyp.js" rebuild --nodedir="$NODEDIR" > "$W/build.log" 2>&1
ls -l build/Release/usb_bindings.node
file build/Release/usb_bindings.node
