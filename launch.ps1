# VisionGuard - the double-click launcher.
#
# What `.\dev.ps1 up` already does: frees ports 8001 and 5173, starts the
# engine and the front end in one window, and stops both on Ctrl-C.
#
# What this adds, and the only reasons it exists:
#
#   1. **Closing the window really does stop everything.** dev.ps1 cleans up in
#      a `finally`, which covers Ctrl-C and a normal exit - but Windows does
#      not reliably run it when somebody clicks the X. This puts the launcher
#      in a Win32 job object marked KILL_ON_JOB_CLOSE, and child processes
#      inherit that job. When this window dies, however it dies, the operating
#      system terminates the engine, npm, node and the webcam handle with it.
#      Nothing is left holding a port and nothing is left holding the camera.
#
#   2. **It opens the console when the console is actually ready** - after the
#      engine answers /healthz and the front end is listening. Opening a
#      moment early gives a blank page and looks like a broken start.
#
# Usage (the desktop shortcut passes no arguments):
#
#     .\launch.ps1              webcam - the same thing you run by hand
#     .\launch.ps1 -Clip        the labelled recording instead of the webcam
#     .\launch.ps1 -Mock        fixtures only, no models, no camera
#     .\launch.ps1 -Mobile      the phone app too, on 5174, and the tab opens on it
#     .\launch.ps1 -NoBrowser   start it, do not open a tab
#
# Re-create the desktop shortcut with:  .\tools\install-shortcut.ps1
# and the phone app's, which passes -Mobile:  .\tools\install-shortcut.ps1 -Mobile

[CmdletBinding()]
param(
    [switch]$Clip,
    [switch]$Mock,
    [switch]$Mobile,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiPort = 8001   # dev engine; 8000 is the installed service's
$WebPort = 5173
$MobilePort = 5174

# The tab opens on what was asked for. -Mobile is what the "VisionGuard
# Mobile" icon passes, so there it is the phone app; the console is still up
# on 5173 behind it, one address away.
if ($Mobile) {
    $Title = 'VisionGuard Mobile'
    $Opens = 'phone app'
    $Url = "http://localhost:$MobilePort/"
} else {
    $Title = 'VisionGuard'
    $Opens = 'console'
    $Url = "http://localhost:$WebPort/"
}

$Host.UI.RawUI.WindowTitle = $Title

# ---------------------------------------------------------------------------
# Kill on close
#
# A job object is the only mechanism on Windows that survives the window being
# closed, the process being killed, or a crash - because the kill is done by
# the kernel when the last handle to the job goes, not by any code of ours
# that has to get a chance to run first.
# ---------------------------------------------------------------------------

function Enable-KillOnClose {
    if (-not ('VgJob' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class VgJob
{
    [StructLayout(LayoutKind.Sequential)]
    struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public Int64 PerProcessUserTimeLimit;
        public Int64 PerJobUserTimeLimit;
        public UInt32 LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public UInt32 ActiveProcessLimit;
        public UIntPtr Affinity;
        public UInt32 PriorityClass;
        public UInt32 SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct IO_COUNTERS
    {
        public UInt64 ReadOperationCount;
        public UInt64 WriteOperationCount;
        public UInt64 OtherOperationCount;
        public UInt64 ReadTransferCount;
        public UInt64 WriteTransferCount;
        public UInt64 OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr CreateJobObject(IntPtr attributes, string name);

    [DllImport("kernel32.dll")]
    static extern bool SetInformationJobObject(
        IntPtr job, int infoClass, IntPtr info, uint length);

    [DllImport("kernel32.dll")]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    // Held for the lifetime of the process ON PURPOSE. The kernel kills the
    // job's processes when the LAST handle to it closes, so letting this be
    // collected would kill the engine while it was still wanted.
    static IntPtr _job = IntPtr.Zero;

    const int ExtendedLimitInformation = 9;
    const uint KillOnJobClose = 0x2000;

    /// <summary>Put this process, and everything it starts, in a job that the
    /// kernel empties when this process ends.</summary>
    public static bool Enable()
    {
        _job = CreateJobObject(IntPtr.Zero, null);
        if (_job == IntPtr.Zero) return false;

        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = KillOnJobClose;

        int size = Marshal.SizeOf(info);
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, buffer, false);
            if (!SetInformationJobObject(
                    _job, ExtendedLimitInformation, buffer, (uint)size))
                return false;
        }
        finally { Marshal.FreeHGlobal(buffer); }

        return AssignProcessToJobObject(
            _job, System.Diagnostics.Process.GetCurrentProcess().Handle);
    }
}
'@
    }
    return [VgJob]::Enable()
}

# ---------------------------------------------------------------------------
# Open the browser, but only once there is something to look at
# ---------------------------------------------------------------------------

function Start-BrowserWhenReady {
    Start-Job -Name 'browser' -ScriptBlock {
        param($url, $apiPort)

        <#
            Ask over HTTP, by the same address a browser would use.

            This used to open a raw socket to 127.0.0.1 on each port. The
            engine is there, but Vite binds the IPv6 loopback and nothing
            else:

                TCP  127.0.0.1:8000   LISTENING     <- engine, found
                TCP  [::1]:5173       LISTENING     <- web, never found

            So the check could never pass, and the tab never opened. Nobody
            noticed for a while because the failure is a silent ninety-second
            wait rather than an error.

            A name, not an address, is the fix: `localhost` resolves to
            whichever loopback the server actually took, exactly as it does
            for the person double-clicking the icon.
        #>
        function Test-Answering([string]$uri) {
            try {
                Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 3 | Out-Null
                return $true
            } catch {
                # An HTTP error is still an answer: something is listening and
                # serving. Only a refused connection means "not yet".
                return ($null -ne $_.Exception.Response)
            }
        }

        # Ninety seconds. A cold start builds no models but does load them,
        # and an RTSP camera can take a second or two to hand over its first
        # frame. Past that something is wrong and a browser tab would only
        # hide it behind a connection error.
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            # Listening is not the same as answering. /healthz is the one
            # endpoint that needs no session, so it is what "ready" means.
            if ((Test-Answering "http://127.0.0.1:$apiPort/healthz") -and
                (Test-Answering $url)) {
                Start-Process $url
                return "opened $url"
            }
            Start-Sleep -Milliseconds 500
        }
        return "gave up waiting for $url - no tab was opened"
    } -ArgumentList $Url, $ApiPort | Out-Null
}

