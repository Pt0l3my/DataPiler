# DataPiler.ps1 - DataPiler's window (build plan 4.12).
#
# DataPiler.exe starts it with -FromLauncher, in a PowerShell window of its own. By hand, from DataPiler's folder:
#   powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\DataPiler.ps1
# It finds Python 3.10 or newer, makes .venv from requirements.lock once the owner answers Y, and runs datapiler.py
# in this window. It writes only inside DataPiler's folder and changes no setting of the PC. Its one use of the
# network is pip, after Y, for the files requirements.lock names by their sha256.
# ASCII only: Windows PowerShell 5.1 reads a script without a byte-order mark in the PC's code page.

param([switch]$FromLauncher)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

$Root = $PSScriptRoot
$App = Join-Path $Root 'datapiler.py'
$Init = Join-Path $Root 'datapiler\__init__.py'
$Lock = Join-Path $Root 'requirements.lock'
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Marker = Join-Path $Venv 'datapiler-lock.sha256'
$PortFile = Join-Path $Root 'datapiler.port'
$StartLog = Join-Path $Root 'datapiler-start.log'
$MinPython = [version]'3.10'

# ------------------------------------------------------------------------------------------------- helpers

# Console writes go through .NET, so they still work in the finally block after Ctrl+C.
function Write-Line([string]$Text, [ConsoleColor]$Colour = [ConsoleColor]::Gray) {
    $old = [Console]::ForegroundColor
    [Console]::ForegroundColor = $Colour
    [Console]::WriteLine($Text)
    [Console]::ForegroundColor = $old
}

# The window's own mutex (below), let go once this window has nothing more to start.
$WindowMutex = $null
function Release-Window {
    if ($script:WindowMutex) {
        try { $script:WindowMutex.ReleaseMutex() } catch { }
        try { $script:WindowMutex.Dispose() } catch { }
        $script:WindowMutex = $null
    }
}

function Close-Window([int]$Code) {
    Release-Window
    Write-Line 'Press Enter to close.' Yellow
    [void][Console]::ReadLine()
    exit $Code
}

function Get-Version {
    try {
        foreach ($line in [System.IO.File]::ReadAllLines($Init)) {
            if ($line -match '^VERSION\s*=\s*"(\d+\.\d+\.\d+)"') { return $Matches[1] }
        }
    } catch { }
    return 'unknown'
}

# The Python's major and minor version, or $null if it does not run.
function Get-PythonVersion([string]$Exe, [string[]]$Pre) {
    try {
        $out = & $Exe @Pre -c 'import sys; print(sys.version_info[0], sys.version_info[1])' 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    $line = @($out | Where-Object { "$_" -match '^\d+ \d+$' } | Select-Object -First 1)
    if ($line.Count -eq 0) { return $null }
    $parts = ([string]$line[0]).Split(' ')
    return [version]('{0}.{1}' -f $parts[0], $parts[1])
}

# py -3, then python: the first that is 3.10 or newer, else the first found, else $null.
function Find-Python {
    $first = $null
    foreach ($cand in @(@{ Exe = 'py'; Pre = @('-3') }, @{ Exe = 'python'; Pre = @() })) {
        $cmd = Get-Command $cand.Exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $cmd) { continue }
        $version = Get-PythonVersion $cmd.Path ([string[]]$cand.Pre)
        if (-not $version) { continue }
        $found = [pscustomobject]@{ Exe = $cmd.Path; Pre = [string[]]$cand.Pre; Version = $version }
        if ($version -ge $MinPython) { return $found }
        if (-not $first) { $first = $found }
    }
    return $first
}

# requirements.lock's header (datapiler-lock/1) and the sha256 of its bytes.
function Read-Lock {
    $info = [pscustomobject]@{ Ok = $false; Pythons = @(); Mb = ''; Packages = @(); Hash = '' }
    try {
        $lines = [System.IO.File]::ReadAllLines($Lock)
        $info.Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Lock -ErrorAction Stop).Hash.ToLowerInvariant()
    } catch {
        return $info
    }
    if ($lines.Count -eq 0 -or $lines[0].Trim() -ne '# datapiler-lock/1') { return $info }
    foreach ($line in $lines) {
        if (-not $line.StartsWith('#')) { break }
        if ($line -match '^# pythons:\s*(.+)$') {
            $info.Pythons = @($Matches[1].Trim() -split '\s+')
        } elseif ($line -match '^# download-mb:\s*(\d+)\s*$') {
            $info.Mb = $Matches[1]
        } elseif ($line -match '^# ([A-Za-z0-9][A-Za-z0-9._-]*) (\d[A-Za-z0-9.+!-]*) ([A-Za-z0-9.+-]+)\s*$') {
            $info.Packages += [pscustomobject]@{ Name = $Matches[1]; Version = $Matches[2]; Licence = $Matches[3] }
        }
    }
    $info.Ok = ($info.Pythons.Count -gt 0 -and $info.Packages.Count -gt 0 -and $info.Mb -ne '')
    return $info
}

