param(
    [switch]$ForceRestart,
    [switch]$SkipInstall,
    [int]$ReadyTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = Join-Path $ProjectRoot "data"
$LogRoot = Join-Path $DataRoot "logs"
$StdoutLog = Join-Path $LogRoot "astrbot.stdout.log"
$StderrLog = Join-Path $LogRoot "astrbot.stderr.log"
function Get-DeclaredPorts {
    # Ports are read from the running configs; account and plugin port constants stay single-sourced.
    $ports = New-Object 'System.Collections.Generic.List[int]'
    $cmdConfigPath = Join-Path $DataRoot "cmd_config.json"
    if (Test-Path -LiteralPath $cmdConfigPath) {
        $cmdConfig = Get-Content -LiteralPath $cmdConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int]$cmdConfig.dashboard.port -gt 0) {
            $ports.Add([int]$cmdConfig.dashboard.port)
        }
        foreach ($platform in @($cmdConfig.platform)) {
            if ([int]$platform.ws_reverse_port -gt 0) {
                $ports.Add([int]$platform.ws_reverse_port)
            }
        }
    }
    $dspConfigPath = Join-Path $DataRoot "config\astrbot_plugin_dsp_knowledge_config.json"
    if (Test-Path -LiteralPath $dspConfigPath) {
        $dspConfig = Get-Content -LiteralPath $dspConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($key in @('api_port', 'port', 'http_port')) {
            if ($dspConfig.PSObject.Properties.Name -contains $key -and [int]$dspConfig.$key -gt 0) {
                $ports.Add([int]$dspConfig.$key)
            }
        }
    }
    $artifactSource = Join-Path $DataRoot "plugins\astrbot_plugin_local_artifact_api\main.py"
    if (Test-Path -LiteralPath $artifactSource) {
        $match = [regex]::Match((Get-Content -LiteralPath $artifactSource -Raw), '(?m)^PORT\s*=\s*(\d+)')
        if ($match.Success) {
            $ports.Add([int]$match.Groups[1].Value)
        }
    }
    return @($ports | Sort-Object -Unique)
}

$RequiredPorts = @(Get-DeclaredPorts)
if ($RequiredPorts.Count -eq 0) {
    throw "AstrBot declared ports are missing from its configs; readiness cannot be verified."
}
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExtraRequirements = Join-Path $ProjectRoot "deployment\extra-requirements.txt"

