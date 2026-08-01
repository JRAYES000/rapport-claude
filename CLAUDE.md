# Reporting Claude Agency — contexte du projet

Application de suivi de l'activité des collaborateurs sur Claude (Cowork + Claude Code),
et suivi client. Trois morceaux qui doivent rester cohérents :

| Morceau | Où | Déploiement |
|---|---|---|
| Application Windows | `bilan_hebdo.py` → exe signé | `.\build.ps1` puis `.\publish.ps1 -Version X -Notes "…"` |
| Fonctions serveur | `functions\*.ts` (Supabase Edge) — **dépôt privé à part**, voir Sécurité | `python sync.py <slug>` puis `python check.py` |
| Site | `web\` → Cloudflare Pages | `.\publier-le-site.ps1` (pull + vérifications + deploy) |

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
(téléchargement par **indice**, jamais par chemin). Le champ `files_n` de l'action `list`
alimente la colonne du tableau. Si on rouvre GitHub à la main, c'est que quelque chose
manque dans l'interface : l'ajouter là plutôt que prendre l'habitude d'aller voir
ailleurs.

Ce que l'équipe voit et ce que le client voit ne sont pas la même liste, et il ne faut
pas les confondre : `filesOf()` rend tout le dossier du dépôt (y compris le travail du
jour), `livrablesOf()` ne rend que les fichiers cités dans un compte rendu **déjà relu
et envoyé**.

**La fiche du tableau de bord ne liste plus les livrables** (28/07, seconde passe) : le
détail et le téléchargement sont dans l'espace client, qu'on ouvre d'un bouton. Ne
subsiste qu'un compte, et surtout `n_attente` — les fichiers déposés que `livrablesOf()`
ne rend pas encore, c'est-à-dire ceux qui attendent la validation d'un compte rendu.
C'est le seul écart entre les deux listes, donc la seule information que l'espace client
ne porte pas ; elle est dépliable pour garder le téléchargement sans rouvrir GitHub. La
fiche remplie par le client est repliée derrière son résumé, pour la même raison : elle
est affichée en entier dans l'onglet « Votre fiche client ». Ne pas remettre ces deux
listes en double, c'est ce qui rendait la page illisible. Les fiches régénérées par le serveur (`LISEZ-MOI.md`, `QUESTIONNAIRE.md`,
`MISSION.md`) sont écartées de la vue équipe, et `LIENS.md` ne s'affiche qu'une fois
**rempli** : `liensRemplis()` lit le fichier et y cherche une URL. La première version
comparait sa taille à celle de `liensTemplate()` — le gabarit a changé le 28/07 et les
trois lignes vides sont aussitôt réapparues chez chaque client. Ne pas revenir à une
heuristique de taille : le gabarit bouge, une URL non.

### Le lien d'inscription (un seul, public)

`https://reporting.claudeagency.fr/client?nouveau=1` — le **même pour tous les prospects**,
donné en prospection. La page est `client.html` en mode inscription : le questionnaire
n'existe qu'à un seul endroit, et une seconde page aurait divergé au premier ajout de
question. Il est affiché et copiable dans l'onglet « Suivi client ».

