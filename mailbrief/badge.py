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


def _make_icon(text, size=16):
    """A round red badge with the number in white, drawn at the exact size Windows shows it (16 px at 100%, 20 / 24 / 32
    on sharper screens) — a 32 px picture shrunk to 16 turned "99+" into a smudge. The number is drawn as a shape and
    scaled to fill the badge; a thin white ring keeps it apart from the icon under it. System.Drawing (.NET)."""
    import clr
    clr.AddReference('System.Drawing')
    from System.Drawing import Bitmap, Color, FontFamily, FontStyle, Graphics, Pen, PointF, RectangleF, SolidBrush,         StringFormat
    from System.Drawing.Drawing2D import GraphicsPath, Matrix, SmoothingMode
    from System.Drawing.Imaging import PixelFormat
    bmp = Bitmap(size, size, PixelFormat.Format32bppArgb)
    g = Graphics.FromImage(bmp)
    g.SmoothingMode = SmoothingMode.AntiAlias
    g.Clear(Color.Transparent)
    ring = max(1.0, size / 16)
    shape = GraphicsPath()                              # always round
    shape.AddEllipse(RectangleF(ring / 2, ring / 2, size - ring, size - ring))
    g.FillPath(SolidBrush(Color.FromArgb(255, 220, 38, 38)), shape)
    g.DrawPath(Pen(Color.White, ring), shape)
    more = text.endswith('+')                           # 100 and up: "99" big, a small "+" beside it
    digits = GraphicsPath()
    digits.AddString(text.rstrip('+'), FontFamily('Segoe UI'), int(FontStyle.Bold), 100.0, PointF(0, 0),
                     StringFormat.GenericTypographic)
    box = digits.GetBounds()
    one = len(text) == 1
    room_w, room_h = size * (0.5 if one else 0.48 if more else 0.62), size * (0.6 if one else 0.4 if more else 0.46)
    k = min(room_w / box.Width, room_h / box.Height)
    m = Matrix()
    m.Translate(size * (0.4 if more else 0.5), size / 2)
    m.Scale(k, k)
    m.Translate(-(box.X + box.Width / 2), -(box.Y + box.Height / 2))
    digits.Transform(m)
    g.FillPath(SolidBrush(Color.White), digits)
    if more:
        arm, t = max(2, round(size * 0.11)), max(1, round(size * 0.08))     # whole pixels: crisp at 16 px
        cx, cy = round(size * 0.8), round(size * 0.4)
        g.SmoothingMode = getattr(SmoothingMode, 'None')          # 'None' is a Python keyword
        g.FillRectangle(SolidBrush(Color.White), cx - arm, cy, 2 * arm + t, t)
        g.FillRectangle(SolidBrush(Color.White), cx, cy - arm, t, 2 * arm + t)
    g.Dispose()
    return bmp.GetHicon().ToInt64()


def _icon_size(hwnd):
    """The small-icon size for the window's screen (taskbar overlays are drawn at it)."""
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd)) or 96
        return ctypes.windll.user32.GetSystemMetricsForDpi(49, dpi) or 16      # SM_CXSMICON
    except Exception:
        return 16


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
        hicon = _make_icon(text, _icon_size(hwnd)) if text else None
        _set_overlay(hwnd, hicon, text)
        if _STATE['icon']:
            ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(_STATE['icon']))
        _STATE['icon'], _STATE['shown'] = hicon, text
    except Exception:
        pass


def primary_only():
    """Gmail: count only the ראשי category (social / updates / promotions pile up by the hundreds). Settings → אישי."""
    from mailbrief import config
    from mailbrief.storage import load_json
    return (load_json(config.SETTINGS_FILE, {}).get('badge') or 'primary') == 'primary'


def unread_total():
    from mailbrief.mail import imap, mailbox
    total, primary = 0, primary_only()
    for acc in mailbox.accounts():
        try:
            with mailbox.session(acc, 'INBOX', readonly=True) as m:
                if primary and imap.is_gmail(acc):
                    total += len(mailbox._search(m, True, 'category:primary', unread=True))
                    continue
                typ, data = m.uid('SEARCH', None, 'UNSEEN')
                if typ == 'OK':
                    total += len((data[0] or b'').split())
        except Exception:
            continue
    return total


def refresh():
    """Right away (the setting changed), in the background."""
    threading.Thread(target=lambda: show(unread_total()), daemon=True, name='badge-now').start()


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
