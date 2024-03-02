from __future__ import annotations

import abc
import asyncio
import json
import os
import sys
import threading
import time
import webbrowser
from enum import Enum
from typing import TYPE_CHECKING

import requests
from prompt_toolkit.application import get_app
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Box, Label, Frame
from sentry_sdk import configure_scope

from riitag import oauth2, user, watcher, presence
from riitag.util import get_cache


# Get resource when frozen with PyInstaller
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


if TYPE_CHECKING:
    from start import RiiTagApplication

with open(resource_path('banner.txt'), 'r+') as banner:
    BANNER = banner.read()


class SettingsModifyMode(Enum):
    INCREASE = 1
    DECREASE = 0


class PreferenceButton(Button):
    def __init__(self, value, increments, limits: tuple):
        self.value = value
        self.increments = increments
        self.limits = limits

        super().__init__(str(self.value))

    def update(self):
        self.text = str(self.value)

    @property
    def is_focused(self):
        return get_app().layout.current_window == self.window

    def increase(self):
        new_value = self.value + self.increments
        if new_value > self.limits[1]:
            return

        self.value = new_value
        self.update()

    def decrease(self):
        new_value = self.value - self.increments
        if new_value < self.limits[0]:
            return

        self.value = new_value
        self.update()


class Menu(metaclass=abc.ABCMeta):
    name = 'Generic Menu'
    is_framed = True

    def __init__(self, application: RiiTagApplication = None):
        self.app = application

        self._run = True
        self._tasks = []
        self._task_thread = threading.Thread(
            target=self._task_manager,
            daemon=True
        )

    def _task_manager(self):
        while self._run:
            to_delete = []

            curr_time = int(time.time())
            for task in self._tasks:
                if curr_time >= task[0]:
                    task[1]()
                    to_delete.append(task)

            if to_delete:
                self.update()

            for task in to_delete:
                self._tasks.remove(task)

            time.sleep(0.5)

    def update(self):
        self.app.invalidate()

    def exec_after(self, seconds, callback):
        exec_at = int(time.time()) + seconds
        self._tasks.append((exec_at, callback))

    def on_start(self):
        self._task_thread.start()

    def on_exit(self):
        self._run = False

        # self._task_thread will just die off eventually... no reason to join()
        self._task_thread = None

    def quit_app(self):
        self.on_exit()

        if self.app.riitag_watcher:
            self.app.riitag_watcher.stop()
            self.app.riitag_watcher.join(timeout=5)

        self.app.exit()

    @abc.abstractmethod
    def get_layout(self):
        ...

    @abc.abstractmethod
    def get_kb(self):
        ...

    def get_all_kb(self):
        kb = KeyBindings()

        @kb.add('c-c')
        def exit_app(_):
            self.quit_app()

        @kb.add('q')
        def exit_app(_):
            self.quit_app()

        extra_kb = self.get_kb() or KeyBindings()
        return merge_key_bindings([kb, extra_kb])


