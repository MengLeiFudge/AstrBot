param(
    [switch]$AssumeYes,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$UpstreamUrl = "https://github.com/AstrBotDevs/AstrBot.git"
$ReleaseApi = "https://api.github.com/repos/AstrBotDevs/AstrBot/releases/latest"
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExtraRequirements = Join-Path $ProjectRoot "deployment\extra-requirements.txt"

function Normalize-GitRemoteUrl {
    param([string]$Url)

    $normalized = ([string]$Url).Trim().TrimEnd("/")
    if ($normalized.EndsWith(".git", [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(0, $normalized.Length - 4)
    }
    return $normalized
}

function Invoke-ProjectCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host ("> " + $FilePath + " " + ($Arguments -join " "))
    if ($DryRun) {
        return
    }
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

Set-Location $ProjectRoot
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required to update this AstrBot project."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to update project dependencies."
}

$branchOutput = & git branch --show-current
$currentBranch = ([string]$branchOutput).Trim()
if ($LASTEXITCODE -ne 0 -or $currentBranch -ne "deployment") {
    throw "Updates must run from the deployment branch; current branch: $currentBranch"
}
if (& git status --porcelain) {
    throw "The AstrBot worktree must be clean before updating."
}

$upstreamOutput = & git remote get-url upstream 2>$null
$upstreamExitCode = $LASTEXITCODE
$upstreamUrl = ([string]$upstreamOutput).Trim()
$normalizedUpstreamUrl = Normalize-GitRemoteUrl -Url $upstreamUrl
$normalizedExpectedUpstreamUrl = Normalize-GitRemoteUrl -Url $UpstreamUrl
if ($upstreamExitCode -ne 0) {
    Invoke-ProjectCommand "git" @("remote", "add", "upstream", $UpstreamUrl)
}
elseif (-not $normalizedUpstreamUrl.Equals(
    $normalizedExpectedUpstreamUrl,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "The upstream remote points to an unexpected URL: $upstreamUrl"
}

$headers = @{
    Accept = "application/vnd.github+json"
    "User-Agent" = "AstrBot-deployment-updater"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$release = Invoke-RestMethod -Uri $ReleaseApi -Headers $headers -TimeoutSec 30
$tag = ([string]$release.tag_name).Trim()
if (-not $tag -or $release.draft -or $release.prerelease) {
    throw "GitHub did not return a stable AstrBot release tag."
}

Write-Host "Latest stable AstrBot release: $tag"
if (-not $AssumeYes -and -not $DryRun) {
    $answer = Read-Host "Merge $tag into deployment and refresh dependencies? Type Y to continue"
    if ($answer -notmatch '(?i)^(y|yes)$') {
        Write-Host "Update cancelled."
        exit 0
    }
}

Invoke-ProjectCommand "git" @("fetch", "upstream", "refs/tags/$tag:refs/tags/$tag")
Invoke-ProjectCommand "git" @("merge", "--no-edit", $tag)
Invoke-ProjectCommand "uv" @("sync")
if (-not $DryRun -and -not (Test-Path $ExtraRequirements -PathType Leaf)) {
    throw "Plugin dependency manifest is missing: $ExtraRequirements"
}
Invoke-ProjectCommand "uv" @("pip", "install", "--python", $ProjectPython, "--requirements", $ExtraRequirements)

Write-Host "AstrBot deployment updated to $tag. No push was performed."
