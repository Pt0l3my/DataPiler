"""The Windows adapter (build plan §3.5).

Everything Windows-only sits here, through ctypes with explicit argtypes and restype (handles are 64-bit). The
portable backend gives the documented fallback answers, so every test runs on Linux too.

The user name, the PC name and the home folder are used for the log's masks and the guard's check 4 only: never
logged, never sent to the page."""

from __future__ import annotations

import os
import signal
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

CLOSE_WAIT = 4.5            # Windows allows about 5 s for a console's close, logoff or shutdown event


@dataclass(frozen=True)
class Proc:
    name: str               # image name, lower-cased, e.g. "eldenring.exe"
    path: str | None        # full image path when readable


class Holder(Protocol):
    def release(self) -> None: ...


class Backend(Protocol):
    def processes(self) -> list[Proc]: ...
    def file_version(self, path: str) -> str | None: ...
    def hold_mutex(self, name: str, fallback_file: Path) -> Holder | None: ...
    def on_console_close(self, fn: Callable[[], None]) -> None: ...
    def set_clipboard(self, text: str) -> bool: ...
    def open_folder(self, path: str) -> bool: ...
    def short_path(self, path: str) -> str | None: ...
    def drive_is_remote(self, path: str) -> bool: ...
    def enable_vt(self) -> None: ...
    def user_name(self) -> str | None: ...
    def pc_name(self) -> str | None: ...
    def home(self) -> str | None: ...


def _run_waiting(fn: Callable[[], None]) -> None:
    """Call fn on its own thread and wait for it, at most CLOSE_WAIT seconds."""
    t = threading.Thread(target=_quiet(fn), name="close-event", daemon=True)
    t.start()
    t.join(CLOSE_WAIT)


def _quiet(fn: Callable[[], None]) -> Callable[[], None]:
    def run() -> None:
        try:
            fn()
        except Exception:       # the close goes on whatever fn did
            pass
    return run


# ---------------------------------------------------------------------------------------------------------- portable


class _FileHolder:
    """The portable stand-in for the named mutex: an exclusive lock on datapiler.lock."""

    def __init__(self, fd: int, path: Path, flocked: bool):
        self._fd = fd
        self._path = path
        self._flocked = flocked
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._fd < 0:
                return
            fd, self._fd = self._fd, -1
        if self._flocked:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
        if not self._flocked:
            try:
                os.unlink(self._path)
            except OSError:
                pass


