from __future__ import annotations

import json
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Any

import requests

from .user import User

API_ENDPOINT = 'https://discord.com/api'
AUTHORIZE_ENDPOINT = 'https://discord.com/api/oauth2/authorize'
TOKEN_ENDPOINT = 'https://discord.com/api/oauth2/token'


class OAuth2Token:
    def __init__(self, client: OAuth2Client, **kwargs):
        self._client = client

        self.access_token = kwargs.pop('access_token')
        self.refresh_token = kwargs.pop('refresh_token')
        self.token_type = kwargs.pop('token_type')
        self.expires_in = kwargs.pop('expires_in')
        self.scope = kwargs.pop('scope')

        self.last_refresh = kwargs.pop('last_refresh', time.time())

        if kwargs:
            raise ValueError('Unexpected arguments: ' + str(kwargs.keys()))

    @property
    def needs_refresh(self):
        curr_time = time.time()
        if curr_time - self.last_refresh > self.expires_in:
            return True

        return False

    def save(self, fn):
        data = {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_type': self.token_type,
            'expires_in': self.expires_in,
            'scope': self.scope,
            'last_refresh': self.last_refresh
        }

        with open(fn, 'w+') as file:
            json.dump(data, file, indent=4)

    def refresh(self):
        payload = {
            'client_id': self._client.config.get('client_id'),
            'client_secret': self._client.config.get('client_secret'),
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'redirect_uri': self._client.redirect_uri,
            'scope': self.scope
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        r = requests.post(TOKEN_ENDPOINT, data=payload, headers=headers)
        r.raise_for_status()

        token_data = r.json()
        self.access_token = token_data.pop('access_token')
        self.refresh_token = token_data.pop('refresh_token')
        self.token_type = token_data.pop('token_type')
        self.expires_in = token_data.pop('expires_in')
        self.scope = token_data.pop('scope')

        self.last_refresh = time.time()

        return True

    def get_user(self) -> User:
        if self.needs_refresh:
            self.refresh()

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }
        r = requests.get(API_ENDPOINT + '/users/@me', headers=headers)
        r.raise_for_status()

        return User(**r.json())


class RequestHandler(BaseHTTPRequestHandler):
    # noinspection PyPep8Naming
    def do_GET(self):
        if not self.path.startswith('/callback'):
            self.handle_404()
            return

        query_str = urllib.parse.urlparse(self.path).query
        query = urllib.parse.parse_qs(query_str)
        code = query.get('code')
        if not code:
            self.handle_400()
            return
        elif len(code) != 1:
            self.handle_400()
            return

        self.server.code = code[0]

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b'You can now close this window. But only if you want to, '
                         b'I guess, I\'m not forcing you or anything.')

    def handle_404(self):
        self.send_response(404)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b'Just leave me alone. Please. I need my privacy.')

        return

    def handle_400(self):
        self.send_response(400)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b'Eh, something went wrong. It\'s my fault, I swear!')

        return

    # noinspection PyShadowingBuiltins
    def log_message(self, format: str, *args: Any) -> None:
        return  # silence, you loud server!


class OAuth2HTTPServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        self.code = None

        super().__init__(*args, **kwargs)


class OAuth2Client:
    def __init__(self, config: dict):
        """OAuth2 client to interact with Discord.

        :param config: the config file, as a dict.
        """
        self.config = config

        self._http_server = None
        self._server_thread = None

    @property
    def redirect_uri(self):
        port = self.config.get("port")
        return f'http://localhost:{port}/callback'

    @property
    def auth_url(self):
        query = {
            'client_id': self.config.get('client_id'),
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': 'identify'
        }
        query_str = urllib.parse.urlencode(query)

        return AUTHORIZE_ENDPOINT + '?' + query_str\

    @property
    def client_id(self):
        return self.config.get('client_id')

    def wait_for_code(self):
        if not self._http_server:
            raise RuntimeError('Server not yet started.')

        while True:
            code = self._http_server.code
            if code:
                return code

    def get_token(self, code):
        payload = {
            'client_id': self.config.get('client_id'),
            'client_secret': self.config.get('client_secret'),
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri,
            'scope': 'identify'
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        r = requests.post(TOKEN_ENDPOINT, data=payload, headers=headers)
        r.raise_for_status()

        token = OAuth2Token(self, **r.json())

        return token

    def start_server(self, port: int) -> None:
        if self._http_server:  # already initialized
            return

        self._http_server = OAuth2HTTPServer(('localhost', port), RequestHandler)

        self._server_thread = threading.Thread(target=self._http_server.serve_forever)
        self._server_thread.daemon = True
        self._server_thread.start()

    def stop_server(self):
        if not self._http_server:
            return

        self._http_server.shutdown()
        self._server_thread.join()

        self._http_server = None
        self._server_thread = None
