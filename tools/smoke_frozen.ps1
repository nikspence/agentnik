param(
    [string]$Executable = 'dist\milestone-d\Agentnik\Agentnik.exe',
    [int]$StartupSeconds = 30
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$exePath = (Resolve-Path -LiteralPath (Join-Path $workspace $Executable)).Path
$smokeRoot = Join-Path $workspace ('test-output\frozen-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class AgentnikSmokeWindows {
 public delegate bool Callback(IntPtr h,IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Callback cb,IntPtr p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
}
"@
$testProcess = Start-Process -FilePath $exePath -ArgumentList @('--data-dir', ('"' + $smokeRoot + '"')) -WindowStyle Hidden -PassThru
try {
    $deadline = (Get-Date).AddSeconds($StartupSeconds)
    $script:appHandle = [IntPtr]::Zero
    do {
        Start-Sleep -Milliseconds 200
        $testProcess.Refresh()
        if ($testProcess.HasExited) { throw 'Packaged application exited before initialization' }
        [AgentnikSmokeWindows]::EnumWindows({
            param($handle,$unused)
            $ownerId = [uint32]0
            [AgentnikSmokeWindows]::GetWindowThreadProcessId($handle,[ref]$ownerId) | Out-Null
            if ($ownerId -eq $testProcess.Id) {
                $title = New-Object System.Text.StringBuilder 256
                [AgentnikSmokeWindows]::GetWindowText($handle,$title,256) | Out-Null
                if ($title.ToString() -eq 'Agentnik') { $script:appHandle = $handle }
            }
            return $true
        },[IntPtr]::Zero) | Out-Null
    } while (($script:appHandle -eq [IntPtr]::Zero -or -not (Test-Path -LiteralPath (Join-Path $smokeRoot 'history.sqlite3'))) -and (Get-Date) -lt $deadline)
    if ($script:appHandle -eq [IntPtr]::Zero -or -not (Test-Path -LiteralPath (Join-Path $smokeRoot 'history.sqlite3'))) { throw 'Packaged window/database did not initialize before the deadline' }
    [AgentnikSmokeWindows]::PostMessage($script:appHandle,0x10,[IntPtr]::Zero,[IntPtr]::Zero) | Out-Null
    if (-not $testProcess.WaitForExit(10000)) { throw 'Packaged app did not close gracefully' }
    if ($testProcess.ExitCode -ne 0) { throw "Packaged application exit code: $($testProcess.ExitCode)" }
    Write-Output 'PASS: frozen Qt window, isolated database, and graceful exit code 0'
} finally {
    if (-not $testProcess.HasExited) { $testProcess.Kill(); $testProcess.WaitForExit() }
}
