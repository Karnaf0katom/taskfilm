$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

function Refresh-TaskfilmPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-TaskfilmDependency([string]$Package) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Install Microsoft App Installer from Microsoft Store, then run setup again.'
    }
    & winget install --exact --id $Package --source winget --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Could not install $Package. Ask Omer to check this window." }
    Refresh-TaskfilmPath
}

Write-Host 'Taskfilm Revit course starter - first Windows setup'
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { Install-TaskfilmDependency 'Python.Python.3.12' }
& py -3.12 -c 'import sys; assert sys.version_info >= (3,12)'
if ($LASTEXITCODE -ne 0) {
    Install-TaskfilmDependency 'Python.Python.3.12'
    & py -3.12 -c 'import sys; assert sys.version_info >= (3,12)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is not available. Close this window and run setup again.' }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Install-TaskfilmDependency 'Gyan.FFmpeg' }
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw 'FFprobe was not found. Restart setup after installing FFmpeg.' }
$ObsInstalled = (Test-Path "$env:ProgramFiles\obs-studio\bin\64bit\obs64.exe") -or (Get-Command obs64 -ErrorAction SilentlyContinue)
if (-not $ObsInstalled) { Install-TaskfilmDependency 'OBSProject.OBSStudio' }

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install the recording dependencies. Check the internet connection.' }

# Pin the published package and verify the release asset before installing it.
$WheelName = 'taskfilm-0.1.0a4-py3-none-any.whl'
$WheelPath = Join-Path $PSScriptRoot $WheelName
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a4/$WheelName" -OutFile $WheelPath
if ((Get-FileHash -LiteralPath $WheelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '3134f21e28bb0bb55a15942c37bae62638e8ab7625af630d3f8511efd3027295') {
    Remove-Item -LiteralPath $WheelPath
    throw 'The downloaded Taskfilm wheel did not match the published SHA256. Installation stopped.'
}
& '.\.venv\Scripts\python.exe' -m pip install $WheelPath
if ($LASTEXITCODE -ne 0) { throw 'Taskfilm installation failed.' }
Remove-Item -LiteralPath $WheelPath
Write-Host 'Setup complete. Open START-HERE.he.txt, start OBS, then double-click 01-START.cmd.'
Write-Host 'Revit, its license and the voice key are supplied separately. No GPU is needed.'
