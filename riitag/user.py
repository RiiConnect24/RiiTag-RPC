import datetime

import requests

from .exceptions import RiitagNotFoundError

RIITAG_ENDPOINT = 'http://tag.rc24.xyz/{}/json'
HEADERS = {'User-Agent': 'RiiTag-RPC WatchThread v2'}


class RiitagGame:
    def __init__(self, **kwargs):
        self.game_id = kwargs.get('game_id')
        self.console = kwargs.get('console')
        self.region = kwargs.get('region')
        self.cover_url = kwargs.get('cover_url')

        self.time = kwargs.get('time')
        if self.time:
            self.time = datetime.datetime.utcfromtimestamp(self.time)

    def __bool__(self):
        return bool(self.game_id)


class RiitagInfo:
    def __init__(self, **kwargs):
        self.name = kwargs.get('user', {}).get('name')
        self.id = kwargs.get('user', {}).get('id')
        self.games = kwargs.get('game_data', {}).get('games', [])

        last_played = kwargs.get('game_data', {}).get('last_played') or {}
        self.last_played = RiitagGame(**last_played)

        self.outdated = False

    def __bool__(self):
        return bool(self.name or self.id or self.games)

    def __eq__(self, other):
        if not isinstance(other, RiitagInfo):
            return False

        return self.last_played == other.last_played and self.outdated == other.outdated


class RiitagTitleResolver:
    WII_TITLES_URL = 'https://www.gametdb.com/wiitdb.txt?LANG=EN'
    WIIU_TITLES_URL = 'https://www.gametdb.com/wiiutdb.txt?LANG=EN'

    UPDATE_EVERY = datetime.timedelta(days=1)

    def __init__(self):
        self.game_ids: dict[(str, str), str] = {}
        self._last_update = datetime.datetime(year=0, month=0, day=0)

    def update_maybe(self):
        now = datetime.datetime.now()
        if (now - self._last_update) >= self.UPDATE_EVERY:
            self.update()
            return True
        return False

    def update(self):
        wii_db = self._get_data(self.WII_TITLES_URL)
        for game_id, name in wii_db.items():
            self.game_ids[('wii', game_id)] = name

        wiiu_db = self._get_data(self.WIIU_TITLES_URL)
        for game_id, name in wiiu_db.items():
            self.game_ids[('wiiu', game_id)] = name

        self._last_update = datetime.datetime.now()

    def get_game_name(self, console: str, game_id: str):
        return self.game_ids.get((console.lower(), game_id.upper()), 'Unknown')

    def resolve(self, console: str, game_id: str):
        self.update_maybe()

        return RiitagTitle(self, console, game_id)

    def _get_data(self, url: str):
        try:
            r = requests.get(url, headers=HEADERS)
            r.raise_for_status()

            return self._parse_db(r.text)
        except requests.RequestException:
            return {}

    def _parse_db(self, db: str):
        res = {}
        for line in db.splitlines():
            game_id, title = line.split(' = ')
            if game_id == 'TITLES':
                continue

            res[game_id] = title
        return res


class RiitagTitle:
    COVER_URL = 'https://discord.dolphin-emu.org/cover-art/US/{game_id}.png'

    def __init__(self, resolver: RiitagTitleResolver, console: str, game_id: str):
        self._resolver = resolver

        self.game_id = game_id
        self.console = console

    @property
    def name(self):
        return self._resolver.get_game_name(self.console, self.game_id)

    @property
    def cover_url(self):
        return self.COVER_URL.format(game_id=self.game_id)


class User:
    def __init__(self, **kwargs):
        """Represents a RiiTag / Discord user."""
        self.id = kwargs.get('id')
        self.username = kwargs.get('username')
        self.discriminator = kwargs.get('discriminator')
        self.avatar = kwargs.get('avatar')
        self.locale = kwargs.get('locale')

        self.riitag = None

    def fetch_riitag(self):
        url = RIITAG_ENDPOINT.format(self.id)
        r = requests.get(url, headers=HEADERS)

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            self.riitag = None

            return

        data = r.json()
        error = data.get('error')
        if error:
            raise RiitagNotFoundError(error)

        riitag = RiitagInfo(**data)
        self.riitag = riitag

        return riitag
