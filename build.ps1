<#
build.ps1 — Compile bilan_hebdo.py en un exécutable Windows auto-installable.
Produit : dist\RapportClaudeSetup.zip

Usage :
  ./build.ps1 -Version 2.27.0     # build de PUBLICATION : estampille la version
  ./build.ps1                     # build de TEST : version inchangee, NE PAS publier

Le numero de version passe ici est ecrit dans bilan_hebdo.py (APP_VERSION) AVANT
la compilation : c'est ce que l'exe affichera, comparera pour se mettre a jour et
remontera au serveur. publish.ps1 refuse ensuite toute publication dont le numero
ne correspond pas a celui embarque dans l'exe.
#>
param([string]$Version = "", [string]$Name = "RapportClaudeSetup")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- 0. Estampillage de la version -----------------------------------------
# Sans cette etape, la constante restait figee : de la 2.24.1 a la 2.26.0, tous
# les builds se declaraient « 2.24.1 » -> pop-up de mise a jour perpetuel et
# reinstallation quotidienne de ~20 Mo sur chaque poste.
$srcPath = Join-Path $PSScriptRoot "bilan_hebdo.py"
# `(?=\r?$)` et non `$` : en .NET, `$` en mode multiligne se cale devant le \n et
# NE saute PAS le \r. Sur une copie de travail en CRLF — ce que produit un
# `git pull` quand core.autocrlf vaut true, et le depot n'a pas de .gitattributes
# pour l'en empecher — la ligne se lit `..."2.30.0"\r`, le motif ne matchait plus,
# et le build s'arretait sur « APP_VERSION introuvable » alors que la ligne est
# bien la (constate le 16/08/2026, au premier pull qui touchait ce fichier depuis
# des semaines : entre deux, c'est build.ps1 lui-meme qui le reecrivait, en LF).
# Le \r reste HORS du match (lookahead) : sans cela, l'estampillage ci-dessous
# l'avalerait et laisserait une ligne en LF au milieu d'un fichier en CRLF.
$rxVer   = [regex]'(?m)^APP_VERSION = "(\d+\.\d+\.\d+)"(?=\r?$)'
$src     = [IO.File]::ReadAllText($srcPath)
$m       = $rxVer.Match($src)
if(-not $m.Success){ throw "APP_VERSION introuvable dans bilan_hebdo.py (ligne attendue : APP_VERSION = ""X.Y.Z"")." }

if($Version){
  if($Version -notmatch '^\d+\.\d+\.\d+$'){ throw "Version invalide : '$Version' (attendu X.Y.Z)" }
  if($m.Groups[1].Value -ne $Version){
    $src = $rxVer.Replace($src, "APP_VERSION = ""$Version""", 1)
    [IO.File]::WriteAllText($srcPath, $src, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "==> APP_VERSION : $($m.Groups[1].Value) -> $Version" -ForegroundColor Green
  } else {
    Write-Host "==> APP_VERSION deja a $Version" -ForegroundColor Green
  }
} else {
  Write-Host "ATTENTION : build de TEST, version inchangee ($($m.Groups[1].Value))." -ForegroundColor Yellow
  Write-Host "            Pour publier, relance : ./build.ps1 -Version X.Y.Z" -ForegroundColor Yellow
}

python -m pip install --upgrade pyinstaller tzdata pystray pillow | Out-Null

# --onedir (et non --onefile) : pas d'auto-extraction en dossier temporaire au
# lancement -> réduit les détections comportementales de l'antivirus.
python -m PyInstaller `
    --onedir `
    --windowed `
    --name $Name `
    --icon "assets\logo.ico" `
    --add-data "assets\logo.png;assets" `
    --collect-all tzdata `
    --collect-submodules pystray `
    --hidden-import pystray._win32 `
    --hidden-import PIL `
    --clean -y `
    bilan_hebdo.py
# $ErrorActionPreference="Stop" ne couvre PAS les executables externes : sans ce
# test, une compilation ratee laissait le script continuer, rezipper le dist\
# precedent et annoncer un succes — on publiait alors l'ancienne version.
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue (code $LASTEXITCODE) - rien n'a ete zippe." }

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