# noinspection PyMethodMayBeStatic
class SplashScreen(Menu):
    name = 'Splash Screen'
    is_framed = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._connect_attempt = 0
        self._is_connecting = False

        self.status_str = 'Loading...'

    def get_layout(self):
        return HSplit([
            Window(FormattedTextControl(BANNER), align=WindowAlign.CENTER),
            Window(FormattedTextControl(
                f'{self.app.version_string}\nCreated by DismissedGuy\n\n\n{self.status_str}'),
                align=WindowAlign.CENTER
            )
        ])

    def on_start(self):
        super().on_start()

        self.exec_after(5, self._new_connect)

    def get_kb(self):
        kb = KeyBindings()

        # time traveller!?!?
        @kb.add('enter')
        def skip_loading(_):
            self._new_connect()

        return kb

    @property
    def is_token_cached(self):
        return os.path.isfile(get_cache('token.json'))

    def _refresh_token(self, token):
        try:
            token.refresh()
            token.save(get_cache('token.json'))

            self.app.token = token
            self.app.user = token.get_user()
        except requests.HTTPError:  # token revoked, modified?
            self.app.set_menu(SetupMenu)

            return

        self.app.set_menu(MainMenu)

    def _new_connect(self):
        if self._is_connecting:
            return

        self._is_connecting = True
        self._connect_presence()

    def _connect_presence(self):
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)

        self._connect_attempt += 1

        self.app.rpc_handler.connect()

        if not self.app.rpc_handler.is_connected:
            self.status_str = f'Trying to connect... ({self._connect_attempt})\n' \
                              f'Please make sure your Discord client is running.'
            self.update()

            time.sleep(4)
            self._connect_presence()
        else:
            self._login()

    def _login(self):
        if self.is_token_cached:
            with open(get_cache('token.json'), 'r') as file:
                token_data = json.load(file)
            try:
                token = oauth2.OAuth2Token(self.app.oauth_client, **token_data)
                if token.needs_refresh:
                    self.status_str = 'Refreshing Discord connection...'
                    self.update()

                    self.exec_after(0.5, lambda: self._refresh_token(token))

                else:
                    self.app.token = token
                    try:
                        self.app.user = token.get_user()
                    except requests.HTTPError:  # generic error
                        self.app.set_menu(SetupMenu)

                        return

                    self.app.set_menu(MainMenu)
            except KeyError:  # invalid token in cache?
                self.app.set_menu(SetupMenu)
        else:
            self.app.set_menu(SetupMenu)


# noinspection PyMethodMayBeStatic
class SetupMenu(Menu):
    name = 'Setup'
    is_framed = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.state = 'setup_start'

        if not os.path.isfile(get_cache('token.json')):  # new user
            self.setup_start_layout = Window(FormattedTextControl(HTML(
                '\n\n\n<b>Hello!</b> It looks like this is your first time using this program.\n'
                'No worries! Let\'s get your Discord account linked up first.\n\n\n'
                'You can exit this program at any time by pressing "q" or "Ctrl-c".\n\n\n'
                '<b>Press enter to show the login prompt.</b>',
            )), align=WindowAlign.CENTER, wrap_lines=True)
        else:  # existing user
            self.setup_start_layout = Window(FormattedTextControl(HTML(
                '\n\n\n<b>We couldn\'t log you in.</b>\n\n'
                'This might have happened because the login token changed,\n'
                'or you revoked access for this application through Discord.\n'
                'Fear not! Let\'s try to get that fixed.\n\n\n'
                '<b>Press enter to log in again.</b>',
            )), align=WindowAlign.CENTER, wrap_lines=True)

        self.waiting_layout = HSplit([
            Window(FormattedTextControl(HTML(
                '\n\n\nWe\'ll try to automagically open up your browser. Fingers crossed...'
            )), align=WindowAlign.CENTER, wrap_lines=True)
        ])

    def get_layout(self):
        if self.state == 'setup_start':
            return self.setup_start_layout
        elif self.state == 'waiting':
            return self.waiting_layout
        else:
            return Window()

    def get_kb(self):
        kb = KeyBindings()

        @kb.add('enter')
        def switch_state(_):
            if self.state == 'setup_start':
                self.state = 'waiting'
                self.update()

                self.exec_after(2, self._get_token)

        return kb

    def _get_token(self):
        auth_url = self.app.oauth_client.auth_url
        try:
            webbrowser.open(auth_url)
            self.waiting_layout.children.append(
                Window(FormattedTextControl(HTML(
                    'Looks like that worked. Sweet!\n'
                    'Please follow the instructions in your browser.'
                )), align=WindowAlign.CENTER, wrap_lines=True)
            )
        except webbrowser.Error:
            self.waiting_layout.children.append(
                Window(FormattedTextControl(HTML(
                    'Yikes, that didn\'t work. Please manually paste this URL into your browser:\n' + auth_url
                )), align=WindowAlign.CENTER, wrap_lines=False)
            )

        self.update()
        code = self.app.oauth_client.wait_for_code()

        self.waiting_layout.children = [
            Window(FormattedTextControl(HTML(
                '\n\n\n\n\nFinishing the last bits...'
            )), align=WindowAlign.CENTER, wrap_lines=False)
        ]
        self.update()

        token = self.app.oauth_client.get_token(code)
        token.save(get_cache('token.json'))
        self.app.token = token

        self.app.user = token.get_user()

        time.sleep(2)
        self.waiting_layout.children = [
            Window(
                FormattedTextControl(
                    HTML(
                        '\n\n\n\n\n<b>Done!</b>\n\n'
                        'Signed in as <b>{}#{}</b>.\n\n'
                    ).format(self.app.user.username, self.app.user.discriminator)
                ),
                align=WindowAlign.CENTER, wrap_lines=False
            )
        ]
        self.update()

        time.sleep(2)
        self.app.set_menu(MainMenu)


