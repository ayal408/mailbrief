"""Windows notifications."""
import os
import subprocess
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from mailbrief.features.calendar import is_holy_time, paused_until


POWERSHELL_TOAST = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml($env:MAILBRIEF_TOAST)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
'''


def toast(title, lines, link=''):
    if is_holy_time() or paused_until():
        return
    body = ''.join(f'<text>{xml_escape(line[:180])}</text>' for line in lines[:2])
    launch = f' activationType="protocol" launch={quoteattr(link)}' if link else ''
    xml = f'<toast{launch}><visual><binding template="ToastGeneric"><text>{xml_escape(title)}</text>{body}</binding></visual></toast>'
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', POWERSHELL_TOAST],
                   env={**os.environ, 'MAILBRIEF_TOAST': xml}, creationflags=0x08000000, timeout=30)
