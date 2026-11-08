// ================================================================
//  DataPiler.exe - native launcher (its version is in app.rc)
//  Adapted from LLM Jobrunner 1.2's launcher, the owner's own code, under DataPiler's
//  MIT licence (DP7). A running DataPiler holds the mutex Local\DataPiler, and a
//  DataPiler.ps1 window holds Local\DataPiler-window from its first line: then this
//  opens that one's page (or waits for it) and leaves, and no second window opens.
//  Otherwise it starts DataPiler.ps1 beside it in a visible PowerShell window, waits
//  for the port file the app writes once its page is up, and opens the browser there.
//  No elevation (asInvoker), no socket probing, no Python embedded.
// ================================================================
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <string>
#include <cstdio>
#include <cstdlib>
#include <cwctype>

static const wchar_t* TITLE = L"DataPiler";
static const wchar_t* MUTEX = L"Local\\DataPiler";       // held by the running app (datapiler.py)
static const wchar_t* WINDOW_MUTEX = L"Local\\DataPiler-window";   // held by a DataPiler.ps1 window
static const ULONGLONG WAIT_MS = 60 * 1000;              // 60 s: for a page another start brings up

static std::wstring ExeDir() {
    wchar_t p[MAX_PATH]; GetModuleFileNameW(NULL, p, MAX_PATH);
    std::wstring s(p);
    size_t k = s.find_last_of(L"\\/");
    return (k == std::wstring::npos) ? s : s.substr(0, k);
}

static bool IsAbsolute(const std::wstring& p) {
    bool sep0 = p.size() >= 1 && (p[0] == L'\\' || p[0] == L'/');
    bool sep1 = p.size() >= 2 && (p[1] == L'\\' || p[1] == L'/');
    bool drive = p.size() >= 3 && iswalpha(p[0]) && p[1] == L':' && (p[2] == L'\\' || p[2] == L'/');
    return drive || (sep0 && sep1);
}

// The folder's full path, lower case, without a trailing separator: for comparing two folders.
static std::wstring FolderKey(const std::wstring& dir) {
    wchar_t buf[MAX_PATH];
    DWORD n = GetFullPathNameW(dir.c_str(), MAX_PATH, buf, NULL);
    std::wstring s = (n && n < MAX_PATH) ? std::wstring(buf) : dir;
    while (s.size() > 3 && (s.back() == L'\\' || s.back() == L'/')) s.pop_back();
    for (auto& c : s) c = (wchar_t)towlower(c);
    return s;
}

