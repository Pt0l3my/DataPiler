# DataPiler.ps1 - DataPiler's window (build plan 4.12; build plan 0.2 section 4.9).
#
# DataPiler.exe starts it with -FromLauncher, in a PowerShell window of its own. By hand, from DataPiler's folder:
#   powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\DataPiler.ps1
# It finds Python 3.10 or newer, makes .venv from requirements.lock once the owner answers Y, and runs datapiler.py
# in this window. It writes only inside DataPiler's folder and changes no setting of the PC. Its one use of the
# network is pip, after Y, for the files requirements.lock names by their sha256.
# An update (Install and restart on the page): the app exits with code 75, this window runs the helper taken from
# the verified download (update\<to>\update-helper.py) with the Python found here, and on success starts the new
# DataPiler.ps1 in this same window with -AfterUpdate. If the new version stops before its page comes up, or its
# script stops before it starts the app, the window offers R to go back. A swap cut off part way (the helper
# stopped, the window closed, the power cut) is put back from its backup, here or at the next start. Every Y builds
# .venv.new and puts it in place only once pip and the marker succeed.
# ASCII only: Windows PowerShell 5.1 reads a script without a byte-order mark in the PC's code page.

param([switch]$FromLauncher, [switch]$AfterUpdate)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

$Root = $PSScriptRoot
$App = Join-Path $Root 'datapiler.py'
$Init = Join-Path $Root 'datapiler\__init__.py'
$Lock = Join-Path $Root 'requirements.lock'
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Marker = Join-Path $Venv 'datapiler-lock.sha256'
$VenvNew = Join-Path $Root '.venv.new'
$NewPython = Join-Path $VenvNew 'Scripts\python.exe'
$NewMarker = Join-Path $VenvNew 'datapiler-lock.sha256'
$VenvPrev = Join-Path $Root '.venv.prev'
$UpdateDir = Join-Path $Root 'update'
$Pending = Join-Path $UpdateDir 'pending.json'
$Result = Join-Path $UpdateDir 'result.json'
$EXIT_UPDATE = 75
$EXIT_SETTLED = 76      # the new script (-AfterUpdate) reached its app and settled R itself
$BACK_SECS = 90
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
    if ($AfterUpdate -and (Test-Path -LiteralPath $Pending -PathType Leaf)) {
        # Just after an update, before this version's app ran: the script that ran the update offers R.
        exit $Code
    }
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

# A leftover .venv.new or .venv.prev: removed, unless it is a link to another folder, which is never followed.
function Remove-Leftover([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $true }
    $name = Split-Path -Leaf $Path
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            Write-Line ('{0} is a link to another folder, which DataPiler leaves alone: remove it yourself.' -f $name) Red
            return $false
        }
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        return $true
    } catch {
        Write-Line ('{0} could not be removed.' -f $name) Red
        return $false
    }
}

# update\pending.json, written by the app at Install: its from and to versions and its nonce, or $null.
function Read-Pending {
    try {
        $doc = [System.IO.File]::ReadAllText($Pending) | ConvertFrom-Json
        $to = [string]$doc.to
        $from = [string]$doc.from
        $nonce = [string]$doc.nonce
        if ($to -match '^\d+\.\d+\.\d+$' -and $from -match '^\d+\.\d+\.\d+$' -and $nonce -match '^[0-9a-f]{32}$') {
            return [pscustomobject]@{ To = $to; From = $from; Nonce = $nonce }
        }
    } catch { }
    return $null
}

# The swap was cut off part way: update\backup-<from>\backup.json is this update's and not complete, and
# update\result.json does not carry this update's nonce (the helper writes it whenever it finishes, put back or not).
function Test-Unfinished($Upd) {
    if (-not $Upd) { return $false }
    try {
        $doc = [System.IO.File]::ReadAllText((Join-Path $UpdateDir ('backup-{0}\backup.json' -f $Upd.From))) | ConvertFrom-Json
        if ([string]$doc.nonce -ne $Upd.Nonce -or $doc.complete -eq $true) { return $false }
    } catch {
        return $false
    }
    try {
        $res = [System.IO.File]::ReadAllText($Result) | ConvertFrom-Json
        if ([string]$res.nonce -eq $Upd.Nonce) { return $false }
    } catch { }
    return $true
}

