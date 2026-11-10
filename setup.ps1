param([switch]$DownloadFFmpeg)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
            & py.exe -3 -m venv (Join-Path $projectRoot '.venv')
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            & python.exe -m venv (Join-Path $projectRoot '.venv')
        } else {
            throw 'Install Python 3.10 or later from python.org, including Tcl/Tk and the Python launcher.'
        }
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
    }

    & $venvPython -c "import sys; assert sys.version_info >= (3, 10), 'KAAT requires Python 3.10+'"
    if ($LASTEXITCODE -ne 0) { throw 'KAAT requires Python 3.10 or later.' }
    & $venvPython -c "import importlib.util; raise SystemExit(importlib.util.find_spec('pip') is None)"
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw 'Bootstrapping pip failed. Install a full Python distribution with ensurepip.' }
    }
    & $venvPython -m pip install --disable-pip-version-check -r requirements.txt -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the error above.' }

    if ($DownloadFFmpeg) {
        $ffmpegProbe = @'
from engine import _ffmpeg
try:
    _ffmpeg()
except RuntimeError:
    raise SystemExit(1)
'@
        & $venvPython -c $ffmpegProbe
        if ($LASTEXITCODE -ne 0) {
            # gyan.dev is a Windows binary distributor linked by https://ffmpeg.org/download.html.
            $toolsRoot = Join-Path $projectRoot '.tools'
            New-Item -ItemType Directory -Path $toolsRoot -Force | Out-Null
            $archive = Join-Path $toolsRoot ('.kaat_download_' + [guid]::NewGuid().ToString('N') + '.zip')
            $downloadUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
            try {
                Write-Host 'Downloading FFmpeg essentials to the project .tools directory...'
                Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $archive
                $checksumResponse = Invoke-WebRequest -UseBasicParsing -Uri ($downloadUrl + '.sha256')
                $expectedHash = [regex]::Match([string]$checksumResponse.Content, '\b[0-9a-fA-F]{64}\b').Value
                $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
                if (-not $expectedHash -or $actualHash -ne $expectedHash) {
                    throw 'FFmpeg checksum verification failed; the archive will not be extracted.'
                }
                Expand-Archive -LiteralPath $archive -DestinationPath $toolsRoot -Force
            } finally {
                if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
            }
        }
    }

    & $venvPython -c "import tkinter; from engine import _ffmpeg; _ffmpeg(); print('Python, Tkinter, FFmpeg and FFprobe are ready.')"
    if ($LASTEXITCODE -ne 0) { throw 'Install FFmpeg on PATH, or rerun setup.ps1 -DownloadFFmpeg. Python must include Tkinter.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    & $venvPython -c "from voice import microphone_permission_error; message=microphone_permission_error(); print('Microphone configuration: ' + message if message else 'No packaged-runtime microphone denial detected; verify live capture in KAAT.')"
    if ($LASTEXITCODE -ne 0) { throw 'Could not check the Python microphone runtime configuration.' }
    Write-Host 'Setup complete. Add your GNANI_API_KEY to .env for voice transcription.'
    Write-Host 'Launch: .\run.ps1'
    Write-Host 'Tests:  .\.venv\Scripts\python.exe -m pytest -q'
} finally {
    Pop-Location
}
