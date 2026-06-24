$ErrorActionPreference = 'Stop'

$project = Join-Path $PSScriptRoot 'CurlRunner.WinUI\CurlRunner.WinUI.csproj'
$source = Join-Path $PSScriptRoot 'CurlRunner.WinUI\bin\x64\Debug\net10.0-windows10.0.22621.0\win-x64'
$artifactRoot = Join-Path $PSScriptRoot 'artifacts'
$destination = Join-Path $artifactRoot 'CurlRunner.WinUI-win-x64'
$zipPath = "$destination.zip"

dotnet build $project -c Debug -r win-x64 --self-contained true -p:Platform=x64
if ($LASTEXITCODE -ne 0) {
    throw "WinUI build failed with exit code $LASTEXITCODE."
}

$artifactRoot = [System.IO.Path]::GetFullPath($artifactRoot)
$destination = [System.IO.Path]::GetFullPath($destination)
$zipPath = [System.IO.Path]::GetFullPath($zipPath)
$artifactPrefix = $artifactRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

if (-not $destination.StartsWith($artifactPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to replace an artifact outside $artifactRoot."
}

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Force -Path $destination | Out-Null
Get-ChildItem -LiteralPath $source -Force |
    Where-Object { $_.Name -ne 'publish' } |
    Copy-Item -Destination $destination -Recurse -Force

$exePath = Join-Path $destination 'CurlRunner.WinUI.exe'
$hostFxrPath = Join-Path $destination 'hostfxr.dll'
if (-not (Test-Path -LiteralPath $exePath) -or -not (Test-Path -LiteralPath $hostFxrPath)) {
    throw 'The self-contained output is incomplete.'
}

Compress-Archive -Path $destination -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "Executable folder: $destination"
Write-Host "Distributable ZIP: $zipPath"
