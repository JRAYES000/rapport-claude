# Procédure de publication d'une version

Objectif : **une seule commande** met à jour, au même instant, la Release GitHub,
le miroir Supabase et la page de téléchargement `reporting.claudeagency.fr/info`.

## En bref

```powershell
# 1. Compiler + signer (produit dist\RapportClaudeSetup.zip)
./build.ps1

# 2. Publier partout, en une commande
./publish.ps1 -Version 2.17.0 -Notes "Correction de l'erreur powershell 0xc0000142 lors des mises à jour."
```

C'est tout. Le parc installé se mettra à jour seul au prochain rapport quotidien.

## Ce que fait `publish.ps1`

| Étape | Effet |
|---|---|
| CHANGELOG.md | Ajoute la nouvelle version en haut. |
| web/version.json | Passe la version, pointe `download` vers la **dernière GitHub Release**, garde le **miroir Supabase**. |
| web/changelog.json | Ajoute l'entrée lue par la page `/info` (section « Nouveautés »). |
| Git | `commit` + `tag vX.Y.Z` + `push`. |
| GitHub Release | Crée la Release et **y attache le ZIP signé**. |
| Supabase | Téléverse le ZIP en miroir (si `SUPABASE_SERVICE_KEY` est défini). |
| Cloudflare Pages | Déploie `web/` → la page `/info` et `version.json` sont à jour en ligne. |

## Prérequis (une fois)

- **GitHub CLI** connecté : `gh auth status` (sinon `gh auth login`).
- **Wrangler / Cloudflare** connecté (déjà le cas sur la machine de build).
- **Signature de code** : voir [`../signing/README-signature.md`](../signing/README-signature.md).
- **Miroir Supabase (optionnel)** : définir la clé de service dans la session PowerShell
  ```powershell
  $env:SUPABASE_SERVICE_KEY = "..."   # clé "service_role" du projet Supabase
  ```
  Sans elle, l'upload Supabase est simplement ignoré (la Release GitHub reste la source officielle).

## Options utiles

- `-DryRun` : montre ce qui serait fait, sans rien modifier.
- `-SkipSupabase` : ne pousse pas le miroir.
- `-SkipDeploy` : ne déploie pas Cloudflare (utile pour tester en local).

## Comment la mise à jour arrive chez les collaborateurs

L'application lit `version.json` à chaque rapport quotidien. Si la version publiée est plus
récente et que `"auto": true`, elle télécharge le ZIP depuis `download` (GitHub Release,
URL stable `releases/latest/download/RapportClaudeSetup.zip`) et s'installe silencieusement.
En cas d'indisponibilité, le champ `mirror` (Supabase) sert de repli.

> Kill-switch : mettre `"auto": false` dans `version.json` (puis redéployer) stoppe les
> mises à jour automatiques du parc sans rien désinstaller.

## Filet de sécurité CI

Le workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) vérifie à chaque push que
`bilan_hebdo.py` compile et que les JSON sont valides, et à chaque Release que le ZIP est bien
attaché et que `version.json` correspond au tag.
