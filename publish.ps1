<#
publish.ps1 - Publier une nouvelle version en UNE commande.

Met a jour, de facon coherente et au meme instant :
  1. GitHub : tag + Release (avec le ZIP signe attache)   -> source officielle
  2. Supabase : miroir du ZIP                              -> repli de telechargement
  3. La page https://reporting.claudeagency.fr/info        -> version + changelog a jour
  4. CHANGELOG.md, web/version.json, web/changelog.json    -> versionnes dans le repo

Prerequis :
  - ./build.ps1 a produit dist\RapportClaudeSetup.zip (signe)
  - gh (GitHub CLI) connecte        : gh auth status
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
function Run($m,[scriptblock]$b){ if($DryRun){ Write-Host "[dry-run] $m" -ForegroundColor Yellow } else { & $b } }

# --- 0. Verifications -------------------------------------------------------
Step "Verifications"
if($Version -notmatch '^\d+\.\d+\.\d+$'){ throw "Version invalide : '$Version' (attendu X.Y.Z)" }
if(-not (Test-Path $zip)){ throw "Introuvable : $zip - lance d'abord ./build.ps1" }
gh auth status 1>$null 2>$null; if($LASTEXITCODE -ne 0){ throw "gh non connecte (gh auth login)" }
Write-Host "ZIP : $zip ($([math]::Round((Get-Item $zip).Length/1MB,1)) Mo)"
Write-Host "Tag : $tag   Date : $today"

# --- 1. CHANGELOG.md --------------------------------------------------------
Step "CHANGELOG.md"
$clPath = Join-Path $PSScriptRoot "CHANGELOG.md"
$cl = Get-Content $clPath -Raw -Encoding UTF8
$bulletBlock = ($Notes -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { "- " + $_.Trim() }) -join "`n"
$entry = "## [$Version] - $today`n`n$bulletBlock`n`n"
$cl = [regex]::Replace($cl, '\n## \[', "`n$entry## [", 1)
Run "ecrire CHANGELOG.md" { $cl | Set-Content $clPath -Encoding UTF8 -NoNewline }

# --- 2. web/version.json ----------------------------------------------------
Step "web/version.json"
$vjPath = Join-Path $PSScriptRoot "web\version.json"
$vj = [ordered]@{
  version   = $Version
  info_url  = $InfoUrl
  download  = $ghLatest
  mirror    = $SupabaseUrl.Replace("/object/downloads","/object/public/downloads")
  github    = $ghRelease
  auto      = $true
  notes     = $Notes
}
Run "ecrire version.json" { ($vj | ConvertTo-Json -Depth 4) | Set-Content $vjPath -Encoding UTF8 }

# --- 3. web/changelog.json (consomme par /info) -----------------------------
Step "web/changelog.json"
$cjPath = Join-Path $PSScriptRoot "web\changelog.json"
$list = @()
if(Test-Path $cjPath){ $list = @(Get-Content $cjPath -Raw -Encoding UTF8 | ConvertFrom-Json) }
$bullets = @($Notes -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
$newItem = [ordered]@{ version=$Version; date=$today; notes=$bullets }
$list = @($newItem) + $list
Run "ecrire changelog.json" { ($list | ConvertTo-Json -Depth 5) | Set-Content $cjPath -Encoding UTF8 }

# --- 4. Git : commit + tag + push ------------------------------------------
Step "Git commit + tag + push"
Run "git add/commit/tag/push" {
  git add -A
  git commit -m "release: v$Version" | Out-Null
  git tag -a $tag -m "v$Version"
  git push origin HEAD
  git push origin $tag
}

# --- 5. GitHub Release (avec ZIP) ------------------------------------------
Step "GitHub Release"
Run "gh release create" {
  gh release create $tag "$zip#RapportClaudeSetup.zip" --repo $Repo --title "v$Version" --notes $Notes
}

# --- 6. Miroir Supabase -----------------------------------------------------
Step "Miroir Supabase"
if($SkipSupabase){ Write-Host "ignore (-SkipSupabase)" -ForegroundColor Yellow }
elseif(-not $env:SUPABASE_SERVICE_KEY){ Write-Host "ignore : SUPABASE_SERVICE_KEY non defini." -ForegroundColor Yellow }
else {
  Run "upload Supabase" {
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
else { Run "wrangler pages deploy" { npx --yes wrangler pages deploy web --project-name $PagesProj --commit-dirty=true } }

Step "Termine"
Write-Host "Version $Version publiee." -ForegroundColor Green
Write-Host "  GitHub  : $ghRelease"
Write-Host "  Page    : $InfoUrl"
Write-Host "  MAJ auto: le parc se mettra a jour au prochain rapport quotidien."
