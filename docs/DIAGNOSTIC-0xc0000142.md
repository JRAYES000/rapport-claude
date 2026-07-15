# Diagnostic — Rapport Claude v2.16.0 (erreur 0xc0000142 à la mise à jour)

**Date :** 15 juillet 2026 · **Analysé :** RapportClaudeSetup.zip (binaire compilé, PyInstaller / Python 3.14) + page https://reporting.claudeagency.fr/info + version.json en ligne (2.16.0)

---

## 1. Ce que fait la mise à jour aujourd'hui (reconstitué depuis le binaire)

Le ZIP ne contient pas le code source : j'ai désassemblé le bytecode Python embarqué dans l'exe pour reconstituer la logique exacte. Le flux de mise à jour (`self_update` → `install --install-silent`) est le suivant :

1. Lecture de `version.json` ; si version plus récente, téléchargement du ZIP dans `%TEMP%\RapportClaudeUpdate`, extraction.
2. Lancement de `RapportClaudeSetup.exe --install-silent` (drapeaux `CREATE_NO_WINDOW | DETACHED_PROCESS`), puis le processus appelant se termine.
3. L'installateur silencieux : supprime la tâche planifiée (`schtasks`), tue l'icône (`taskkill`), recopie l'application par-dessus `%LOCALAPPDATA%\Programs\RapportClaude` (6 tentatives), recrée la tâche planifiée, **puis lance PowerShell trois fois de suite** :
   - suppression de l'ancien raccourci Bureau ;
   - suppression du raccourci « État » ;
   - recréation du raccourci `.lnk` dans le dossier Démarrage (`_shortcut_create` : `powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; …"`).
4. Relance de l'icône `RapportClaude.exe --tray`.

## 2. Cause de l'erreur « powershell.exe (0xc0000142) »

Le code `0xc0000142` signifie *STATUS_DLL_INIT_FAILED* : powershell.exe démarre mais l'initialisation d'une DLL échoue immédiatement, et Windows affiche la boîte d'erreur que voient vos collaborateurs. Dans votre contexte, c'est la combinaison de ces facteurs, présents dans le flux ci-dessus :