static bool IsFile(const std::wstring& p) {
    DWORD a = GetFileAttributesW(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

// name in one of PATH's own folders. Not SearchPathW(NULL, ...), which tries the exe's own folder
// and the current folder before PATH: a pwsh.exe lying beside DataPiler.exe (an unpacked download)
// would run instead. Empty and relative entries are skipped, and so are those two folders.
static bool FindOnPath(const wchar_t* name, std::wstring& out) {
    DWORD n = GetEnvironmentVariableW(L"PATH", NULL, 0);
    if (!n) return false;
    std::wstring path(n, L'\0');
    n = GetEnvironmentVariableW(L"PATH", &path[0], n);
    if (!n || n >= path.size()) return false;
    path.resize(n);
    std::wstring exeKey = FolderKey(ExeDir());
    wchar_t cwd[MAX_PATH];
    DWORD c = GetCurrentDirectoryW(MAX_PATH, cwd);
    std::wstring cwdKey = (c && c < MAX_PATH) ? FolderKey(cwd) : std::wstring();
    size_t start = 0;
    while (start <= path.size()) {
        size_t end = path.find(L';', start);
        if (end == std::wstring::npos) end = path.size();
        std::wstring dir = path.substr(start, end - start);
        start = end + 1;
        if (dir.size() >= 2 && dir.front() == L'"' && dir.back() == L'"') dir = dir.substr(1, dir.size() - 2);
        if (dir.empty() || !IsAbsolute(dir)) continue;
        std::wstring key = FolderKey(dir);
        if (key == exeKey || (!cwdKey.empty() && key == cwdKey)) continue;
        std::wstring cand = dir;
        if (cand.back() != L'\\' && cand.back() != L'/') cand += L'\\';
        cand += name;
        if (IsFile(cand)) { out = cand; return true; }
    }
    return false;
}

// Windows PowerShell 5.1 where Windows keeps it, under the system folder: never found by a search.
static bool SystemPowerShell(const wchar_t* name, std::wstring& out) {
    wchar_t sys[MAX_PATH];
    UINT n = GetSystemDirectoryW(sys, MAX_PATH);
    if (!n || n >= MAX_PATH) return false;
    std::wstring p = std::wstring(sys) + L"\\WindowsPowerShell\\v1.0\\" + name;
    if (!IsFile(p)) return false;
    out = p;
    return true;
}

static ULONGLONG Ticks(const FILETIME& ft) {
    return ((ULONGLONG)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
}

// The port the tool wrote, if the file was written since this start began (2 s of slack for the
// file system's clock): a file left by an earlier run that was killed is never trusted.
static int FreshPort(const std::wstring& path, ULONGLONG since) {
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &a)) return 0;
    if (Ticks(a.ftLastWriteTime) + 20000000ULL < since) return 0;
    FILE* f = _wfopen(path.c_str(), L"rb");
    if (!f) return 0;
    char buf[16]; ZeroMemory(buf, sizeof(buf));
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    if (!n) return 0;
    int port = atoi(buf);
    return (port > 0 && port < 65536) ? port : 0;
}

static bool Held(const wchar_t* name) {
    HANDLE m = OpenMutexW(SYNCHRONIZE, FALSE, name);
    if (m) { CloseHandle(m); return true; }
    return GetLastError() == ERROR_ACCESS_DENIED;          // it exists, under rights we lack
}

// Is a DataPiler running? Its app holds the named mutex for as long as it runs.
static bool Running() { return Held(MUTEX); }

// Is a DataPiler.ps1 window open? It holds its mutex from its first line until its app has
// stopped: also while it asks its setup question, makes .venv or runs pip, before the app's mutex.
static bool Starting() { return Held(WINDOW_MUTEX); }

static void OpenPage(int port) {
    wchar_t url[64];
    wsprintfW(url, L"http://127.0.0.1:%d/", port);
    ShellExecuteW(NULL, L"open", url, NULL, NULL, SW_SHOWNORMAL);
}

// Waits for the port file. since == 0: any file will do (the running app removed an old one at
// its start). window: the PowerShell window started here, or NULL; *closed is set if it ends
// before the port file appears. With a window there is no time limit while it is open: a first
// start asks the owner a question there and may download the libraries, which no bound fits, and
// the window itself says what it is doing. Without one, up to 60 s.
static int WaitPort(const std::wstring& pf, ULONGLONG since, HANDLE window, bool* closed) {
    ULONGLONG t0 = GetTickCount64();
    for (int i = 0; ; i++) {
        int port = FreshPort(pf, since);
        if (port) return port;
        if (window && WaitForSingleObject(window, 0) == WAIT_OBJECT_0) {
            port = FreshPort(pf, since);
            if (!port && closed) *closed = true;
            return port;
        }
        if (!window && GetTickCount64() - t0 >= WAIT_MS) return 0;
        Sleep(i < 12 ? 200 : 400);
    }
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    std::wstring dir = ExeDir();
    std::wstring pf = dir + L"\\datapiler.port";

    // Held: DataPiler is running already. Open its page; start nothing.
    if (Running()) {
        int port = WaitPort(pf, 0, NULL, NULL);
        if (port) { OpenPage(port); return 0; }
        MessageBoxW(NULL, L"DataPiler is running, but its page did not come up within 60 seconds.\n"
                          L"Its window says why.", TITLE, MB_ICONWARNING);
        return 1;
    }

    // A DataPiler window is open but its app is not up yet (its setup question, .venv, pip):
    // start nothing, so .venv is never made twice at once; open its page once it comes up.
    if (Starting()) {
        FILETIME now0; GetSystemTimeAsFileTime(&now0);
        int port = WaitPort(pf, Ticks(now0), NULL, NULL);
        if (port) { OpenPage(port); return 0; }
        MessageBoxW(NULL, L"DataPiler is starting in its window, which may be waiting for your answer.\n"
                          L"Its page opens once it is up.", TITLE, MB_ICONINFORMATION);
        return 0;
    }

    // Not held: start DataPiler.ps1 in its own, visible PowerShell window.
    std::wstring script = dir + L"\\DataPiler.ps1";
    if (GetFileAttributesW(script.c_str()) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"DataPiler.ps1 is not next to DataPiler.exe.\n"
                          L"Unpack the whole DataPiler folder and start DataPiler.exe from there.",
                    TITLE, MB_ICONERROR);
        return 1;
    }
    std::wstring ps;
    // PowerShell 7 if it is on PATH, else Windows PowerShell 5.1 from the system folder.
    if (!FindOnPath(L"pwsh.exe", ps) && !SystemPowerShell(L"powershell.exe", ps)) {
        MessageBoxW(NULL, L"No PowerShell found: no pwsh.exe on PATH, and no Windows PowerShell in the\n"
                          L"system folder. DataPiler needs Windows PowerShell 5.1 or PowerShell 7.",
                    TITLE, MB_ICONERROR);
        return 1;
    }
    FILETIME now; GetSystemTimeAsFileTime(&now);
    ULONGLONG t0 = Ticks(now);
    // -ExecutionPolicy Bypass applies to this one process only; nothing is changed on the PC.
    std::wstring cmd = L"\"" + ps + L"\" -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"" + script +
                       L"\" -FromLauncher";
    STARTUPINFOW si; ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    PROCESS_INFORMATION pi; ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, &cmd[0], NULL, NULL, FALSE, CREATE_NEW_CONSOLE, NULL, dir.c_str(), &si, &pi)) {
        MessageBoxW(NULL, L"PowerShell did not start.", TITLE, MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    bool closed = false;
    int port = WaitPort(pf, t0, pi.hProcess, &closed);
    CloseHandle(pi.hProcess);
    if (port) { OpenPage(port); return 0; }
    // The window ended first while another DataPiler holds the mutex (two starts at once): the
    // window has opened that one's page, or says the other window is starting.
    if (closed && (Running() || Starting())) return 0;
    // WaitPort returns without a port only once the window has closed: never while it still works.
    MessageBoxW(NULL, L"DataPiler's window closed before its page came up.\n"
                      L"If it did not say why, datapiler-start.log in DataPiler's folder may.",
                TITLE, MB_ICONWARNING);
    return 1;
}