class PortableBackend:
    """The answers DataPiler uses off Windows: /proc for processes, flock for the mutex, signals for the close."""

    def processes(self) -> list[Proc]:
        proc = Path("/proc")
        if not proc.is_dir():
            return []
        out: list[Proc] = []
        try:
            entries = list(proc.iterdir())
        except OSError as e:
            raise OSError(e.errno, "process list") from None
        for entry in entries:
            if not entry.name.isdigit():
                continue
            path: str | None
            try:
                path = os.readlink(entry / "exe")
            except OSError:
                path = None
            name = ""
            if path:
                name = os.path.basename(path)
            else:
                try:
                    name = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    continue
            if name:
                out.append(Proc(name=name.lower(), path=path))
        return out

    def file_version(self, path: str) -> str | None:
        return None

    def hold_mutex(self, name: str, fallback_file: Path) -> Holder | None:
        fallback_file = Path(fallback_file)
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl is not None:
            fd = os.open(str(fallback_file), os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return None
            return _FileHolder(fd, fallback_file, True)
        try:
            fd = os.open(str(fallback_file), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return None
        return _FileHolder(fd, fallback_file, False)

    def on_console_close(self, fn: Callable[[], None]) -> None:
        def handler(signum, frame):  # noqa: ARG001
            # The handler runs on the main thread, which has to get back to the page's loop for the stop to run;
            # nothing kills the process once the handler returns, so fn runs on its own thread, unawaited.
            threading.Thread(target=_quiet(fn), name="close-signal", daemon=True).start()
        for name in ("SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):   # not the main thread, or not allowed here
                pass

    def set_clipboard(self, text: str) -> bool:
        return False

    def open_folder(self, path: str) -> bool:
        return False

    def short_path(self, path: str) -> str | None:
        return None

    def drive_is_remote(self, path: str) -> bool:
        return False

    def enable_vt(self) -> None:
        return None

    def user_name(self) -> str | None:
        for key in ("USER", "LOGNAME", "USERNAME"):
            v = os.environ.get(key)
            if v:
                return v
        try:
            import pwd
            return pwd.getpwuid(os.getuid()).pw_name or None
        except (ImportError, KeyError, OSError, AttributeError):
            return None

    def pc_name(self) -> str | None:
        try:
            import socket
            return socket.gethostname() or None
        except OSError:
            return None

    def home(self) -> str | None:
        h = os.path.expanduser("~")
        return h if h and h != "~" else None


# ---------------------------------------------------------------------------------------------------------- Windows


class WindowsBackend:  # pragma: no cover - exercised by the Windows run in CI
    """The Win32 calls, each with its argtypes and restype."""

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ALREADY_EXISTS = 183
    DRIVE_REMOTE = 4
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    STD_OUTPUT_HANDLE = -11
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 2, 5, 6

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        self._c = ctypes
        self._w = w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u = ctypes.WinDLL("user32", use_last_error=True)
        self._k, self._u = k, u
        self._v = None
        self._handlers: list[object] = []

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260),
            ]
        self._PE = PROCESSENTRY32W

        H = w.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = H
        k.Process32FirstW.argtypes = [H, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32FirstW.restype = w.BOOL
        k.Process32NextW.argtypes = [H, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.restype = w.BOOL
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = H
        k.QueryFullProcessImageNameW.argtypes = [H, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.QueryFullProcessImageNameW.restype = w.BOOL
        k.CloseHandle.argtypes = [H]
        k.CloseHandle.restype = w.BOOL
        k.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
        k.CreateMutexW.restype = H
        k.GetShortPathNameW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
        k.GetShortPathNameW.restype = w.DWORD
        k.GetDriveTypeW.argtypes = [w.LPCWSTR]
        k.GetDriveTypeW.restype = w.UINT
        k.GetStdHandle.argtypes = [w.DWORD]
        k.GetStdHandle.restype = H
        k.GetConsoleMode.argtypes = [H, ctypes.POINTER(w.DWORD)]
        k.GetConsoleMode.restype = w.BOOL
        k.SetConsoleMode.argtypes = [H, w.DWORD]
        k.SetConsoleMode.restype = w.BOOL
        k.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
        k.GlobalAlloc.restype = w.HGLOBAL
        k.GlobalLock.argtypes = [w.HGLOBAL]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [w.HGLOBAL]
        k.GlobalUnlock.restype = w.BOOL
        k.GlobalFree.argtypes = [w.HGLOBAL]
        k.GlobalFree.restype = w.HGLOBAL
        self._ROUTINE = ctypes.WINFUNCTYPE(w.BOOL, w.DWORD)
        k.SetConsoleCtrlHandler.argtypes = [self._ROUTINE, w.BOOL]
        k.SetConsoleCtrlHandler.restype = w.BOOL
        u.OpenClipboard.argtypes = [w.HWND]
        u.OpenClipboard.restype = w.BOOL
        u.EmptyClipboard.argtypes = []
        u.EmptyClipboard.restype = w.BOOL
        u.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
        u.SetClipboardData.restype = w.HANDLE
        u.CloseClipboard.argtypes = []
        u.CloseClipboard.restype = w.BOOL

    def _invalid(self, h) -> bool:
        return not h or h == self._c.c_void_p(-1).value

    def processes(self) -> list[Proc]:
        c, w, k = self._c, self._w, self._k
        snap = k.CreateToolhelp32Snapshot(self.TH32CS_SNAPPROCESS, 0)
        if self._invalid(snap):
            raise OSError(c.get_last_error(), "process snapshot")
        out: list[Proc] = []
        try:
            entry = self._PE()
            entry.dwSize = c.sizeof(self._PE)
            ok = k.Process32FirstW(snap, c.byref(entry))
            while ok:
                name = entry.szExeFile.lower()
                out.append(Proc(name=name, path=self._image_path(entry.th32ProcessID)))
                ok = k.Process32NextW(snap, c.byref(entry))
        finally:
            k.CloseHandle(snap)
        return out

    def _image_path(self, pid: int) -> str | None:
        c, w, k = self._c, self._w, self._k
        if not pid:
            return None
        h = k.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            size = w.DWORD(32768)
            buf = c.create_unicode_buffer(size.value)
            if not k.QueryFullProcessImageNameW(h, 0, buf, c.byref(size)):
                return None
            return buf.value or None
        finally:
            k.CloseHandle(h)

    def file_version(self, path: str) -> str | None:
        c, w = self._c, self._w
        if self._v is None:
            v = c.WinDLL("version", use_last_error=True)
            v.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, c.POINTER(w.DWORD)]
            v.GetFileVersionInfoSizeW.restype = w.DWORD
            v.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p]
            v.GetFileVersionInfoW.restype = w.BOOL
            v.VerQueryValueW.argtypes = [c.c_void_p, w.LPCWSTR, c.POINTER(c.c_void_p), c.POINTER(w.UINT)]
            v.VerQueryValueW.restype = w.BOOL
            self._v = v
        v = self._v

        class VS_FIXEDFILEINFO(c.Structure):
            _fields_ = [(n, w.DWORD) for n in (
                "dwSignature", "dwStrucVersion", "dwFileVersionMS", "dwFileVersionLS", "dwProductVersionMS",
                "dwProductVersionLS", "dwFileFlagsMask", "dwFileFlags", "dwFileOS", "dwFileType",
                "dwFileSubtype", "dwFileDateMS", "dwFileDateLS")]

        handle = w.DWORD(0)
        size = v.GetFileVersionInfoSizeW(path, c.byref(handle))
        if not size:
            return None
        buf = c.create_string_buffer(size)
        if not v.GetFileVersionInfoW(path, 0, size, buf):
            return None
        ptr = c.c_void_p()
        length = w.UINT(0)
        if not v.VerQueryValueW(buf, "\\", c.byref(ptr), c.byref(length)) or not ptr.value:
            return None
        if length.value < c.sizeof(VS_FIXEDFILEINFO):
            return None
        info = VS_FIXEDFILEINFO.from_address(ptr.value)
        if info.dwSignature != 0xFEEF04BD:
            return None
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)

    def hold_mutex(self, name: str, fallback_file: Path) -> Holder | None:
        c, k = self._c, self._k
        h = k.CreateMutexW(None, False, name)
        err = c.get_last_error()
        if not h:
            raise OSError(err, "mutex")
        if err == self.ERROR_ALREADY_EXISTS:
            k.CloseHandle(h)
            return None
        backend = self

        class _MutexHolder:
            def __init__(self) -> None:
                self._h = h

            def release(self) -> None:
                hh, self._h = self._h, None
                if hh:
                    backend._k.CloseHandle(hh)

        return _MutexHolder()

    def on_console_close(self, fn: Callable[[], None]) -> None:
        closing = (self.CTRL_CLOSE_EVENT, self.CTRL_LOGOFF_EVENT, self.CTRL_SHUTDOWN_EVENT)

        def routine(event: int) -> bool:
            if event in closing:
                _run_waiting(fn)
                return True
            return False            # Ctrl+C and Ctrl+Break stay KeyboardInterrupt

        cb = self._ROUTINE(routine)
        self._handlers.append(cb)   # kept alive for the process's life
        self._k.SetConsoleCtrlHandler(cb, True)

    def set_clipboard(self, text: str) -> bool:
        c, k, u = self._c, self._k, self._u
        data = (text + "\0").encode("utf-16-le")
        if not u.OpenClipboard(None):
            return False
        try:
            u.EmptyClipboard()
            hmem = k.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
            if not hmem:
                return False
            p = k.GlobalLock(hmem)
            if not p:
                k.GlobalFree(hmem)
                return False
            c.memmove(p, data, len(data))
            k.GlobalUnlock(hmem)
            if not u.SetClipboardData(self.CF_UNICODETEXT, hmem):
                k.GlobalFree(hmem)
                return False
            return True
        finally:
            u.CloseClipboard()

    def open_folder(self, path: str) -> bool:
        try:
            os.startfile(path)      # type: ignore[attr-defined]
            return True
        except OSError:
            return False

    def short_path(self, path: str) -> str | None:
        c, k = self._c, self._k
        n = k.GetShortPathNameW(path, None, 0)
        if not n:
            return None
        buf = c.create_unicode_buffer(n)
        if not k.GetShortPathNameW(path, buf, n):
            return None
        return buf.value or None

    def drive_is_remote(self, path: str) -> bool:
        """The folder's drive is a mapped network drive, or the path is a UNC one."""
        p = os.path.abspath(path)
        drive = os.path.splitdrive(p)[0]
        if not drive:
            return False
        if drive.startswith("\\\\") or drive.startswith("//"):
            return True
        return self._k.GetDriveTypeW(drive + "\\") == self.DRIVE_REMOTE

    def enable_vt(self) -> None:
        c, w, k = self._c, self._w, self._k
        h = k.GetStdHandle(self.STD_OUTPUT_HANDLE & 0xFFFFFFFF)
        if self._invalid(h):
            return
        mode = w.DWORD(0)
        if k.GetConsoleMode(h, c.byref(mode)):
            k.SetConsoleMode(h, mode.value | self.ENABLE_VIRTUAL_TERMINAL_PROCESSING)

    def user_name(self) -> str | None:
        return os.environ.get("USERNAME") or None

    def pc_name(self) -> str | None:
        return os.environ.get("COMPUTERNAME") or None

    def home(self) -> str | None:
        h = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        return h if h and h != "~" else None


# ---------------------------------------------------------------------------------------------------------- choice

_lock = threading.Lock()
_current: Backend | None = None


def backend() -> Backend:
    """The Windows backend on Windows, else the portable one."""
    global _current
    with _lock:
        if _current is None:
            _current = WindowsBackend() if sys.platform == "win32" else PortableBackend()
        return _current


@contextmanager
def use(b: Backend) -> Iterator[None]:
    """For tests: replace the backend inside the block."""
    global _current
    with _lock:
        old = _current
        _current = b
    try:
        yield
    finally:
        with _lock:
            _current = old
