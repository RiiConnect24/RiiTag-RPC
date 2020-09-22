import json
import os


class Preferences:
    DEFAULTS = {
        'check_interval': 10,
        'presence_timeout': 30
    }

    def __init__(self, **values):
        self._values = values

    @classmethod
    def load(cls, fn):
        if not os.path.isfile(fn):  # create new
            preferences = cls(**cls.DEFAULTS)
            preferences.save(fn)

            return preferences

        with open(fn) as file:
            data: dict = json.load(file)

            return cls(**data)

    def save(self, fn):
        with open(fn, 'w+') as file:
            json.dump(self._values, file, indent=4)

    def get(self, value):
        return self._values.get(value, self.DEFAULTS.get(value))

    @property
    def check_interval(self):
        return self.get('check_interval')

    @check_interval.setter
    def check_interval(self, value):
        self._values['check_interval'] = value

    @property
    def presence_timeout(self):
        return self.get('presence_timeout')

    @presence_timeout.setter
    def presence_timeout(self, value):
        self._values['presence_timeout'] = value
