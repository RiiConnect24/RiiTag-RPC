import time
from datetime import datetime, timedelta
from threading import Thread
from typing import TYPE_CHECKING

from prompt_toolkit.application import get_app

from .exceptions import RiitagNotFoundError
from .preferences import Preferences
from .user import User, RiitagInfo

if TYPE_CHECKING:
    from start import RiiTagApplication


class RiitagWatcher(Thread):
    def __init__(self, preferences: Preferences, user: User,
                 update_callback, message_callback, *args, **kwargs):
        super().__init__(*args, **kwargs, daemon=True)

        self.preferences = preferences
        self._user = user
        self._update_callback = update_callback
        self._message_callback = message_callback

        self._run = True
        self._last_check = datetime(year=2000, month=1, day=1)  # force check on first run
        self._no_riitag_warning_shown = False

        self._last_riitag: RiitagInfo = RiitagInfo()

    @property
    def interval(self):
        return self.preferences.check_interval

    @property
    def presence_timeout(self):
        return self.preferences.presence_timeout

    def start(self):
        self._run = True

        super().start()

    def stop(self):
        self._run = False

    def _get_riitag(self):
        try:
            riitag = self._user.fetch_riitag()
        except RiitagNotFoundError:
            if not self._no_riitag_warning_shown:
                app: RiiTagApplication = get_app()
                app.show_message(
                    'RiiTag not found',
                    'We couldn\'t find your RiiTag.\n\nTo create one, please visit https://tag.rc24.xyz/'
                )

            return RiitagInfo()

        return riitag

    def run(self):
        self._last_riitag = self._get_riitag()

        while self._run:
            new_riitag = self._last_riitag

            now = datetime.utcnow()
            if now - self._last_check >= timedelta(seconds=self.interval):
                # time for a new check!
                self._last_check = now

                new_riitag = self._get_riitag()
                if new_riitag is None:
                    # some error while fetching, probably server issue
                    time.sleep(5)
                    continue

            if self._last_riitag:
                last_play_time = self._last_riitag.last_played.time
                if not last_play_time or now - last_play_time >= timedelta(minutes=self.presence_timeout):
                    new_riitag.outdated = True

            if new_riitag != self._last_riitag:
                self._update_callback(new_riitag)

                self._last_riitag = new_riitag

            time.sleep(1)
