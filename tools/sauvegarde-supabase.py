# -*- coding: utf-8 -*-
"""Sauvegarde quotidienne de la base Supabase, sur le poste de Julien.

    python tools/sauvegarde-supabase.py            # sauvegarde du jour
    python tools/sauvegarde-supabase.py --verifier # relit la derniere et la controle

POURQUOI CE FICHIER. Verification du 02/08/2026 par l'API de gestion : le projet est
en plan `free`, `pitr_enabled` est a false et la liste des sauvegardes est VIDE. Il
n'existe donc aucun point de restauration. Une migration ratee ou un DELETE sans WHERE
sur `clients` et le suivi client disparait sans etape intermediaire. C'est le seul
risque du projet qui soit irreversible.

POURQUOI PAS pg_dump. Le poste n'a ni pg_dump, ni psql, ni la CLI Supabase, ni Docker,
et le mot de passe Postgres n'est expose par aucune API. L'API de gestion, elle,
execute du SQL avec le jeton qui sert deja a deployer les fonctions : aucun secret
supplementaire a poser sur le disque, rien a installer.

CE QUI EST SAUVEGARDE : toutes les tables du schema `public`, ligne par ligne, en JSON ;
plus la structure (colonnes, contraintes, index, politiques RLS, fonctions, taches cron)
dans un fichier a part. Les donnees NE QUITTENT PAS LA MACHINE : tout est ecrit dans
%USERPROFILE%\\Claude\\Backups\\supabase.

CE QUI N'EST PAS SAUVEGARDE : les fichiers du Storage, les secrets du projet et les
comptes Auth. Le Storage ne sert qu'aux telechargements publics de l'exe, qui est aussi
sur GitHub ; les secrets sont chez Supabase et connus par ailleurs ; l'application ne se
sert pas de Auth (elle a sa propre table). Si l'un des trois change, revoir cette liste.
"""
import argparse, json, os, sys, urllib.error, urllib.request
from datetime import date, datetime

PROJECT = "ifutijlvjgkdaonxzzpi"
RACINE = os.path.join(os.path.expanduser("~"), "Claude", "Backups", "supabase")
GARDER = 30                  # jours de sauvegardes conservees
PAGE = 500                   # lignes par requete : une reponse trop grosse est refusee
ICI = os.path.dirname(os.path.abspath(__file__))
JETON = os.path.join(ICI, "..", "functions", ".supabase_token")


def token():
    t = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    if t:
        return t
    with open(JETON, encoding="utf-8") as f:
        return f.read().strip()


