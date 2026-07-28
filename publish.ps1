<#
publish.ps1 - Publier une nouvelle version en UNE commande.

Met a jour, de facon coherente et au meme instant :
  1. GitHub : tag + Release (avec le ZIP signe attache)   -> source officielle
  2. Supabase : miroir du ZIP                              -> repli de telechargement
  3. La page https://reporting.claudeagency.fr/info        -> version + changelog a jour
  4. CHANGELOG.md, web/version.json, web/changelog.json    -> versionnes dans le repo

Prerequis :
  - ./build.ps1 a produit dist\RapportClaudeSetup.zip (signe)
  - gh (GitHub CLI) connecte        : gh auth login   (verifier : gh auth status)
  - npx wrangler connecte a Cloudflare
  - (miroir) variable d'env SUPABASE_SERVICE_KEY definie, sinon l'upload Supabase est ignore

Exemples :
  ./publish.ps1 -Version 2.17.0 -Notes "Correction de l'erreur powershell 0xc0000142 lors des mises a jour."
  ./publish.ps1 -Version 2.17.0 -Notes "..." -SkipSupabase
  ./publish.ps1 -Version 2.17.0 -Notes "..." -DryRun
#>

param(
  [Parameter(Mandatory=$true)][string]$Version,
  [Parameter(Mandatory=$true)][string]$Notes,
  [switch]$SkipSupabase,
  [switch]$SkipDeploy,
  [switch]$ForceWeb,
  [switch]$DryRun
)

# NB : on NE met PAS $ErrorActionPreference="Stop" globalement. En PowerShell 5.1,
# cela transforme la moindre ecriture sur stderr par git/gh/npx (messages de
# progression) en erreur fatale. On verifie plutot explicitement $LASTEXITCODE.
Set-Location $PSScriptRoot

$Repo        = "JRAYES000/rapport-claude"
$PagesProj   = "claude-reporting"
$SupabaseUrl = "https://ifutijlvjgkdaonxzzpi.supabase.co/storage/v1/object/downloads/RapportClaudeSetup.zip"
$InfoUrl     = "https://reporting.claudeagency.fr/info"
$zip         = Join-Path $PSScriptRoot "dist\RapportClaudeSetup.zip"
$tag         = "v$Version"
$today       = (Get-Date).ToString("yyyy-MM-dd")
$ghLatest    = "https://github.com/$Repo/releases/latest/download/RapportClaudeSetup.zip"
$ghRelease   = "https://github.com/$Repo/releases/tag/$tag"
$Utf8NoBom   = New-Object System.Text.UTF8Encoding($false)