# While the helper swaps or puts files back, Ctrl+C is a key like any other in this console, so neither the helper
# nor this window is cut off part way; the keys pressed meanwhile are dropped afterwards.
function Set-CtrlCHeld([bool]$On) {
    try {
        [Console]::TreatControlCAsInput = $On
        if (-not $On) {
            while ([Console]::KeyAvailable) { [void][Console]::ReadKey($true) }
        }
    } catch { }
}

# update\result.json's reason, as the helper wrote it, or $null.
function Read-ResultText {
    try {
        $doc = [System.IO.File]::ReadAllText($Result) | ConvertFrom-Json
        $text = [string]$doc.text
        if ($text -and $text.Length -le 300) { return $text }
    } catch { }
    return $null
}

# R or Enter, from the console's keys.
function Read-RorEnter {
    while ($true) {
        try {
            $k = [Console]::ReadKey($true)
        } catch {
            return ''
        }
        if ($k.Key -eq [ConsoleKey]::R) { return 'R' }
        if ($k.Key -eq [ConsoleKey]::Enter) { return '' }
    }
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
    if (-not $AfterUpdate) { Clear-Host }     # after an update, the helper's lines stay in view
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
if (-not $Owned -and $AfterUpdate) {
    # Started by this window's own script after the swap: that script holds the mutex on this same thread, so the
    # wait above normally succeeds (a mutex is re-entrant for its owner); if it did not, it is still this window's.
    try { $WindowMutex.Dispose() } catch { }
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

# An environment left half-made, or kept from before an update whose new version has since come up: removed. After
# an update (-AfterUpdate), .venv.prev stays until the new version's page has come up, so R can put it back.
if (-not $AfterUpdate) {
    [void](Remove-Leftover $VenvNew)
    [void](Remove-Leftover $VenvPrev)
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

# ------------------------------------------------------------------------------------------------- a swap cut off

# An update whose swap was cut off (the window closed, the power cut): its files are put back before anything starts.
if (-not $AfterUpdate) {
    $Upd = Read-Pending
    if (Test-Unfinished $Upd) {
        Write-Line ('The update to {0} did not finish - the files of {1} are put back from update\backup-{1}\.' -f $Upd.To, $Upd.From) Yellow
        $HelperPath = Join-Path $UpdateDir ('{0}\update-helper.py' -f $Upd.To)
        $Pre = $Python.Pre
        Set-CtrlCHeld $true
        & $Python.Exe @Pre $HelperPath --rollback (Join-Path $UpdateDir ('backup-{0}' -f $Upd.From))
        $Undone = $LASTEXITCODE
        Set-CtrlCHeld $false
        if ($Undone -ne 0) {
            Write-Line ('Putting the files back did not complete - logs\update.log has why, and the copies are in update\backup-{0}\.' -f $Upd.From) Red
            Close-Window 1
        }
    }
}

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
    if ($AfterUpdate) {
        Write-Line 'The Python libraries changed with the update.' Yellow
    } elseif (Test-Path -LiteralPath $Venv) {
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
        # Built as .venv.new beside the old one, which stays until pip and the marker have succeeded.
        $ok = $true
        if (Test-Path -LiteralPath $Venv) {
            $item = Get-Item -LiteralPath $Venv -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                Write-Line '.venv is a link to another folder, which DataPiler leaves alone: remove it yourself.' Red
                $ok = $false
            }
        }
        if ($ok) { $ok = Remove-Leftover $VenvNew }
        if ($ok) {
            Write-Line 'Making .venv.new ...'
            $Pre = $Python.Pre
            & $Python.Exe @Pre -m venv $VenvNew
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $NewPython -PathType Leaf)) {
                Write-Line 'The venv could not be made.' Red
                $ok = $false
            }
        }
        if ($ok) {
            Write-Line 'Installing from requirements.lock ...'
            & $NewPython -m pip install --isolated --disable-pip-version-check --no-input --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r $Lock
            if ($LASTEXITCODE -ne 0) {
                Write-Line 'pip did not finish.' Red
                $ok = $false
            }
        }
        if ($ok) {
            try {
                [System.IO.File]::WriteAllText($NewMarker, $LockInfo.Hash + "`n", [System.Text.Encoding]::ASCII)
            } catch {
                Write-Line "The venv's marker could not be written." Red
                $ok = $false
            }
        }
        if ($ok) {
            # The swap: .venv to .venv.prev, .venv.new to .venv; the old one put back if the second rename fails.
            $hadOld = Test-Path -LiteralPath $Venv
            if ($hadOld) { $ok = Remove-Leftover $VenvPrev }
            if ($ok) {
                try {
                    if ($hadOld) { Rename-Item -LiteralPath $Venv -NewName '.venv.prev' -ErrorAction Stop }
                    Rename-Item -LiteralPath $VenvNew -NewName '.venv' -ErrorAction Stop
                } catch {
                    Write-Line 'The new .venv could not be put in place.' Red
                    if ($hadOld -and -not (Test-Path -LiteralPath $Venv) -and (Test-Path -LiteralPath $VenvPrev)) {
                        try { Rename-Item -LiteralPath $VenvPrev -NewName '.venv' -ErrorAction Stop } catch { }
                    }
                    $ok = $false
                }
            }
        }
        if ($ok) {
            if ($AfterUpdate) {
                Write-Line 'environment made (.venv); the old one is kept until the new version is up' Green
            } elseif ($hadOld) {
                [void](Remove-Leftover $VenvPrev)
                Write-Line 'environment made (.venv); the old one removed' Green
            } else {
                Write-Line 'environment made (.venv)' Green
            }
        } else {
            [void](Remove-Leftover $VenvNew)
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
$Handed = $false
$Answered = $false
$NewStopped = $false
$Settled = $false
try {
    while ($true) {
        $Started = Get-Date
        $Code = 1
        $Proc = $null
        try {
            $Proc = [System.Diagnostics.Process]::Start($Info)
            $Proc.WaitForExit()
            $Code = $Proc.ExitCode
        } catch {
            Write-Line 'Python did not start.' Red
        }
        if ($Code -ne $EXIT_UPDATE) { break }
        # Exit code 75: Install and restart. The helper from the verified download, with the Python found above
        # (never the venv's, which the update may replace).
        $Proc = $null
        $Upd = Read-Pending
        if (-not $Upd) {
            Write-Line 'DataPiler stopped to update, but update\pending.json could not be read - it starts again.' Yellow
            continue
        }
        Write-Line ('DataPiler stopped to update to {0}.' -f $Upd.To)
        $HelperPath = Join-Path $UpdateDir ('{0}\update-helper.py' -f $Upd.To)
        $Pre = $Python.Pre
        Set-CtrlCHeld $true
        & $Python.Exe @Pre $HelperPath --pending $Pending
        $Helped = $LASTEXITCODE
        Set-CtrlCHeld $false
        if ($Helped -eq 0) {
            # The new DataPiler.ps1, in this window; this one was read whole before it ran, so its replacement on
            # disk changed nothing here. The window's mutex stays held: the new script takes it again.
            Write-Line ('Starting DataPiler {0}...' -f $Upd.To) Green
            $Started = Get-Date
            try {
                & "$PSScriptRoot\DataPiler.ps1" -AfterUpdate
                $Code = $LASTEXITCODE
            } catch {
                Write-Line ("DataPiler {0}'s DataPiler.ps1 could not run." -f $Upd.To) Red
                $Code = 1
            }
            $Handed = $true
            # The new script stopped before its app ran, or could not run at all: R is offered below, from here.
            $NewStopped = ($Code -ne 0 -and $Code -ne 3 -and $Code -ne $EXIT_SETTLED)
            break
        }
        if (Test-Unfinished $Upd) {
            # The helper stopped part way, without its own putting back: the backup puts the old files back.
            Write-Line ('The update to {0} stopped part way - the files of {1} are put back.' -f $Upd.To, $Upd.From) Yellow
            Set-CtrlCHeld $true
            & $Python.Exe @Pre $HelperPath --rollback (Join-Path $UpdateDir ('backup-{0}' -f $Upd.From))
            $Undone = $LASTEXITCODE
            Set-CtrlCHeld $false
            if ($Undone -ne 0) {
                Write-Line ('Putting the files back did not complete - logs\update.log has why, and the copies are in update\backup-{0}\.' -f $Upd.From) Red
                $Code = 1
                break
            }
        }
        $Why = Read-ResultText
        if ($Why) {
            Write-Line ('The update did not complete: {0}' -f $Why) Red
        } else {
            Write-Line 'The update did not complete - logs\update.log has why.' Red
        }
        Write-Line ('DataPiler {0} starts again.' -f (Get-Version)) Yellow
    }
} finally {
    # Ctrl+C reaches the app and this script alike: the app stops as Quit does, and this waits for it.
    if ($Proc -and -not $Handed) {
        $Proc.WaitForExit()
        $Code = $Proc.ExitCode
    }
    $Upd = $null
    if ($AfterUpdate -and -not $Handed) {
        # The new version stopped before its page came up (pending.json is removed once it is up): R goes back.
        # Whatever happens here, the script that started this one asks nothing more (exit code 76).
        $Settled = $true
        $Ran = ((Get-Date) - $Started).TotalSeconds
        if ($Code -ne 0 -and $Code -ne 3 -and $Ran -lt $BACK_SECS -and (Test-Path -LiteralPath $Pending -PathType Leaf)) {
            $Upd = Read-Pending
        } elseif (-not (Test-Path -LiteralPath $Pending)) {
            # Its page came up: the environment from before the update is no longer needed.
            [void](Remove-Leftover $VenvPrev)
        }
    } elseif ($NewStopped -and (Test-Path -LiteralPath $Pending -PathType Leaf)) {
        # The new version's script stopped before it started its app, or could not run: R is offered from here.
        $Upd = Read-Pending
    }
    if ($Upd) {
        [Console]::WriteLine()
        Write-Line ('DataPiler {0} stopped before its page came up (exit code {1}) - datapiler-start.log has why.' -f $Upd.To, $Code) Red
        Write-Line ('Press R to go back to {0}, or Enter to close this window.' -f $Upd.From) Yellow
        $Back = $false
        if ((Read-RorEnter) -eq 'R') {
            $HelperPath = Join-Path $UpdateDir ('{0}\update-helper.py' -f $Upd.To)
            $Pre = $Python.Pre
            Set-CtrlCHeld $true
            & $Python.Exe @Pre $HelperPath --rollback (Join-Path $UpdateDir ('backup-{0}' -f $Upd.From))
            $Undone = $LASTEXITCODE
            Set-CtrlCHeld $false
            if ($Undone -eq 0) {
                if (Test-Path -LiteralPath $VenvPrev) {
                    if (Remove-Leftover $Venv) {
                        try { Rename-Item -LiteralPath $VenvPrev -NewName '.venv' -ErrorAction Stop } catch { }
                    }
                }
                Write-Line ('Back on {0} - it starts now.' -f $Upd.From) Green
                & "$PSScriptRoot\DataPiler.ps1"
                $Code = $LASTEXITCODE
                $Back = $true
            } else {
                Write-Line 'Going back did not complete - logs\update.log has why.' Red
                Write-Line 'Press Enter to close.' Yellow
                [void][Console]::ReadLine()
            }
        }
        $Handed = $Handed -or $Back
        $Answered = -not $Handed
    }
    Release-Window
    [Console]::WriteLine()
    if ($Handed -or $Answered) {
        # the new script, or the old one after R, has said its own last words; or the owner pressed Enter at R
    } elseif ($Code -eq 0) {
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
if ($Settled) { $Code = $EXIT_SETTLED }
exit $Code
