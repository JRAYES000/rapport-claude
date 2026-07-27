"""Contrôles de la v2.21.0 : interprétation de la réponse serveur + rattrapage.

Deux logiques dont la panne est silencieuse par nature :
  - send_email : le serveur répond 200 même quand il n'enregistre rien ;
  - days_to_process : décide quels jours manqués sont renvoyés.
Lancer : python test_send_email.py
"""
import json
import os
import tempfile
from datetime import date, timedelta

import bilan_hebdo as bh

DATA = {"period_end": "2026-07-27", "total_active_minutes": 0, "total_sessions": 0,
        "total_requests": 0, "sessions": [], "min_minutes": 120}


# --- 1. « envoyé » ne doit pas vouloir dire « enregistré » ------------------
def envoi(reponse_serveur):
    bh._post_json = lambda cfg, key, payload, timeout: reponse_serveur
    return bh.send_email({}, DATA, lambda _m: None)


assert envoi({"ok": True, "db": True, "mail": True}) is True, "enregistré -> True"
assert envoi({"ok": True, "skipped": "empty"}) is False, "rapport vide ignoré -> False"
assert envoi({"ok": False, "db": False, "dbDetail": "boom"}) is False, "upsert refusé -> False"


# --- 2. file de rattrapage : les jours manqués reviennent, bornés ----------
tmp = tempfile.mkdtemp()
bh.install_dir = lambda: tmp
muet = lambda _m: None
today = date.today()


def vide():
    for f in ("retry_queue.json", "last_run.json"):
        p = os.path.join(tmp, f)
        if os.path.exists(p):
            os.remove(p)


vide()
assert bh.days_to_process(today, muet) == ([today], []), "sans historique : le jour cible seul"

# PC éteint 3 jours : les jours sautés reviennent, le plus récent d'abord.
vide()
bh.write_last_run(today - timedelta(days=4), [], [], ok=True)
jours, reportes = bh.days_to_process(today, muet)
assert jours == [today - timedelta(days=3), today - timedelta(days=2),
                 today - timedelta(days=1), today], f"jours sautés rattrapés, or {jours}"
assert reportes == [], "3 jours = plafond RETRY_PER_RUN, rien à reporter"

# Au-delà du plafond, le surplus est reporté au run suivant (durée du run bornée).
vide()
bh.write_last_run(today - timedelta(days=6), [], [], ok=True)
jours, reportes = bh.days_to_process(today, muet)
assert len(jours) == bh.RETRY_PER_RUN + 1, f"plafond non respecté : {jours}"
assert reportes, "le surplus doit rester en file"

# Un jour trop ancien est abandonné (pas de rattrapage sans fin).
vide()
bh.save_retry_queue([today - timedelta(days=bh.RETRY_MAX_AGE_DAYS + 3)])
assert bh.load_retry_queue() == [], "jour hors fenêtre purgé"

# Un échec remet bien le jour en file, relu tel quel au run suivant.
vide()
bh.save_retry_queue([today - timedelta(days=2)])
assert bh.load_retry_queue() == [today - timedelta(days=2)], "aller-retour disque"

print("OK — reponse serveur et file de rattrapage se comportent comme prevu.")
