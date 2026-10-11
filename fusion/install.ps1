[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Destination = (Join-Path $env:APPDATA 'Blackmagic Design/DaVinci Resolve/Support/Fusion/Fuses'),
    [string]$ModelPath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $ModelPath) { $ModelPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'models/yolov8n-pose.pt' }
$sourceFile = Join-Path $PSScriptRoot 'BirdDJI.fuse'
$destinationFolder = [System.IO.Path]::GetFullPath($Destination)
$destinationFile = Join-Path $destinationFolder 'BirdDJI.fuse'
if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
    throw "Fuse source is missing: $sourceFile"
}
if ([System.IO.Path]::GetFullPath($sourceFile) -eq $destinationFile) {
    throw 'Source and destination must differ.'
}
if ($PSCmdlet.ShouldProcess($destinationFile, 'Install Bird DJI HUD Fuse')) {
    $uv = (Get-Command uv -ErrorAction Stop).Source
    $ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
        throw "Pose model is missing: $ModelPath. Place yolov8n-pose.pt in models/, or use -ModelPath."
    }
    New-Item -ItemType Directory -Force -Path $destinationFolder | Out-Null
    $componentFolder = Join-Path $destinationFolder 'BirdDJI'
    $analyzerFolder = Join-Path $componentFolder 'analyzer'
    $repositoryFolder = Split-Path $PSScriptRoot -Parent
    New-Item -ItemType Directory -Force -Path (Join-Path $analyzerFolder 'src/bird_dji') | Out-Null
    foreach ($file in @('pyproject.toml','uv.lock','README.md')) {
        Copy-Item -LiteralPath (Join-Path $repositoryFolder $file) -Destination (Join-Path $analyzerFolder $file) -Force
    }
    Get-ChildItem -LiteralPath (Join-Path $repositoryFolder 'src/bird_dji') -Filter '*.py' -File |
        Copy-Item -Destination (Join-Path $analyzerFolder 'src/bird_dji') -Force
    Write-Host 'Preparing the bundled analysis environment (first installation may download dependencies)...'
    & $uv --cache-dir (Join-Path $repositoryFolder '.uv-cache') sync --project $analyzerFolder --extra pose --locked --no-editable --reinstall-package bird-dji
    if ($LASTEXITCODE -ne 0) { throw 'Analysis environment installation failed; the existing Fuse was not replaced.' }
    $analysisPython = Join-Path $analyzerFolder '.venv/Scripts/python.exe'
    $torchPins = @'
import sys, tomllib
with open(sys.argv[1], 'rb') as f:
    data = tomllib.load(f)
for package in data['package']:
    if package['name'] in ('torch', 'torchvision'):
        print(package['name'] + '==' + package['version'])
'@ | & $analysisPython -I - (Join-Path $analyzerFolder 'uv.lock')
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read pinned PyTorch versions.' }
    & $uv --cache-dir (Join-Path $repositoryFolder '.uv-cache') pip install --python $analysisPython --torch-backend auto --upgrade-package torch --upgrade-package torchvision @torchPins
    if ($LASTEXITCODE -ne 0) { throw 'Automatic CPU/CUDA dependency installation failed.' }
    New-Item -ItemType Directory -Force -Path (Join-Path $componentFolder 'models'),(Join-Path $componentFolder 'bin') | Out-Null
    Copy-Item -LiteralPath $ModelPath -Destination (Join-Path $componentFolder 'models/yolov8n-pose.pt') -Force
    Copy-Item -LiteralPath $ffprobe -Destination (Join-Path $componentFolder 'bin/ffprobe.exe') -Force
    & (Join-Path $analyzerFolder '.venv/Scripts/python.exe') -I -c 'import bird_dji.fusion_job, cv2, ultralytics'
    if ($LASTEXITCODE -ne 0) { throw 'Bundled analysis environment verification failed.' }
    & (Join-Path $componentFolder 'bin/ffprobe.exe') -version | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw 'Bundled ffprobe verification failed; a standalone FFmpeg distribution is required.' }
    if (Test-Path -LiteralPath $destinationFile) {
        $backupFile = "$destinationFile.$(Get-Date -Format 'yyyyMMdd-HHmmss').bak"
        Copy-Item -LiteralPath $destinationFile -Destination $backupFile
        Write-Host "Previous plugin saved: $backupFile"
    }
    Copy-Item -LiteralPath $sourceFile -Destination $destinationFile -Force
    foreach ($component in @('analysis-button.lua','launch-analysis.py')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $component) -Destination (Join-Path $componentFolder $component) -Force
    }
    $config = @{ bundle_version = 1; runtime = 'analyzer/.venv/Scripts/python.exe'; model = 'models/yolov8n-pose.pt' } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText((Join-Path $componentFolder 'install.json'),$config,[System.Text.UTF8Encoding]::new($false))
    Write-Host "Installed: $destinationFile"
    Write-Host 'Restart Resolve. In Fusion press Shift+Space, search for Bird DJI HUD.'
}
