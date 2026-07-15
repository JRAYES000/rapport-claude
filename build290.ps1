# Build v2.9.0 : PyInstaller (sans pip upgrade qui bloque) + signature + zip
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Start-Transcript -Path (Join-Path $PSScriptRoot "build_2.9.0.log") -Force

python -m PyInstaller --onedir --windowed --name RapportClaudeSetup `
    --icon "assets\logo.ico" --add-data "assets\logo.png;assets" `
    --collect-all reportlab --collect-all tzdata `
    --collect-submodules pystray --hidden-import pystray._win32 --hidden-import PIL `
    --clean -y bilan_hebdo.py
if ($LASTEXITCODE -ne 0) { Stop-Transcript; throw "PyInstaller a echoue ($LASTEXITCODE)" }

$src = Join-Path $PSScriptRoot "dist\RapportClaudeSetup"
$exe = Join-Path $src "RapportClaudeSetup.exe"
$zip = Join-Path $PSScriptRoot "dist\RapportClaudeSetup.zip"

# Signature Azure Artifact Signing
$signMeta = Join-Path $PSScriptRoot "signing\metadata.json"
$signtool = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
$dlib = Join-Path $PSScriptRoot "signing\tools\Microsoft.ArtifactSigning.Client\bin\x64\Azure.CodeSigning.Dlib.dll"
& $signtool sign /v /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 /dlib $dlib /dmdf $signMeta $exe
if ($LASTEXITCODE -ne 0) { Stop-Transcript; throw "Signature echouee ($LASTEXITCODE)" }
& $signtool verify /pa $exe

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $src -DestinationPath $zip
Write-Output ("ZIP_OK " + [math]::Round((Get-Item $zip).Length/1MB,1) + " MB")
Stop-Transcript
