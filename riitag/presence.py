import calendar

import pypresence

from os import path
from requests import get

from .user import RiitagInfo, RiitagTitle


def format_presence(riitag_info: RiitagInfo):
    last_played = riitag_info.last_played
    start_timestamp = None
    if last_played:
        start_timestamp = calendar.timegm(last_played.time.utctimetuple())

    return {
        'details': f'Playing {RiitagTitle(last_played.game_id)} ({last_played.console.title()})',
        'state': f'https://gametdb.com/{last_played.console.title()}/{last_played.game_id}',
        'start': start_timestamp,

        'large_image': 'console_wii',
        'large_text': 'Playing on Wii',

        'small_image': 'logo',
        'small_text': 'tag.rc24.xyz',

        'party_id': 'joinmypartyplsss',
        'join': 'hahajoinsecretgobrrrr',
        'match': 'vroomvroom'
    }


class RPCHandler:
    def __init__(self, client_id, on_error=None):
        self._presence = pypresence.Presence(
            client_id=client_id,
            handler=None
        )

        self._on_error = on_error

        self._is_connected = False
        self._error_count = 0

    @property
    def is_connected(self):
        return self._is_connected

    def _error_handler(self, exception, future):
        self._error_count += 1
        if self._error_count >= 3:
            if self._on_error:
                self._on_error(exception, future)

    def connect(self):
        try:
            self._presence.connect()
        except ConnectionRefusedError:
            self._is_connected = False
            return False
        else:
            self._is_connected = True
            return True

    def clear(self):
        self._presence.clear()

    def set_presence(self, **options):
        self._presence.update(**options)
