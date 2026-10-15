"""JSON files on disk and Windows DPAPI encryption for secrets."""
import contextlib
import functools
import tempfile
import threading
import time
import base64
import ctypes
import json
import os
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    inp = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def encrypt(text: str) -> str:
    return base64.b64encode(_dpapi(text.encode('utf-8'), True)).decode()


def decrypt(blob: str) -> str:
    return _dpapi(base64.b64decode(blob), False).decode('utf-8')


def load_json(path, default):
    try:
        with file_lock(path), open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


_LOCKS = {}
_GUARD = threading.Lock()
_LOCAL = threading.local()


@contextlib.contextmanager
def file_lock(path):
    """Reentrant lock shared by threads and processes (desktop and scheduled runs)."""
    path = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _GUARD:
        lock = _LOCKS.setdefault(path, threading.RLock())
    with lock:
        held = getattr(_LOCAL, 'held', {})
        if path in held:
            yield
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.lock', 'a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                if os.path.getsize(path + '.lock') == 0:
                    handle.write(b'0')
                    handle.flush()
                while True:
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            held[path] = True
            _LOCAL.held = held
            try:
                yield
            finally:
                del held[path]
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def locked(path_getter):
    """Serialize a complete read/change/write operation, including nested save_json calls."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with file_lock(path_getter()):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def save_json(path, value):
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with file_lock(path):
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + '.', suffix='.tmp', dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