Le prospect remplit, l'action `signup` crée le client, son lien personnel part par email
(ce qui **vérifie l'adresse au passage**) et Julien reçoit une alerte. Le client arrive
**sans collaborateur assigné**, ce qui est sans danger : `client-report` ne génère que
pour les fiches assignées, donc rien ne part chez lui avant la décision de Julien. La
colonne « Assigné à » affiche une pastille `à assigner`, sinon un client resterait en
attente sans que rien ne le signale.

Ce lien n'ouvre **aucune fiche existante** — il ne fait qu'écrire. Ne jamais lui faire
lire quoi que ce soit : le jeton personnel reste la seule porte vers un espace.

Quatre garde-fous, tous vérifiés en production le 28/07 : email obligatoire et valide ;
un email déjà en base **ne crée pas de doublon** (`contact_email` est unique, on renvoie
son lien existant) ; plafond de `INSCRIPTIONS_PAR_JOUR` créations ; piège à robots (champ
`site` hors écran — le remplir renvoie `ok` sans rien créer). `slugPris()` refuse aussi
deux sociétés qui donneraient le même dossier de dépôt.

### L'espace client (`web\client.html`)

Trois onglets — avancement, livrables, fiche — dans une seule page. L'onglet d'arrivée
dépend de l'état du dossier : « Où en est votre projet » dès qu'un compte rendu a été
envoyé, la fiche sinon. Un client qui revient chaque semaine ne doit pas retomber sur un
formulaire de treize champs.

**Un canal de couleur par onglet** (`data-canal` 1/2/3/4 → terracotta, vert, ocre, bleu
ardoise), **et un canal par challenge dans l'onglet Analyse**. La
teinte n'est pas décorative : elle est reprise par les titres de section, les pastilles,
la jauge et le bouton principal du panneau, si bien que trois écrans plus bas le client
sait encore où il est. Chaque canal a **deux valeurs, et il ne faut pas les confondre** :
`--cN-ink` porte le **texte** (≥ 4,5:1) et `--cN` ne touche que des **traits et aplats**
(≥ 3:1). C'est cette confusion qui rendait le libellé de l'onglet actif illisible —
`#CC785C` sur crème ne fait que 3,07:1. Les gris ont été relus dans la foulée : les
anciens (`#7a736c`, `#8c847b`, `#adaba3`) donnaient 4,4 / 3,5 / **2,2**. `--gris-pale`
ne sert plus qu'aux bordures.

Dans l'onglet **Analyse**, chaque `<section class="ch" data-ch="1|2|3">` **redéfinit le
canal** sur sa propre teinte. Tout ce qui vit dedans lit déjà `var(--canal*)`, donc titre,
pastilles numérotées, filets des encarts et mot « Livrable » se recolorent sans une règle
de plus. Les trois teintes sont celles des autres onglets, déjà mesurées : au-delà de
trois challenges on recycle. **Ne pas inventer de quatrième teinte de challenge** — sept
couleurs à tenir pour un gain nul. Seul l'encart « Points de vigilance » échappe à la
teinte de son challenge, fond compris : son rôle prime sur son appartenance, et le filet
rouge seul disparaissait à côté de la terracotta du challenge 1.

Le contraste ne se relit pas à l'œil : `node tools/test-contraste.js` mesure les 27 paires
couleur/fond déclarées **et** vérifie que les commentaires et accolades du `<style>` sont
équilibrés — un `*/` orphelin a fait disparaître une règle entière le 29/07/2026 sans que
rien ne le signale, le navigateur sautant en silence une règle invalide.
Pour mesurer **sur le rendu** (ce que le fichier déclaré ne peut pas voir : héritage,
superposition), ouvrir la page avec un jeton et parcourir les éléments porteurs de texte
en comparant `getComputedStyle(el).color` au premier fond opaque au-dessus. Fait le
29/07/2026 sur l'onglet Analyse : 195 éléments, aucun sous le seuil.

Un `test-client.js` était annoncé ici et **n'a jamais existé** ; `tools/test-contraste.js`
le remplace. Les fichiers de test vivent dans `tools\`, pas dans `web\` : tout ce qui est
dans `web\` part en ligne et serait lisible par n'importe qui.

`rapportPropre()` retire aussi le **cadre** de la carte du compte rendu, pas seulement
son enveloppe : elle contient une carte par challenge, et garder le sien donnait des
cartes dans une carte.

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

### L'audit interne des livrables (bouton « Analyser », manager seul)

Le bouton enchaîne deux appels au modèle : une critique par fichier
(`analyze-deliverables`, mode `single`) puis la rédaction du message au
collaborateur (`messageCollaborateur` dans `clients.ts`). **Les deux échouent
séparément**, et pendant longtemps l'écran rendait la même page dans les deux cas
que pour un succès sans remarque. La réponse porte donc `diag` quand — et
seulement quand — il n'y a pas de message : modèle ayant répondu par fichier,
verdict obtenu, chemin du livrable. Ce champ ne sort que de l'action `review` ;
la réponse lue par le client ne le porte jamais, et il nomme des chemins de
dépôt. Ne pas le remettre dans une réponse publique.

Depuis le 02/08/2026 le message **annonce la note sur 100 au collaborateur**. La
pastille de note ne s'affiche donc plus que si le message est absent — sinon la
note apparaissait deux fois à trois lignes d'écart. Attention : cette note n'est
pas stable, le même fichier a été relevé à 35, 55, 65 et 70 selon le clic. Elle
était un indicateur interne ; envoyée au collaborateur, elle devient un chiffre
qu'il peut comparer d'une semaine sur l'autre.

### Le budget de tokens porte AUSSI le raisonnement

Le piège qui a coûté le plus cher le 01-02/08. `max_tokens` ne borne pas la
réponse : il borne raisonnement **plus** réponse. Un modèle qui réfléchit trop
longtemps consomme le budget entier et renvoie un `content` **vide** — pas une
erreur, pas un 4xx, pas de repli déclenché, rien dans les journaux. Une réponse
valide et vide, impossible à distinguer d'un modèle qui n'a rien à dire.

- DeepSeek V4 Flash raisonne à `high` **par défaut**. Les quatre fonctions lui
  imposent `reasoning: { effort: "low" }` via une table `OR_EFFORT` dont la clé
  doit rester **exactement** le slug de la liste des modèles, alias compris :
  c'est une égalité de chaîne, et un slug qui bouge d'un côté sans l'autre fait
  retomber le modèle à `high` sans qu'aucun appel n'échoue.
- **V4 Pro n'accepte que `high`/`xhigh`.** Sur un prompt très cadré il rend vide
  quel que soit le budget raisonnable : mesuré à 4000 tokens, vide. C'est un
  repli fragile, pas un filet. Le premier modèle a donc droit à deux essais dans
  `demander()` avant qu'on bascule.
- Ordres de grandeur mesurés le 02/08 sur le prompt du message (14 consignes,
  audit d'un fichier) : Flash en `low`, 2362 tokens de sortie. Le plafond était
  à 900. Allonger un prompt augmente le raisonnement, donc **rallonger un prompt
  oblige à relever le plafond**.

---

## Pièges qui ont déjà coûté cher

- **Pas de `_redirects` dans `web\`.** Le 27/07, un `_redirects` a détourné *toute*
  requête portant une query string vers `index.html` — dont `version.json?t=…`, c'est-à-dire
  le canal de mise à jour de tout le parc. Le nom du client dans le lien passe par un
  **paramètre** (`/client?c=slug&t=jeton`), pas par un segment de chemin.
- **Un déploiement Pages remplace le site EN ENTIER.** Avant tout déploiement, vérifier
  que `web\` contient bien `index.html`, `client.html`, `info.html`, `version.json`,
  `_headers`. Un fichier absent du dossier disparaît de la production. `publier-le-site.ps1`
  fait ce contrôle et refuse de déployer s'il en manque un.
- **Ne pas donner à Julien de commande qui suppose le bon dossier courant.** Une nouvelle
  fenêtre PowerShell s'ouvre dans `AppData\Roaming\OpenShell\Pinned` : `git pull` y répond
  « not a git repository » et wrangler cherche un `web\` qui n'existe pas. C'est arrivé
  trois fois le 28/07. Le clone est dans `%USERPROFILE%\Claude\Projects\rapport-claude` ;
  `publier-le-site.ps1` se cale sur `$PSScriptRoot` et marche depuis n'importe où.
- **`publish.ps1` pose une question interactive** si une page en ligne diffère du local.
  Deux corrections successives ont désamorcé ce piège, mais il faut savoir pourquoi :
  le garde-fou est passé **avant** le commit et le push (un abandon ne laisse donc plus
  de release orpheline avec un `version.json` périmé), et le 28/07 sa comparaison a été
  corrigée — il lisait la page en ligne en latin-1, si bien que le moindre accent la
  faisait différer et que la question se posait à **chaque** publication. Il ne se
  déclenche désormais que sur une vraie différence ; quand il parle, il faut l'écouter.
  `-ForceWeb` passe outre, à n'utiliser qu'après avoir vérifié la différence à la main.
  Vérifier `version.json` en ligne après un `publish` reste la bonne habitude.
- **Une PR faite sur GitHub ne peut pas contenir sa fonction serveur.** `functions/` est
  dans le `.gitignore` : une PR qui ajoute un appel à une nouvelle action arrive donc
  avec son front et **sans son back**, sans que rien ne le signale. C'est arrivé le
  28/07 avec la PR #1 (`files` / `getfile`), détectée seulement au moment de publier.
  Avant de déployer `web\`, vérifier que chaque action appelée existe côté serveur —
  `grep` de l'action dans `functions\` ne suffit pas, il faut la version **déployée**.
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

- **Aucun secret dans le code depuis le 29/07/2026.** Mailjet, OpenRouter, Notion,
  `GH_TOKEN` et `WORKER_KEY` sont des variables d'environnement du projet Supabase. Ne
  jamais réintroduire de valeur en dur, même en repli.
- **`functions/` est versionné, mais dans un autre dépôt** : `JRAYES000/rapport-claude-functions`,
  **privé**. Ce dépôt-ci est **public** (il porte les releases publiques de l'exe, dont
  dépend la mise à jour de tout le parc) : y publier le code serveur donnerait à lire la
  fabrication des jetons clients, les plafonds anti-abus et le nom du champ piège à
  robots. `functions/` reste donc dans le `.gitignore` d'ici, et se committe depuis
  `functions/` lui-même.
- **`account` n'écrit plus rien.** Sa v2 posait un mot de passe sur tout compte dont
  l'empreinte était vide, sans preuve qu'on possède l'adresse — trois comptes sur quatre
  étaient dans ce cas, et une réinitialisation rouvrait la même fenêtre sur n'importe
  quel compte, admin compris. Choisir un mot de passe passe **uniquement** par le lien
  envoyé par `forgot-password`, qui le pose dans la requête consommant le jeton : le
  compte n'est jamais, à aucun instant, un compte sans mot de passe. `account status` ne
  renvoie plus ni le rôle ni le nom. Ne pas rouvrir de chemin « première connexion »
  ailleurs.
- **`llm_jobs` a RLS active** (29/07/2026). Elle était la seule table sans RLS : la file
  des prompts était lisible *et écrivable* avec la clé publiable, qui est publique. Ne
  jamais désactiver RLS sur une table : les fonctions passent par la clé de service.
- Les mots de passe sont des **SHA-256 sans sel**, sans limitation de tentatives.
  C'est le prochain chantier de fond ; le mot de passe transite aussi en clair dans le
  corps de chaque requête et dort dans `sessionStorage`.
- **`WORKER_KEY` a été renouvelée le 29/07/2026.** Elle vit à trois endroits qu'il faut
  changer **ensemble**, sinon le compte rendu client quotidien s'arrête sans bruit :
  le secret Supabase, le corps du `pg_cron` `client-reports-quotidien` (la clé y est
  écrite en dur dans le `body`), et le repli du worker local
  (`…\_ANCIEN-bilan-hebdo-app-NE-PAS-UTILISER\worker\claude_worker.py`).
  L'ancienne valeur est refusée par `llm-worker`, `sign-upload` et `client-report`.
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

Un seul envoi Mailjet, deux destinataires : `alerterMessage()` construit
`[SENDER_EMAIL, assigned_email]`. Si l'un reçoit, l'autre aussi — vérifié en réel le
28/07 (`prevenu: true`, c'est-à-dire `Messages[0].Status === "success"`, pas seulement un
200). `prevenu` est renvoyé à la page : un email refusé ne doit pas passer pour un envoi.

Ouvrir la fiche marque les messages comme lus : la pastille du tableau retombe toute
seule. C'est délibéré — un compteur qui exige un clic de plus ne redescend jamais.

`clients.last_seen_at` retient la dernière ouverture de l'espace par le client, écrasée
à chaque visite. Colonne « Vu le » du tableau : elle dit lesquels décrochent. Rien
d'autre n'est enregistré sur sa navigation.

`rotate` régénère le lien personnel et remet `invited_at` à zéro. L'ancien lien meurt à
la seconde — à utiliser quand un client part, ou si son lien a pu circuler.

## Le déploiement des fonctions : git arbitre

Le 28/07, un `sync.py` lancé depuis le poste a écrasé en production une version déployée
quinze secondes plus tôt depuis une session Claude. Les deux copies de `functions/`
divergeaient sans historique commun, et il a fallu reconstituer la version perdue en
lisant les fichiers qu'elle avait écrits sur le dépôt de livrables.

Depuis le 29/07, `functions/` est versionné dans son propre dépôt privé
(`JRAYES000/rapport-claude-functions`) : c'est git qui arbitre. Avant de déployer,
`git pull` **depuis `functions/`** — c'est un dépôt à part, le `git pull` de la racine ne
le touche pas.

**En cas de doute sur ce qui tourne, `python pull.py` tranche** : il rend le source
réellement déployé, et un `diff` avec le dossier dit tout de suite si quelqu'un d'autre
est passé. C'est ce qui a servi le 29/07 quand deux sessions déployaient en parallèle :
`clients` est repartie trois fois avec les clés en dur parce qu'une session travaillait
sur une copie antérieure au nettoyage.

## Chantiers ouverts

- **Empreintes de mots de passe** : SHA-256 sans sel, sans plafond de tentatives. Passer
  à un dérivé lent (bcrypt/scrypt) et limiter les essais sur `get-settings`.
- **Le mot de passe circule en clair** dans le corps de chaque requête et dort dans
  `sessionStorage`. Un jeton de session court le remplacerait, et un XSS cesserait de
  valoir le compte.
- **`GH_TOKEN` est déjà à la portée minimale — ne pas en faire créer un autre.** C'est le
  jeton *fine-grained* `reporting-claude-agency` : accès au seul dépôt
  `livrables-Claude-Agency`, `Read and Write access to code` + `Read access to metadata`,
  aucune permission de compte. Vérifié le 29/07/2026.
  L'audit avait conclu l'inverse, et il avait tort : `analyze-deliverables.ts` portait un
  repli `Deno.env.get("GH_TOKEN") || "gho_…"` dont la valeur en dur était le jeton
  personnel du `gh` CLI (écriture sur tous les dépôts). Ce repli n'était **jamais
  atteint**, la variable d'environnement étant posée. Ne pas déduire d'une valeur en dur
  qu'elle est celle qui sert : la variable d'environnement gagne toujours. Le repli a été
  retiré du code.
- **Mailjet et OpenRouter n'ont pas été renouvelées, volontairement.** Elles n'ont jamais
  quitté le disque : rien dans l'historique des deux dépôts, vérifié sur tous les commits.
  Les renouveler couperait le seul canal d'email de l'activité pendant la bascule, pour un
  gain nul tant qu'elles ne fuient pas. À faire le jour où un poste est compromis, ou par
  hygiène annuelle. `WORKER_KEY`, elle, a bien été renouvelée le 29/07 (secret Supabase +
  corps du `pg_cron` + repli du worker local, les trois alignés et vérifiés).
- **Le cron `client-report` tourne à 10:00 UTC**, l'exe à midi *local*. Cohérent tant que
  l'équipe est en UTC+3 ; un collaborateur en France remonterait, l'hiver, après le cron,
  et son travail manquerait au compte rendu du jour.
- **`net.http_post` répond « succeeded » dès la mise en file**, pas quand `client-report`
  a réussi : les exécutions vertes de `cron.job_run_details` ne prouvent rien.
- **Les empreintes de mots de passe restent du SHA-256 sans sel**, et le mot de passe
  circule en clair dans le corps de chaque requête et dort dans `sessionStorage`. Le
  remplacer par un jeton de session court est le chantier de fond restant ; il touche la
  vérification d'identité dans neuf fonctions, donc il ne s'improvise pas en fin de
  séance. Tant que RLS tient, l'exposition suppose déjà une compromission de la base.

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
