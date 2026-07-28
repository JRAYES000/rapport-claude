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
client, que Julien valide en un clic dans l'onglet « Suivi client ». Dans la foulée,
`client-report` envoie à Julien **un seul email récapitulatif** (action `digest`) listant
ce qui attend sa validation et ce qui n'a pas pu être généré. Pas de brouillon en
attente et pas d'incident : pas d'email — un récapitulatif quotidien systématique
finirait par ne plus être lu. Le bouton de l'email ouvre le tableau de bord et ne
déclenche aucun envoi : un lien GET « Envoyer » serait visité tout seul par les
antivirus de messagerie, et un compte rendu partirait chez un client sans être relu.

### Personne n'ouvre GitHub

Le dépôt de livrables est une infrastructure, pas un lieu de travail. Le collaborateur
n'y a pas de compte (`push-deliverables` écrit à sa place) ; le client non plus (il
télécharge depuis sa page). Depuis le 28/07, le manager non plus : la fonction `clients`
expose deux actions d'équipe, `files` (contenu du dossier d'un client) et `getfile`
(téléchargement par **indice**, jamais par chemin), et l'onglet « Suivi client » affiche
les livrables dans la fiche. Le champ `files_n` de l'action `list` alimente la colonne
du tableau. Si on rouvre GitHub à la main, c'est que quelque chose manque dans
l'interface : l'ajouter là plutôt que prendre l'habitude d'aller voir ailleurs.

Ce que l'équipe voit et ce que le client voit ne sont pas la même liste, et il ne faut
pas les confondre : `filesOf()` rend tout le dossier du dépôt (y compris le travail du
jour), `livrablesOf()` ne rend que les fichiers cités dans un compte rendu **déjà relu
et envoyé**. Les fiches régénérées par le serveur (`LISEZ-MOI.md`, `QUESTIONNAIRE.md`,
`MISSION.md`) sont écartées de la vue équipe, et `LIENS.md` ne s'affiche qu'une fois
**rempli** : `liensRemplis()` lit le fichier et y cherche une URL. La première version
comparait sa taille à celle de `liensTemplate()` — le gabarit a changé le 28/07 et les
trois lignes vides sont aussitôt réapparues chez chaque client. Ne pas revenir à une
heuristique de taille : le gabarit bouge, une URL non.

### L'espace client (`web\client.html`)

Trois onglets — avancement, livrables, fiche — dans une seule page. L'onglet d'arrivée
dépend de l'état du dossier : « Où en est votre projet » dès qu'un compte rendu a été
envoyé, la fiche sinon. Un client qui revient chaque semaine ne doit pas retomber sur un
formulaire de treize champs.

Le **cadre d'intervention reste dans l'onglet de la fiche**, au-dessus des questions, et
pas dans un onglet à lui : c'est la seule position où le client ne peut pas envoyer sa
fiche sans l'avoir eu sous les yeux, et c'est ce qui donne sa valeur à la date
enregistrée dans `terms_accepted_at`.

`rapportPropre()` fait une petite chirurgie sur le compte rendu injecté : celui-ci est
fabriqué **pour un email** par `client-report`, donc il arrive avec sa propre enveloppe
(fond crème, largeur 640 px) et rappelle en tête la marque, la société et la date. Sans
ce nettoyage, la page affiche le nom du client trois fois et la date deux fois sur le
même écran. La fonction est défensive de bout en bout : toute structure inattendue
renvoie le HTML d'origine. Si `buildHtml()` change d'en-tête, c'est là qu'il faut
regarder.

Attention à `esc()` : il échappe le `&`, donc une entité HTML placée dans une chaîne qui
lui est passée s'affiche en toutes lettres (`&nbsp;` visible à l'écran). Dans ces
chaînes-là, utiliser un vrai caractère d'espace insécable.

### Le rattachement du travail à un client

C'est le cœur du système, et il a une histoire. Le collaborateur travaille dans
`<client>/<challenge-N>/<son prénom>` sur son PC. `work_folder()` (dans `bilan_hebdo.py`)
**s'ancre sur le segment `challenge-N`** et remonte `client/challenge/collaborateur` avec
chaque tâche. Côté serveur, `client-report` compare ce dossier au nom des clients
assignés, segment par segment.

- Ne jamais revenir à « les 3 derniers dossiers du chemin » : dès que le collaborateur
  travaille dans un sous-dossier, le nom du client sort du champ et plus rien ne se
  rattache.
- **Cowork ne remonte aucun dossier exploitable** (son `cwd` est une suite d'uuid).
  D'où le repli sur `clients.code`, cité en conversation. Ce repli est invisible dans
  l'interface depuis le 28/07 — Julien ne veut plus rien imposer au collaborateur — mais
  le code reste en base et sert toujours.

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

### Le client peut répondre

Le compte rendu lui demande régulièrement un accès ou une validation ; il répond depuis
l'onglet « Où en est votre projet ». Le message va dans `client_messages`, part aussitôt
par email au manager **et** au collaborateur assigné, et s'affiche dans la fiche. Deux
plafonds le bornent : 3000 caractères, et 10 messages par jour et par client — un lien
qui fuite ne doit pas pouvoir noyer une boîte mail.

Ouvrir la fiche marque les messages comme lus : la pastille du tableau retombe toute
seule. C'est délibéré — un compteur qui exige un clic de plus ne redescend jamais.

`clients.last_seen_at` retient la dernière ouverture de l'espace par le client, écrasée
à chaque visite. Colonne « Vu le » du tableau : elle dit lesquels décrochent. Rien
d'autre n'est enregistré sur sa navigation.

`rotate` régénère le lien personnel et remet `invited_at` à zéro. L'ancien lien meurt à
la seconde — à utiliser quand un client part, ou si son lien a pu circuler.

## Le déploiement des fonctions : une seule main

Le 28/07, un `sync.py` lancé depuis le poste a écrasé en production une version
déployée quinze secondes plus tôt depuis une session Claude. Les deux copies de
`functions/` divergeaient sans historique commun, et il a fallu reconstituer la version
perdue en lisant les fichiers qu'elle avait écrits sur le dépôt de livrables.

Tant que `functions/` n'est pas dans le dépôt git, **une seule main déploie à la fois**.
Concrètement : ne pas lancer `sync.py` sans avoir d'abord posé sur le disque les sources
fournies en fin de session. Le correctif de fond reste le même que dans les chantiers
ouverts — déporter les secrets, sortir `functions/` du `.gitignore`, et laisser git
arbitrer.

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
