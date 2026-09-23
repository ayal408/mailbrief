"""Small shared helpers: HTML escaping, safe file names, money formatting."""
import datetime as dt
import html
import os
import re


def safe_name(text):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', text).strip(' ._')[:120] or 'file'


def write_once(folder, name, data):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        with open(path, 'wb') as f:
            f.write(data)
    return path


e = html.escape


def month_back(n):
    today = dt.date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        m, y = m + 12, y - 1
    return f'{y}-{m:02d}'


def money(v):
    return f'₪{v:,.0f}'