$env:ASTRBOT_ROOT = $ProjectRoot
$env:QQBOT_ASTRBOT_ACCOUNT = "1443944862"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Get-AstrBotProcesses {
    $escapedRoot = [regex]::Escape([System.IO.Path]::GetFullPath($ProjectRoot))
    @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'cmd.exe' OR Name = 'powershell.exe'" -OperationTimeoutSec 5 |
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
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
            $stop = Start-Process -FilePath (Join-Path $env:SystemRoot "System32\taskkill.exe") `
                -ArgumentList @("/PID", $process.ProcessId, "/T", "/F") -WindowStyle Hidden -PassThru
            [void]$stop.Handle
            try {
                if (-not $stop.WaitForExit(10000)) {
                    $stop.Kill()
                    throw "Timed out stopping AstrBot process $($process.ProcessId)."
                }
                if ($stop.ExitCode -ne 0 -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
                    throw "Failed to stop AstrBot process $($process.ProcessId)."
                }
            }
            finally {
                $stop.Dispose()
            }
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = @($processes | Where-Object {
            Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        })
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "AstrBot processes did not stop within 15 seconds."
}

function Test-LocalPort {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(200) -and $client.Connected
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
        if ($Process -and $Process.HasExited) {
            throw "AstrBot exited with code $($Process.ExitCode). Logs: $StdoutLog ; $StderrLog"
        }
        $missing = @(Get-MissingPorts)
        if ($missing.Count -eq 0) {
            Write-Host ("AstrBot is ready on ports {0}." -f ($RequiredPorts -join ', '))
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    throw "AstrBot readiness timed out; missing ports: $($missing -join ', '). Logs: $StdoutLog ; $StderrLog"
}

if (-not $ForceRestart) {
    $running = @(Get-AstrBotProcesses)
    if ($running.Count -gt 0) {
        $runningIds = (($running | ForEach-Object { $_.ProcessId } | Sort-Object -Unique) -join ", ")
        Write-Host "AstrBot is already running; PIDs: $runningIds. Logs: $StdoutLog ; $StderrLog"
        Write-Host "Waiting for required ports."
        Wait-AstrBotReady
        Write-Host ("[AstrBot] Reused runtime in {0:F2}s." -f $timer.Elapsed.TotalSeconds)
        exit 0
    }
}

Set-Location $ProjectRoot
if (-not (Test-Path $ProjectPython -PathType Leaf)) {
    if ($SkipInstall) {
        throw "The project environment is missing. Rerun without -SkipInstall."
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        throw "uv is required to install this project's environment."
    }
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
Write-Host ("[AstrBot] Environment ready in {0:F2}s; reusing project Python." -f $timer.Elapsed.TotalSeconds)

if ($ForceRestart) {
    $stopAt = $timer.Elapsed.TotalSeconds
    Stop-AstrBotProcesses
    Write-Host ("[AstrBot] Previous runtime stopped in {0:F2}s." -f ($timer.Elapsed.TotalSeconds - $stopAt))
}

$occupied = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object {
    $_.Port -in $RequiredPorts
})
if ($occupied.Count -gt 0) {
    throw "AstrBot ports are still occupied: $(($occupied.Port | Sort-Object -Unique) -join ', '). Refusing to start another runtime."
}

$env:VIRTUAL_ENV = Join-Path $ProjectRoot ".venv"
$env:Path = (Split-Path -Parent $ProjectPython) + ";" + $env:Path
$env:PYTHONUNBUFFERED = "1"
# Plugin .py edits reload in-process; a framework restart never touches NapCat.
$env:ASTRBOT_RELOAD = "1"
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$mainPath = Join-Path $ProjectRoot "main.py"
# WMI owns the detached process; cmd writes logs without inheriting the launcher's streams.
$startupClass = Get-CimClass -ClassName Win32_ProcessStartup -OperationTimeoutSec 5
$startup = New-CimInstance -CimClass $startupClass -ClientOnly -Property @{
    ShowWindow = [uint16]0
    CreateFlags = [uint32]0x00000010
    EnvironmentVariables = [string[]]@([Environment]::GetEnvironmentVariables().GetEnumerator() | ForEach-Object {
        "{0}={1}" -f $_.Key, $_.Value
    })
}
$commandLine = '"{0}" /d /s /v:off /c ""{1}" "{2}" <NUL >"{3}" 2>"{4}""' -f `
    $env:ComSpec, $ProjectPython, $mainPath, $StdoutLog, $StderrLog
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -OperationTimeoutSec 10 -Arguments @{
    CommandLine = $commandLine
    CurrentDirectory = $ProjectRoot
    ProcessStartupInformation = $startup
}
if ($created.ReturnValue -ne 0) {
    throw "AstrBot process creation failed with code $($created.ReturnValue)."
}
$process = $null
try {
    $process = Get-Process -Id $created.ProcessId -ErrorAction Stop
    [void]$process.Handle
    $launchAt = $timer.Elapsed.TotalSeconds
    Write-Host "Started AstrBot process $($process.Id). Logs: $StdoutLog ; $StderrLog"
    Wait-AstrBotReady -Process $process
    Write-Host ("[AstrBot] Startup ready in {0:F2}s; total {1:F2}s." -f `
        ($timer.Elapsed.TotalSeconds - $launchAt), $timer.Elapsed.TotalSeconds)
}
finally {
    if ($null -ne $process) {
        $process.Dispose()
    }
}
exit 0
