# MiniDisc Manager

A program for Windows, and as a beta for Macs with Apple silicon, for managing Hi-MD and standard MiniDisc recorders over USB: see what is on a disc, add, move, split, combine, rename and delete tracks, group them, copy a disc, save tracks to the PC, and play a disc on the PC, a Sonos speaker or a Google TV while the disc is read.

Version 0.36.1 (Windows) · 0.36.1 (beta) (macOS) · Copyright (c) 2026 Vinny Powell · see `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt`

## What it does

- Reads and edits Hi-MD discs (PCM, ATRAC3 LP2/LP4, ATRAC3plus, MP3) and NetMD / standard MiniDisc discs.
- Adds tracks from files, audio CDs, Bandcamp, SoundCloud, internet radio and Yoto cards.
- **0.36.1:** new: **Update now** in the new-version notice (installed Windows copy): the program downloads the new Setup, checks it against the published checksum, closes, installs it and starts again by itself; it will not start while a disc operation is running.
- **0.36.0:** new: new-version notice. Once a day the program asks this project's GitHub release page which version is the newest and shows a small box (Open download page, Later, Skip this version) if yours is older. Nothing about you is sent and nothing is installed by itself; switch it off in Settings, or use Help > Check for updates.
- **0.35.2:** fix: the bass (LFE) meter in the Surround channels display now moves; it is judged against its own loud level instead of the full-range channels.
- **0.35.1:** fix: the program now starts even when the numpy library cannot be loaded on a computer (for example a missing Microsoft Visual C++ runtime); only the Surround channels display, binaural playback and the TV picture styles are switched off then.
- **0.35.0:** new **Disc J-Cards** tab (Recording box): makes the J-card for the slim MiniDisc case (11 mm tab, 5.5 mm spine, 68 mm front, with an optional 66 mm fold-out panel for the track list) and a disc sticker, to print on any printer (Print, a PDF with crop and fold marks, or PNG pictures). On a Hi-MD disc the printable page can be stored as `JCARD.PDF` and opened again from an **Open J-Card** button in Disc Information. The Disc labelling tab is now called **Disc Stickers** (unchanged otherwise). French, German, Dutch and Spanish texts included. Same version number on the Mac (beta). There is no Intel Mac version of 0.35.0: the experimental Intel image stays at 0.34.5 and is no longer updated.
- **0.34.5:** the Windows and Mac versions now share one version number. Windows has no other changes. On the Mac (beta): adding a spatial audio track with the Opus (smaller) setting now works (the error "Unrecognized option 'vbr'" is fixed), and copying a whole disc to the Mac (Disc Package, Clone, cut and join) no longer fails on a disc with more than 5 tracks. The Intel Mac image has both fixes too.
- **0.34.0:** the disc is now named "Album: Artist" when you name it as you add tracks or rip a CD; Rip a CD has Tick all and Untick all buttons; a Hi-MD recorder's name ends with "(Hi-MD disc)"; smaller layout and Clone fixes. **New: a macOS version (beta, Apple silicon)** with the same version number: Hi-MD and standard discs, CD ripping, playing discs (also 5.1 to a Google TV), Convert, recording from Bandcamp and SoundCloud and internet radio, and lyrics, including the "Listen" recogniser. See the macOS section below.
- **0.33.5:** Clearer "How it works" help for Disc Package, Clone, Remove, Disc labelling, Groups and the Recording entries (Rip CD, Yoto, Internet Radio), as short step-by-step lists in all five languages.
- **0.33.4:** Find YouTube videos now searches every track when none is ticked, and its window closes by itself when the search is finished.
- **0.33.3:** the Sony NetMD decks MDS-JB980, MDS-JE780 and MDS-NT1 now show their own details and picture. They share one USB ID, so when the program cannot tell which is connected it asks, and remembers the answer.
- **0.33.2:** many more of the pop-ups, progress lines and messages are translated (French, German, Dutch, Spanish); folded cards, open tabs and the zoom are remembered with the card layout; adding SP tracks to a standard disc shows the expected time and notes that LP2 / LP4 send faster; the Surround channels display reads its spatial file only when it is chosen; the volume slider for a Google TV is smoother.
- **0.33.1:** the visualiser and the Surround channels display now work while playing to a Sonos room, and the card layout (places, sizes, hidden cards) is remembered between runs, with a switch in Settings.
- **Disc packages (0.33.0):** save a whole disc as one `.mdpack` file and let someone else write a copy of it with their own copy of the program: the audio exactly as stored, the names, groups, disc name, picture, sticker label, group pictures, lyrics and YouTube links. **Disc Extras > Disc Package > Export disc package...** asks where to save it first; **Import package...** checks every file and then writes it to a blank disc of the same kind, with a byte-for-byte check on a Hi-MD disc. The write now shows overall progress, a step list and a time estimate. There is also a **Help** menu (user manual and read me) and a Settings switch for the optional firmware patch on MZ-NH700-type recorders. Everything new is translated into French, German, Dutch and Spanish.
- **Surround channels display (0.32.0):** for a track that has a spatial version, three new visualiser styles show the live level of every channel in dB with peak marks: speaker circles laid out like the room, vertical bars, or horizontal bars, with a see-through Sound centre ring that follows where the sound is coming from. It also works while a 5.1 track plays on a Google TV.
- **Split a long file before adding it (0.31.3):** a whole album ripped as one long file (a DVD-Audio or vinyl rip, 5.1 and 7.1 included) can be cut into its tracks on the PC before it is added, from a pasted list of lengths or start times or from the file's own chapter marks, rather than written to the disc as one long track and split afterwards. Each cut is moved to the quietest moment nearby, each surround piece keeps its own spatial version, and the disc is written once.
- Name the disc as you add: the Add window has Artist, Album and Disc name boxes that apply to every added track.
- Splits, combines, moves, fades and renames tracks, with groups, auto split, album look-up and timed lyrics.
- Clones a disc, saves tracks to the PC, burns an audio CD, keeps a track list on the disc.
- Converts a standard (SP / LP) disc to Hi-MD, and rewrites LP2 / LP4 tracks as SP (spreading them over two discs when they do not fit) so that players without LP support can play them.
- Prints disc labels (HP Sprocket and Polaroid Hi-Print over Bluetooth, or as a picture).
- Plays the disc on the PC, a Sonos room or a Google TV, with a choice of level-meter and spectrum displays.
- **Spatial audio:** keeps the surround version of a track on a Hi-MD disc next to its normal stereo track; Clone and Split carry it across (0.31.0); splitting a long track is explained step by step (0.31.2). See below.

