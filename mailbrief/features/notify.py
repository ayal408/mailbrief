"""Windows notifications."""
import datetime as dt
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr
from urllib.parse import urlsplit, urlunsplit

from mailbrief import config
from mailbrief.features.calendar import is_holy_time, paused_until
from mailbrief.storage import load_json


APP_ID = 'MailBrief'
LEGACY_APP_ID = r'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

def quiet_now(now=None):
    """Quiet hours from the settings, e.g. 22:00-07:00 (may cross midnight)."""
    cfg = load_json(config.SETTINGS_FILE, {}).get('quiet') or {}
    if not cfg.get('on'):
        return False
    hour, start, end = (now or dt.datetime.now()).hour, int(cfg.get('from', 22)), int(cfg.get('to', 7))
    return start <= hour < end if start < end else hour >= start or hour < end


def vip_list():
    """Addresses / domains that may break through the quiet hours (never Shabbat, Yom Tov or a pause)."""
    cfg = load_json(config.SETTINGS_FILE, {}).get('quiet') or {}
    return {v.strip().lower().lstrip('@') for v in cfg.get('vip', []) if v.strip()}


def sound_mode():
    """'urgent' (default: a sound only for urgent / VIP / security), 'all', or 'off'."""
    return load_json(config.SETTINGS_FILE, {}).get('sound') or 'urgent'


def activation_url(url):
    """Turn a local web address into a protocol link that starts MailBrief before opening the page."""
    if not url:
        return ''
    parts = urlsplit(url)
    if parts.scheme in ('http', 'https') and parts.hostname in ('mailbrief.localhost', 'localhost', '127.0.0.1', '::1'):
        return urlunsplit(('mailbrief', 'open', '/' + parts.path.lstrip('/'), parts.query, parts.fragment))
    return url


def clear():
    """Remove delivered MailBrief notifications so stale reminders cannot survive an uninstall."""
    for app_id in (APP_ID, LEGACY_APP_ID):
        try:
            _clear_history(app_id)
        except (ImportError, OSError, RuntimeError):
            continue


def _clear_history(app_id):
    from winrt.windows.ui.notifications import ToastNotificationManager
    ToastNotificationManager.history.clear_with_id(app_id)


def _show(xml):
    from winrt.windows.data.xml.dom import XmlDocument
    from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager
    document = XmlDocument()
    document.load_xml(xml)
    ToastNotificationManager.create_toast_notifier_with_id(APP_ID).show(ToastNotification(document))


def toast(title, lines, link='', vip=False, actions=(), loud=False, kind='alert'):
    """actions: [(label, url)] — buttons on the notification (they open a MailBrief address that does the action)."""
    settings = load_json(config.SETTINGS_FILE, {})
    if not settings.get('notifications_enabled', True) or (kind == 'reminder' and not settings.get('reminders_enabled', True)):
        return False
    if is_holy_time(saved_only=True) or paused_until() or (quiet_now() and not vip):
        return False
    body = ''.join(f'<text>{xml_escape(line[:180])}</text>' for line in lines[:2])
    link = activation_url(link)
    launch = f' activationType="protocol" launch={quoteattr(link)}' if link else ''
    buttons = ''.join(f'<action content={quoteattr(label)} activationType="protocol" arguments={quoteattr(activation_url(url))}/>'
                      for label, url in actions[:4])
    mode = sound_mode()
    audio = '' if mode == 'all' or (mode == 'urgent' and (loud or vip)) else '<audio silent="true"/>'
    xml = (f'<toast{launch}><visual><binding template="ToastGeneric"><text>{xml_escape(title)}</text>{body}</binding></visual>'
           + (f'<actions>{buttons}</actions>' if buttons else '') + f'{audio}</toast>')
    try:
        _show(xml)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return True
