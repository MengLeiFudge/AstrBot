param(
    [switch]$ForceRestart,
    [switch]$SkipInstall,
    [int]$ReadyTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = Join-Path $ProjectRoot "data"
$LogRoot = Join-Path $DataRoot "logs"
$StdoutLog = Join-Path $LogRoot "astrbot.stdout.log"
$StderrLog = Join-Path $LogRoot "astrbot.stderr.log"
$RequiredPorts = @(6185, 6200, 8080)
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExtraRequirements = Join-Path $ProjectRoot "deployment\extra-requirements.txt"

$env:ASTRBOT_ROOT = $ProjectRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Get-AstrBotProcesses {
    $escapedRoot = [regex]::Escape([System.IO.Path]::GetFullPath($ProjectRoot))
    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ProcessId -ne $PID -and
                $_.CommandLine -match $escapedRoot -and
                $_.CommandLine -match '(?i)(?:main\.py|scripts\\start\.ps1)'
            }
    )
}

function Stop-AstrBotProcesses {
    $processes = @(Get-AstrBotProcesses)
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-AstrBotProcesses).Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "AstrBot processes did not stop within 15 seconds."
}

function Test-LocalPort {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(500) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-MissingPorts {
    @($RequiredPorts | Where-Object { -not (Test-LocalPort -Port $_) })
}

function Wait-AstrBotReady {
    param([System.Diagnostics.Process]$Process)

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $ReadyTimeoutSeconds))
    do {
        $missing = @(Get-MissingPorts)
        if ($missing.Count -eq 0) {
            Write-Host "AstrBot is ready on ports 6185, 6200, and 8080."
            return
        }
        if ($Process -and $Process.HasExited) {
            throw "AstrBot exited with code $($Process.ExitCode). Logs: $StdoutLog ; $StderrLog"
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "AstrBot readiness timed out; missing ports: $($missing -join ', '). Logs: $StdoutLog ; $StderrLog"
}

if ($ForceRestart) {
    Stop-AstrBotProcesses
}
else {
    $running = @(Get-AstrBotProcesses)
    if ($running.Count -gt 0) {
        $runningIds = (($running | ForEach-Object { $_.ProcessId } | Sort-Object -Unique) -join ", ")
        Write-Host "AstrBot is already running; PIDs: $runningIds. Logs: $StdoutLog ; $StderrLog"
        Write-Host "Waiting for required ports."
        Wait-AstrBotReady
        exit 0
    }
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/ and rerun this script."
}

Set-Location $ProjectRoot
if (-not $SkipInstall) {
    & $uv.Source sync
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path $ExtraRequirements -PathType Leaf)) {
        throw "Plugin dependency manifest is missing: $ExtraRequirements"
    }
    & $uv.Source pip install --python $ProjectPython --requirements $ExtraRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin dependency installation failed with exit code $LASTEXITCODE."
    }
}
elseif (-not (Test-Path $ProjectPython -PathType Leaf)) {
    throw "The project environment is missing. Rerun without -SkipInstall."
}

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$process = Start-Process `
    -FilePath $uv.Source `
    -ArgumentList @("run", "--no-sync", "python", "main.py") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru

Write-Host "Started AstrBot process $($process.Id). Logs: $StdoutLog ; $StderrLog"
Wait-AstrBotReady -Process $process