# .venv matches the lock when its marker holds the lock's sha256 and its Python runs.
function Test-Venv([string]$Hash) {
    if (-not $Hash) { return $false }
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { return $false }
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) { return $false }
    try {
        $mark = [System.IO.File]::ReadAllText($Marker).Trim().ToLowerInvariant()
    } catch {
        return $false
    }
    if ($mark -ne $Hash) { return $false }
    return [bool](Get-PythonVersion $VenvPython @())
}

function Read-YesNo([string]$Prompt) {
    while ($true) {
        $answer = Read-Host $Prompt
        if ($null -eq $answer) { return $false }
        $answer = $answer.Trim()
        if ($answer -eq 'Y' -or $answer -eq 'y') { return $true }
        if ($answer -eq 'N' -or $answer -eq 'n') { return $false }
        Write-Line 'Answer Y or N.' Yellow
    }
}

function Write-NoLink {
    Write-Line 'DataPiler starts without the server link: the guided exports and Outputs work, and a dropped job is' Yellow
    Write-Line "checked at once, but jobs and Extract's server rows wait for the libraries, as every job reads from" Yellow
    Write-Line 'Smithbox first. Start DataPiler again and answer Y to set them up.' Yellow
}

function Open-RunningPage {
    try {
        $text = [System.IO.File]::ReadAllText($PortFile).Trim()
        if ($text -match '^\d{1,5}$' -and [int]$text -gt 0 -and [int]$text -lt 65536) {
            Start-Process ('http://127.0.0.1:{0}/' -f [int]$text)
        }
    } catch { }
}

# ------------------------------------------------------------------------------------------------- the window

try {
    $Host.UI.RawUI.WindowTitle = 'DataPiler'
    $Host.UI.RawUI.BackgroundColor = 'Black'
    $Host.UI.RawUI.ForegroundColor = 'Gray'
    Clear-Host
} catch { }

Write-Line ("DataPiler {0} - Elden Ring's data from your own install, through Smithbox" -f (Get-Version)) Green

# ------------------------------------------------------------------------------------------------- one window

# The app's mutex is taken only once datapiler.py runs, after the question, .venv and pip. This window holds its
# own from here until its app has stopped, so a second start meanwhile opens no second window (DataPiler.exe
# waits for the page instead) and .venv is never made twice at once.
$Owned = $false
try {
    $WindowMutex = New-Object System.Threading.Mutex($false, 'Local\DataPiler-window')
    try {
        $Owned = $WindowMutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $Owned = $true
    }
} catch {
    $WindowMutex = $null
    $Owned = $true
}
if (-not $Owned) {
    $WindowMutex.Dispose()
    $WindowMutex = $null
    $AppMutex = $null
    $AppRuns = $false
    try {
        $AppRuns = [System.Threading.Mutex]::TryOpenExisting('Local\DataPiler', [ref]$AppMutex)
        if ($AppMutex) { $AppMutex.Dispose() }
    } catch {
        $AppRuns = $true
    }
    if ($AppRuns) {
        Write-Line 'DataPiler is running already - its page opens' Yellow
        Open-RunningPage
    } else {
        Write-Line 'DataPiler is starting in another window - answer there. This window closes in 5 s.' Yellow
    }
    [System.Threading.Thread]::Sleep(5000)
    exit 3
}

if (-not (Test-Path -LiteralPath $App -PathType Leaf)) {
    Write-Line 'datapiler.py is not next to DataPiler.ps1: unpack the whole DataPiler folder and start it from there.' Red
    Close-Window 1
}

# ------------------------------------------------------------------------------------------------- Python

$Python = Find-Python
if (-not $Python) {
    Write-Line 'No Python found (py -3, then python). DataPiler needs Python 3.10 or newer, from python.org.' Red
    Close-Window 1
}
$PyName = '{0}.{1}' -f $Python.Version.Major, $Python.Version.Minor
if ($Python.Version -lt $MinPython) {
    Write-Line ('This is Python {0}. DataPiler needs Python 3.10 or newer, from python.org.' -f $PyName) Red
    Close-Window 1
}
Write-Line ('Python {0}' -f $PyName)

# ------------------------------------------------------------------------------------------------- .venv

$RunExe = $Python.Exe
$RunPre = $Python.Pre
$NoLink = $false
$LockInfo = Read-Lock

