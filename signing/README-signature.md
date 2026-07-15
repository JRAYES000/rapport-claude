# Signature de code — Azure Artifact Signing (ex « Trusted Signing »)

Objectif : signer `RapportClaudeSetup.exe` pour que Windows Defender / SmartScreen
fassent confiance au logiciel et cessent de le flaguer — sur **tous** les builds.

Principe : **config Azure une seule fois**, puis chaque `build.ps1` signe l'exe
automatiquement (étape déjà ajoutée au script). Certificats éphémères (3 jours)
auto-renouvelés côté Microsoft : **aucune clé ni token à stocker ou renouveler**.
Coût ≈ 10 €/mois (l'usage, pas l'acte de versionner).

---

## A. Côté Azure — À FAIRE PAR JULIEN (une seule fois)

> Implique un compte Azure, un moyen de paiement et la validation d'identité de
> l'entreprise : ces étapes ne peuvent pas être automatisées à ma place.

1. **Abonnement Azure payant** — créer/activer un abonnement « Pay-As-You-Go » sur
   https://portal.azure.com (les abonnements gratuits/essai ne sont PAS acceptés).
2. **Compte Artifact Signing** — créer la ressource **Artifact Signing account**
   dans une région **UE** (recommandé : **West Europe** → endpoint `https://weu.codesigning.azure.net`).
   SKU « Basic » suffit.
3. **Validation d'identité** — dans le compte, créer une **Identity Validation**
   d'organisation pour **Claude Agency** (raison sociale, adresse, SIREN…).
   Microsoft vérifie : **compter quelques jours**. C'est le point bloquant, à lancer en premier.
4. **Certificate profile** — une fois l'identité validée, créer un **Certificate
   Profile** de type *Public Trust* lié à cette identité.
5. **Rôle de signature** — attribuer le rôle **« Artifact Signing Certificate Profile Signer »**
   au compte qui signera (ton compte Azure, ou un service principal) sur le compte Artifact Signing
   (Access control / IAM → Add role assignment).

**À me transmettre ensuite (valeurs NON secrètes) :**
- la **région** choisie (→ endpoint, ex. West Europe = `https://weu.codesigning.azure.net`),
- le **nom du compte** Artifact Signing (`CodeSigningAccountName`),
- le **nom du certificate profile** (`CertificateProfileName`).

---

## B. Côté machine de build — je m'en occupe (une seule fois, quand A est prêt)

1. Outils de signature (installe signtool dlib + .NET 8 Runtime + VC++ redist) :
   ```powershell
   winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
   ```
2. Azure CLI (pour l'authentification de la machine) :
   ```powershell
   winget install -e --id Microsoft.AzureCLI
   ```
3. Connexion (interactive, **par Julien** — je ne saisis pas tes identifiants) :
   ```powershell
   az login
   ```
4. Copier `signing\metadata.template.json` → `signing\metadata.json` et y mettre les
   3 valeurs du point A.

> `metadata.json` ne contient **aucun secret** (pas de clé ni token : l'auth passe par `az login`).

---

## C. Ensuite — automatique

`build.ps1` détecte `signing\metadata.json` et signe l'exe après PyInstaller, avec
**horodatage** (`http://timestamp.acs.microsoft.com`) — indispensable : il fige la
validité de la signature des années, même après expiration du certificat de 3 jours.
Le ZIP distribué contient alors l'exe **signé**. Vérif : `signtool verify /pa /v`.

Cycle final : modifier l'app → `build.ps1` → exe signé → upload. Versionning illimité,
aucune action Azure répétée.
