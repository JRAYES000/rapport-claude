# Reporting Claude Agency — contexte du projet

Application de suivi de l'activité des collaborateurs sur Claude (Cowork + Claude Code),
et suivi client. Trois morceaux qui doivent rester cohérents :

| Morceau | Où | Déploiement |
|---|---|---|
| Application Windows | `bilan_hebdo.py` → exe signé | `.\build.ps1` puis `.\publish.ps1 -Version X -Notes "…"` |
| Fonctions serveur | `functions\*.ts` (Supabase Edge) | `python sync.py <slug>` puis `python check.py` |
| Site | `web\` → Cloudflare Pages | `npx wrangler pages deploy web --project-name claude-reporting` |

Projet Supabase : `ifutijlvjgkdaonxzzpi`. Site : https://reporting.claudeagency.fr
Dépôt des livrables : `JRAYES000/livrables-Claude-Agency` (privé).

**Réponds en français. Va droit au but, pas de formule d'introduction.**

---

## Comment ça marche, en une page

L'exe tourne à midi sur le poste de chaque collaborateur. Il lit les transcrits Claude
Code et Cowork de la journée, en tire des sessions de travail, puis :

1. **dépose son dossier de travail** sur GitHub via `push-deliverables` ;
2. **lit les livrables du jour** via `get-deliverables` ;
3. **demande l'évaluation IA** à `summarize` ;
4. **envoie le rapport** via `send-report` (base + email + Notion).

À 13 h locale, un `pg_cron` appelle `client-report` : un brouillon de compte rendu par
client, que Julien valide en un clic dans l'onglet « Suivi client ».

### Le rattachement du travail à un client

C'est le cœur du système, et il a une histoire. Le collaborateur travaille dans
`<client>/<challenge-N>/<son prénom>` sur son PC. `work_folder()` (dans `bilan_hebdo.py`)
**s'ancre sur le segment `challenge-N`** et remonte `client/challenge/collaborateur` avec
chaque tâche. Côté serveur, `client-report` compare ce dossier au nom des clients
assignés, segment par segment.

- Ne jamais revenir à « les 3 derniers dossiers du chemin » : dès que le collaborateur
  travaille dans un sous-dossier, le nom du client sort du champ et plus rien ne se
  rattache.
- **Cowork marche aussi, depuis le 28/07.** Son `cwd` est bien une suite d'uuid, mais le
  dossier réellement ouvert par le collaborateur est dans le fichier de session
  `local_<uuid>.json` (champ `userSelectedFolders`), frère du dossier `local_<uuid>` qui
  contient le transcrit. `cowork_cwd()` le lit et le substitue au `cwd` : rattachement
  client **et** dépôt GitHub des livrables repartent normalement. Les deux outils sont
  donc autorisés ; la seule consigne au collaborateur est d'ouvrir son dossier
  `<client>/challenge-N/<prénom>` avant de commencer.
- Le repli sur `clients.code`, cité en conversation, existe toujours en base et dans
  `client-report.ts`, mais il est invisible dans l'interface depuis le 28/07 — Julien ne
  veut plus rien imposer au collaborateur. Ne pas compter dessus.

### Objectif et coût : heures d'un côté, jours de l'autre

Depuis le 28/07/2026, le coût se calcule **par jour travaillé**, pas par heure :
`collaborator_settings.daily_rate` est un tarif **journalier** (35 € par défaut, constante
`DAY_RATE` dans `web\index.html`, reprise dans `freeze_month()` côté Postgres). Un jour
travaillé = un jour avec une remontée, quelle que soit sa durée.

L'objectif, lui, reste stocké en **minutes** (`objective_minutes`) parce que l'exe,
`summarize` et `send-report` le lisent ainsi — seul le web saisit et affiche des heures,
et multiplie par 60 avant d'appeler `set-collab-settings`. Ne pas « harmoniser » en
passant la base en heures : les trois lecteurs comparent des minutes.

Les mois figés **avant** la bascule n'ont que `hourly_rate` dans
`monthly_cost_snapshots` ; l'onglet Coûts les réaffiche en €/h. Les nouveaux gels
remplissent `days` + `daily_rate`. Ne pas recalculer l'historique.

### Numérotation des challenges

Un challenge est **local à un client** (deux clients ont chacun leur « challenge 1 »),
alors que `summarize` et `send-report` raisonnent sur un numéro **unique par
collaborateur**. `get-challenges` renumérote en continu (clients triés par `company`,
puis 1, 2, 3) et `get-deliverables` **l'appelle** pour appliquer la même règle.
Ne jamais dupliquer cette numérotation ailleurs : deux listes désalignées et les
livrables se retrouvent sous le mauvais challenge.

### Source des challenges

Les challenges viennent des **fiches clients** (`clients.answers`, questions
« Challenge 1 / 2 / 3 » remplies par le client lui-même), plus d'un README GitHub.

---

## Pièges qui ont déjà coûté cher

- **Pas de `_redirects` dans `web\`.** Le 27/07, un `_redirects` a détourné *toute*
  requête portant une query string vers `index.html` — dont `version.json?t=…`, c'est-à-dire
  le canal de mise à jour de tout le parc. Le nom du client dans le lien passe par un
  **paramètre** (`/client?c=slug&t=jeton`), pas par un segment de chemin.
- **Un déploiement Pages remplace le site EN ENTIER.** Avant tout déploiement, vérifier
  que `web\` contient bien `index.html`, `client.html`, `info.html`, `version.json`,
  `_headers`. Un fichier absent du dossier disparaît de la production.
- **`publish.ps1` pose une question interactive** avant de déployer si une page en ligne
  diffère du local. Sans réponse, il coupe **après** avoir poussé le tag et la release :
  on se retrouve avec une release publiée et un `version.json` en ligne périmé, donc
  aucun poste ne se met à jour. Toujours vérifier `version.json` en ligne après un
  `publish`.
- **`verify_jwt` doit rester `false`** pour les fonctions appelées sans jeton
  (`get-settings`, `clients`, `forgot-password`, `client-report`, `push-deliverables`,
  `get-challenges`, `get-deliverables`). `sync.py` conserve le réglage actuel ; `--public`
  le force à `false`.
- **Déployer une fonction par `PATCH { body }`** produit un bundle invalide (503 sur tous
  les appels). `sync.py` utilise `POST /functions/deploy`. Toujours enchaîner avec
  `python check.py`.
- **`reporting.claudeagency.fr` renvoie 403 au user-agent d'urllib** (Cloudflare). Tester
  les pages avec `curl` ou `Invoke-WebRequest`, pas avec urllib. Les fonctions Supabase,
  elles, répondent très bien en urllib.
- **Mailjet v3.1 répond 200 même pour un message refusé.** Le verdict est dans
  `Messages[0].Status === "success"`. `forgot-password.ts` a encore l'ancien défaut
  (`return resp.ok`).
- **Écritures GitHub séquentielles.** Deux `PUT` simultanés sur la même branche se
  répondent 409.

## Sécurité

- Les sources des fonctions contiennent encore des **secrets en dur** (Notion,
  OpenRouter, Mailjet) avec un repli `Deno.env.get(...)`. C'est pour cela que
  `functions/` est dans le `.gitignore` : au premier push, la protection GitHub avait
  bloqué le commit. **Le disque est la seule copie de ces sources — ne pas les perdre.**
  Correctif propre à faire : poser chaque secret en variable d'environnement du projet
  Supabase, retirer les valeurs en dur, redéployer, puis sortir `functions/` du
  `.gitignore`.
- `GH_TOKEN` est un secret Supabase et **ne doit jamais descendre sur un poste** : l'exe
  envoie ses fichiers à `push-deliverables`, qui est seule à écrire sur GitHub.
- `push-deliverables` refuse un dépôt **en entier** si un fichier contient un secret, et
  alerte Julien par email. Ne pas assouplir en « on dépose ce qui est propre » : le
  collaborateur croirait son travail sauvegardé.

## Manière de travailler attendue

- Vérifier en réel plutôt qu'en théorie : déployer, appeler la fonction, lire la réponse,
  purger le jeu d'essai. Un test qui n'a pas tourné ne compte pas.
- La solution la plus simple qui marche. Pas d'abstraction non demandée.
- Ne jamais dire à Julien de se reposer ou de reprendre plus tard.

## Chantiers ouverts

- Déporter les secrets en dur (≈ 1 h, voir plus haut).
- `forgot-password.ts` : lire `Messages[0].Status` au lieu de `resp.ok`.
## Jeu de démonstration — à conserver

`Boulangerie Duchene (demo)` est un **client fictif volontairement gardé en base** pour
inspecter ce que voit un client sans toucher à un vrai dossier. Ne pas le purger.

- Lien : `/client?c=boulangerie-duchene-demo&t=<jeton de la fiche>` (le jeton est dans
  l'onglet Suivi client, champ « Copier »).
- Il porte un compte rendu `status='sent'` du 27/07/2026, trois challenges à des stades
  différents, et deux livrables téléchargeables déposés dans le dépôt.
- Le compte rendu contient une **difficulté interne** : elle sert à vérifier qu'elle
  n'apparaît jamais côté client. Même chose pour le nom du collaborateur.
- **Il n'a volontairement aucun `daily_reports`** : un rapport fictif polluerait les
  moyennes de temps actif et les coûts de la vue d'ensemble. La page client lit
  `client_reports`, jamais `daily_reports` — la démo fonctionne donc sans lui.
- Le collaborateur fictif `Nomena (demo)` existe dans `users` et apparaît dans le menu
  « Assigné à » : ne pas le confondre avec le vrai Nomena au moment d'assigner un client.
