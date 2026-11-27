# MiniDisc Manager

A software utility for Windows, and as a beta for Macs with Apple silicon, to manage Hi-MD and standard MiniDisc recorders over USB: see what is on a disc, add, move, split, combine, rename and delete tracks, group them, copy a disc, save tracks to the PC or to a Walkman, and play a disc on the PC, a Sonos speaker or a Google TV while the disc is read.

Version 0.43.0 (Windows) · 0.43.0 (beta) (macOS) · Copyright (c) 2026 Vinny Powell · see `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt`

## What it does

- Reads and edits Hi-MD discs (PCM, ATRAC3 LP2/LP4, ATRAC3plus, MP3) and NetMD / standard MiniDisc discs.
- Adds tracks from files, audio CDs, Bandcamp, SoundCloud, internet radio, podcasts, audiobooks, Yoto cards and a Sony Walkman (or another audio player that shows up as a drive), and copies a disc to such a player.
- **0.43.0:** new: **gapless albums on a Google TV**: while 5.1 surround plays, the tracks that follow are joined into one continuous stream, so the sound runs from one track into the next with no pause (before, the TV stopped for several seconds between tracks). The TV starts after the first track and the other tracks are read from the disc and added while it plays; the tracks stay separate in the list and each shows its own lyrics. Two new Settings: "Play an album straight through on a Google TV, with no pause between tracks" and "Start the album on a Google TV after the first track". New: **Sonos rooms are told which track comes next**, so they move on by themselves the moment a track ends. The Pop Out **lyrics timing** control now goes to ±5 seconds (it stopped at 1.5; Shift-click moves in steps of 0.25 s), because the best setting for a Google TV can be well over a second. French, German, Dutch and Spanish texts are included.
- **0.42.0:** new: a smaller sticker size in **Disc Stickers**, "J-card disc sticker (7:12, 35 × 60 mm)", the same shape as the Disc J-Cards sticker (now 35 mm wide by default); it can be sent to the HP Sprocket and the Polaroid Hi-Print, centred at its true size on the 2 × 3 inch paper, with a tick box for a thin cut line around the 35 × 60 mm area. New: a disc with HMSA spatial audio tracks (for example HMSA Opus 5.1) can show an **HMSA badge** on its stickers and J-cards. With the track list switched off, the album name and artist are set larger to fill the sticker. French, German, Dutch and Spanish texts are included.
- **0.41.2:** new: **lyrics on a Google TV during 5.1 surround**: a spatial track that plays as 5.1 surround on a TV now shows its cover, title, artist, album and the timed lyrics (the line being sung lit) on the TV, with the same 5.1 sound, instead of a still picture (a track without timed lyrics keeps the still picture). Switch it in Settings or with the Lyrics button in the player bar. New: **Font on the TV lyric screens** (Settings), nine typefaces for the stereo lyric video and the 5.1 screen. The Pop Out window now has a TV lyrics tick box, a TV font list and a Lyrics timing control. Fix: a long track title no longer runs over the album line on the TV. French, German, Dutch and Spanish texts are included.
- **0.41.1:** fix: when an album plays on from one track to the next, the lyrics of the new track no longer jump ahead to the last lines while the track is still being read from the disc.
- **0.41.0:** fix: the lyrics in the Pop Out window now keep time with the music even when the main window is behind it or minimised. The player bar at the bottom no longer clips its right-hand buttons (Play on, Repeat, EQ, Surround, room, volume) in a narrow window: they drop to a second row.
- **0.40.0:** new: **Pop Out Playing Disc Information**: once a track is playing, a button at the top opens the Visualiser, the Track time display, the cover, the play / previous / next buttons, the seek bar, a volume slider and the lyrics in a window of their own (on another screen if you like), and the main window takes the space back. Fix: Disc Stickers and Disc J-Cards now use the album picture kept on the PC for a standard disc. French, German, Dutch and Spanish texts are included.
- **0.39.0:** new: **Add tracks from Walkman (Audio Player)** and **Save tracks to Walkman (Audio Player)**: for a Sony Walkman, or another audio player that shows up as a drive when plugged in (or any folder you choose). Add its music to the disc through the usual Add to disc window, or copy the whole disc or just the ticked tracks to the player as FLAC, MP3 or WAV in a new Artist / Album folder. The heading says whether the whole disc or only some tracks are copied, every track has a tick box, and the artist and album folder names are worked out from the tracks and the disc title and can be changed. Existing files on the player are never changed. French, German, Dutch and Spanish texts are included. Tried with a Sony NW-A30 on Windows; the Mac version (beta) is new there and has not yet been tried with a real player.
- **0.38.0:** new: **Add tracks from Podcasts** and **Add tracks from Audiobooks** (free public-domain books from LibriVox, found through the Internet Archive): browse by genre or subject, or search by name, subject or episode title; episodes show their length; no album art lookup for them. Add to disc shows an encoding time estimate for the ATRAC3+ formats and a warning for files over 30 minutes on a standard disc. The Visualiser card is hidden unless a track is playing. Fix: some Spanish texts appeared in the French language.
- **0.37.0:** new: **ATRAC3+ 48 kbps** recording option for Hi-MD discs, mainly for podcasts and audio books (speech): about 0.36 MB a minute, roughly 45 hours on an empty 1 GB disc. Unlike the other formats it is encoded by the free online ATRAC encoder at atrac.minidisc.wiki, so the audio of those tracks is sent over the internet to that service (nothing else is; every other option stays on your PC); long tracks are sent in ten-minute pieces, and if the service cannot be reached the program says so and suggests Hi-LP 64 kbps. Music at 48 kbps sounds thin. Also fixed: a saved card height can no longer leave a large empty gap above the Tracks list.
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

See the Releases page for the Windows installer, the portable zip, the user manual and and the Mac disk image (`MiniDisc-Manager-0.37.0-beta-mac-arm64.dmg`). The highly experimental Intel Mac disk image stays at 0.34.5 (release `v_0_34_5`) and is no longer updated.

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