## What is in this repository

The source of the program.

| Path | Purpose |
|---|---|
| `himd_app.py` and the other `.py` files | the application, USB access to Hi-MD and NetMD recorders, disc editing, lyrics, album look-up, recording from online sources, playing to Sonos and Google TV |
| `ui/` | the window (one HTML page) and the recorder pictures |
| `helper/` | the Node helper scripts that read and write the disc, an audio helper and a CD-burn script |
| `ps/` | small PowerShell scripts (Bluetooth, sound outputs) |
| `macos/` | the Mac version (beta): the same program adapted for macOS, with its background service and install scripts (see its own README) |
| `installer/` | the build script and Inno Setup file that make the installer and portable zip |
| `LICENSES/`, `LICENSE.txt`, `THIRD-PARTY-NOTICES.txt` | licences |
| `README.txt` | the full user guide |
| `experimental/` | work in progress, not used by the program |

**Not included:** the bundled runtime (Python, Node.js with the MiniDisc libraries, ffmpeg), which is large. The installer and portable zip on the Releases page contain everything and need nothing else installed. To run from source you need Windows, Python 3.12 with the packages in `LICENSES/python`, and the runtime folder from a release (copy its `runtime` folder next to `himd_app.py`).

## Spatial audio (HMSA)

A Hi-MD disc can keep the **surround version of a track** next to its normal stereo track. The recorder plays the stereo track like any other; the surround version is a hidden file on the disc in a small format called **HMSA** (Hi-MD Spatial Audio: ordinary Opus or WavPack audio in a wrapper that keeps every channel). Only this program can read it.

