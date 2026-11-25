# SPDX-License-Identifier: GPL-3.0-or-later
<#
.SYNOPSIS
    Install, update or remove IngeTrazo Web on a Windows 10 or 11 PC.

.DESCRIPTION
    Does every step of the README's "Install on Windows" section:

      1. Finds Python 3.10 to 3.14, or installs Python 3.13 for this user with winget.
      2. Finds Git, or installs it with winget.
      3. Downloads IngeTrazo Web (or updates it if it is already there).
      4. Creates its Python environment and installs the packages.
      5. Writes a small launcher that holds the settings, starts the server
         without a console window, and logs to server.log in the data folder.
      6. Adds Start menu entries, starts the server with Windows sign-in, starts it now
         and opens it in the browser.

    No administrator rights are needed, except for the firewall rule of -Network.
    Run the script again at any time to update; use the same options as the first time.

.PARAMETER InstallDir
    Where the program goes. Default: %LOCALAPPDATA%\IngeTrazoWeb

.PARAMETER DataDir
    Where documents, revisions and users are kept. Default: %USERPROFILE%\IngeTrazoWebData
    An update or -Uninstall never deletes it (unless -RemoveData is given).

.PARAMETER Port
    The port the server listens on. Default: 8000

.PARAMETER Network
    Let other computers on the network use the server. Creates an administrator account
    (named by -AdminName) if none exists and prints its access token once, listens on all
    addresses and, when run as administrator, opens the port in Windows Firewall for
    private and domain networks.

.PARAMETER AdminName
    The administrator account -Network creates. Default: admin

.PARAMETER NoAutostart
    Do not start the server when you sign in to Windows.

.PARAMETER Uninstall
    Stop the server and remove the program, its shortcuts and its firewall rule.

.PARAMETER RemoveData
    With -Uninstall, also delete the data folder (every document).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-windows.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-windows.ps1 -Network -Port 8080

.EXAMPLE
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/felixriestra/ingetrazo-web-open/main/install-windows.ps1)))

    Downloads and runs it in one line; add options after the last parenthesis.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'IngeTrazoWeb'),
    [string]$DataDir = (Join-Path $env:USERPROFILE 'IngeTrazoWebData'),
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$Network,
    [ValidatePattern('^[A-Za-z0-9._-]+$')][string]$AdminName = 'admin',
    [switch]$NoAutostart,
    [switch]$Uninstall,
    [switch]$RemoveData,
    [string]$Repository = 'https://github.com/felixriestra/ingetrazo-web-open.git',
    [string]$Branch = 'main'
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # Invoke-WebRequest is very slow with the bar

$AppDir      = Join-Path $InstallDir 'app'
$VenvPython  = Join-Path $AppDir '.venv\Scripts\python.exe'
$VenvPythonw = Join-Path $AppDir '.venv\Scripts\pythonw.exe'
$Launcher    = Join-Path $InstallDir 'launch.pyw'
$StartMenu   = Join-Path ([Environment]::GetFolderPath('Programs')) 'IngeTrazo Web'
$StartupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'IngeTrazo Web server.lnk'
$RuleName    = 'IngeTrazo Web'
$Url         = "http://127.0.0.1:$Port"

# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Note([string]$Text) { Write-Host "    $Text" }

# Run a program and stop the script if it fails. Its output goes straight to the console.
function Invoke-Checked([string]$Exe, [string[]]$Arguments, [string]$What) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

# Run a program quietly and return its exit code and standard output. Windows PowerShell 5.1
# turns redirected stderr into errors, which would stop the script, hence the local setting.
function Invoke-Quiet([string]$Exe, [string[]]$Arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Arguments 2>$null
        return [pscustomobject]@{ Code = $LASTEXITCODE; Out = (($out | ForEach-Object { "$_" }) -join "`n").Trim() }
    } catch {
        return [pscustomobject]@{ Code = 1; Out = '' }
    } finally {
        $ErrorActionPreference = $saved
    }
}

# Pick up PATH changes made by an installer that ran a moment ago.
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-WithWinget([string]$Id, [string]$What, [switch]$UserScope) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$What is not installed and winget is not available to install it. Install $What " +
              "by hand (see the README, 'Install on Windows') and run this script again."
    }
    Write-Step "Installing $What with winget"
    $common = @('install', '--exact', '--id', $Id, '--silent',
                '--accept-package-agreements', '--accept-source-agreements')
    $done = $false
    if ($UserScope) {
        & winget @($common + @('--scope', 'user'))
        $done = ($LASTEXITCODE -eq 0)
    }
    if (-not $done) {
        & winget @common
        if ($LASTEXITCODE -ne 0) { throw "winget could not install $What (exit code $LASTEXITCODE)." }
    }
    Update-SessionPath
}

