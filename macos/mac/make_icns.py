"""Makes the PNG files of a macOS .iconset from a Windows .ico (run by build_app.sh on the Mac; iconutil turns the folder into an .icns).
Usage: python make_icns.py <icon.ico> <output .iconset folder>"""
import sys
from PIL import Image

im = Image.open(sys.argv[1])
try:
    im.size = max(im.ico.sizes())          # the largest picture inside the .ico
except Exception:
    pass
im = im.convert('RGBA')
for s in (16, 32, 128, 256, 512):
    im.resize((s, s), Image.LANCZOS).save('%s/icon_%dx%d.png' % (sys.argv[2], s, s))
    im.resize((s * 2, s * 2), Image.LANCZOS).save('%s/icon_%dx%d@2x.png' % (sys.argv[2], s, s))
