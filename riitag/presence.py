import calendar

import pypresence

from .user import RiitagInfo, RiitagTitleResolver

resolver = RiitagTitleResolver()


def format_presence(riitag_info: RiitagInfo):
    last_played = riitag_info.last_played
    if not last_played:
        return {}

    start_timestamp = calendar.timegm(last_played.time.utctimetuple())

    title = resolver.resolve(last_played.console, last_played.game_id)

    return {
        'details': f'Playing {title.name}',
        'state': f'Playing on {title.console_name}',
        'start': start_timestamp,

        'large_image': title.get_cover_url(),
        'large_text': title.name,

        'small_image': 'logo',
        'small_text': 'tag.rc24.xyz',

        'buttons': [
            {'label': 'View RiiTag', 'url': f'https://tag.rc24.xyz/user/{riitag_info.id}'}
        ]
    }


class RPCHandler:
    def __init__(self, client_id, on_error=None):
        self._presence = pypresence.Presence(
            client_id=client_id,
            response_timeout=5,
            connection_timeout=5,
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
        except (ConnectionRefusedError, pypresence.PyPresenceException):
            self._is_connected = False
            return False
        else:
            self._is_connected = True
            return True

    def clear(self):
        self._presence.clear()

    def set_presence(self, **options):
        self._presence.update(**options)