# noinspection PyMethodMayBeStatic
class MainMenu(Menu):
    name = 'Main Menu'
    is_framed = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.riitag_info = user.RiitagInfo()  # placeholder

        if discord_user := self.app.user:
            with configure_scope() as scope:
                scope.set_tag('discord.user', f'{discord_user.username}#{discord_user.discriminator}')
                scope.set_tag('discord.id', discord_user.id)

        self.menu_settings_button = Button('Settings', handler=lambda: self._set_state('Settings'))
        self.menu_view_button = Button('View Tag', handler=self.view_riitag)
        self.menu_exit_button = Button('Exit', handler=self.quit_app)
        self.menu_logout_button = Button('Logout', handler=self._logout)

        self.settings_back_button = Button('Back...', width=12, handler=lambda: self._set_state('Menu'))
        self.settings_reset_button = Button('Reset...', width=12, handler=self._reset_preferences)
        self.settings_pres_timeout_button = PreferenceButton(
            value=self.app.preferences.presence_timeout,
            increments=10,
            limits=(10, 12 * 60)
        )
        self.settings_check_interval_button = PreferenceButton(
            value=self.app.preferences.check_interval,
            increments=10,
            limits=(30, 60)
        )

        self.right_panel_state = 'Menu'
        self.menu_layout = Frame(
            Box(
                HSplit([
                    self.menu_settings_button,
                    Label(''),
                    self.menu_view_button,
                    self.menu_exit_button,
                    self.menu_logout_button,
                ]),
                padding_left=3,
                padding_top=2
            ),
            title='Menu'
        )
        self.settings_layout = Frame(
            Box(
                HSplit([
                    Window(FormattedTextControl(HTML(
                        'This is where you can modify settings\nregarding the underlying presence\nwatcher.'
                    )), wrap_lines=True, width=25),
                    Label(''),
                    VSplit([Label('Presence Timeout (min.):'), self.settings_pres_timeout_button], width=15),
                    VSplit([Label('Refresh Interval (sec.):'), self.settings_check_interval_button], padding=3),
                    Label(''),
                    VSplit([self.settings_back_button, self.settings_reset_button], align=WindowAlign.CENTER)
                ]),
                padding_left=3,
                padding_top=2
            ),
            title='Settings'
        )

    def on_start(self):
        super().on_start()

        self.app.layout.focus(self.menu_settings_button)
        self._start_thread()

    def get_layout(self):
        game_labels = []
        for game in self.riitag_info.games:
            if not game:
                continue

            console_and_game_id = game.split('-')
            if len(console_and_game_id) == 2:
                console: str = console_and_game_id[0]
                game_id: str = console_and_game_id[1]

                label_text = HTML('<b>-</b> {} ({})').format(game_id, console.title())
            else:
                label_text = HTML('<b>-</b> {}').format(console_and_game_id[0])
            game_labels.append(Label(label_text))

        right_panel_layout = HSplit([])
        if self.right_panel_state == 'Menu':
            right_panel_layout = self.menu_layout
        elif self.right_panel_state == 'Settings':
            right_panel_layout = self.settings_layout

        return HSplit([
            Box(
                Label(text='Use the arrow keys and enter to navigate.'),
                height=3,
                padding_left=2
            ),
            VSplit([
                Frame(
                    Box(
                        HSplit([
                            Label(HTML('<b>Name:</b>   {}').format(self.riitag_info.name)),
                            Label(HTML('<b>Games:</b>  {}').format(len(game_labels))),
                            *game_labels
                        ]), padding_left=3, padding_top=2
                    ), title='RiiTag'),
                right_panel_layout
            ])
        ])

    def get_kb(self):
        kb = KeyBindings()

        @kb.add('tab')
        @kb.add('down')
        def next_option(event):
            focus_next(event)

        @kb.add('s-tab')
        @kb.add('up')
        def prev_option(event):
            focus_previous(event)

        @kb.add('right')
        def increase_preference(event):
            modified = self._modify_setting(SettingsModifyMode.INCREASE)
            if not modified:  # treat as regular event
                focus_next(event)

        @kb.add('left')
        def decrease_preference(event):
            modified = self._modify_setting(SettingsModifyMode.DECREASE)
            if not modified:  # treat as regular event
                focus_previous(event)

        return kb

    ################
    # Helper Funcs #
    ################

    def _logout_callback(self, confirm):
        if confirm:
            os.remove(get_cache('token.json'))
            self.app.exit()

    def _logout(self):
        self.app.show_message(
            'Logout Confirmation',

            'Are you sure you want to log out?\n\n'
            'This will close RiiTag-RPC, and you\n'
            'will have to log in again the next time\n'
            'you use it.',

            callback=self._logout_callback
        )

    def _modify_setting(self, mode):
        is_modified = False

        if self.settings_check_interval_button.is_focused:
            if mode == SettingsModifyMode.INCREASE:
                self.settings_check_interval_button.increase()
            elif mode == SettingsModifyMode.DECREASE:
                self.settings_check_interval_button.decrease()

            is_modified = True
            self.app.preferences.check_interval = self.settings_check_interval_button.value

        elif self.settings_pres_timeout_button.is_focused:
            if mode == SettingsModifyMode.INCREASE:
                self.settings_pres_timeout_button.increase()
            elif mode == SettingsModifyMode.DECREASE:
                self.settings_pres_timeout_button.decrease()

            is_modified = True
            self.app.preferences.presence_timeout = self.settings_pres_timeout_button.value

        self.app.preferences.save(get_cache('prefs.json'))

        return is_modified

    def _reset_preferences(self):
        self.app.preferences.reset()
        self.app.preferences.save(get_cache('prefs.json'))

        self.settings_pres_timeout_button.value = self.app.preferences.presence_timeout
        self.settings_pres_timeout_button.update()
        self.settings_check_interval_button.value = self.app.preferences.check_interval
        self.settings_check_interval_button.update()

    def _set_state(self, state):
        self.right_panel_state = state

        self.update()

        if state == 'Menu':
            self.app.layout.focus(self.menu_settings_button)
        elif state == 'Settings':
            self.app.layout.focus(self.settings_back_button)

    def _update_riitag(self, riitag: user.RiitagInfo):
        if not riitag:
            return

        self.riitag_info = riitag

        if not riitag.outdated:
            options = presence.format_presence(self.riitag_info)
            self.app.rpc_handler.set_presence(**options)
        else:
            self.app.rpc_handler.clear()

        self.update()

    def view_riitag(self):
        client_id = self.app.user.id
        tag_url = f"https://tag.rc24.xyz/{client_id}"
        try:
            webbrowser.open(tag_url)
        except webbrowser.Error:
            self.app.show_message(
                'Title',
                'Yikes, that didn\'t work. Please manually paste this URL into your browser:\n' + tag_url
            )

    def _start_thread(self):
        self.app.riitag_watcher = watcher.RiitagWatcher(
            preferences=self.app.preferences,
            user=self.app.user,
            update_callback=self._update_riitag,
            message_callback=None
        )
        self.app.riitag_watcher.start()
