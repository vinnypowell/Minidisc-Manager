# MiniDisc Manager for macOS (beta)

Version 0.37.0 (beta) · for Macs with Apple silicon (M1 or newer), macOS 13 or newer.

This folder is the Mac version of MiniDisc Manager: the same program as the Windows version in the main folder, adapted for macOS.
The download is the `.dmg` on the Releases page (`MiniDisc-Manager-0.37.0-beta-mac-arm64.dmg`).

## What is different on the Mac

- **A background service.** macOS does not let ordinary programs talk to a recorder over USB, so a small service (`helper/mac_daemon.js`, installed with `mac/mac_install.sh`)
  holds the recorder and runs the disc commands for the app. The app asks for your Mac password once to install it. The service only runs a short list of
  checked commands, and a mount guard (`mac/native/mdm_mountguard.c`) keeps macOS from mounting the recorder's disc, because macOS would write to it.
- **Audio CDs** are read through macOS (`cdrip_mac.py`), **sound from streaming-site windows** is recorded with ScreenCaptureKit (`helper/appaudio_mac.swift`),
  and the optional lyric recogniser is whisper.cpp built for Apple silicon (`mac/build_whisper.sh`).
- **Not in the Mac version:** Yoto, Save to disc, the Bluetooth speaker chooser and Bluetooth label printing. Burn Audio CD is experimental. See
  [`mac/RELEASE-NOTES.txt`](mac/RELEASE-NOTES.txt) for what works, what is experimental and the known quirks.

## Installing

Open the `.dmg` and read **READ ME FIRST** ([`mac/DMG-READ-ME.txt`](mac/DMG-READ-ME.txt)). In short: drag the app to Applications; because the app is not
signed by Apple, open it once through System Settings > Privacy & Security > Open Anyway; press "Set up" when it offers to install the background service;
plug in the recorder and wait about a minute. `Uninstall MiniDisc Manager.command` in the disk image removes everything.

## Tested on

One Mac mini (M1, macOS 26) with one recorder, a Sony MZ-NH700, and a handful of Hi-MD and standard discs. Copy anything you cannot replace to your Mac before editing a disc.

## Intel Macs (highly experimental)

The 0.34.5 release carries `MiniDisc-Manager-0.34.5-experimental-mac-x86_64.dmg`, the program built for Intel Macs. There is no Intel version of 0.35.0 and it is no longer updated. It was built on an Apple silicon Mac and only its programs were run there, under Rosetta (ffmpeg, the ATRAC3+ encoder, Node and the USB module, checked); it has never been run on a real Intel Mac or with a recorder, so the recorder hand-over and the mount guard are untried on Intel. Its speech recogniser (for "Listen" lyrics) is built without the GPU and without the fast CPU instructions, so it is slower, and ffmpeg is built without the Intel assembly optimisations. No further development of it is planned. `mac/x64/build_x64_tools.sh` rewrites the build recipes in `mac/` to build the Intel tools under Rosetta.

## Building from source

The recipes for the tools that come with the app are in `mac/`: `build_ffmpeg_full.sh` (ffmpeg with MP3, https and text filters), `build_atracdenc.sh` (the ATRAC3+ encoder, with its small
patch), `build_whisper.sh` and `build_usb_module.sh`. Their licences and sources are listed in `THIRD-PARTY-NOTICES.txt` (section C-Mac). To run from source you need Python 3.9 or newer with
`pywebview`, `pyusb`, `libusb-package`, `numpy`, `pillow` and the `pyobjc` frameworks, plus the Node runtime and tools those scripts produce.

The licence is the same as for the Windows version: see `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt`.
