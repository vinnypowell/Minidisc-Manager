"""The pop-out window: the Visualiser and the track that is playing in a window of their own. PopoutMixin is mixed into himd_app.Api (the page calls
these methods on it).

The window is a second page (ui/popout.html) served by the same local web server as the main page, so both have the same address and can talk to each
other through the browser (a BroadcastChannel): the main window draws the Visualiser as always and sends each picture, the title and the time across, and
the pop-out sends back what was pressed. Python only opens and closes the window."""
import urllib.parse

import webview


class PopoutMixin:
    def popout_open(self, title='MiniDisc Manager', width=760, height=560):
        """Opens the pop-out window (or brings the open one forward)."""
        try:
            win = getattr(self, '_pop_win', None)
            if win is not None:
                try:
                    win.show()
                    return {'ok': True}
                except Exception:
                    self._pop_win = None
            base = str(getattr(self._window, 'real_url', '') or getattr(self._window, 'original_url', '') or '')
            if not base.startswith('http'):
                return {'error': 'The pop-out window needs the program\'s own page address, which is not available here.'}
            url = urllib.parse.urljoin(base, 'popout.html')
            w = max(420, min(int(width or 760), 4000))
            h = max(320, min(int(height or 560), 3000))
            win = webview.create_window(str(title or 'MiniDisc Manager')[:80], url, width=w, height=h, min_size=(420, 320), background_color='#0f1115')

            def closed(*_a):
                self._pop_win = None
                try:
                    self._window.evaluate_js('window.popoutClosed && window.popoutClosed()')      # the Visualiser goes back into the main window
                except Exception:
                    pass
            win.events.closed += closed
            self._pop_win = win
            return {'ok': True}
        except Exception as exc:
            self.log('popout_open failed: %r' % (exc,))
            return {'error': 'The pop-out window could not be opened: %s' % exc}

    def popout_close(self):
        win = getattr(self, '_pop_win', None)
        self._pop_win = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        return {'ok': True}