# A Python 3.10 to 3.14, preferring 3.13. Skips the Microsoft Store placeholder.
function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in '3.13', '3.14', '3.12', '3.11', '3.10') {
            $probe = Invoke-Quiet 'py' @("-$version", '-c', 'import sys; print(sys.executable)')
            if ($probe.Code -eq 0 -and $probe.Out) { return $probe.Out }
        }
    }
    $check = 'import sys; print((3, 10) <= sys.version_info[:2] <= (3, 14))'
    foreach ($command in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        if ($command.Source -like '*\WindowsApps\*') { continue }
        if ((Invoke-Quiet $command.Source @('-c', $check)).Out -eq 'True') { return $command.Source }
    }
    foreach ($version in '313', '314', '312', '311', '310') {   # where winget puts a user install
        $exe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

function Find-Git {
    $command = Get-Command git -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($exe in "$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe") {
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

# Stop the server and its import/export workers: every process run from this install's Python.
function Stop-Server {
    $venv = (Join-Path $AppDir '.venv\')
    $running = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) })
    foreach ($process in $running) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($running.Count) {
        Write-Note "Stopped the running server."
        Start-Sleep -Seconds 2                     # let Windows release the files
    }
}

function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Description) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $WorkDir
    $link.Description = $Description
    $link.Save()
}

function Write-Utf8([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding $false))
}

# A Python raw string literal for a Windows path. Windows paths cannot contain a double
# quote, and a raw string cannot end in a backslash.
function ConvertTo-PyPath([string]$Path) { return 'r"' + $Path.TrimEnd('\') + '"' }

# ---------------------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------------------

if ($env:OS -ne 'Windows_NT') { throw 'This script is for Windows. See the README for macOS and Linux.' }

if ($Uninstall) {
    Write-Step 'Removing IngeTrazo Web'
    Stop-Server
    foreach ($path in $StartupLink, $StartMenu) {
        if (Test-Path $path) { Remove-Item $path -Recurse -Force; Write-Note "Removed $path" }
    }
    if (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) {
        if (Test-Administrator) {
            Remove-NetFirewallRule -DisplayName $RuleName
            Write-Note 'Removed the firewall rule.'
        } else {
            Write-Note "Run this as administrator to remove the firewall rule '$RuleName' too."
        }
    }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force; Write-Note "Removed $InstallDir" }
    if ($RemoveData -and (Test-Path $DataDir)) {
        Remove-Item $DataDir -Recurse -Force
        Write-Note "Removed $DataDir and every document in it."
    } elseif (Test-Path $DataDir) {
        Write-Note "Kept your documents in $DataDir (delete the folder yourself, or use -RemoveData)."
    }
    Write-Step 'Done.'
    return
}

# ---------------------------------------------------------------------------------------
# Install or update
# ---------------------------------------------------------------------------------------

Write-Host ''
Write-Host 'IngeTrazo Web installer' -ForegroundColor White
Write-Note "Program:   $InstallDir"
Write-Note "Documents: $DataDir"
Write-Host ''

Write-Step 'Looking for Python 3.10 to 3.14'
$Python = Find-Python
if (-not $Python) {
    Install-WithWinget 'Python.Python.3.13' 'Python 3.13' -UserScope
    $Python = Find-Python
    if (-not $Python) { throw 'Python was installed but cannot be found. Open a new PowerShell window and run this script again.' }
}
Write-Note "Using $Python"

Write-Step 'Looking for Git'
$Git = Find-Git
if (-not $Git) {
    Install-WithWinget 'Git.Git' 'Git'
    $Git = Find-Git
    if (-not $Git) { throw 'Git was installed but cannot be found. Open a new PowerShell window and run this script again.' }
}
# pip needs git on the PATH to install the SketchUp reader.
$env:Path = (Split-Path $Git) + ';' + $env:Path
Write-Note "Using $Git"

New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir | Out-Null
Stop-Server

if (Test-Path (Join-Path $AppDir '.git')) {
    Write-Step 'Updating IngeTrazo Web'
    Invoke-Checked $Git @('-C', $AppDir, 'pull', '--ff-only') 'Updating the program (git pull)'
} elseif (Test-Path $AppDir) {
    throw "$AppDir exists but is not a Git checkout. Move it away, or choose another -InstallDir."
} else {
    Write-Step 'Downloading IngeTrazo Web'
    Invoke-Checked $Git @('clone', '--depth', '1', '--branch', $Branch, $Repository, $AppDir) 'Downloading the program (git clone)'
}

if (-not (Test-Path $VenvPython)) {
    Write-Step 'Creating the Python environment'
    Invoke-Checked $Python @('-m', 'venv', (Join-Path $AppDir '.venv')) 'Creating the Python environment'
}

Write-Step 'Installing the Python packages (a few minutes the first time)'
Push-Location $AppDir
try {
    Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pip') 'Updating pip'
    Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
                                 '-r', 'requirements.txt', '-r', 'web\backend\requirements.txt') 'Installing the packages'
    Invoke-Checked $VenvPython @('-c', 'import PySide6, numpy, fastapi, uvicorn, openskp, manifold3d, ezdxf') 'Checking the packages'
} finally {
    Pop-Location
}

