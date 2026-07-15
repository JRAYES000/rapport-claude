# Rapport d'activité Claude

Application Windows autonome de reporting d'activité **Claude** (Cowork & Claude Code),
distribuée aux collaborateurs de Claude Agency.

Une fois par jour, l'application lit **en local** l'historique des sessions Claude,
en produit un récapitulatif (temps actif, tâches, requêtes notées), génère un PDF,
l'envoie par email et alimente un tableau de bord.

- **Page collaborateurs / téléchargement :** https://reporting.claudeagency.fr/info
- **Tableau de bord :** https://reporting.claudeagency.fr/
- **Version courante :** voir [`web/version.json`](web/version.json) et [CHANGELOG.md](CHANGELOG.md)

> Ce dépôt est **public par transparence** mais le logiciel n'est pas libre — voir [LICENSE](LICENSE).
> Il ne contient **aucun secret** : les clés d'envoi (Mailjet, etc.) vivent côté serveur
> (fonctions Supabase) et ne sont jamais embarquées dans le code ni dans l'exe.

## Ce que fait l'application (en bref)

- Lit uniquement deux dossiers : `…\Claude\local-agent-mode-sessions` (Cowork) et `…\.claude\projects` (Claude Code).
- Estime le temps actif (inactivité plafonnée à 5 min), compte les requêtes, extrait la 1re demande de chaque tâche.
- Génère un PDF, l'envoie au manager et au collaborateur, l'archive dans Notion, alimente le dashboard.
- Aucune capture d'écran, aucun keylogger, aucune surveillance continue. Détail : [page /info](https://reporting.claudeagency.fr/info).

## Structure du dépôt

| Chemin | Rôle |
|---|---|
| `bilan_hebdo.py` | Code source unique de l'application. |
| `build.ps1` | Compile l'exe (PyInstaller `--onedir`) et le signe (Azure Artifact Signing). |
| `RapportClaudeSetup.spec` | Spécification PyInstaller. |
| `assets/` | Logo et icône. |
| `signing/` | Modèle de configuration et notice de signature de code (le SDK Azure n'est pas versionné). |
| `web/` | Site déployé sur Cloudflare Pages (`claude-reporting`) : `/info`, dashboard, `version.json`, `changelog.json`. |
| `publish.ps1` | **Publication en une commande** : GitHub Release + Supabase + page de téléchargement (voir ci-dessous). |
| `docs/` | Diagnostic technique, correctifs, procédure de release. |
| `sample/`, `web/*.pdf` | Exemples de rapports. |

## Compiler

```powershell
# Prérequis de signature : voir signing/README-signature.md (az login + profil de certificat)
./build.ps1
# Produit dist/RapportClaudeSetup.zip (signé)
```

## Publier une nouvelle version

Tout passe par **un seul script** qui met à jour **GitHub ET la page de téléchargement** en même temps :

```powershell
./publish.ps1 -Version 2.17.0 -Notes "Correction de l'erreur powershell 0xc0000142 lors des mises à jour."
```

Détails et fonctionnement : [docs/RELEASE.md](docs/RELEASE.md).

## Mécanisme de mise à jour automatique

L'application vérifie `https://reporting.claudeagency.fr/version.json` à chaque rapport quotidien.
Si une version plus récente y est publiée (et que `"auto": true`), elle se met à jour seule et
silencieusement. `version.json` pointe vers l'archive **de la dernière GitHub Release**
(`releases/latest/download/RapportClaudeSetup.zip`), avec un **miroir Supabase** de secours.
Publier une version = exécuter `publish.ps1` ; tout le parc suit au rapport suivant.
