"""The app's own on/off settings (the Settings button in the top bar). AppSettingsMixin is mixed into himd_app.Api.

Kept in app-settings.json in USER_DIR (it is part of a backup). To add a setting: put its key and default in DEFAULTS, read it in Python with
self._app_setting('key') and in the page from the object get_app_settings() returns, then add a row for it in openSettings() in ui\\index.html."""
import json
import os

from mdm_paths import USER_DIR

SETTINGS_FILE = os.path.join(USER_DIR, 'app-settings.json')
DEFAULTS = {
    'autoLookupCommercial': True,        # a pre-recorded (commercial) standard disc is looked up online by itself when it is inserted
    'askConvert': True,                  # a standard disc with audio in a Hi-MD-capable recorder shows the "can be converted to Hi-MD" note under the Recorder card
    'askLpToSp': True,                   # a standard disc with LP2 / LP4 tracks shows the "convert to SP" note under the Recorder card
    'autoAlign': False,                  # after lyrics are found, fine-tune their timing by listening to each track (slow; OFF unless switched on)
    'fillArtist': True,                  # a track whose lyrics were found and matched, and that has no artist, takes the artist the lyrics record names
    'spatialBinaural': True,             # a track with a spatial version on the disc plays that version here, rendered for headphones; off: the stereo track plays
    'spatialTvSurround': False,          # a spatial track played on a Google TV goes there as Dolby Digital Plus 5.1 SOUND (a soundbar then plays real surround, but that TV shows no picture); off: the stereo lyric video
    'spatialTvLyrics': True,             # with 5.1 surround on a Google TV, a track that has timed lyrics shows the lyric screen (the sound is the same 5.1); off: the still picture
    'spatialTvGapless': True,            # with 5.1 on a Google TV, the tracks that follow in the album are joined into one video so there is no pause between tracks (the first start waits while the whole album is read from the disc); off: each track is sent on its own
    'sonosQueue': True,                  # a Sonos room is told which track comes next, so it carries on by itself with no pause between tracks; off: each track is started when the last one ends
    'spatialTvHls': True,                # EXPERIMENT: the album goes to a Google TV as a growing HLS stream, so it starts after the first track while the rest is read and added; if the TV refuses it the finished-file album is used
    'tvFont':'Arial',             # the typeface of the lyric screens on a Google TV (one of lyricvideo.TV_FONTS); the only setting that is a name, not on / off
    'allowPatch': True,                # a Hi-MD recorder in standard-disc mode (MZ-NH700...) may be given the temporary firmware patch that lets it send a track back (playback, save, identify, clone...); off: never, it is played by remote control
    'rememberLayout': True,              # the card places, sizes and hidden cards are kept between runs; off: the app always opens in the stock layout
    'checkUpdates': True,                # once a day (and on Help > Check for updates) the program asks the project's GitHub page whether a newer version exists and shows a notice
    'suggestPopout': True,               # while a track plays the Pop out button pulses and a note offers the pop-out window (stops once it has been used)
    'askMissing': True,                  # a disc with details missing (artist, album, picture, lyrics) shows the "missing some details" prompt
}


def _choices(key):
    """The allowed values of a setting that is a name (not on / off)."""
    if key == 'tvFont':
        import lyricvideo
        return lyricvideo.TV_FONTS
    return ()


class AppSettingsMixin:
    def _app_settings_read(self):
        out = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in DEFAULTS:
                    if isinstance(DEFAULTS[k], str):
                        if saved.get(k) in _choices(k):
                            out[k] = saved[k]
                    elif isinstance(saved.get(k), bool):
                        out[k] = saved[k]
        except (OSError, ValueError):
            pass
        return out

    def _app_setting(self, key):
        return self._app_settings_read().get(key, DEFAULTS.get(key))

    def get_app_settings(self):
        return self._app_settings_read()

    def set_app_setting(self, key, value):
        if key not in DEFAULTS:
            return {'error': 'Unknown setting.'}
        cur = self._app_settings_read()
        if isinstance(DEFAULTS[key], str):
            if value not in _choices(key):
                return {'error': 'That is not one of the choices.'}
            cur[key] = value
        else:
            cur[key] = bool(value)
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            tmp = SETTINGS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cur, f, indent=1)
            os.replace(tmp, SETTINGS_FILE)
        except OSError as e:
            return {'error': 'The setting could not be saved: %s' % e}
        return cur
