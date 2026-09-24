"""The icon next to the clock (pure Win32 via ctypes)."""
import ctypes
import sys
import threading
from ctypes import wintypes

from mailbrief.address import link
from mailbrief.features.alerts import check_alerts
from mailbrief.features.calendar import is_holy_time, pause_for, paused_until
from mailbrief.features.reminders import fire_reminders
from mailbrief.window import open_window


TRAY = {'hwnd': None}


def run_tray(on_exit=None):
    """An icon next to the clock with a right-click menu (pure Win32 via ctypes). Blocks until "Exit".
    on_exit: also close the app window (the tray then runs on its own thread)."""
    w = wintypes
    user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [('style', w.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                    ('hInstance', w.HINSTANCE), ('hIcon', w.HICON), ('hCursor', w.HANDLE), ('hbrBackground', w.HBRUSH),
                    ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR)]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [('cbSize', w.DWORD), ('hWnd', w.HWND), ('uID', w.UINT), ('uFlags', w.UINT), ('uCallbackMessage', w.UINT),
                    ('hIcon', w.HICON), ('szTip', w.WCHAR * 128), ('dwState', w.DWORD), ('dwStateMask', w.DWORD),
                    ('szInfo', w.WCHAR * 256), ('uVersion', w.UINT), ('szInfoTitle', w.WCHAR * 64), ('dwInfoFlags', w.DWORD),
                    ('guidItem', ctypes.c_byte * 16), ('hBalloonIcon', w.HICON)]

    user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
    user32.CreateWindowExW.restype = w.HWND
    user32.CreatePopupMenu.restype = w.HMENU
    user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID]
    user32.DestroyMenu.argtypes = [w.HMENU]
    user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user32.LoadIconW.argtypes = [w.HINSTANCE, w.LPVOID]
    user32.LoadIconW.restype = w.HICON
    shell32.ExtractIconW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT]
    shell32.ExtractIconW.restype = w.HICON
    shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.c_void_p]
    kernel32.GetModuleHandleW.restype = w.HMODULE

    WM_TRAY, WM_COMMAND, WM_DESTROY, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0400 + 20, 0x0111, 0x0002, 0x0203, 0x0205
    base = link()
    menu_items = [(1, 'פתיחת MailBrief'), (2, 'היום שלי'), (3, 'אוטומציות'), (0, None), (4, 'בדיקה עכשיו'),
                  (5, 'השהיה לשעתיים'), (6, 'השהיה עד מחר בבוקר'), (7, 'ביטול השהיה'), (0, None), (9, 'יציאה')]

    def background_check():
        if not (is_holy_time() or paused_until()):
            check_alerts()
            fire_reminders()

    def command(cid, hwnd):
        if cid in (1, 2, 3):
            open_window(base + {1: '', 2: 'today', 3: 'automations'}[cid])
        elif cid == 4:
            threading.Thread(target=background_check, daemon=True).start()
        elif cid in (5, 6, 7):
            pause_for({5: '2h', 6: 'tomorrow', 7: 'off'}[cid])
            update_tip()
        elif cid == 9:
            user32.DestroyWindow(hwnd)
            if on_exit:
                on_exit()

    def update_tip():
        until = paused_until()
        nid.szTip = f'MailBrief — מושהה עד {until:%H:%M}' if until else 'MailBrief'
        shell32.Shell_NotifyIconW(1, ctypes.byref(nid))              # NIM_MODIFY

    @WNDPROC
    def proc(hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONDBLCLK:
                command(2, hwnd)
            elif lparam == WM_RBUTTONUP:
                menu = user32.CreatePopupMenu()
                for cid, text in menu_items:
                    user32.AppendMenuW(menu, 0x800 if text is None else 0, cid, text)
                pt = w.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.SetForegroundWindow(hwnd)
                user32.TrackPopupMenu(menu, 0x8000, pt.x, pt.y, 0, hwnd, None)      # TPM_LAYOUTRTL: Hebrew menu
                user32.DestroyMenu(menu)
            return 0
        if msg == WM_COMMAND:
            command(wparam & 0xFFFF, hwnd)
            return 0
        if msg == WM_DESTROY:
            shell32.Shell_NotifyIconW(2, ctypes.byref(nid))          # NIM_DELETE
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS(lpfnWndProc=proc, hInstance=hinst, lpszClassName='MailBriefTray')
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, 'MailBriefTray', 'MailBrief', 0, 0, 0, 0, 0, None, None, hinst, None)
    icon = shell32.ExtractIconW(hinst, sys.executable, 0) if getattr(sys, 'frozen', False) else None
    nid = NOTIFYICONDATA(cbSize=ctypes.sizeof(NOTIFYICONDATA), hWnd=hwnd, uID=1, uFlags=0x1 | 0x2 | 0x4,
                         uCallbackMessage=WM_TRAY, hIcon=icon or user32.LoadIconW(None, ctypes.c_void_p(32512)))
    if not shell32.Shell_NotifyIconW(0, ctypes.byref(nid)):         # NIM_ADD
        raise OSError('tray icon could not be added')
    TRAY['hwnd'] = hwnd
    update_tip()
    msg = w.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    TRAY['hwnd'] = None


def close_tray():
    if TRAY['hwnd']:
        ctypes.windll.user32.PostMessageW(TRAY['hwnd'], 0x0010, 0, 0)    # WM_CLOSE
