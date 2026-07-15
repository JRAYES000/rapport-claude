<#
publish.ps1 — Publier une nouvelle version en UNE commande.

Met à jour, de façon cohérente et au même instant :
  1. GitHub : tag + Release (avec le ZIP signé attaché)   -> source officielle
  2. Supabase : miroir du ZIP                              -> repli de téléchargement
  3. La page https://reporting.claudeagency.fr/info        -> version + changelog à jour
  4. CHANGELOG.md, web/version.json, web/changelog.json    -> versionnés dans le repo

Prérequis :
  - ./build.ps1 a produit dist\RapportClaudeSetup.zip (signé)
  - gh (GitHub CLI) connecté        : gh auth status
  - npx wrangler connecté à Cloudflare
  - (miroir) variable d'env SUPABASE_SERVICE_KEY définie, sinon l'upload Supabase est ignoré

Exemples :
  ./publish.ps1 -Version 2.17.0 -Notes "Correction de l'erreur powershell 0xc0000142 lors des mises à jour."
  ./publish.ps1 -Version 2.17.0 -Notes "..." -SkipSupabase
  ./publish.ps1 -Version 2.17.0 -Notes "..." -DryRun
#>

param(
  [Parameter(Mandatory=$true)][string]$Version,
  [Parameter(Mandatory=$true)][string]$Notes,
  [switch]$SkipSupabase,
  [switch]$SkipDeploy,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
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

function Step($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Do($m,[scriptblock]$b){ if($DryRun){ Write-Host "[dry-run] $m" -ForegroundColor Yellow } else { & $b } }

# --- 0. Vérifications -------------------------------------------------------
Step "Vérifications"
if($Version -notmatch '^\d+\.\d+\.\d+$'){ throw "Version invalide : '$Version' (attendu X.Y.Z)" }
if(-not (Test-Path $zip)){ throw "Introuvable : $zip — lance d'abord ./build.ps1" }
gh auth status 1>$null 2>$null; if($LASTEXITCODE -ne 0){ throw "gh non connecté (gh auth login)" }
Write-Host "ZIP : $zip ($([math]::Round((Get-Item $zip).Length/1MB,1)) Mo)"
Write-Host "Tag : $tag   Date : $today"

# --- 1. CHANGELOG.md --------------------------------------------------------
Step "CHANGELOG.md"
$clPath = Join-Path $PSScriptRoot "CHANGELOG.md"
$cl = Get-Content $clPath -Raw -Encoding UTF8
$entry = "## [$Version] — $today`n`n- $($Notes -replace '`r?`n', "`n- ")`n`n"
# insère la nouvelle version juste avant la 1re entrée existante
$cl = $cl -replace '(?s)(\n## \[)', "`n$entry## [", 1
Do "écrire CHANGELOG.md" { $cl | Set-Content $clPath -Encoding UTF8 -NoNewline }

# --- 2. web/version.json ----------------------------------------------------
Step "web/version.json"
$vjPath = Join-Path $PSScriptRoot "web\version.json"
$vj = [ordered]@{
  version   = $Version
  info_url  = $InfoUrl
  download  = $ghLatest            # source officielle : dernière GitHub Release
  mirror    = $SupabaseUrl.Replace("/object/downloads","/object/public/downloads")  # repli
  github    = $ghRelease
  auto      = $true
  notes     = $Notes
}
Do "écrire version.json" { ($vj | ConvertTo-Json -Depth 4) | Set-Content $vjPath -Encoding UTF8 }

# --- 3. web/changelog.json (consommé par /info) -----------------------------
Step "web/changelog.json"
$cjPath = Join-Path $PSScriptRoot "web\changelog.json"
$list = @()
if(Test-Path $cjPath){ $list = @(Get-Content $cjPath -Raw -Encoding UTF8 | ConvertFrom-Json) }
$bullets = @($Notes -split "`r?`n" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
$newItem = [ordered]@{ version=$Version; date=$today; notes=$bullets }
$list = @($newItem) + $list
Do "écrire changelog.json" { ($list | ConvertTo-Json -Depth 5) | Set-Content $cjPath -Encoding UTF8 }

# --- 4. Git : commit + tag + push ------------------------------------------
Step "Git commit + tag + push"
Do "git add/commit/tag/push" {
  git add -A
  git commit -m "release: v$Version" | Out-Null
  git tag -a $tag -m "v$Version : $Notes"
  git push origin HEAD
  git push origin $tag
}

# --- 5. GitHub Release (avec ZIP) ------------------------------------------
Step "GitHub Release"
Do "gh release create" {
  gh release create $tag $zip --repo $Repo --title "v$Version" --notes $Notes
}

# --- 6. Miroir Supabase -----------------------------------------------------
Step "Miroir Supabase"
if($SkipSupabase){ Write-Host "ignoré (-SkipSupabase)" -ForegroundColor Yellow }
elseif(-not $env:SUPABASE_SERVICE_KEY){ Write-Host "ignoré : SUPABASE_SERVICE_KEY non défini." -ForegroundColor Yellow }
else {
  Do "upload Supabase" {
    Invoke-RestMethod -Method Put -Uri $SupabaseUrl -InFile $zip -Headers @{
      "Authorization" = "Bearer $($env:SUPABASE_SERVICE_KEY)"
      "apikey"        = $env:SUPABASE_SERVICE_KEY
      "x-upsert"      = "true"
      "Content-Type"  = "application/zip"
    } | Out-Null
    Write-Host "miroir Supabase mis à jour."
  }
}

# --- 7. Déploiement Cloudflare Pages (page /info + version.json) ------------
Step "Déploiement Cloudflare Pages"
if($SkipDeploy){ Write-Host "ignoré (-SkipDeploy)" -ForegroundColor Yellow }
else { Do "wrangler pages deploy" { npx --yes wrangler pages deploy web --project-name $PagesProj --commit-dirty=true } }

Step "Terminé"
Write-Host "Version $Version publiée." -ForegroundColor Green
Write-Host "  GitHub  : $ghRelease"
Write-Host "  Page    : $InfoUrl"
Write-Host "  MAJ auto: le parc se mettra à jour au prochain rapport quotidien."