**Cause principale (très probable) — blocage antivirus / EDR comportemental.** La séquence « un exe lancé depuis `%TEMP%`, sans fenêtre, détaché, qui exécute PowerShell caché pour écrire dans le dossier Démarrage » est *exactement* la signature comportementale d'un malware. Beaucoup d'antivirus (Defender ATP, ESET, Avast…) injectent une DLL dans le PowerShell enfant ou bloquent son initialisation → échec 0xc0000142, de façon intermittente selon le poste et l'antivirus. C'est cohérent avec le « parfois » que vous observez, et le développeur en avait déjà l'intuition : un commentaire du code justifie l'usage de `taskkill` « natif (pas de PowerShell/CIM, moins susceptible de déclencher l'antivirus comportemental) » — mais PowerShell est resté pour les raccourcis.

**Facteurs aggravants (confirmés dans le binaire) :**
- Les trois appels PowerShell sont lancés **sans** `creationflags=CREATE_NO_WINDOW`, depuis un parent détaché sans console : Windows doit allouer une nouvelle console (conhost) pour chacun — source connue d'échecs 0xc0000142 dans les contextes non interactifs (tâche planifiée du matin), et de « flashs » de fenêtres noires dans les autres cas.
- Ces appels sont **inutiles lors d'une mise à jour** : le chemin de l'exe ne change pas (`%LOCALAPPDATA%\Programs\RapportClaude`), donc le raccourci Démarrage existant est déjà correct. On recrée pour rien ce qui provoque l'erreur.
- Aucune suppression du mode d'erreur Windows : quand un processus enfant échoue à l'initialisation, la boîte de dialogue s'affiche chez l'utilisateur au lieu d'échouer silencieusement (l'erreur est de toute façon non bloquante : le `try/except Exception` du code l'ignore — le logiciel continue de fonctionner, seule la boîte est visible).

**À noter :** l'erreur est cosmétique (la mise à jour aboutit quand même), mais elle est anxiogène pour des collaborateurs à qui la page /info promet un outil discret et transparent.

## 3. Correctifs recommandés (fichier `correctifs_rapport_claude.py` joint)

Par ordre d'impact, à intégrer dans `rapport_claude.py` :

1. **Supprimer PowerShell du chemin de mise à jour** (correctif n°1 du fichier joint) : lors d'un `--install-silent`, ne pas toucher aux raccourcis si le `.lnk` Démarrage existe déjà et pointe vers le bon exe. À lui seul, ce correctif fait disparaître l'erreur lors des mises à jour.
2. **Supprimer PowerShell tout court** (correctif n°2) : création/suppression des `.lnk` en Python pur via COM (`ctypes` + IShellLink, sans dépendance), et résolution des dossiers spéciaux via l'API Windows. Plus rapide, plus fiable, et supprime le déclencheur antivirus à l'installation initiale aussi.
3. **`CREATE_NO_WINDOW` sur tous les sous-processus** (correctif n°3) : `schtasks`, `taskkill`, `cmd` — supprime les flashs de console résiduels.
4. **`SetErrorMode` en mode silencieux** (correctif n°4) : même si un enfant échoue encore, plus aucune boîte d'erreur n'apparaît chez l'utilisateur pendant une mise à jour de fond.
5. **Vérifier la signature Authenticode du binaire téléchargé avant de l'exécuter** (correctif n°5, sécurité) : aujourd'hui, `self_update` télécharge et exécute sans aucun contrôle d'intégrité. Si le site ou le stockage Supabase était compromis, tout le parc exécuterait du code arbitraire au prochain rapport. L'exe étant déjà signé « École de Naturopathie et Sophrologie », la vérification via `WinVerifyTrust` est fournie clé en main.

## 4. Autres points relevés (robustesse)

- **Copie « par-dessus » l'installation** (`copytree(dirs_exist_ok=True)`) : les fichiers supprimés d'une version à l'autre restent en place dans `_internal`, avec un risque de mélange de DLL entre versions (autre cause classique de 0xc0000142, cette fois sur `RapportClaude.exe`). Recommandé : vider `_internal` avant copie, ou copier vers un dossier neuf puis basculer.
- **Boîte « Impossible de copier l'application »** : vérifier qu'elle est bien inhibée quand `RC_NO_UI=1` (mise à jour de fond) ; sinon un échec de copie à 7 h du matin affiche un dialogue en plein écran de travail.
- Les garde-fous existants sont bons : anti-boucle de mise à jour (6 h), snooze utilisateur (24 h), kill-switch serveur (`"auto": false` dans version.json), 6 tentatives de copie avec `taskkill` + pause entre chaque.

## 5. Expérience utilisateur — améliorations rapides

- **Page /info** : ajouter une courte section « Dépannage » (« Une fenêtre "powershell.exe 0xc0000142" peut apparaître lors d'une mise à jour sur les versions ≤ 2.16 : elle est sans conséquence, cliquez OK. Corrigé en v2.17. ») et afficher le numéro de la version courante sur la page (déjà présent dans version.json, il suffit de l'injecter) pour que chacun vérifie s'il est à jour via l'icône tray.
- **Installation** : le parcours ZIP → « Extraire tout » → double-clic est le point de friction principal ; un exe unique auto-extractible éviterait l'étape d'extraction et les lancements ratés depuis l'aperçu du ZIP.
- **Après mise à jour** : une notification tray discrète « Mis à jour en v2.17 » rassurerait (aujourd'hui la mise à jour silencieuse est invisible, ce qui rend n'importe quelle boîte d'erreur d'autant plus suspecte).

## 6. Pour publier le correctif

Intégrer les correctifs dans `rapport_claude.py`, incrémenter `app_version` (2.17.0), recompiler/signer via `build.ps1`, téléverser le ZIP sur Supabase et mettre à jour `version.json` : le parc se mettra à jour seul au prochain rapport quotidien — et ce sera la dernière fois que l'erreur peut apparaître (elle est produite par l'ancienne version qui s'installe elle-même ; dès la v2.17 en place, les mises à jour suivantes seront propres).

---

*Sources techniques : désassemblage du bytecode de RapportClaudeSetup.exe (fonctions `self_update`, `auto_update_if_available`, `install`, `_shortcut_create`, `_shortcut_remove`, `kill_tray`) ; documentation Windows sur STATUS_DLL_INIT_FAILED ; cas connus d'antivirus bloquant PowerShell enfant ([winhelponline](https://www.winhelponline.com/blog/0xc0000142-cmd-powershell-sfc-dism/), [sevenforums](https://www.sevenforums.com/general-discussion/361169-powershell-exe-application-error-0xc0000142-2.html)).*
