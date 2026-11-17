# MiniDisc Manager

A Windows program for managing Hi-MD and standard MiniDisc recorders over USB: see what is on a disc, add, move, split, combine, rename and delete tracks, group them, copy a disc, save tracks to the PC, and play a disc on the PC, a Sonos speaker or a Google TV while the disc is read.

Version 0.31.3 · Copyright (c) 2026 Vinny Powell · see `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt`

## What it does

- Reads and edits Hi-MD discs (PCM, ATRAC3 LP2/LP4, ATRAC3plus, MP3) and NetMD / standard MiniDisc discs.
- Adds tracks from files, audio CDs, Bandcamp, SoundCloud, internet radio and Yoto cards.
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

See the Releases page for the Windows installer, the portable zip and the user manual.

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
