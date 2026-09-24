"""MailBrief's own window: a native Windows window with the built-in WebView2 engine (pywebview), like Teams or the new
Outlook. Closing it keeps MailBrief next to the clock; "Exit" in the tray menu really quits.
Without pywebview (running from source) it falls back to an Edge / Chrome app window, then to the plain browser."""
import ctypes
import importlib.util
import os
import subprocess
import threading
import webbrowser
import winreg

from mailbrief import config
from mailbrief.storage import load_json


APP = {'window': None, 'quitting': False, 'hint_shown': False}


# ---- the real window --------------------------------------------------------------------------------------------------

def available():
    try:
        return importlib.util.find_spec('webview') is not None
    except Exception:
        return False


def _work_area():
    """The screen minus the taskbar: (left, top, width, height)."""
    try:
        rect = (ctypes.c_long * 4)()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):      # SPI_GETWORKAREA
            return rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
    except Exception:
        pass
    return 0, 0, 1536, 824


def _size():
    _, _, aw, ah = _work_area()
    return min(1280, int(aw * 0.88)), min(880, int(ah * 0.88))


def _place():
    """Width, height, x, y: centred in the free area, never under the taskbar."""
    left, top, aw, ah = _work_area()
    width, height = _size()
    return width, height, left + (aw - width) // 2, top + (ah - height) // 2


def run_app(url, on_hidden=None):
    """Runs on the main thread and returns when the user picks "Exit" (tray menu or the page's ⏻ button)."""
    import webview
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True       # Gmail and websites open in the user's browser
    try:                                                             # ... the one already open, not always Edge
        from webview.platforms import edgechromium
        edgechromium.webbrowser = type('OpenBrowser', (), {'open': staticmethod(lambda u, *a, **k: open_browser_tab(u))})
    except Exception:
        pass
    width, height, x, y = _place()
    win = webview.create_window('MailBrief', url, width=width, height=height, x=x, y=y, min_size=(820, 560),
                                text_select=True, background_color='#FBF7F2')

    def closing():
        if APP['quitting']:
            return True
        win.hide()                                                   # ✕ = back to the tray, like Teams
        if on_hidden and not APP['hint_shown']:
            APP['hint_shown'] = True
            threading.Thread(target=on_hidden, daemon=True).start()
        return False
    win.events.closing += closing
    APP['window'] = win
    os.makedirs(os.path.join(config.DATA, 'window'), exist_ok=True)
    webview.start(gui='edgechromium', private_mode=False, storage_path=os.path.join(config.DATA, 'window'))
    APP['window'] = None


def show(url=None):
    """Brings the window back (from the tray, or when MailBrief is started a second time)."""
    win = APP['window']
    if not win:
        return False
    if url:
        win.load_url(url)
    win.show()
    try:
        win.restore()
    except Exception:
        pass
    return True


def quit_app():
    APP['quitting'] = True
    if APP['window']:
        try:
            APP['window'].destroy()
        except Exception:
            pass


def in_app():
    return APP['window'] is not None


# ---- fallbacks --------------------------------------------------------------------------------------------------------

def _candidates():
    pf, pf86, local = (os.environ.get(k, '') for k in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'))
    return {
        'chrome': [os.path.join(p, r'Google\Chrome\Application\chrome.exe') for p in (pf, pf86, local) if p],
        'edge': [os.path.join(p, r'Microsoft\Edge\Application\msedge.exe') for p in (pf86, pf, local) if p],
    }


def _default_browser():
    try:
        key = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            prog = winreg.QueryValueEx(k, 'ProgId')[0].lower()
    except OSError:
        return ''
    return 'chrome' if 'chrome' in prog else 'edge' if 'msedge' in prog else ''


def app_browser():
    found = {name: next((p for p in paths if os.path.isfile(p)), None) for name, paths in _candidates().items()}
    first = _default_browser()
    order = [first] + [n for n in ('edge', 'chrome') if n != first] if first else ['edge', 'chrome']
    return next((found[n] for n in order if found.get(n)), None)


def open_window(url):
    """Shows MailBrief: the real window when it is running, otherwise an app-mode browser window or the plain browser."""
    if show(url):
        return
    exe = app_browser()
    if load_json(config.SETTINGS_FILE, {}).get('open_in_browser') or not exe:
        webbrowser.open(url)
        return
    width, height = _size()
    try:
        subprocess.Popen([exe, f'--app={url}', f'--window-size={width},{height}'], creationflags=0x00000008 | 0x00000200)
    except OSError:
        webbrowser.open(url)


# browsers by their process name: the one already open gets the page (as a new tab), not whatever Windows defaults to
BROWSERS = ('chrome.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe', 'msedge.exe')


def _running():
    try:
        out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000).stdout.lower()                     # CREATE_NO_WINDOW
    except (OSError, subprocess.SubprocessError):
        return set()
    return {name for name in BROWSERS if f'"{name}"' in out}


def _exe_path(name):
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, rf'Software\Microsoft\Windows\CurrentVersion\App Paths\{name}') as k:
                path = winreg.QueryValueEx(k, '')[0].strip('"')
                if os.path.isfile(path):
                    return path
        except OSError:
            pass
    return next((p for p in _candidates().get(name.split('.')[0], []) if os.path.isfile(p)), None)


def open_browser_tab(url):
    """Opens url in the browser that is already open. Edge runs in the background on most computers (and is often the
    Windows default without anyone choosing it), so it counts only when no other browser is open.
    Nothing open: the Windows default browser."""
    running = _running()
    order = [b for b in BROWSERS if b in running]                    # BROWSERS lists Edge last
    for name in order:
        exe = _exe_path(name)
        if exe:
            try:
                subprocess.Popen([exe, url], creationflags=0x00000008 | 0x00000200)
                return
            except OSError:
                pass
    webbrowser.open(url)


def open_external(url):
    """Pages that must not open inside the app window (Google / Microsoft sign-in, a sender's unsubscribe page)."""
    open_browser_tab(url)
