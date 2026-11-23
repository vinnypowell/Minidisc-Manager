"""Disc labels: the page draws the label (cover, album, artist, track list) on a canvas; this saves the picture as a PNG.
LabelMixin is mixed into himd_app.Api. The label can also be sent to a paired HP Sprocket printer over Bluetooth (sprocket.py)."""
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import webview
import himd_dev
import himd_fs
import sprocket
import hiprint
from mdm_paths import BACKUP_DIR, USER_DIR


class LabelMixin:
    def label_save(self, data_url, name):
        """Ask where to save, then write the PNG the page drew (a data: URL)."""
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        try:
            data = base64.b64decode(m.group(1))
        except Exception:
            return {'error': 'The label picture could not be read.'}
        safe = re.sub(r'[\\/:*?"<>|]+', ' ', name or 'disc label').strip()[:80] or 'disc label'
        kind = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        start = getattr(self, '_last_save_dir', None)
        path = self._window.create_file_dialog(
            kind, directory=start if start and os.path.isdir(start) else os.path.join(os.path.expanduser('~'), 'Pictures'),
            save_filename=safe + ' label.png', file_types=('PNG picture (*.png)',))
        if not path:
            return {'cancelled': True}
        path = path if isinstance(path, str) else path[0]
        if not path.lower().endswith('.png'):
            path += '.png'
        try:
            with open(path, 'wb') as f:
                f.write(data)
        except OSError as exc:
            return {'error': 'The label could not be saved: %s' % exc}
        return {'saved': path}

    def label_save_many(self, items):
        """Ask for a folder, then write one PNG per item ({name, data}: data is a PNG data: URL), e.g. one label per group of a disc."""
        kind = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or webview.FOLDER_DIALOG
        start = getattr(self, '_last_save_dir', None)
        folder = self._window.create_file_dialog(
            kind, directory=start if start and os.path.isdir(start) else os.path.join(os.path.expanduser('~'), 'Pictures'))
        if not folder:
            return {'cancelled': True}
        folder = folder if isinstance(folder, str) else folder[0]
        count = 0
        try:
            for i, item in enumerate(items or [], 1):
                m = re.match(r'data:image/png;base64,(.+)$', (item or {}).get('data') or '', re.S)
                if not m:
                    return {'error': 'A label picture was not in the expected form.'}
                safe = re.sub(r'[\\/:*?"<>|]+', ' ', (item.get('name') or 'group')).strip()[:60] or 'group'
                path = os.path.join(folder, '%02d %s label.png' % (i, safe))
                with open(path, 'wb') as f:
                    f.write(base64.b64decode(m.group(1)))
                count += 1
        except (OSError, ValueError) as exc:
            return {'error': 'The labels could not be saved: %s' % exc}
        return {'saved': folder, 'count': count}

    def label_save_disc(self, index, data_url):
        """WRITES A FILE TO THE DISC. Stores the label the page drew as /LABEL.JPG in the root folder (a Hi-MD disc only), replacing an earlier one."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a label picture.'}
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        folder = tempfile.mkdtemp(prefix='mdm-label-')
        try:
            png, jpg = os.path.join(folder, 'label.png'), os.path.join(folder, 'LABEL.JPG')
            with open(png, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            for q in ('2', '4', '8'):                                  # high quality first, lower only if the file is large
                try:
                    self._ffmpeg(['-i', png, '-frames:v', '1', '-pix_fmt', 'yuvj420p', '-q:v', q, jpg])
                except RuntimeError as exc:
                    return {'error': 'The label could not be prepared: %s' % exc}
                if os.path.getsize(jpg) <= 600000:
                    break
            res = {'error': 'not tried'}
            for attempt in range(3):                                   # a recorder can stay busy for a few seconds after a write
                with self._lock:
                    res = self._run_helper('label_set', {'file': jpg, 'backupDir': os.path.join(BACKUP_DIR, 'label_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})
                if 'error' not in res:
                    break
                time.sleep(2.5)
            if 'error' in res:
                self.log('label_save_disc failed: %s' % res['error'])
            return res
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def label_remove(self, index):
        """WRITES TO THE DISC. Removes /LABEL.JPG."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a label picture.'}
        with self._lock:
            return self._run_helper('label_remove', {'backupDir': os.path.join(BACKUP_DIR, 'label_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})

    # -- printing on an HP Sprocket ---------------------------------------------------------------------
    @staticmethod
    def _sprocket_cache():
        return os.path.join(USER_DIR, 'sprocket.json')

    @staticmethod
    def _paired_bluetooth(name_regex, cache, default_name):
        """(address, name) of a paired Bluetooth device whose name matches: Windows' list of paired devices, remembered once found."""
        ps = ("Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match '" + name_regex + "' -and "
              "$_.InstanceId -match 'BTHENUM\\\\DEV_([0-9A-F]{12})' } | ForEach-Object { $_.FriendlyName + '|' + $matches[1] }")
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, timeout=25,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            found = [ln.strip().split('|') for ln in r.stdout.splitlines() if '|' in ln]
        except Exception:
            found = []
        if found:
            name, raw = found[0]
            mac = ':'.join(raw[i:i + 2] for i in range(0, 12, 2))
            try:
                with open(cache, 'w') as f:
                    json.dump({'mac': mac, 'name': name}, f)
            except OSError:
                pass
            return mac, name
        try:
            with open(cache) as f:
                c = json.load(f)
            return c['mac'], c.get('name', default_name)
        except Exception:
            return None, None

    def _sprocket_mac(self):
        """The Bluetooth address of the paired HP Sprocket."""
        return self._paired_bluetooth('sprocket', self._sprocket_cache(), 'HP Sprocket')

    def label_sprocket_print(self, data_url, landscape=False):
        """Shrinks the label to 640 x 960 and sends it to the paired Sprocket, which prints it. A landscape label is turned a quarter turn first,
        because the printer takes portrait pictures (the sticker is then read with the paper turned sideways)."""
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        mac, name = self._sprocket_mac()
        if not mac:
            return {'error': 'No paired HP Sprocket was found. Pair it first in Windows (Settings > Bluetooth & devices), with the printer switched on.'}
        folder = tempfile.mkdtemp(prefix='mdm-sprocket-')
        try:
            png, jpg = os.path.join(folder, 'label.png'), os.path.join(folder, 'label.jpg')
            with open(png, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            for q in ('3', '6', '10', '16'):                                  # the printer wants a small file: lower the quality until it is
                try:
                    self._ffmpeg(['-i', png, '-frames:v', '1', '-vf', ('transpose=1,' if landscape else '') + 'scale=640:960:flags=lanczos', '-pix_fmt', 'yuvj420p', '-q:v', q, jpg])
                except RuntimeError as exc:
                    return {'error': 'The label could not be prepared: %s' % exc}
                if os.path.getsize(jpg) <= 45000:
                    break
            with open(jpg, 'rb') as f:
                data = f.read()
            self.log('sprocket: sending %d bytes to %s (%s)' % (len(data), name, mac))
            try:
                sprocket.send_jpeg(mac, data)
            except sprocket.SprocketError as exc:
                self.log('sprocket failed: %s (%s)' % (exc, getattr(exc, 'detail', '')))
                return {'error': str(exc)}
            return {'ok': True, 'printer': name, 'bytes': len(data)}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    # -- printing on a Polaroid Hi-Print (groundwork: the print commands are not known yet, see hiprint.py) ---------------
    def _hiprint_mac(self):
        """The Bluetooth address of the paired Polaroid Hi-Print, found like the Sprocket and remembered once found."""
        return self._paired_bluetooth('hi-?print', os.path.join(USER_DIR, 'hiprint.json'), 'Polaroid Hi-Print')

    # The printer cannot report how many sheets are left (it ignores the statistics request), so the program keeps its own count:
    # the user says how many sheets are in the printer, and every successful print here takes one off. Prints made from the phone are not seen.
    @staticmethod
    def _hiprint_film_file():
        return os.path.join(USER_DIR, 'hiprint_film.json')

    def label_hiprint_film_get(self):
        try:
            with open(self._hiprint_film_file()) as f:
                left = json.load(f).get('left')
            return {'left': int(left) if left is not None else None}
        except Exception:
            return {'left': None}

    def label_hiprint_film_set(self, left):
        """The user says how many sheets are in the printer now (None clears the count)."""
        try:
            n = None if left in (None, '') else max(0, min(99, int(left)))
        except (TypeError, ValueError):
            return {'error': 'Please give a whole number of sheets.'}
        try:
            with open(self._hiprint_film_file(), 'w') as f:
                json.dump({'left': n}, f)
        except OSError as exc:
            return {'error': 'The count could not be saved: %s' % exc}
        return {'left': n}

    def label_hiprint_print(self, data_url, landscape=False):
        """Prepares the label for the Hi-Print as a 640 x 1024 JPEG (a landscape label is turned a quarter turn, as for the Sprocket) and prints it
        with hiprint.send_jpeg (Prinics protocol worked out from the Polaroid app; uses one sheet of film)."""
        m = re.match(r'data:image/png;base64,(.+)$', data_url or '', re.S)
        if not m:
            return {'error': 'The label picture was not in the expected form.'}
        mac, name = self._hiprint_mac()
        if not mac:
            return {'error': 'No paired Polaroid Hi-Print was found. Pair it first in Windows (Settings > Bluetooth & devices), with the printer switched on.'}
        w, h = hiprint.IMAGE_SIZE
        folder = tempfile.mkdtemp(prefix='mdm-hiprint-')
        try:
            png, jpg = os.path.join(folder, 'label.png'), os.path.join(folder, 'label.jpg')
            with open(png, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            try:
                self._ffmpeg(['-i', png, '-frames:v', '1', '-vf', ('transpose=1,' if landscape else '') + 'scale=%d:-2:flags=lanczos,pad=%d:%d:0:(oh-ih)/2:white' % (w, w, h),
                              '-pix_fmt', 'yuvj420p', '-q:v', '2', jpg])           # fit the width, white margin top and bottom (the label is 2:3, the paper 5:8)
            except RuntimeError as exc:
                return {'error': 'The label could not be prepared: %s' % exc}
            with open(jpg, 'rb') as f:
                data = f.read()
            self.log('hiprint: prepared %d bytes for %s (%s)' % (len(data), name, mac))
            try:
                res = hiprint.send_jpeg(mac, data, log=self.log)
                self.log('hiprint: done, status %s' % (res.get('status'),))
                left = self.label_hiprint_film_get().get('left')
                if res.get('printed') and left is not None:                      # one sheet used: count down (never below 0)
                    self.label_hiprint_film_set(max(0, left - 1))
            except hiprint.HiPrintError as exc:
                self.log('hiprint: %s (%s)' % (exc, getattr(exc, 'detail', '')))
                return {'error': str(exc)}
            return {'ok': True, 'printer': name, 'bytes': len(data)}
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class JCardMixin:
    """Disc J-cards: the page draws the front cover, rear insert and disc sticker as pictures; this lays them out at their real size on an A4 or
    Letter page (crop and fold marks included) and writes a PDF for an ordinary printer. No extra library: the PDF is written by hand."""
    _PAPER_MM = {'a4': (210.0, 297.0), 'letter': (215.9, 279.4), 'a4l': (297.0, 210.0), 'letterl': (279.4, 215.9)}

    @staticmethod
    def _jcard_pdf(items, paper):
        pw, ph = JCardMixin._PAPER_MM.get(paper, JCardMixin._PAPER_MM['a4'])
        pt = 72.0 / 25.4
        objs = []                                                       # object bodies (bytes); object n is objs[n-1]
        def add(b):
            objs.append(b)
            return len(objs)
        add(b'')                                                        # 1 catalog, 2 pages, 3 page: filled in below
        add(b''); add(b'')
        names, ops = [], []
        for i, it in enumerate(items):
            m = re.match(r'data:image/jpeg;base64,(.+)$', it.get('data') or '', re.S)
            if not m:
                raise ValueError('A picture was not in the expected form.')
            raw = base64.b64decode(m.group(1))
            n = add(b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n'
                    % (int(it['wpx']), int(it['hpx']), len(raw)) + raw + b'\nendstream')
            names.append((i, n))
            x, y, w, h = float(it['x']), float(it['y']), float(it['w']), float(it['h'])
            ops.append('q %.3f 0 0 %.3f %.3f %.3f cm /Im%d Do Q' % (w * pt, h * pt, x * pt, (ph - y - h) * pt, i))
            ln = []                                                     # crop marks at the four corners, fold ticks above and below
            g, L = 1.5, 4.0
            for cx, cy, sx, sy in ((x, y, -1, -1), (x + w, y, 1, -1), (x, y + h, -1, 1), (x + w, y + h, 1, 1)):
                ln.append((cx + sx * g, cy, cx + sx * (g + L), cy)); ln.append((cx, cy + sy * g, cx, cy + sy * (g + L)))
            for f in it.get('folds') or []:
                ln.append((x + float(f), y - g, x + float(f), y - g - L)); ln.append((x + float(f), y + h + g, x + float(f), y + h + g + L))
            ops.append('0.3 w 0.35 G ' + ' '.join('%.3f %.3f m %.3f %.3f l S' % (a * pt, (ph - b) * pt, c * pt, (ph - d) * pt) for a, b, c, d in ln))
        content = '\n'.join(ops).encode('ascii')
        cn = add(b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream')
        xo = ' '.join('/Im%d %d 0 R' % (i, n) for i, n in names)
        objs[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
        objs[1] = b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>'
        objs[2] = ('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /XObject << %s >> >> /Contents %d 0 R >>' % (pw * pt, ph * pt, xo, cn)).encode('ascii')
        out = bytearray(b'%PDF-1.4\n'); offs = []
        for n, b in enumerate(objs, 1):
            offs.append(len(out)); out += b'%d 0 obj\n' % n + b + b'\nendobj\n'
        xr = len(out)
        out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
        for o in offs:
            out += b'%010d 00000 n \n' % o
        out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xr)
        return bytes(out)

    def jcard_save_pdf(self, items, paper, name):
        """Ask where to save, write the PDF, and open it so it can be printed at 100 % (actual size)."""
        try:
            data = self._jcard_pdf(items or [], paper)
        except (ValueError, KeyError, TypeError) as exc:
            return {'error': 'The J-card page could not be made: %s' % exc}
        safe = re.sub(r'[\/:*?"<>|]+', ' ', name or 'J-card').strip()[:80] or 'J-card'
        kind = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        start = getattr(self, '_last_save_dir', None)
        path = self._window.create_file_dialog(
            kind, directory=start if start and os.path.isdir(start) else os.path.join(os.path.expanduser('~'), 'Documents'),
            save_filename=safe + ' J-card.pdf', file_types=('PDF file (*.pdf)',))
        if not path:
            return {'cancelled': True}
        path = path if isinstance(path, str) else path[0]
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        try:
            with open(path, 'wb') as f:
                f.write(data)
        except OSError as exc:
            return {'error': 'The J-card page could not be saved: %s' % exc}
        try:
            if os.name == 'nt':
                os.startfile(path)                                      # opens in the PDF viewer; print from there at 100 %
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
        except Exception:
            pass
        return {'saved': path}

    def jcard_save_disc(self, index, items, paper):
        """WRITES A FILE TO THE DISC. Stores the printable J-card page as /JCARD.PDF in the root folder (a Hi-MD disc only), replacing an earlier one."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a J-card file.'}
        try:
            data = self._jcard_pdf(items or [], paper)
        except (ValueError, KeyError, TypeError) as exc:
            return {'error': 'The J-card page could not be made: %s' % exc}
        folder = tempfile.mkdtemp(prefix='mdm-jcard-')
        try:
            pdf = os.path.join(folder, 'JCARD.PDF')
            with open(pdf, 'wb') as f:
                f.write(data)
            res = {'error': 'not tried'}
            for attempt in range(3):                                   # a recorder can stay busy for a few seconds after a write
                with self._lock:
                    res = self._run_helper('jcard_set', {'file': pdf, 'backupDir': os.path.join(BACKUP_DIR, 'jcard_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})
                if 'error' not in res:
                    break
                time.sleep(2.5)
            if 'error' in res:
                self.log('jcard_save_disc failed: %s' % res['error'])
            return res
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def jcard_remove(self, index):
        """WRITES TO THE DISC. Removes /JCARD.PDF."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a J-card file.'}
        with self._lock:
            return self._run_helper('jcard_remove', {'backupDir': os.path.join(BACKUP_DIR, 'jcard_' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))})

    def jcard_open(self, index):
        """Copies JCARD.PDF off the disc into a temporary folder and opens it (print from there at 100 %)."""
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs can hold a J-card file.'}
        with self._lock:
            try:
                dev = himd_dev.Device(self._devices[int(index)])
                fs = himd_fs.Fat16(dev)
                if not any(not e['dir'] and e['short'].upper() == 'JCARD.PDF' for e in fs.listdir('/')):
                    return {'error': 'There is no J-card on this disc yet.'}
                data = bytes(fs.read_file('/JCARD.PDF'))
            except Exception as exc:
                return {'error': 'The J-card could not be read from the disc: %s' % exc}
            finally:
                self._release_devices()
        return self._jcard_open_bytes(data, 'J-card from disc.pdf')

    def jcard_open_page(self, items, paper):
        """Opens the page in the PDF viewer without asking where to save (used when the built-in print window is not available)."""
        try:
            data = self._jcard_pdf(items or [], paper)
        except (ValueError, KeyError, TypeError) as exc:
            return {'error': 'The J-card page could not be made: %s' % exc}
        return self._jcard_open_bytes(data, 'J-card.pdf')

    @staticmethod
    def _jcard_open_bytes(data, name):
        folder = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-jcard')
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        try:
            with open(path, 'wb') as f:
                f.write(data)
            if os.name == 'nt':
                os.startfile(path)
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
        except OSError as exc:
            return {'error': 'The J-card could not be opened: %s' % exc}
        return {'ok': True, 'path': path}
