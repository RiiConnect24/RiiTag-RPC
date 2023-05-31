import os
import platform

CACHE_DIR_NAME = 'riitag-rpc'


def get_cache_dir():
    plat = platform.system()
    if plat == 'Windows':
        path = os.getenv('LOCALAPPDATA')
    elif plat == 'Linux':
        fallback = os.path.join(os.getenv('HOME'), '.cache')
        path = os.getenv('XDG_CACHE_HOME', fallback)
    elif plat == 'Darwin':
        fallback = os.path.join(os.getenv('HOME'), 'Library/Caches')
        path = os.getenv('XDG_CACHE_HOME', fallback)
    else:
        raise OSError(f'Platform unsupported: {plat}')

    path = os.path.join(path, CACHE_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_cache(filename):
    return os.path.join(get_cache_dir(), filename)
