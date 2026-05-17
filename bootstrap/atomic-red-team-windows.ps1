#Requires -Version 5.1
<#
.SYNOPSIS
  XDR Lab — Atomic Red Team preparation for Windows targets (e.g. windows-victim).

.DESCRIPTION
  - Clone Atomic Red Team repository (or use an existing path)
  - (Optional) Install Invoke-AtomicRedTeam from PowerShell Gallery
  - Optional ExecutionPolicy relaxation in Process scope only (LocalMachine unchanged)
  - Microsoft Defender: not disabled; no exclusions added by default
  - SafeMode (default $true): Invoke-AtomicTest is never run automatically

.NOTES
  Deploy CALDERA Sandcat via `aella_cli lab scenario agent deploy`.
  ART is auxiliary; authoritative scenario execution is CALDERA operations.

.EXAMPLE
  # Elevated PowerShell
  .\atomic-red-team-windows.ps1 -AtomicInstallPath 'C:\AtomicRedTeam\atomic-red-team'

.EXAMPLE
  # Include Invoke-AtomicRedTeam module install
  .\atomic-red-team-windows.ps1 -InstallModule -AtomicInstallPath 'C:\AtomicRedTeam\atomic-red-team'
#>
[CmdletBinding()]
param(
    [string] $AtomicInstallPath = 'C:\AtomicRedTeam\atomic-red-team',
    [string] $AtomicGitUrl = 'https://github.com/redcanaryco/atomic-red-team.git',
    [switch] $InstallModule,
    [bool] $SafeMode = $true,
    [switch] $SetProcessExecutionPolicy,
    [switch] $SkipCloneIfExists
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string] $Message) {
    Write-Host "[xdr-lab][atomic-win] $Message" -ForegroundColor Cyan
}

function Test-IsAdministrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    throw 'Run from an elevated (Administrator) PowerShell session.'
}

if ($SetProcessExecutionPolicy) {
    Write-Step 'ExecutionPolicy: Process = Bypass (session only; LocalMachine unchanged)'
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
}

Write-Step "Repository path: $AtomicInstallPath"
$parent = Split-Path -Parent $AtomicInstallPath
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

$gitDir = Join-Path $AtomicInstallPath '.git'
if ((Test-Path -LiteralPath $gitDir) -and $SkipCloneIfExists) {
    Write-Step 'SkipCloneIfExists: keeping existing repository'
}
elseif (-not (Test-Path -LiteralPath $gitDir)) {
    if (Test-Path -LiteralPath $AtomicInstallPath) {
        throw "Path exists but is not a git repository: $AtomicInstallPath"
    }
    Write-Step "git clone $AtomicGitUrl"
    git clone --depth 1 $AtomicGitUrl $AtomicInstallPath
}
else {
    Write-Step 'Keeping existing git repository (update with git pull)'
}

$readme = Join-Path $AtomicInstallPath 'XDR-LAB-ATOMIC-SAFE.md'
@'
# XDR Lab — Atomic Red Team (Windows) safe defaults

- **Microsoft Defender was not disabled and no exclusions were added.**
- SafeMode default: this script **does not execute** any tests.
- Before execution: take a VM **snapshot**, confirm lab isolation, follow change control.
- When using Invoke-AtomicTest: scope to reviewed -AtomicTechnique / -TestNumbers only;
  use -Confirm:$false with extreme care.

CALDERA-based scenarios: docs/caldera-integration.md
'@ | Set-Content -LiteralPath $readme -Encoding UTF8

if ($InstallModule) {
    Write-Step 'Install-Module invoke-atomicredteam (AllUsers; gallery trust required)'
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    Install-Module -Name invoke-atomicredteam -Scope AllUsers -Force -AllowClobber -ErrorAction Stop
}

[System.Environment]::SetEnvironmentVariable('ATOMIC_RED_TEAM_PATH', $AtomicInstallPath, 'Machine')
Write-Step "Machine environment variable ATOMIC_RED_TEAM_PATH=$AtomicInstallPath"

if ($SafeMode) {
    Write-Step 'SafeMode: no automatic Invoke-AtomicTest; manual execution only.'
}
else {
    Write-Warning 'SafeMode is off; destructive techniques may run if invoked.'
}

Write-Step 'Done. Keep Defender policy aligned with your organization standards.'