- **Add** a real 5.1, 7.1 or larger surround file (WAV, FLAC, MKA, AC-3 and similar) and tick *Also keep the spatial version on the disc*. Choose Compact (Opus) or Lossless (WavPack).
- **Listen on the PC** in headphone surround, or on a **Google TV with a soundbar** as 5.1 surround (Dolby Digital Plus). In that mode the TV shows a still picture of the track instead of the lyric video, which stays the default.
- **Clone and Split** carry the spatial versions across: Clone copies them to the new disc, and Split cuts them at the same places so each part gets its own. A progress bar shows each spatial file being written and checked.
- **Save spatial version…** writes the surround as FLAC 5.1 / 7.1, Dolby Digital Plus 5.1 or every channel as stored, for any home-cinema player.
- It **never makes surround from stereo**, does not render Dolby Atmos objects, and does not remove copy protection.

Read the full guide, including exactly what was and was not tested: **[SPATIAL-AUDIO.md](SPATIAL-AUDIO.md)** (also `SPATIAL-AUDIO.txt` in the download).

## Download

See the Releases page for the Windows installer, the portable zip, the user manual and and the Mac disk image (`MiniDisc-Manager-0.36.1-beta-mac-arm64.dmg`). The highly experimental Intel Mac disk image stays at 0.34.5 (release `v_0_34_5`) and is no longer updated.

## macOS (beta)

A Mac with Apple silicon (M1 or newer) and macOS 13 or newer. Download the `.dmg` from the Releases page, drag the app to Applications and read **READ ME FIRST** in the disk image. The app is not signed by Apple, so the first time you open it you use System Settings > Privacy & Security > Open Anyway; it then offers to install a small background service (macOS only lets a service talk to a recorder), which asks for your Mac password once. It has been tried on one recorder (a Sony MZ-NH700) and one Mac. Yoto, Save to disc, Bluetooth printing and speakers are not in the Mac version, and Burn Audio CD is experimental: see [`macos/mac/RELEASE-NOTES.txt`](macos/mac/RELEASE-NOTES.txt). The source is in [`macos/`](macos/).

**Intel Macs (highly experimental, no longer updated):** the last separate disk image for Macs with an Intel chip is `MiniDisc-Manager-0.34.5-experimental-mac-x86_64.dmg` on the 0.34.5 release; there is no Intel version of 0.35.0. It was only built and checked by running its programs under Rosetta on an Apple silicon Mac: it has never been run on a real Intel Mac or with a recorder, and no further development of it is planned. Use it at your own risk, and never on a disc you cannot replace. The Apple silicon version above is the supported one.

## Languages and installation help

The program can be used in **English, French (Français), German (Deutsch), Dutch (Nederlands) and Spanish (Español)**: use the Language button with the flag at the top of the window. The translations are drafts, and corrections are welcome (please open an issue).

Installation and USB driver setup, in your language:

- **USB driver guide:** `DRIVER-SETUP.html` comes with the download and opens in your browser in English, French, German, Dutch or Spanish (flag buttons at the top of the page). The program opens it in the language you have chosen.
- **Portable zip, first steps:** [Français](installer/LISEZ-MOI.txt) · [Deutsch](installer/LIES-MICH.txt) · [Nederlands](installer/LEES-MIJ.txt) · [Español](installer/LEEME.txt) · [English](installer/portable-readme.txt). They cover unzipping (and the Windows "Unblock" step), the first start, driver setup, backups and requirements.

The full user guide (`README.txt`) is English only.

## Warning

MiniDisc Manager can write to and erase MiniDiscs. It has been tested on a Sony MZ-NH700 and an MZ-RH1 only. Copy any recordings you cannot replace to your PC before editing a disc. Use it at your own risk. Close any other recorder software first: only one program can use the recorder at a time.

## Licence

The Python program and the window are under the MIT licence; the helper scripts in `helper/` that load the GPL-2.0 libraries are under GPL-2.0. `LICENSE.txt` says which is which, and `THIRD-PARTY-NOTICES.txt` lists the libraries the program uses.

Dolby, Dolby Audio, Dolby Digital Plus and Dolby Atmos are trademarks of Dolby Laboratories. Not affiliated with, authorised or endorsed by Sony, Sonos, Google or Dolby. Product and company names belong to their owners.