$env:INGETRAZO_WEB_DATA = $DataDir
$Token = $null
if ($Network) {
    Write-Step 'Setting up accounts'
    Push-Location $AppDir
    try {
        $users = Invoke-Quiet $VenvPython @('-m', 'web.backend', 'users', 'list')
        if ($users.Code -ne 0) { throw 'Could not read the user accounts.' }
        if ($users.Out) {
            Write-Note 'Accounts already exist; keeping them.'
        } else {
            $created = Invoke-Quiet $VenvPython @('-m', 'web.backend', 'users', 'add', $AdminName, '--admin')
            if ($created.Code -ne 0) { throw "Could not create the account '$AdminName'." }
            $Token = ($created.Out -split "`n")[-1].Trim()
        }
    } finally {
        Pop-Location
    }
}

Write-Step 'Writing the launcher'
$HostAddress = if ($Network) { '0.0.0.0' } else { '127.0.0.1' }
$launcherText = @"
# IngeTrazo Web launcher, written by install-windows.ps1. Running the installer again
# rewrites it, so change the settings there (or edit them here and restart the server).
import os
import runpy
import sys

APP = $(ConvertTo-PyPath $AppDir)
os.environ['INGETRAZO_WEB_DATA'] = $(ConvertTo-PyPath $DataDir)
os.environ['INGETRAZO_WEB_HOST'] = '$HostAddress'
os.environ['INGETRAZO_WEB_PORT'] = '$Port'

# pythonw has no console: send output (also of the import/export workers) to a log file.
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(os.path.join(os.environ['INGETRAZO_WEB_DATA'], 'server.log'),
                                   'a', buffering=1, encoding='utf-8')

if __name__ == '__main__':          # workers re-import this file; only the parent serves
    os.chdir(APP)
    sys.path.insert(0, APP)
    sys.argv = ['web.backend']
    runpy.run_module('web.backend', run_name='__main__', alter_sys=True)
"@
Write-Utf8 $Launcher $launcherText

Write-Step 'Adding Start menu entries'
New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
Write-Utf8 (Join-Path $StartMenu 'IngeTrazo Web.url') "[InternetShortcut]`r`nURL=$Url/`r`n"
New-Shortcut (Join-Path $StartMenu 'Start IngeTrazo Web server.lnk') $VenvPythonw "`"$Launcher`"" $AppDir 'Start the IngeTrazo Web server'
if ($NoAutostart) {
    if (Test-Path $StartupLink) { Remove-Item $StartupLink -Force }
} else {
    New-Shortcut $StartupLink $VenvPythonw "`"$Launcher`"" $AppDir 'Start the IngeTrazo Web server when you sign in'
    Write-Note 'The server will start each time you sign in to Windows.'
}

if ($Network) {
    if (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) {
        Write-Note 'The firewall rule already exists.'
    } elseif (Test-Administrator) {
        New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -Profile Private, Domain | Out-Null
        Write-Note "Opened TCP port $Port in Windows Firewall (private and domain networks)."
        Write-Note 'If Windows calls your network Public, set it to Private in Settings > Network.'
    } else {
        Write-Note 'To let other computers in, run this once in an administrator PowerShell:'
        Write-Note "  New-NetFirewallRule -DisplayName '$RuleName' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private,Domain"
    }
}

Write-Step 'Starting the server'
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Another program already uses port $Port. Run the script again with -Port and another number."
}
Start-Process -FilePath $VenvPythonw -ArgumentList "`"$Launcher`"" -WorkingDirectory $AppDir
$ready = $false
foreach ($attempt in 1..60) {
    Start-Sleep -Seconds 1
    try {
        $reply = Invoke-WebRequest -Uri "$Url/api/v1/health" -UseBasicParsing -TimeoutSec 2
        if ($reply.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    throw "The server did not start within a minute. See $(Join-Path $DataDir 'server.log')."
}
if (-not $env:INGETRAZO_NO_BROWSER) { Start-Process "$Url/" }

Write-Host ''
Write-Host "IngeTrazo Web is running at $Url/" -ForegroundColor Green
Write-Note "Start menu: 'IngeTrazo Web' opens it; 'Start IngeTrazo Web server' starts the server."
Write-Note "Log: $(Join-Path $DataDir 'server.log')"
if ($Network) {
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        ForEach-Object { "http://$($_.IPAddress):$Port/" })
    if ($addresses.Count) { Write-Note "From other computers: $($addresses -join ', ')" }
    Write-Note 'Without HTTPS, access tokens travel in plain text; see the README before exposing it beyond your network.'
    if ($Token) {
        Write-Host ''
        Write-Host "Access token for '$AdminName' (shown only once; keep it safe):" -ForegroundColor Yellow
        Write-Host $Token -ForegroundColor Yellow
    }
}
Write-Note 'Update: run this script again. Remove: run it with -Uninstall.'
