"""🔴 Unread mail on the taskbar icon, like Outlook: a red badge with the number of unread messages in the inboxes
(99+ above 99), gone when everything is read. Windows' own taskbar overlay (ITaskbarList3::SetOverlayIcon) on
MailBrief's window; the count comes from a quick STATUS of each inbox, again whenever new mail arrives."""
import ctypes
import threading
import time
from ctypes import wintypes


_STATE = {'shown': None, 'icon': None}

_CLSID_TASKBARLIST = '{56FDF344-FD6D-11d0-958A-006097C9A090}'
_IID_ITASKBARLIST3 = '{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}'


class _GUID(ctypes.Structure):
    _fields_ = [('a', ctypes.c_ulong), ('b', ctypes.c_ushort), ('c', ctypes.c_ushort), ('d', ctypes.c_ubyte * 8)]


def _guid(text):
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def label(count):
    return '' if count <= 0 else '99+' if count > 99 else str(count)


def _make_icon(text):
    """A red circle with the number in white, 32×32 — drawn with .NET's System.Drawing (already loaded by the window)."""
    import clr
    clr.AddReference('System.Drawing')
    from System.Drawing import Bitmap, Brushes, Color, Font, FontStyle, Graphics, SolidBrush, StringAlignment, \
        StringFormat, RectangleF
    from System.Drawing.Drawing2D import SmoothingMode
    from System.Drawing.Text import TextRenderingHint
    bmp = Bitmap(32, 32)
    g = Graphics.FromImage(bmp)
    g.SmoothingMode = SmoothingMode.AntiAlias
    g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit
    g.Clear(Color.Transparent)
    g.FillEllipse(SolidBrush(Color.FromArgb(255, 220, 38, 38)), 0, 0, 31, 31)
    size = 15 if len(text) == 1 else 12 if len(text) == 2 else 9
    fmt = StringFormat()
    fmt.Alignment = fmt.LineAlignment = StringAlignment.Center
    g.DrawString(text, Font('Segoe UI', size, FontStyle.Bold), Brushes.White, RectangleF(0, 0, 32, 33), fmt)
    g.Dispose()
    return bmp.GetHicon().ToInt64()


def _set_overlay(hwnd, hicon, text):
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    try:
        ptr = ctypes.c_void_p()
        ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_TASKBARLIST)), None, 1, ctypes.byref(_guid(_IID_ITASKBARLIST3)),
                               ctypes.byref(ptr))
        vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        hr_init = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[3])
        overlay = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_void_p, ctypes.c_wchar_p)(vtbl[18])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        hr_init(ptr)
        overlay(ptr, hwnd, hicon or None, f'{text} הודעות שלא נקראו' if text else '')
        release(ptr)
    finally:
        ole32.CoUninitialize()


def show(count):
    """Puts the number on MailBrief's taskbar button (0 removes it). Quietly nothing outside the app window."""
    from mailbrief import window
    text = label(count)
    win = window.APP.get('window')
    if text == _STATE['shown'] or not win:
        return
    try:
        hwnd = win.native.Handle.ToInt64()
        hicon = _make_icon(text) if text else None
        _set_overlay(hwnd, hicon, text)
        if _STATE['icon']:
            ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(_STATE['icon']))
        _STATE['icon'], _STATE['shown'] = hicon, text
    except Exception:
        pass


def unread_total():
    from mailbrief.mail import mailbox
    total = 0
    for acc in mailbox.accounts():
        try:
            with mailbox.session(acc, 'INBOX', readonly=True) as m:
                typ, data = m.uid('SEARCH', None, 'UNSEEN')
                if typ == 'OK':
                    total += len((data[0] or b'').split())
        except Exception:
            continue
    return total


def watch():
    """Keeps the badge right: on new mail (the live version changes) and every two minutes."""
    from mailbrief.features import live

    def loop():
        seen, last = None, 0.0
        while True:
            try:
                v = live.version()
                if v != seen or time.time() - last > 120:
                    seen, last = v, time.time()
                    show(unread_total())
            except Exception:
                pass
            time.sleep(10)
    threading.Thread(target=loop, daemon=True, name='badge').start()