# ---------------------------------------------------------------------------

Write-Host ''
Write-Host "  $Title" -ForegroundColor Cyan

if (Enable-KillOnClose) {
    Write-Host '  [ ok ] closing this window will stop the engine and the web server' `
        -ForegroundColor Green
} else {
    # Said out loud rather than assumed. Without the job object the cleanup is
    # only as good as dev.ps1's `finally`, which a hard window close can skip -
    # and the symptom would be a port still held next time, which is a
    # confusing thing to meet with no warning.
    Write-Host '  [warn] could not set up kill-on-close. Use Ctrl-C to stop, not the X.' `
        -ForegroundColor Yellow
    Write-Host '         If a port is still held next time, run: .\dev.ps1 down' `
        -ForegroundColor DarkGray
}

if (-not $NoBrowser) {
    # The address, not just the promise. If the tab never arrives - a browser
    # that refuses to be launched from a background job, a start that takes
    # longer than the deadline - the thing to type is already on screen.
    Write-Host "  [ ok ] $Opens at $Url - a tab opens once the engine answers" `
        -ForegroundColor Green
    Start-BrowserWhenReady
}

# dev.ps1 does the actual work: frees the ports, starts both, streams both
# logs into this one window. Duplicating any of that here would be a second
# copy to keep in step.
# Named, not splatted. `& dev.ps1 @('up','-Mock')` passes "-Mock" as dev.ps1's
# SECOND POSITIONAL argument, which it does not accept - the switch never
# arrives and the whole thing fails on a message that names the switch and not
# the reason. `-Switch:$false` is how PowerShell passes "off" explicitly.
# The project venv is deliberately not built yet (DEV_PLAN.md 1.4 - it is
# blocked on the re-ID handover, which decides the Python version). Without
# this flag dev.ps1 refuses to start at all, which is the whole reason the two
# commands were being run by hand instead. Detected rather than hardcoded, so
# the day the venv exists this uses it and says nothing.
$system = -not (Test-Path (Join-Path $Root '.venv\Scripts\python.exe'))
if ($system) {
    Write-Host '  [ ok ] no project venv yet - using the python on your PATH' `
        -ForegroundColor Green
}

try {
    & (Join-Path $Root 'dev.ps1') up -Clip:$Clip -Mock:$Mock -Mobile:$Mobile `
        -AllowSystemPython:$system
    $code = $LASTEXITCODE
} catch {
    Write-Host ''
    Write-Host "  [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    $code = 1
}

# What the browser job made of it. Nobody was watching while dev.ps1 held the
# console, so it is said here - and on a start that failed, this is the line
# that explains the tab that never appeared.
$browser = Get-Job -Name 'browser' -ErrorAction SilentlyContinue
if ($browser) {
    $said = Receive-Job -Job $browser -ErrorAction SilentlyContinue
    Remove-Job -Job $browser -Force -ErrorAction SilentlyContinue
    if ($said -and $said -notmatch '^opened ') {
        Write-Host "  [warn] browser: $said" -ForegroundColor Yellow
    }
}

# Only when something went wrong. A clean stop should just close, but a
# failure that closes instantly is a failure nobody can read - and this window
# is usually opened by double-clicking an icon, with no shell left behind to
# show what happened.
if ($code -ne 0) {
    Write-Host ''
    Write-Host '  Something above stopped it starting. The error is in the log' `
        -ForegroundColor Yellow
    Write-Host '  above, usually on the last [engine] or [web] line.' `
        -ForegroundColor Yellow
    Write-Host ''
    Read-Host '  Press Enter to close'
}

exit $code
