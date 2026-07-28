# Journal des versions

Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/).
Ce fichier est mis à jour automatiquement par `publish.ps1` à chaque nouvelle version.

## [2.24.1] - 2026-07-28

- Correction : deux mises a jour lancees en meme temps pouvaient casser l'installation.

## [2.24.0] - 2026-07-28

- Les dossiers de travail sont crees automatiquement sur le poste, d'apres les clients assignes.
- Nouveau menu : Ouvrir mon dossier de travail.
- Les fiches MISSION.md et QUESTIONNAIRE.md sont recopiees en local.

## [2.23.0] - 2026-07-28

- Le dossier de travail est desormais depose automatiquement sur GitHub a midi, en meme temps que le rapport. Un collegue peut ainsi reprendre le travail d'un absent. Aucun fichier sensible n'est envoye.

## [2.22.0] - 2026-07-27

- Chaque travail realise est desormais rattache au dossier dans lequel il a ete fait. Cela prepare le suivi par client : le travail effectue pour un client sera identifie automatiquement, sans rien avoir a saisir.

## [2.22.0] - 2026-07-27

- Chaque travail realise est desormais rattache au dossier dans lequel il a ete fait. Cela prepare le suivi par client : le travail effectue pour un client sera identifie automatiquement, sans rien avoir a saisir.

## [2.21.0] - 2026-07-27

- Les rapports qui n'ont pas pu partir (PC eteint, panne reseau, Claude indisponible) sont a nouveau rattrapes automatiquement, jusqu'a 7 jours en arriere, et l'icone previent en cas d'echec.
- Un rapport ignore par le serveur faute d'activite detectee n'est plus compte comme envoye : il est retente et le poste remonte l'anomalie au lieu de rester silencieux.
- Application allegee : le PDF, qui n'etait plus utilise, a ete retire.

## [2.20.0] - 2026-07-15

- Correction de l'erreur « Accès refusé » à la réinstallation quand la tâche planifiée avait été créée en mode administrateur. Messages d'erreur Windows désormais lisibles, avec procédure de dépannage affichée.

## [2.19.0] - 2026-07-15

- Rattrapage automatique : un rapport qui n'a pas pu partir (PC eteint, Claude indisponible, panne reseau) est renvoye tout seul au prochain rapport, jusqu'a 7 jours en arriere.
- L'icone de la barre des taches previent discretement si un envoi a echoue et affiche les jours en attente de renvoi.
- L'email quotidien affiche l'essentiel (objectif, temps, note, synthese, conseils, taches) sans avoir a ouvrir le PDF.
- Le fuseau horaire du poste est detecte automatiquement.

## [2.17.0] - 2026-07-15

- Correction de l'erreur powershell 0xc0000142 qui pouvait apparaitre lors des mises a jour ; les fenetres de console sont supprimees et le processus de mise a jour est fiabilise.

## [2.16.0] — 2026-07-15

- Le rapport affiche le bon objectif quotidien (par collaborateur).
- La production de contenu (VSL, vidéos, images, articles SEO) est désormais classée comme travail entreprise.
- Fiabilisation de la mise à jour automatique.

## [2.15.0] — 2026-07

- **Mise à jour automatique** : le logiciel s'installe seul, silencieusement, au moment du rapport quotidien.

## [2.12.0] — 2026-06

- L'icône de la barre des tâches affiche l'état du jour ; suppression du raccourci « État » devenu inutile.

## [2.9.0] — 2026-07-07

- Notation de chaque requête (0–100) avec reformulations proposées.
- Statut par tâche (abouti / en cours / abandonné).
- Distinction temps aligné entreprise vs temps total, synthèse du jour, axe d'amélioration, tendance.
- Ces notes alimentent le Challenge du mois.

---

_Les versions antérieures à la mise en place de ce dépôt sont reconstituées à partir des notes de publication ; l'historique complet et détaillé démarre à la v2.16.0._
