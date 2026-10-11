[CmdletBinding()]
param(
    [string]$Video,
    [string]$Srt,
    [string]$Output,
    [switch]$NoPose,
    [double]$PoseInterval = 2
)
$ErrorActionPreference = 'Stop'
$repositoryFolder = Split-Path $PSScriptRoot -Parent
if (-not $Video) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Select DJI footage'
    $picker.Filter = 'Video files|*.mp4;*.mov|All files|*.*'
    if ($picker.ShowDialog() -ne 'OK') { return }
    $Video = $picker.FileName
    $picker.Dispose()
}
$Video = (Resolve-Path -LiteralPath $Video).Path
if (-not $Srt) {
    $videoFolder = Split-Path $Video -Parent
    $videoStem = [System.IO.Path]::GetFileNameWithoutExtension($Video)
    $match = Get-ChildItem -LiteralPath $videoFolder -File | Where-Object {
        $_.BaseName -eq $videoStem -and $_.Extension -eq '.srt'
    } | Select-Object -First 1
    if ($match) { $Srt = $match.FullName }
    else {
        Add-Type -AssemblyName System.Windows.Forms
        $picker = New-Object System.Windows.Forms.OpenFileDialog
        $picker.Title = 'Select the matching DJI SRT'
        $picker.Filter = 'Subtitles|*.srt|All files|*.*'
        if ($picker.ShowDialog() -ne 'OK') { return }
        $Srt = $picker.FileName
        $picker.Dispose()
    }
}
$Srt = (Resolve-Path -LiteralPath $Srt).Path
if (-not $Output) {
    $Output = Join-Path $repositoryFolder ("outputs/"+[System.IO.Path]::GetFileNameWithoutExtension($Video)+'.fusion.json')
}
$Output = [System.IO.Path]::GetFullPath($Output)
$previousFolder = Get-Location
try {
    Set-Location -LiteralPath $repositoryFolder
    $arguments = @('--cache-dir', '.uv-cache', 'run', '--extra', 'pose', 'bird-dji', 'analyze',
                   '--video', $Video, '--srt', $Srt, '-o', $Output, '--pose-interval', "$PoseInterval", '--overwrite')
    if (-not $NoPose) { $arguments += '--pose' }
    & uv @arguments
    if ($LASTEXITCODE -ne 0) { throw "Analysis failed (exit $LASTEXITCODE)." }
    Write-Host "Select this JSON in the Fuse's Data tab: $Output"
} finally {
    Set-Location -LiteralPath $previousFolder.Path
}
