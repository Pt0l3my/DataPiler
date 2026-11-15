"""The PC's hardware, and how much of it DataPiler's image steps use (DP29 (b), settled S83).

`scan` reads, once a minute at most, what the image steps need: the logical and physical cores, the memory in all and
free, and, for the Status page alone, the processor's and the graphics cards' names. On Windows it reads them through
ctypes (explicit argtypes, as winapi.py does) and the registry; elsewhere it gives what the standard library knows, so
every test runs on Linux too. Nothing here is ever logged but counts, nor written to a share file: the names stay on the
Status page, on the PC.

`plan` turns the scan and the two Settings caps into what a step may use: worker processes (by default every logical
core but one, so the PC stays responsive) and memory for decoded tiles (by default a quarter of the free memory). The
graphics card is shown, never used (DP29: copying small images to it costs about what it saves)."""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

AUTO = 0                        # a Settings cap of 0: DataPiler chooses
MEMORY_SHARE = 4                # automatic: a quarter of the free memory
MEMORY_MIN = 256 * 2 ** 20      # never less than this for decoded tiles
MEMORY_MAX_AUTO = 8 * 2 ** 30   # automatic: never more than this
MAX_CORES = 256
RESCAN = 60.0                   # seconds a scan is reused


@dataclass(frozen=True)
class Hardware:
    logical: int                # logical processors (os.cpu_count)
    physical: int | None        # cores, when the system says
    memory: int | None          # bytes in all
    free: int | None            # bytes free when scanned
    cpu: str | None             # the processor's name, for the Status page only
    graphics: tuple[str, ...]   # the graphics cards' names, for the Status page only

    def public(self) -> dict:
        return {"logical": self.logical, "physical": self.physical, "memory": self.memory, "free": self.free,
                "cpu": self.cpu, "graphics": list(self.graphics)}


@dataclass(frozen=True)
class Work:
    workers: int                # worker processes an image step may run
    memory: int                 # bytes of decoded tiles kept, in all workers together
    auto_workers: bool
    auto_memory: bool

    def public(self) -> dict:
        return {"workers": self.workers, "memory": self.memory, "auto_workers": self.auto_workers,
                "auto_memory": self.auto_memory}


def plan(hw: Hardware, cores: int = AUTO, memory_mb: int = AUTO) -> Work:
    """S83: what an image step may use. cores: the Settings cap (0: every logical core but one); memory_mb: likewise
    (0: a quarter of the free memory, within MEMORY_MIN and MEMORY_MAX_AUTO)."""
    logical = max(1, hw.logical)
    workers = max(1, logical - 1) if cores == AUTO else max(1, min(cores, logical))
    if memory_mb == AUTO:
        free = hw.free if hw.free else MEMORY_MIN * MEMORY_SHARE
        memory = min(MEMORY_MAX_AUTO, max(MEMORY_MIN, free // MEMORY_SHARE))
    else:
        memory = memory_mb * 2 ** 20
    return Work(workers, memory, cores == AUTO, memory_mb == AUTO)


# ------------------------------------------------------------------------------------------------ reading it

def _windows() -> Hardware:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]

    memory = free = None
    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    k32.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(MEMORYSTATUSEX),)
    k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    if k32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        memory, free = int(ms.ullTotalPhys), int(ms.ullAvailPhys)

    physical = None
    try:
        size = wintypes.DWORD(0)
        f = k32.GetLogicalProcessorInformation
        f.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
        f.restype = wintypes.BOOL
        f(None, ctypes.byref(size))
        if 0 < size.value <= 1 << 20:
            buf = ctypes.create_string_buffer(size.value)
            if f(buf, ctypes.byref(size)):
                step = 32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24
                raw = buf.raw[:size.value]
                at = 8 if step == 32 else 4
                physical = sum(1 for k in range(0, len(raw) - step + 1, step)
                               if int.from_bytes(raw[k + at:k + at + 4], "little") == 0) or None
    except (OSError, AttributeError):
        physical = None

    cpu = None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            v, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            cpu = " ".join(str(v).split()) or None
    except OSError:
        cpu = None

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    graphics: list[str] = []
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        e = u32.EnumDisplayDevicesW
        e.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD)
        e.restype = wintypes.BOOL
        for i in range(32):
            dd = DISPLAY_DEVICEW()
            dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if not e(None, i, ctypes.byref(dd), 0):
                break
            name = " ".join(dd.DeviceString.split())
            if name and not dd.StateFlags & 0x8 and name not in graphics:      # 0x8: a mirroring driver
                graphics.append(name)
    except (OSError, AttributeError):
        graphics = []
    return Hardware(os.cpu_count() or 1, physical, memory, free, cpu, tuple(graphics))


def _portable() -> Hardware:
    memory = free = None
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        memory = os.sysconf("SC_PHYS_PAGES") * page
        free = os.sysconf("SC_AVPHYS_PAGES") * page
    except (AttributeError, ValueError, OSError):
        pass
    cpu = None
    physical = None
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            cores = set()
            for line in f:
                k, _, v = line.partition(":")
                k = k.strip()
                if k == "model name" and cpu is None:
                    cpu = " ".join(v.split()) or None
                elif k == "core id":
                    cores.add(v.strip())
            physical = len(cores) or None
    except OSError:
        pass
    return Hardware(os.cpu_count() or 1, physical, memory, free, cpu, ())


_lock = threading.Lock()
_last: tuple[float, Hardware] | None = None


def scan(*, fresh: bool = False) -> Hardware:
    """The PC's hardware, read again after RESCAN seconds (or when fresh). Never raises: what cannot be read is None."""
    global _last
    with _lock:
        now = time.monotonic()
        if not fresh and _last is not None and now - _last[0] < RESCAN:
            return _last[1]
        try:
            hw = _windows() if sys.platform == "win32" else _portable()
        except Exception:
            hw = Hardware(os.cpu_count() or 1, None, None, None, None, ())
        _last = (now, hw)
        return hw