def sql(q, jeton):
    """Execute une requete. Leve une exception explicite : une sauvegarde qui echoue
    a moitie en silence est pire que pas de sauvegarde du tout."""
    req = urllib.request.Request(
        "https://api.supabase.com/v1/projects/%s/database/query" % PROJECT,
        data=json.dumps({"query": q}).encode("utf-8"),
        headers={"Authorization": "Bearer " + jeton,
                 "Content-Type": "application/json",
                 # Cloudflare renvoie 1010 au user-agent d'urllib.
                 "User-Agent": "curl/8.4.0"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("SQL refuse (HTTP %s) : %s" % (e.code, detail))


def tables(jeton):
    r = sql("select tablename from pg_tables where schemaname = 'public' "
            "order by tablename", jeton)
    return [x["tablename"] for x in r]


def lignes(table, jeton):
    """Toutes les lignes, paginees. `to_jsonb(t)` conserve les types (dates, json,
    booleens) la ou un CSV les aurait tous aplatis en texte."""
    out, offset = [], 0
    while True:
        r = sql("select to_jsonb(t) as l from public.%s t order by 1 "
                "limit %d offset %d" % (table, PAGE, offset), jeton)
        if not r:
            break
        out.extend(x["l"] for x in r)
        if len(r) < PAGE:
            break
        offset += PAGE
    return out


STRUCTURE = {
    "colonnes": "select table_name, ordinal_position, column_name, data_type, "
                "is_nullable, column_default from information_schema.columns "
                "where table_schema='public' order by table_name, ordinal_position",
    "contraintes": "select conrelid::regclass::text as t, conname, "
                   "pg_get_constraintdef(oid) as def from pg_constraint "
                   "where connamespace='public'::regnamespace order by 1,2",
    "index": "select tablename, indexname, indexdef from pg_indexes "
             "where schemaname='public' order by 1,2",
    "politiques_rls": "select schemaname, tablename, policyname, permissive, roles, "
                      "cmd, qual, with_check from pg_policies "
                      "where schemaname='public' order by 1,2,3",
    "rls_active": "select relname, relrowsecurity from pg_class "
                  "where relnamespace='public'::regnamespace and relkind='r' order by 1",
    "fonctions": "select p.proname, pg_get_functiondef(p.oid) as def from pg_proc p "
                 "where p.pronamespace='public'::regnamespace order by 1",
    "cron": "select jobid, schedule, command, active, jobname from cron.job order by jobid",
}


def sauvegarder():
    jeton = token()
    jour = date.today().isoformat()
    dossier = os.path.join(RACINE, jour)
    os.makedirs(dossier, exist_ok=True)

    manifeste = {"projet": PROJECT, "date": jour,
                 "fait_le": datetime.now().isoformat(timespec="seconds"),
                 "tables": {}, "structure": {}, "incidents": []}

    for t in tables(jeton):
        try:
            rows = lignes(t, jeton)
        except Exception as e:
            manifeste["incidents"].append("table %s : %s" % (t, e))
            continue
        with open(os.path.join(dossier, "table-%s.json" % t), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1, default=str)
        manifeste["tables"][t] = len(rows)

    struct = {}
    for nom, q in STRUCTURE.items():
        try:
            struct[nom] = sql(q, jeton)
        except Exception as e:
            # `cron` peut ne pas exister : ce n'est pas un echec de sauvegarde.
            manifeste["incidents"].append("structure %s : %s" % (nom, e))
            continue
        manifeste["structure"][nom] = len(struct[nom])
    with open(os.path.join(dossier, "structure.json"), "w", encoding="utf-8") as f:
        json.dump(struct, f, ensure_ascii=False, indent=1, default=str)

    with open(os.path.join(dossier, "manifeste.json"), "w", encoding="utf-8") as f:
        json.dump(manifeste, f, ensure_ascii=False, indent=1)

    total = sum(manifeste["tables"].values())
    print("Sauvegarde du %s -> %s" % (jour, dossier))
    for t, n in sorted(manifeste["tables"].items()):
        print("   %-28s %6d ligne(s)" % (t, n))
    print("   %-28s %6d ligne(s) au total, %d table(s)"
          % ("TOTAL", total, len(manifeste["tables"])))
    for i in manifeste["incidents"]:
        print("   INCIDENT :", i)
    purger()
    # Une sauvegarde vide est une panne, pas un jour calme : la base n'est jamais vide.
    if total == 0:
        print("ECHEC : aucune ligne sauvegardee.", file=sys.stderr)
        return 1
    return 1 if manifeste["incidents"] else 0


def purger():
    if not os.path.isdir(RACINE):
        return
    jours = sorted(d for d in os.listdir(RACINE)
                   if os.path.isdir(os.path.join(RACINE, d)))
    for vieux in jours[:-GARDER]:
        chemin = os.path.join(RACINE, vieux)
        for f in os.listdir(chemin):
            os.remove(os.path.join(chemin, f))
        os.rmdir(chemin)
        print("   purge :", vieux)


def verifier():
    """Relit la derniere sauvegarde et la compare a la base VIVANTE. C'est la seule
    facon de savoir qu'elle vaut quelque chose : un fichier ecrit n'est pas une
    sauvegarde tant que personne ne l'a relu."""
    if not os.path.isdir(RACINE):
        print("Aucune sauvegarde.", file=sys.stderr)
        return 1
    jours = sorted(d for d in os.listdir(RACINE)
                   if os.path.isdir(os.path.join(RACINE, d)))
    if not jours:
        print("Aucune sauvegarde.", file=sys.stderr)
        return 1
    dossier = os.path.join(RACINE, jours[-1])
    with open(os.path.join(dossier, "manifeste.json"), encoding="utf-8") as f:
        man = json.load(f)
    jeton = token()
    print("Verification de", dossier)
    ko = 0
    for t, attendu in sorted(man["tables"].items()):
        chemin = os.path.join(dossier, "table-%s.json" % t)
        try:
            with open(chemin, encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            print("   KO %-26s illisible : %s" % (t, e)); ko += 1; continue
        vivant = sql("select count(*)::int as n from public.%s" % t, jeton)[0]["n"]
        etat = "ok" if len(rows) == attendu else "KO"
        if etat == "KO":
            ko += 1
        # L'ecart avec la base vivante n'est PAS une erreur : elle a bouge depuis.
        print("   %s %-26s %5d relue(s) / %5d au manifeste / %5d en base aujourd'hui"
              % (etat, t, len(rows), attendu, vivant))
    print("Structure :", "ok" if os.path.exists(os.path.join(dossier, "structure.json"))
          else "MANQUANTE")
    return 1 if ko else 0


class Journal:
    """Tout ce qui s'affiche part AUSSI dans un journal. La tache planifiee tourne sans
    fenetre : sans ce fichier, une sauvegarde qui echoue tous les jours ne se verrait
    qu'au moment ou on en aurait besoin."""

    def __init__(self, flux, chemin):
        self.flux, self.f = flux, open(chemin, "a", encoding="utf-8")

    def write(self, s):
        self.flux.write(s)
        self.f.write(s)

    def flush(self):
        self.flux.flush()
        self.f.flush()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Sauvegarde de la base Supabase.")
    p.add_argument("--verifier", action="store_true",
                   help="relit la derniere sauvegarde au lieu d'en faire une")
    a = p.parse_args()
    os.makedirs(RACINE, exist_ok=True)
    j = Journal(sys.stdout, os.path.join(RACINE, "journal.txt"))
    sys.stdout = j
    print("\n--- %s ---" % datetime.now().isoformat(timespec="seconds"))
    try:
        code = verifier() if a.verifier else sauvegarder()
    except Exception as e:
        print("ECHEC :", e)
        code = 1
    print("code de sortie :", code)
    j.flush()
    sys.exit(code)