function Step($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# Execute une commande native et echoue proprement sur code retour != 0.
function Native($label, [scriptblock]$b){
  if($DryRun){ Write-Host "[dry-run] $label" -ForegroundColor Yellow; return }
  & $b
  if($LASTEXITCODE -ne 0){ throw "$label a echoue (code $LASTEXITCODE)." }
}
# Execute une action (cmdlets PowerShell) en s'arretant sur erreur.
function Do1($label, [scriptblock]$b){
  if($DryRun){ Write-Host "[dry-run] $label" -ForegroundColor Yellow; return }
  try { & $b } catch { throw "$label a echoue : $($_.Exception.Message)" }
}

# --- 0. Verifications -------------------------------------------------------
Step "Verifications"
if($Version -notmatch '^\d+\.\d+\.\d+$'){ throw "Version invalide : '$Version' (attendu X.Y.Z)" }
if(-not (Test-Path $zip)){ throw "Introuvable : $zip - lance d'abord ./build.ps1" }
gh auth status 2>&1 | Out-Null
if($LASTEXITCODE -ne 0){ throw "gh non connecte dans ce terminal. Lance : gh auth login" }
Write-Host "ZIP : $zip ($([math]::Round((Get-Item $zip).Length/1MB,1)) Mo)"
Write-Host "Tag : $tag   Date : $today"

# Garde-fou : deployer web\ ecrase le site EN ENTIER. Si une page en ligne ne
# correspond pas au web\ local, c'est qu'elle a ete publiee depuis ailleurs et
# on s'apprete a la perdre (incident du 27/07 : onglet Clients et client.html
# effaces par une publication partie d'un web\ plus ancien).
# Ici et pas plus bas : au moment du deploiement, le tag et la release GitHub
# sont deja pousses, un abandon laisserait une version a moitie publiee.
if(-not $SkipDeploy){
  $perdues = @()
  # Seulement les .html : version.json et changelog.json sont reecrits juste au-dessus,
  # il est normal qu'ils different de ce qui est en ligne.
  foreach($f in Get-ChildItem (Join-Path $PSScriptRoot "web") -File | Where-Object { $_.Extension -eq ".html" }){
    # On interroge la ROUTE (/, /client) et non le fichier : Cloudflare Pages
    # repond 308 sur /x.html, que Invoke-WebRequest (PS 5.1) traite en erreur —
    # le garde-fou sautait alors toutes les pages sans rien dire.
    $route = if($f.BaseName -eq "index"){ "" } else { $f.BaseName }
    try {
      # .Content et non RawContentStream : PS 5.1 decode la reponse en latin-1 des que
      # l'en-tete ne porte pas de charset, si bien que le moindre accent ou tiret
      # cadratin faisait differer TOUTE page de son fichier local. Le garde-fou criait
      # alors au loup a chaque publication, la question se posait a tous les coups, et
      # c'est la que la publication se coupait a mi-chemin. On decode les octets bruts.
      $rep = Invoke-WebRequest -Uri "https://reporting.claudeagency.fr/$route`?nocache=$(Get-Random)" -UseBasicParsing -TimeoutSec 20
      $enLigne = [Text.Encoding]::UTF8.GetString($rep.RawContentStream.ToArray())
    } catch { continue }   # 404 = page nouvelle, rien a perdre
    if($enLigne.Trim() -ne [IO.File]::ReadAllText($f.FullName).Trim()){ $perdues += $f.Name }
  }
  if($perdues){
    Write-Host "`nATTENTION : ces pages different de la version en ligne :" -ForegroundColor Yellow
    $perdues | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    Write-Host "Le deploiement les REMPLACERA par le contenu local." -ForegroundColor Yellow
    Write-Host "Si tu as modifie le site ailleurs, rapatrie-le dans web\ avant de publier."
    if(-not $ForceWeb -and -not $DryRun){
      $r = Read-Host "Continuer quand meme ? (oui/non)"
      if($r -notmatch '^(o|oui|y|yes)$'){ throw "Publication annulee : web\ n'est pas a jour." }
    } elseif($ForceWeb) { Write-Host "(-ForceWeb : on continue)" -ForegroundColor Yellow }
  } else {
    Write-Host "web\ est aligne avec le site en ligne."
  }
}

# --- 1. CHANGELOG.md --------------------------------------------------------
Step "CHANGELOG.md"
$clPath = Join-Path $PSScriptRoot "CHANGELOG.md"
$bulletBlock = ($Notes -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { "- " + $_.Trim() }) -join "`n"
$entry = "## [$Version] - $today`n`n$bulletBlock`n`n"
Do1 "ecrire CHANGELOG.md" {
  $cl = Get-Content $clPath -Raw -Encoding UTF8
  # NB : [regex]::Replace($s,$p,$r,1) n'existe pas — le 4e argument serait
  # interprete comme RegexOptions et TOUTES les occurrences seraient remplacees
  # (bug historique : l'entree se dupliquait devant chaque ancienne version).
  # On utilise une instance de Regex, dont Replace() accepte bien un compteur.
  $re = New-Object System.Text.RegularExpressions.Regex '\n## \['
  $cl = $re.Replace($cl, "`n$entry## [", 1)
  [System.IO.File]::WriteAllText($clPath, $cl, $Utf8NoBom)
}

# --- 2. web/version.json ----------------------------------------------------
Step "web/version.json"
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
$vjPath = Join-Path $PSScriptRoot "web\version.json"
$vj = [ordered]@{
  version   = $Version
  info_url  = $InfoUrl
  download  = $ghLatest
  mirror    = $SupabaseUrl.Replace("/object/downloads","/object/public/downloads")
  github    = $ghRelease
  sha256    = $sha
  auto      = $true
  notes     = $Notes
}
Do1 "ecrire version.json" { [System.IO.File]::WriteAllText($vjPath, ($vj | ConvertTo-Json -Depth 4), $Utf8NoBom) }

# --- 3. web/changelog.json (consomme par /info) -----------------------------
Step "web/changelog.json"
$cjPath = Join-Path $PSScriptRoot "web\changelog.json"
$bullets = @($Notes -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
Do1 "ecrire changelog.json" {
  # NB : sous PowerShell 5.1, ConvertFrom-Json renvoie le tableau JSON comme UN
  # SEUL objet (non enumere) : sans ForEach-Object, l'historique entier se
  # retrouvait imbrique en 2e element, serialise en { value, Count }.
  $list = @()
  if(Test-Path $cjPath){ $list = @(Get-Content $cjPath -Raw -Encoding UTF8 | ConvertFrom-Json | ForEach-Object { $_ }) }
  $newItem = [ordered]@{ version=$Version; date=$today; notes=$bullets }
  $list = @($newItem) + $list
  # -InputObject preserve le tableau racine meme s'il n'a qu'un element.
  [System.IO.File]::WriteAllText($cjPath, (ConvertTo-Json -InputObject $list -Depth 5), $Utf8NoBom)
}

# --- 4. Git : commit + push -------------------------------------------------
# Le tag n'est PAS cree ici : `gh release create` le pose lui-meme sur le commit
# pousse. Avant, un tag deja pousse suivi d'un echec de la release bloquait tout
# nouvel essai avec la meme version ("tag already exists") et laissait une
# version a moitie publiee.
Step "Git commit + push"
Native "git add"            { git add -A }
Native "git commit"        { git commit -m "release: v$Version" }
Native "git push (main)"   { git push origin HEAD }

# --- 5. GitHub Release (avec ZIP) ------------------------------------------
Step "GitHub Release"
Native "gh release create" { gh release create $tag "$zip#RapportClaudeSetup.zip" --repo $Repo --title "v$Version" --notes $Notes }

# --- 6. Miroir Supabase -----------------------------------------------------
Step "Miroir Supabase"
if($SkipSupabase){ Write-Host "ignore (-SkipSupabase)" -ForegroundColor Yellow }
elseif(-not $env:SUPABASE_SERVICE_KEY){ Write-Host "ignore : SUPABASE_SERVICE_KEY non defini." -ForegroundColor Yellow }
else {
  Do1 "upload Supabase" {
    Invoke-RestMethod -Method Put -Uri $SupabaseUrl -InFile $zip -Headers @{
      "Authorization" = "Bearer $($env:SUPABASE_SERVICE_KEY)"
      "apikey"        = $env:SUPABASE_SERVICE_KEY
      "x-upsert"      = "true"
      "Content-Type"  = "application/zip"
    } | Out-Null
    Write-Host "miroir Supabase mis a jour."
  }
}

# --- 7. Deploiement Cloudflare Pages (page /info + version.json) ------------
Step "Deploiement Cloudflare Pages"
if($SkipDeploy){ Write-Host "ignore (-SkipDeploy)" -ForegroundColor Yellow }
else { Native "wrangler pages deploy" { npx --yes wrangler pages deploy web --project-name $PagesProj --commit-dirty=true } }

Step "Termine"
Write-Host "Version $Version publiee." -ForegroundColor Green
Write-Host "  GitHub  : $ghRelease"
Write-Host "  Page    : $InfoUrl"
Write-Host "  MAJ auto: le parc se mettra a jour au prochain rapport quotidien."