if (Test-Venv $LockInfo.Hash) {
    $RunExe = $VenvPython
    $RunPre = @()
} elseif (-not $LockInfo.Ok) {
    Write-Line 'requirements.lock is missing or is not a datapiler-lock/1 file.' Yellow
    $NoLink = $true
    Write-NoLink
} elseif ($LockInfo.Pythons -notcontains $PyName) {
    Write-Line ('The server link supports Python {0}; this is Python {1}.' -f ($LockInfo.Pythons -join ', '), $PyName) Yellow
    $NoLink = $true
    Write-NoLink
} else {
    if (Test-Path -LiteralPath $Venv) {
        Write-Line 'The .venv in this folder does not match requirements.lock: Y replaces it.' Yellow
    }
    Write-Line "DataPiler's server link needs these libraries, which are not set up yet:"
    foreach ($p in $LockInfo.Packages) {
        $why = ''
        if ($p.Name -eq 'typing-extensions') { $why = ', which grpcio needs' }
        Write-Line ('  {0} {1} ({2}){3}' -f $p.Name, $p.Version, $p.Licence, $why)
    }
    Write-Line ('About {0} MB, from pypi.org over https, into .venv in this folder. pip checks every file against' -f $LockInfo.Mb)
    Write-Line 'its sha256 in requirements.lock, and no later start touches the network.'
    Write-Line '  Y: download and set them up now.'
    Write-Line '  N: start without the server link (asked again at the next start).'
    $ok = $false
    if (Read-YesNo 'Set them up now? [Y/N]') {
        $ok = $true
        if (Test-Path -LiteralPath $Venv) {
            $item = Get-Item -LiteralPath $Venv -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                Write-Line '.venv is a link to another folder, which DataPiler leaves alone: remove it yourself.' Red
                $ok = $false
            } else {
                Write-Line 'Removing the old .venv ...'
                try {
                    Remove-Item -LiteralPath $Venv -Recurse -Force -ErrorAction Stop
                } catch {
                    Write-Line 'The old .venv could not be removed.' Red
                    $ok = $false
                }
            }
        }
        if ($ok) {
            Write-Line 'Making .venv ...'
            $Pre = $Python.Pre
            & $Python.Exe @Pre -m venv $Venv
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
                Write-Line 'The venv could not be made.' Red
                $ok = $false
            }
        }
        if ($ok) {
            Write-Line 'Installing from requirements.lock ...'
            & $VenvPython -m pip install --isolated --disable-pip-version-check --no-input --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r $Lock
            if ($LASTEXITCODE -ne 0) {
                Write-Line 'pip did not finish.' Red
                $ok = $false
            }
        }
        if ($ok) {
            try {
                [System.IO.File]::WriteAllText($Marker, $LockInfo.Hash + "`n", [System.Text.Encoding]::ASCII)
            } catch {
                Write-Line "The venv's marker could not be written." Red
                $ok = $false
            }
        }
    }
    if ($ok) {
        Write-Line 'The libraries are set up.' Green
        $RunExe = $VenvPython
        $RunPre = @()
    } else {
        $NoLink = $true
        Write-NoLink
    }
}

# ------------------------------------------------------------------------------------------------- the app

$Arguments = @()
$Arguments += $RunPre
$Arguments += ('"{0}"' -f $App)
$Arguments += '--console'
if ($FromLauncher) { $Arguments += '--no-browser' }
if ($NoLink) { $Arguments += '--no-link' }

$Info = New-Object System.Diagnostics.ProcessStartInfo
$Info.FileName = $RunExe
$Info.Arguments = $Arguments -join ' '
$Info.UseShellExecute = $false
$Info.WorkingDirectory = $Root

$Started = Get-Date
$Code = 1
$Proc = $null
try {
    $Proc = [System.Diagnostics.Process]::Start($Info)
    $Proc.WaitForExit()
} catch {
    Write-Line 'Python did not start.' Red
} finally {
    # Ctrl+C reaches the app and this script alike: the app stops as Quit does, and this waits for it.
    if ($Proc) {
        $Proc.WaitForExit()
        $Code = $Proc.ExitCode
    }
    Release-Window
    [Console]::WriteLine()
    if ($Code -eq 0) {
        Write-Line 'DataPiler has stopped - this window closes in 5 s' Green
        [System.Threading.Thread]::Sleep(5000)
    } elseif ($Code -eq 3) {
        Write-Line 'DataPiler is running already - its page opens' Yellow
        Open-RunningPage
        [System.Threading.Thread]::Sleep(5000)
    } else {
        Write-Line ('DataPiler stopped with code {0}' -f $Code) Red
        if ((Test-Path -LiteralPath $StartLog -PathType Leaf) -and (Get-Item -LiteralPath $StartLog).LastWriteTime -ge $Started) {
            Write-Line 'datapiler-start.log in this folder says why.' Red
        }
        Write-Line 'Press Enter to close.' Yellow
        [void][Console]::ReadLine()
    }
}
exit $Code
