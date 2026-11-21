"""Where the program's files are, and where it keeps what it writes. Shared by himd_app.py and the modules split out of it."""
import os
import sys
import tempfile

FROZEN = bool(getattr(sys, 'frozen', False))          # True in the installed / portable program (built with PyInstaller)
HERE = os.path.dirname(os.path.abspath(__file__))     # the program's own files: runtime\, helper\, ui\ (only read)

# Files the program writes (index backups, the log): next to the program when it runs from source, under AppData when installed
# (an installed program may sit in a folder it is not allowed to write to).
# Where a user's program data lives on this system: AppData\Local on Windows, ~/Library/Application Support on macOS, ~/.local/share elsewhere.
if sys.platform == 'win32':
    APPDATA = os.path.join(os.environ.get('LOCALAPPDATA') or HERE, 'MiniDiscManager')
elif sys.platform == 'darwin':
    APPDATA = os.path.expanduser('~/Library/Application Support/MiniDiscManager')
else:
    APPDATA = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'MiniDiscManager')
USER_DIR = APPDATA if FROZEN else HERE
BACKUP_DIR = os.path.join(USER_DIR, 'backups')

HELPER = os.path.join(HERE, 'helper', 'himd_helper.js')
NETMD_HELPER = os.path.join(HERE, 'helper', 'netmd_helper.js')     # standard MiniDiscs (NetMD)
# Bundled Node runtime (with himd-js in runtime\node_modules); no other program needs to be installed.
EXE = '.exe' if sys.platform == 'win32' else ''       # program-file suffix: runtime/node.exe on Windows, runtime/node on macOS and Linux
NODE_EXE = os.path.join(HERE, 'runtime', 'node' + EXE)
WHISPER_EXE = None                                    # macOS: the speech recogniser program that comes with the app (set below); Windows downloads its own
FFMPEG_EXE = os.path.join(HERE, 'runtime', 'ffmpeg' + EXE)   # decodes and encodes every audio format
APPAUDIO = os.path.join(HERE, 'helper', 'appaudio.exe')   # records one program's sound (used for the streaming-site windows)
APPAUDIO_SOURCE = os.path.join(HERE, 'helper', 'appaudio_mac.swift')   # macOS: the same job with ScreenCaptureKit; compiled on first use (see bandcamp.ensure_appaudio_mac)

if sys.platform == 'darwin':
    # macOS: a normal program cannot claim the recorder, so the Hi-MD helper is the client of the MiniDisc Manager background service
    # (installed once with mac_install.sh), which also brings the Node runtime and ffmpeg. The app's own copies are used when it has them.
    _SERVICE_DIR = '/Library/Application Support/MiniDiscManager'
    if os.path.exists(os.path.join(_SERVICE_DIR, 'helper', 'mac_client.js')):
        HELPER = os.path.join(_SERVICE_DIR, 'helper', 'mac_client.js')
    if os.path.exists(os.path.join(_SERVICE_DIR, 'helper', 'mac_netmd_client.js')):
        NETMD_HELPER = os.path.join(_SERVICE_DIR, 'helper', 'mac_netmd_client.js')      # standard discs: the same service, asked for NetMD commands
    if not os.path.exists(NODE_EXE) and os.path.exists(os.path.join(_SERVICE_DIR, 'runtime', 'node')):
        NODE_EXE = os.path.join(_SERVICE_DIR, 'runtime', 'node')
    if not os.path.exists(FFMPEG_EXE) and os.path.exists(os.path.join(_SERVICE_DIR, 'runtime', 'ffmpeg')):
        FFMPEG_EXE = os.path.join(_SERVICE_DIR, 'runtime', 'ffmpeg')
    # The speech recogniser program (whisper.cpp built for the Mac) comes with the app: next to the other tools, in the app's Resources folder, or in the service's runtime.
    for _w in (os.path.join(HERE, 'runtime', 'whisper-cli'), os.path.join(os.path.dirname(HERE), 'Resources', 'runtime', 'whisper-cli'),
               os.path.join(_SERVICE_DIR, 'runtime', 'whisper-cli')):
        if os.path.isfile(_w):
            WHISPER_EXE = _w
            break


