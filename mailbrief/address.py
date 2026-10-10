"""The address shown in the browser: http://mailbrief.localhost (any *.localhost name always means this computer)."""
import os

from mailbrief import config


def base_url():
    """The running server writes its address on start: without a port when it got port 80, otherwise with :8765."""
    try:
        with open(config.URL_FILE, encoding='utf-8') as f:
            saved = f.read().strip()
    except OSError:
        saved = ''
    return saved or f'http://{config.NICE_HOST}:{config.PORT}'


def link(path=''):
    return base_url() + '/' + path.lstrip('/')


def remember(nice_port, host=config.NICE_HOST):
    """host is 127.0.0.1 when another program answers on the IPv6 side (::1) of the port — a *.localhost name could reach it."""
    os.makedirs(config.DATA, exist_ok=True)
    with open(config.URL_FILE, 'w', encoding='utf-8') as f:
        f.write(f'http://{host}' + ('' if nice_port == 80 else f':{nice_port}'))
