# Publier le site — une seule commande, depuis n'importe où.
#
# POURQUOI CE FICHIER. Une nouvelle fenêtre PowerShell s'ouvre dans le dossier des
# raccourcis de Windows, pas dans le dépôt. Taper « git pull » là-bas répond toujours
# « not a git repository », et « wrangler pages deploy web » cherche un dossier web
# qui n'existe pas. Ce script se repère tout seul : il travaille dans SON dossier,
# quel que soit celui de la fenêtre.
#
# UTILISATION — coller cette ligne, quel que soit le dossier affiché :
#   & "$HOME\Claude\Projects\rapport-claude\publier-le-site.ps1"

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
Write-Host "Dossier de travail : $PSScriptRoot" -ForegroundColor DarkGray

Write-Host "`n1/3  Récupération de la dernière version..." -ForegroundColor Cyan
git pull origin main
if ($LASTEXITCODE -ne 0) {
  Write-Host "`nLe téléchargement a échoué. Ne déploie pas : le site partirait dans un état incomplet." -ForegroundColor Red
  Write-Host "Envoie le message ci-dessus a Claude." -ForegroundColor Red
  exit 1
}

# Un déploiement Cloudflare Pages remplace le site EN ENTIER : un fichier absent du
# dossier disparait de la production. On vérifie donc avant d'envoyer, pas après.
Write-Host "`n2/3  Vérification du dossier web..." -ForegroundColor Cyan
$requis = @("index.html", "client.html", "info.html", "version.json", "_headers")
$manquants = $requis | Where-Object { -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "web\$_")) }
if ($manquants) {
  Write-Host "`nFichier(s) manquant(s) dans web\ : $($manquants -join ', ')" -ForegroundColor Red
  Write-Host "Deployer maintenant les effacerait de la production. Arret." -ForegroundColor Red
  exit 1
}
$version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot "web\version.json") -Raw | ConvertFrom-Json).version
Write-Host "     $($requis.Count) fichiers presents, version.json = $version" -ForegroundColor DarkGray

Write-Host "`n3/3  Publication sur Cloudflare..." -ForegroundColor Cyan
npx wrangler pages deploy web --project-name claude-reporting
if ($LASTEXITCODE -ne 0) {
  Write-Host "`nLa publication a echoue. Le site en ligne n'a pas change." -ForegroundColor Red
  exit 1
}

Write-Host "`nC'est en ligne : https://reporting.claudeagency.fr" -ForegroundColor Green
Write-Host "Ouvre le site en navigation privee pour voir la nouvelle version." -ForegroundColor DarkGray
