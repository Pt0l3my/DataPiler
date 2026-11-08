# Building DataPiler.exe

`DataPiler.exe` is a small C++ launcher, adapted from LLM Jobrunner's (see the README). If a DataPiler is running
already, or its window is still starting (asking its setup question, making `.venv`), it waits up to 60 s for that
one's page and opens it, and starts nothing. Otherwise it starts `DataPiler.ps1` in a visible PowerShell window
(PowerShell 7 from a folder on PATH, else Windows PowerShell 5.1 from the system folder: never a `pwsh.exe` lying in
its own folder or the current one), waits for the port file the app writes once its page is up (never one older than
this start) for as long as that window is open, as a first start may wait for the owner's answer and a download, and
opens the browser there. It asks for no elevation (`asInvoker`), probes no socket and embeds no Python. Its source is
`launcher-src/launcher.cpp`, with `app.rc` (its name and version) and `app.manifest`; 0.1 has no icon.

Two routes give the same exe: a local build with MinGW-w64, and the release workflow on GitHub.

## A local build

You need MinGW-w64 (`x86_64-w64-mingw32-g++` and `x86_64-w64-mingw32-windres`): `sudo apt-get install mingw-w64` on
Linux, or MSYS2's `mingw-w64-x86_64-gcc` on Windows (in its MINGW64 shell the same tools are `g++` and `windres`).
`app.rc` names `app.manifest` by its bare file name, so build in a folder holding the three inputs. From the
repository's root (`build/` is ignored by git):

```
mkdir -p build && cp launcher-src/launcher.cpp launcher-src/app.rc launcher-src/app.manifest build/ && cd build
x86_64-w64-mingw32-windres app.rc -O coff -o app.res
x86_64-w64-mingw32-g++ -std=c++17 -O2 -municode -mwindows -static -s -Wl,--no-insert-timestamp launcher.cpp app.res -o DataPiler.exe -lshell32 -lole32
```

These are Jobrunner's commands and flags, with DataPiler's file names and one more flag:
`-Wl,--no-insert-timestamp` leaves the PE header's time stamp at zero, so two builds with the same compiler give the
same bytes.

Then check it:

- `file DataPiler.exe` must say **PE32+ executable (GUI) x86-64**.
- `strings -a -el DataPiler.exe | grep 0.1.0.0` finds its version, which is `VERSION` in `datapiler/__init__.py`.
- `x86_64-w64-mingw32-objdump -p DataPiler.exe | grep "DLL Name"` lists only `KERNEL32.dll`, `msvcrt.dll`,
  `SHELL32.dll` and `USER32.dll`: no socket library.

Put `DataPiler.exe` in DataPiler's folder, beside `DataPiler.ps1`.

## The release workflow

`.github/workflows/release.yml` runs only when the owner pushes a version tag (`v0.1.0` for 0.1.0). On
`windows-latest`, with MSYS2's MinGW-w64, it builds the exe from `launcher-src/` with the commands above, checks that
the tag names `VERSION`, and prints the compiler's versions and the exe's sha256. The exe is linked `-static`, so
parts of the MinGW-w64 runtime are inside it; the workflow copies their licence files from the toolchain into
`THIRD-PARTY-NOTICES.txt` (NOTICE, section 4). A second job attaches `DataPiler.exe`, `DataPiler.exe.sha256` and
`THIRD-PARTY-NOTICES.txt` to a **draft** release for that tag; publishing it stays the owner's act. Anyone can read
the workflow's log and see the exe was made from the source at that tag.

## Comparing a release's exe with your own build

1. Download `DataPiler.exe` and `DataPiler.exe.sha256` from the release, and check the file against its hash
   (`sha256sum -c DataPiler.exe.sha256`, or `Get-FileHash DataPiler.exe` in PowerShell, which prints it in capitals).
2. Build at the same tag with the gcc and binutils versions the workflow's log names (MSYS2's
   `mingw-w64-x86_64-gcc` and `mingw-w64-x86_64-binutils`), and compare the two sha256s: they match.

Another compiler version, such as Linux's MinGW-w64, gives an exe that works the same but differs in its bytes.

The exe is unsigned, so Windows' SmartScreen may warn on its first start: More info, then Run anyway.