def open_path(path):
    """Opens a file or folder with whatever the system uses for it (Explorer / Finder / the desktop's default)."""
    import subprocess
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


# Big working copies are kept out of OneDrive on purpose, always under AppData (also when run from source).
_APPDATA = APPDATA
COPIES_DIR = os.path.join(_APPDATA, 'copies')    # FLAC copies of the tracks this app adds to standard discs, so they can be played here
CLONE_DIR = os.path.join(_APPDATA, 'clone')      # the PC copy of a disc being cloned (it can be a gigabyte); stays until the clone is written and checked
CONVERT_DIR = os.path.join(_APPDATA, 'convert')  # the PC copy of a standard disc being converted to Hi-MD; stays until it is written back and checked
LPSP_DIR = os.path.join(_APPDATA, 'lpsp')      # the PC copy of LP tracks being rewritten as SP; stays while tracks wait for a second disc
SPATIAL_DIR = os.path.join(_APPDATA, 'spatial')  # spatial (multichannel) files made for tracks being added, until they are written to the disc
SPLIT_DIR = os.path.join(_APPDATA, 'split')     # new tracks saved by a split that did not fit, until they are written
ASR_DIR = os.path.join(_APPDATA, 'whisper')      # the optional speech recogniser (whisper.cpp + one model, ~200 MB) that writes timed lyrics from a track's audio
RESCUE_DIR =os.path.join(_APPDATA, 'rescue')    # the cut parts of a standard-disc split whose original was deleted first and whose writing then failed (kept, never swept)

RECORDER_PHOTOS = os.path.join(USER_DIR, 'recorder_photos')   # pictures of recorders kept on this PC only, e.g. MZ-NH700.jpg (not part of the installer)
REC_DIR = os.path.join(USER_DIR, 'recordings')                # tracks recorded from the streaming-site windows: KEPT until removed
WEBVIEW_DIR = os.path.join(USER_DIR, 'webview')               # the web views' cookies: keeps the site logins between runs
BC_DIR = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-bandcamp')   # scratch (cover picture), deleted on exit
PLAY_DIR = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-play')     # tracks being played, deleted on exit


def h264_args(fps, gop, kbps=1200):
    """The ffmpeg video-encoder options for H.264 that a Google TV accepts (no B-frames, regular keyframes). Windows uses the bundled libopenh264; the Mac uses
    Apple's own VideoToolbox encoder (the Mac ffmpeg is built without libopenh264)."""
    if sys.platform == 'darwin':
        return ['-c:v', 'h264_videotoolbox', '-profile:v', 'main', '-r', str(fps), '-b:v', '%dk' % kbps, '-g', str(gop), '-bf', '0']
    return ['-c:v', 'libopenh264', '-r', str(fps), '-b:v', '%dk' % kbps, '-g', str(gop), '-bf', '0', '-allow_skip_frames', '0']


def ui_font(size, bold=False):
    """A scalable font for the pictures the program draws itself (the TV splash picture, the TV visualizer). Windows: Segoe UI. Mac: Tahoma / Arial, which
    every Mac has (the Windows font files are not there, and the library's built-in fallback is a tiny fixed-size font)."""
    from PIL import ImageFont
    if sys.platform == 'darwin':
        names = ['/System/Library/Fonts/Supplemental/Tahoma Bold.ttf' if bold else '/System/Library/Fonts/Supplemental/Tahoma.ttf',
                 '/System/Library/Fonts/Supplemental/Arial Bold.ttf' if bold else '/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/System/Library/Fonts/Helvetica.ttc']
    else:
        names = ['C:/Windows/Fonts/%s.ttf' % ('segoeuib' if bold else 'segoeui')]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)                     # a recent Pillow can scale its built-in font
    except TypeError:
        return ImageFont.load_default()
