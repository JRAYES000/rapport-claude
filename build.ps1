<#
build.ps1 — Compile bilan_hebdo.py en un exécutable Windows auto-installable.
Produit : dist\BilanHebdoSetup.exe

Avant de builder la version finale à donner à Krassy : renseigner les champs
gmail_user / gmail_app_password dans la section CONFIG de bilan_hebdo.py
(ou laisser vide et fournir un config.json à côté de l'exe).
#>
param([string]$Name = "RapportClaudeSetup")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pyinstaller reportlab tzdata pystray pillow | Out-Null

# --onedir (et non --onefile) : pas d'auto-extraction en dossier temporaire au
# lancement -> réduit les détections comportementales de l'antivirus.
python -m PyInstaller `
    --onedir `
    --windowed `
    --name $Name `
    --icon "assets\logo.ico" `
    --add-data "assets\logo.png;assets" `
    --collect-all reportlab `
    --collect-all tzdata `
    --collect-submodules pystray `
    --hidden-import pystray._win32 `
    --hidden-import PIL `
    --clean -y `
    bilan_hebdo.py

$src = Join-Path $PSScriptRoot "dist\$Name"
$zip = Join-Path $PSScriptRoot "dist\$Name.zip"
$exe = Join-Path $src "$Name.exe"

# --- Signature de code (Azure Artifact Signing) ---------------------------------
# One-shot côté Azure : compte Artifact Signing + validation d'identité + certificate
# profile + rôle "Artifact Signing Certificate Profile Signer". Sur la machine de build :
#   winget install -e --id Microsoft.Azure.ArtifactSigningClientTools   (signtool dlib + .NET8 + VC++)
#   winget install -e --id Microsoft.AzureCLI   puis   az login
# Puis renseigner signing\metadata.json (cf signing\metadata.template.json). Ensuite, à
# CHAQUE build l'exe est signé automatiquement — rien à refaire dans le portail Azure.
$signMeta = Join-Path $PSScriptRoot "signing\metadata.json"
if (Test-Path $signMeta) {
    Write-Output "==> Signature de l'exe (Azure Artifact Signing)..."
    $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    # dlib Artifact Signing : package NuGet local au projet (Microsoft.ArtifactSigning.Client), sinon recherche Program Files
    $dlib = Join-Path $PSScriptRoot "signing\tools\Microsoft.ArtifactSigning.Client\bin\x64\Azure.CodeSigning.Dlib.dll"
    if (-not (Test-Path $dlib)) {
        $dlib = Get-ChildItem "C:\Program Files","C:\Program Files (x86)" -Recurse -Filter "Azure.CodeSigning.Dlib.dll" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } | Select-Object -First 1 -ExpandProperty FullName
    }
    if ($signtool -and $dlib -and (Test-Path $dlib)) {
        & $signtool sign /v /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 `
            /dlib $dlib /dmdf $signMeta $exe
        if ($LASTEXITCODE -ne 0) { throw "Echec de la signature (signtool code $LASTEXITCODE)." }
        & $signtool verify /pa /v $exe
    } else {
        Write-Warning "Outils de signature introuvables (signtool x64 / Azure.CodeSigning.Dlib.dll). Exe NON signe."
    }
} else {
    Write-Output "==> (signature ignoree : signing\metadata.json absent)"
}

# Zip du dossier pour distribution (contient l'exe signe si la signature a eu lieu)
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $src -DestinationPath $zip
Write-Output "==> dist\$Name.zip (dossier $Name)"
