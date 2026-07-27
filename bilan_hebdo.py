#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rapport_claude.py — Application Windows autonome de reporting d'activité Claude.

Pensée pour être compilée en .exe auto-installable (PyInstaller, voir build.ps1)
et distribuée à TOUS les collaborateurs. Aucune dépendance à Claude/Cowork au
moment de l'exécution : l'app lit en LOCAL les transcripts de sessions Claude
(Cowork + Claude Code) et transmet le rapport à une fonction serveur, qui se
charge de l'enregistrement et de l'envoi de l'email.

MODES
  (aucun argument)  INSTALLATION : mini-formulaire (nom + email, nom pré-rempli
                    depuis le compte Windows), copie l'app dans %LOCALAPPDATA%,
                    crée une tâche planifiée Windows QUOTIDIENNE (par défaut 18h),
                    puis affiche une confirmation.
  --run             EXÉCUTION QUOTIDIENNE (planificateur) : collecte, extraction,
                    envoi du rapport au serveur (email au manager ET au
                    collaborateur). Si l'activité du jour est < seuil (2 h),
                    marque [ALERTE <2h] + bannière.
  --run-now         Exécute le job tout de suite (test, sans planifier).
  --uninstall       Supprime la tâche planifiée Windows.

IDENTIFICATION
  Le nom et l'email du collaborateur sont saisis une fois à l'installation et
  stockés dans config.json (dossier d'installation). Chaque machine s'identifie
  donc d'elle-même (Krassy, Alex, Julien…). L'email du MANAGER et les identifiants
  Gmail d'envoi sont, eux, embarqués dans l'exe au moment du build (communs à tous).
"""
import argparse
import html
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import datetime, date, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# Lance les sous-processus console (powershell, schtasks, taskkill, cmd) SANS
# fenêtre ni console : supprime les flashs et une cause connue de l'erreur
# « powershell 0xc0000142 » quand le parent est détaché (mise à jour silencieuse
# ou tâche planifiée).
CREATE_NO_WINDOW = 0x08000000


def _silence_child_error_dialogs():
    """En mode silencieux / planifié, empêche Windows d'afficher une boîte d'erreur
    si un processus enfant échoue à s'initialiser (ex. powershell 0xc0000142).
    Le mode d'erreur est hérité par les processus enfants."""
    try:
        import ctypes
        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

# ===========================================================================
# CONFIGURATION (les champs vides sont remplis à l'installation / au build)
# ===========================================================================
CONFIG = {
    # --- propre à chaque collaborateur (rempli à l'installation) ---
    "collaborator": "",            # ex. "Krassy"  (pré-rempli depuis Windows)
    "collaborator_email": "",      # ex. "krassy@ecole-naturo.fr"
    # --- commun à tous (embarqué au build) ---
    "manager": "Julien",
    "recipient": "contact@claudeagency.fr", # destinataire manager (info; le vrai destinataire est fixé côté serveur dans send-report)
    # Envoi d'email : délégué à une fonction serveur (Supabase Edge Function).
    # AUCUNE clé Mailjet n'est embarquée dans l'exe — elles vivent côté serveur.
    "report_function_url": "https://ifutijlvjgkdaonxzzpi.supabase.co/functions/v1/send-report",
    "install_function_url": "https://ifutijlvjgkdaonxzzpi.supabase.co/functions/v1/register-install",
    "summarize_function_url": "https://ifutijlvjgkdaonxzzpi.supabase.co/functions/v1/summarize",
    "settings_function_url": "https://ifutijlvjgkdaonxzzpi.supabase.co/functions/v1/get-settings",
    "trend_function_url": "https://ifutijlvjgkdaonxzzpi.supabase.co/functions/v1/get-trend",
    "deliverables_function_url": "https://ifutijlvjgkdaonxzzpi.supabase.co/functions/v1/get-deliverables",
    "version_url": "https://reporting.claudeagency.fr/version.json",
    # Remontée centralisée (Supabase REST, clé publique)
    "supabase_url": "https://ifutijlvjgkdaonxzzpi.supabase.co",
    "supabase_key": "sb_publishable_AMATmViFhzzEHM7t1GYHhQ_0I68c4c4",
    # --- comportement ---
    "subject_template": "Rapport quotidien {collaborator} — {start}",
    "alert_subject_prefix": "[ALERTE <2h] ",
    "timezone": "Europe/Sofia",
    "days": 1,                # 1 = rapport du jour. >1 = période glissante.
    "report_day_offset": 1,   # 1 = traite la VEILLE complète (évite la coupure de 18h)
    "min_minutes": 120,       # seuil d'alerte (2 h)
    # 12:00 et non le matin : le rapport est alors redige par l'abonnement Claude Max
    # de Julien (worker local), qui suppose son PC allume. Cf. ensure_schedule_time().
    "schedule_time": "12:00",
    "task_name": "RapportQuotidienClaude",
    "install_dirname": "RapportClaude",
    "app_version": "2.21.0",
}

# ===========================================================================
# Extraction (logique reprise de extract_sessions.py)
# ===========================================================================
IDLE_CAP_S = 300
MIN_TASK_MIN = 1
PROMPT_PREVIEW_CHARS = 800
GROUP_MIN = 3
MAX_REQUESTS = 60          # plafond de requêtes détaillées par tâche (payload)

# Rattrapage : un jour dont le rapport n'a pas pu partir (PC éteint, source
# illisible, réseau) est mémorisé et renvoyé aux runs suivants — au plus
# RETRY_MAX_AGE_DAYS en arrière, et RETRY_PER_RUN jours rattrapés par run
# (borne le temps d'exécution de la tâche planifiée).
RETRY_MAX_AGE_DAYS = 7
RETRY_PER_RUN = 3

SKIP_PREFIXES = (
    "<command-name>", "<command-message>", "<command-args>", "<local-command",
    "<system-reminder", "<bash-", "<user-prompt-submit", "<output", "<-",
    "<scheduled-task", "caveat:", "[request interrupted", "[la requete",
    "donotreply", "return exactly",
)

FR_DAYS_ABBR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FR_MONTHS = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]


def parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def to_local(dt, tz):
    if dt is None:
        return None
    if tz is not None:
        try:
            return dt.astimezone(tz)
        except Exception:
            return dt
    return dt


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                return None
        parts = [b.get("text") for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        return "\n".join(parts) if parts else None
    return None


def _clean_req_text(t):
    """Nettoie une requête pour l'affichage/notation : retire les blocs de
    pièces jointes et balises techniques injectés par Claude, sans toucher
    au texte utile."""
    t = re.sub(r"<uploaded_files>.*?</uploaded_files>", "[fichiers joints] ", t or "", flags=re.S)
    t = re.sub(r"</?(?:file|file_path|uploaded_files|attachment[a-z_]*)>", " ", t)
    return " ".join(t.split())


def is_genuine_prompt(text):
    if not text or not text.strip():
        return False
    head = text.strip()[:60].lower()
    return not any(head.startswith(p) for p in SKIP_PREFIXES)


def active_intervals(events, cap=IDLE_CAP_S):
    if not events:
        return []
    ivs = []
    a = prev = events[0]
    for e in events[1:]:
        if (e - prev).total_seconds() > cap:
            ivs.append((a, prev))
            a = e
        prev = e
    ivs.append((a, prev))
    return ivs


def union_minutes(intervals):
    if not intervals:
        return 0
    ivs = sorted(intervals, key=lambda x: x[0])
    total = 0.0
    ca, cb = ivs[0]
    for a, b in ivs[1:]:
        if a <= cb:
            if b > cb:
                cb = b
        else:
            total += (cb - ca).total_seconds()
            ca, cb = a, b
    total += (cb - ca).total_seconds()
    return total


# Serveurs MCP internes de Claude (toujours présents) : ne comptent PAS comme
# de l'outillage volontaire du collaborateur.
MCP_BUILTIN = {"cowork", "workspace", "visualize", "scheduled-tasks", "session_info",
               "skills", "mcp-registry", "plugins", "cowork-onboarding", "plugin"}


def _scan_tooling(o, skills, mcp, agents):
    """Détecte l'outillage volontaire dans une ligne de transcript :
    skills invoquées (<command-name>), sous-agents (isSidechain / outil Task),
    connecteurs MCP externes (tool_use mcp__<serveur>__...)."""
    if o.get("isSidechain"):
        agents[0] = True
    msg = o.get("message") or {}
    content = msg.get("content")
    if o.get("type") == "user" and isinstance(content, str) and "<command-name>" in content:
        for m in re.findall(r"<command-name>\s*/?([^<]{1,60})</command-name>", content):
            m = m.strip()
            if m and not m.startswith("clear"):
                skills.add("/" + m)
    if o.get("type") == "assistant" and isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                name = str(blk.get("name") or "")
                if name in ("Task", "Agent"):
                    agents[0] = True
                elif name.startswith("mcp__"):
                    parts = name.split("__")
                    srv = parts[1] if len(parts) > 1 else ""
                    if srv and srv.lower() not in MCP_BUILTIN:
                        mcp.add(srv)


def process_file(path, source, target_day, tz):
    events, prompts, assistant_texts = [], [], []
    t_skills, t_mcp, t_agents = set(), set(), [False]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                dt = to_local(parse_ts(o.get("timestamp")), tz)
                if dt is None or dt.date() != target_day:
                    continue
                events.append(dt)
                try:
                    _scan_tooling(o, t_skills, t_mcp, t_agents)
                except Exception:
                    pass
                if o.get("type") == "user" and not o.get("isSidechain") and not o.get("isMeta"):
                    msg = o.get("message") or {}
                    if msg.get("role") == "user":
                        t = extract_text(msg.get("content"))
                        if is_genuine_prompt(t):
                            prompts.append((dt, t.strip()))
                elif o.get("type") == "assistant":
                    msg = o.get("message") or {}
                    at = extract_text(msg.get("content"))
                    if at and at.strip():
                        assistant_texts.append(at.strip())
    except Exception:
        return None
    if not events or not prompts:
        return None
    events.sort()
    ivs = active_intervals(events)
    active_s = sum((b - a).total_seconds() for a, b in ivs)
    prompts.sort(key=lambda x: x[0])
    # Contenu compact de la session pour l'IA : demandes + extrait des réponses.
    user_join = "\n".join("• " + p[1][:280] for p in prompts)
    asst_tail = ("\n".join(assistant_texts))[-900:] if assistant_texts else ""
    all_text = "DEMANDES:\n" + user_join
    if asst_tail:
        all_text += "\n\nEXTRAIT DES REPONSES:\n" + asst_tail
    return {
        "source": source,
        "start_dt": events[0], "end_dt": events[-1],
        "intervals": ivs,
        "duration_min": max(MIN_TASK_MIN, int(math.ceil(active_s / 60.0))),
        "n_requests": len(prompts),
        "first_prompt": _clean_req_text(prompts[0][1])[:PROMPT_PREVIEW_CHARS],
        "all_text": all_text[:1600],
        # Liste complète des requêtes horodatées (verbatim) : sert au scoring
        # IA par requête et à la traçabilité du rapport. Plafond pour borner le payload.
        "requests": [{"t": p[0].strftime("%H:%M"), "text": _clean_req_text(p[1])[:1500]}
                     for p in prompts[:MAX_REQUESTS]],
        "tools": {"skills": sorted(t_skills)[:8], "agents": bool(t_agents[0]),
                  "mcp": sorted(t_mcp)[:8]},
    }


def hm(dt):
    return dt.strftime("%H:%M")


def _source_ready(base, tries=4, delay=3.0):
    """Vérifie qu'un dossier source est réellement accessible. Force un accès
    (`os.listdir`) — ce qui matérialise un dossier 'à la demande'/cloud ou pas
    encore prêt au démarrage — et réessaie. Plus fiable que `os.path.isdir` seul,
    qui peut renvoyer faux transitoirement (cause des '0 min' observés)."""
    for attempt in range(tries):
        try:
            os.listdir(base)
            return True
        except Exception:
            if attempt < tries - 1:
                time.sleep(delay)
    return False


def cowork_bases():
    """Candidats pour le dossier des sessions Cowork, par ordre de priorité.
    Claude étant une appli PACKAGÉE (Store/MSIX), `%APPDATA%\\Claude\\...` est une
    REDIRECTION vers `%LOCALAPPDATA%\\Packages\\Claude_xxx\\LocalCache\\Roaming\\Claude\\...`
    qui n'est résolue QUE quand Claude tourne. Le vrai dossier LocalCache, lui, est
    toujours accessible (même Claude fermé) → on le privilégie."""
    userprofile = os.environ.get("USERPROFILE", "")
    localappdata = os.environ.get("LOCALAPPDATA", "") or os.path.join(userprofile, "AppData", "Local")
    appdata = os.environ.get("APPDATA", "") or os.path.join(userprofile, "AppData", "Roaming")
    out = []
    try:
        pkgs = os.path.join(localappdata, "Packages")
        for d in sorted(os.listdir(pkgs)):
            if d.lower().startswith("claude"):
                out.append(os.path.join(pkgs, d, "LocalCache", "Roaming", "Claude", "local-agent-mode-sessions"))
    except Exception:
        pass
    out.append(os.path.join(appdata, "Claude", "local-agent-mode-sessions"))
    return out


def cowork_base():
    """Renvoie le 1er dossier Cowork réellement listable (priorité LocalCache packagé)."""
    cands = cowork_bases()
    for p in cands:
        try:
            os.listdir(p)
            return p
        except Exception:
            continue
    return cands[0] if cands else ""


def collect_files(cfg, log, lookback_days=None):
    """Liste (path, source) des transcripts Claude modifiés récemment.
    lookback_days élargit la fenêtre quand des jours anciens sont rattrapés."""
    userprofile = os.environ.get("USERPROFILE", "")
    bases = [
        (cowork_base(), "Cowork"),
        (os.path.join(userprofile, ".claude", "projects"), "Claude Code"),
    ]
    window = max(cfg["days"], lookback_days or 0)
    cutoff = datetime.now().timestamp() - (window + 2) * 86400
    files = []
    for base, source in bases:
        if not _source_ready(base):
            log(f"  (source indisponible après plusieurs essais : {base})")
            continue
        for root, _dirs, names in os.walk(base):
            for nm in names:
                if not nm.endswith(".jsonl"):
                    continue
                low = nm.lower()
                if "audit" in low or "__agent-" in nm or "_sessions_raw" in root:
                    continue
                p = os.path.join(root, nm)
                try:
                    stx = os.stat(p)
                    if stx.st_size == 0 or stx.st_mtime < cutoff:
                        continue
                except OSError:
                    continue
                files.append((p, source))
    log(f"  {len(files)} transcript(s) dans la fenetre.")
    return files


def extract_day(files, target_day, tz):
    """Renvoie (entries, active_min, n_requests, n_sessions) pour un jour."""
    raw = []
    for path, source in files:
        s = process_file(path, source, target_day, tz)
        if s:
            raw.append(s)
    if not raw:
        return [], 0, 0, 0

    groups, order = {}, []
    for s in raw:
        key = " ".join(s["first_prompt"][:60].lower().split())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)

    entries = []
    for key in order:
        g = groups[key]
        if len(g) >= GROUP_MIN:
            ivs = [iv for s in g for iv in s["intervals"]]
            merged_reqs = []
            mt_skills, mt_mcp, mt_agents = set(), set(), False
            for s in g:
                merged_reqs.extend(s.get("requests") or [])
                tl = s.get("tools") or {}
                mt_skills.update(tl.get("skills") or [])
                mt_mcp.update(tl.get("mcp") or [])
                mt_agents = mt_agents or bool(tl.get("agents"))
            merged_reqs.sort(key=lambda r: r.get("t", ""))
            entries.append({
                "kind": "batch", "source": g[0]["source"],
                "start": hm(min(s["start_dt"] for s in g)),
                "end": hm(max(s["end_dt"] for s in g)),
                "duration_min": max(MIN_TASK_MIN, int(math.ceil(union_minutes(ivs) / 60.0))),
                "n_sessions": len(g),
                "n_requests": sum(s["n_requests"] for s in g),
                "first_prompt": g[0]["first_prompt"],
                "content": "\n\n----\n\n".join(s.get("all_text", "") for s in g[:3])[:2000],
                "requests": merged_reqs[:MAX_REQUESTS],
                "tools": {"skills": sorted(mt_skills)[:8], "agents": mt_agents,
                          "mcp": sorted(mt_mcp)[:8]},
            })
        else:
            for s in g:
                entries.append({
                    "kind": "task", "source": s["source"],
                    "start": hm(s["start_dt"]), "end": hm(s["end_dt"]),
                    "duration_min": s["duration_min"], "n_sessions": 1,
                    "n_requests": s["n_requests"], "first_prompt": s["first_prompt"],
                    "content": s.get("all_text", ""),
                    "requests": s.get("requests") or [],
                    "tools": s.get("tools") or {},
                })
    entries.sort(key=lambda e: e["start"])
    active = int(math.ceil(union_minutes([iv for s in raw for iv in s["intervals"]]) / 60.0))
    return entries, active, sum(s["n_requests"] for s in raw), len(raw)


def clean_label(text, n=78):
    """Titre court, sans saut de ligne, à partir de la 1re demande (sans IA)."""
    t = " ".join((text or "").split())
    t = t.lstrip("«»\"'-—–·•:>* ").strip()
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0] + "…"
    return t or "(tâche sans intitulé)"


def build_report(cfg, tz, log, target_day, files):
    """Assemble la structure du rapport d'UNE journée (rédaction par règles,
    sans IA). Le jour cible et la liste des transcripts sont fournis par
    l'appelant (run_job), qui peut traiter plusieurs jours — le jour normal
    plus d'éventuels jours en rattrapage."""
    today = target_day

    sessions, total_requests, total_tasks = [], 0, 0
    entries, total_active, total_requests, _ns = extract_day(files, today, tz)
    for e in entries:
        total_tasks += 1
        title = clean_label(e["first_prompt"])
        if e["kind"] == "batch":
            summary = (f"Lot de {e['n_sessions']} sessions parallèles "
                       f"({e['n_requests']} requêtes) sur {e['source']}. "
                       f"Demande type : « {clean_label(e['first_prompt'], 160)} »")
        else:
            nr = e["n_requests"]
            summary = (f"{nr} requête{'s' if nr > 1 else ''} sur {e['source']}. "
                       f"Première demande : « {clean_label(e['first_prompt'], 200)} »")
        sessions.append({
            "source": e["source"], "start": e["start"], "end": e["end"],
            "duration_min": e["duration_min"], "n_requests": e["n_requests"],
            "title": title, "summary": summary, "content": e.get("content", ""),
            "category": "", "relevance": None,
            "requests": e.get("requests") or [],
            "status": "", "aligned": True,
            "tools": e.get("tools") or {},
        })
    log(f"  {today} : {total_tasks} tache(s), "
        f"{total_requests} requete(s), {total_active} min actives "
        f"(seuil {cfg['min_minutes']}).")
    return {
        "period_start": today.isoformat(), "period_end": today.isoformat(),
        "collaborator": cfg["collaborator"] or "(inconnu)", "manager": cfg["manager"],
        "total_sessions": total_tasks, "total_requests": total_requests,
        "total_active_minutes": total_active, "min_minutes": cfg["min_minutes"],
        "alert": total_active < cfg["min_minutes"], "sessions": sessions,
        # Remplis après l'évaluation IA (ai_daily / finalize_metrics / fetch_trend)
        "aligned_minutes": total_active, "n_done": 0, "n_abandoned": 0,
        "relevance_score": None, "scores": {}, "verdict": "",
        "synthesis": [], "advice": [], "strength": "", "trend": [],
        "n_tooled": 0, "tooling_score": None, "habit": "",
        "deliverables": None,
    }


# ===========================================================================
# Email (Mailjet API) + remontée centrale (Supabase REST)
# ===========================================================================
def _recipients(cfg):
    out = []
    for addr in (cfg.get("recipient", ""), cfg.get("collaborator_email", "")):
        addr = (addr or "").strip()
        if addr and addr not in out:
            out.append(addr)
    return out


def _post_json(cfg, url_key, payload, timeout):
    """POST JSON authentifié (clé publiable) vers une fonction serveur.
    Renvoie la réponse décodée (dict). Lève en cas d'erreur réseau/config —
    chaque appelant garde sa propre stratégie de repli."""
    url = (cfg.get(url_key) or "").strip()
    key = (cfg.get("supabase_key") or "").strip()
    if not (url and key):
        raise ValueError("config manquante : " + url_key)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


def send_email(cfg, data, log):
    """Délègue l'envoi de l'email à la fonction serveur (Supabase Edge Function).
    L'exe ne détient AUCUNE clé Mailjet : seules la clé publiable Supabase et
    l'URL de la fonction sont transmises. Le serveur ajoute le destinataire
    manager, l'expéditeur, et appelle Mailjet avec les secrets stockés côté serveur."""
    # Payload complet : la fonction serveur fait l'UPSERT en base (clé service) ET l'email.
    # L'exe n'écrit plus directement dans Supabase (RLS fermée à la clé publiable).
    payload = {
        "collaborator": cfg.get("collaborator") or "(inconnu)",
        "collaborator_email": cfg.get("collaborator_email") or "",
        "report_date": data["period_end"],
        "active_minutes": data["total_active_minutes"],
        "aligned_minutes": data.get("aligned_minutes"),
        "n_tasks": data["total_sessions"],
        "n_requests": data["total_requests"],
        "min_minutes": data.get("min_minutes", 120),
        "under_threshold": bool(data.get("alert")),
        "synthesis": data.get("synthesis") or [],
        "advice": data.get("advice") or [],
        "strength": data.get("strength") or "",
        "verdict": data.get("verdict") or "",
        "habit": data.get("habit") or "",
        "deliverables": data.get("deliverables"),
        "scores": data.get("scores") or {},
        "tooling_score": data.get("tooling_score"),
        "n_done": data.get("n_done", 0),
        "n_abandoned": data.get("n_abandoned", 0),
        "tasks": [{"title": s["title"], "duration_min": s["duration_min"],
                   "source": s["source"], "n_requests": s["n_requests"],
                   "start": s["start"], "end": s["end"],
                   "summary": s["summary"], "content": s.get("content", ""),
                   "category": s.get("category", ""),
                   "status": s.get("status") or None,
                   "aligned": bool(s.get("aligned", True)),
                   "tools": s.get("tools") or {},
                   # Requêtes verbatim conservées pour la traçabilité Notion.
                   # Plus de notes par requête (scoring global).
                   "requests": [{"t": r.get("t", ""), "text": (r.get("text") or "")[:300]}
                                for r in (s.get("requests") or [])[:MAX_REQUESTS]]}
                  for s in data["sessions"]],
        "machine": os.environ.get("COMPUTERNAME") or "",
        "app_version": cfg.get("app_version", ""),
    }
    out = _post_json(cfg, "report_function_url", payload, 120)
    log("  [envoi] rapport transmis à la fonction serveur (upsert + email côté serveur).")
    log("  [envoi] réponse : " + json.dumps(out, ensure_ascii=False)[:200])
    # Le serveur répond 200 même quand il ignore un rapport vide (0 tâche / 0 min :
    # protection anti-écrasement) ou quand l'upsert échoue. Sans ce contrôle, un poste
    # qui ne voit AUCUN transcript remonte "ok" indéfiniment (cas SOLOHERY, 3 semaines
    # de silence invisible). On distingue donc "envoyé" de "enregistré".
    if out.get("skipped"):
        log("  [envoi] ATTENTION : rapport ignoré par le serveur (" + str(out.get("skipped"))
            + ") — aucun transcript Claude détecté sur ce poste.")
        return False
    if out.get("db") is False:
        log("  [envoi] ATTENTION : écriture en base refusée — " + str(out.get("dbDetail"))[:200])
        return False
    return True


def ping_install(cfg, log=None, run_status=None, report_date=None):
    """Signale au serveur que ce poste est installé/actif (table installations).
    Permet à l'admin de voir un collaborateur dès l'installation, avant le 1er rapport.
    Si run_status est fourni, enregistre aussi le statut de la dernière exécution
    (santé : 'ok' / 'error' + date du rapport) pour distinguer panne vs inactivité."""
    payload = {
        "collaborator": cfg.get("collaborator") or "(inconnu)",
        "collaborator_email": cfg.get("collaborator_email") or "",
        "machine": os.environ.get("COMPUTERNAME") or "",
        "app_version": cfg.get("app_version", ""),
    }
    if run_status:
        payload["last_run_status"] = run_status
    if report_date:
        payload["last_report_date"] = report_date
    try:
        _post_json(cfg, "install_function_url", payload, 30)
        if log:
            log("  [poste] enregistrement/heartbeat OK.")
        return True
    except Exception as e:
        if log:
            log(f"  [poste] enregistrement échoué : {e}")
        return False


def ensure_schedule_time(log=None):
    """Aligne l'heure de la tâche planifiée sur CONFIG["schedule_time"].

    Les postes installés avant un changement d'heure gardent l'ancienne : cet appel,
    joué à chaque exécution, les corrige tout seuls. `schtasks /Change /ST` ne touche
    que l'heure de départ, tout le reste de la tâche (rattrapage, batterie) est conservé.
    """
    want = CONFIG.get("schedule_time", "12:00")
    try:
        # ponytail: applique sans lire l'heure courante — /Change est idempotent et
        # /Query renverrait un format dépendant de la langue de Windows.
        subprocess.run(["schtasks", "/Change", "/TN", CONFIG["task_name"], "/ST", want],
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        if log:
            log(f"  [planification] heure non ajustée ({e}).")


def fetch_objective(cfg, log=None):
    """Lit l'objectif (minutes/jour) défini côté serveur (page Réglages admin).
    Permet de changer le seuil sans recompiler/réinstaller l'exe. Repli sur la valeur locale."""
    try:
        out = _post_json(cfg, "settings_function_url",
                         {"collaborator": cfg.get("collaborator") or ""}, 20)
        m = int(out.get("objective_minutes") or 0)
        if m > 0:
            return m
    except Exception as e:
        if log:
            log(f"  [objectif] lecture serveur échouée ({e}) -> valeur locale conservée.")
    return None


def _tooling_from(sessions):
    """Part du temps (sessions >= 15 min) passée en sessions outillées
    (au moins une skill / sous-agent / connecteur MCP)."""
    def _tooled(s):
        tl = s.get("tools") or {}
        return bool(tl.get("skills")) or bool(tl.get("agents")) or bool(tl.get("mcp"))
    for s in sessions:
        s["tooled"] = _tooled(s)
    tw = tm = 0
    for s in sessions:
        dm = int(s.get("duration_min") or 0)
        if dm >= 15:
            tm += dm
            if s["tooled"]:
                tw += dm
    return sum(1 for s in sessions if s["tooled"]), (int(round(100.0 * tw / tm)) if tm else None)


def ai_daily(cfg, data, log):
    """UNE seule évaluation IA globale du jour (fonction `summarize` mode=daily) :
    3 sous-notes (formulation / maîtrise / pugnacité) + note globale + verdict
    franc, résumés par tâche en langage dirigeant, statut par tâche, synthèse,
    conseils et point fort. Remplace l'ancien scoring par requête (qui échouait
    sur les journées à fort volume). Repli mécanique si l'IA est indisponible."""
    sessions = data.get("sessions") or []
    if not sessions:
        return False
    # Outillage factuel (calculé en local, transmis à l'IA comme ancrage « maîtrise »).
    data["n_tooled"], data["tooling_score"] = _tooling_from(sessions)
    payload = {
        "mode": "daily",
        "collaborator": data.get("collaborator") or "",
        "date": data.get("period_end") or "",
        "active_minutes": data.get("total_active_minutes", 0),
        "aligned_minutes": None,  # calculé après (dépend du flag aligned par tâche)
        "objective_minutes": data.get("min_minutes", 120),
        "tooling_score": data.get("tooling_score"),
        "tasks": [{"title": s["title"], "summary": s["summary"], "source": s["source"],
                   "duration_min": s.get("duration_min", 0), "n_requests": s["n_requests"],
                   "content": s.get("content", ""), "tools": s.get("tools") or {},
                   "requests": [{"t": r.get("t", ""), "text": (r.get("text") or "")[:180]}
                                for r in (s.get("requests") or [])[:MAX_REQUESTS]]}
                  for s in sessions],
    }
    try:
        out = _post_json(cfg, "summarize_function_url", payload, 180)
    except Exception as e:
        log(f"  [IA] évaluation indisponible ({e}) -> résumé mécanique conservé.")
        return False
    rt = out.get("tasks") or []
    if out.get("ai") and len(rt) == len(sessions):
        byi = {}
        for x in rt:
            try:
                byi[int(x.get("i"))] = x
            except Exception:
                pass
        for i, s in enumerate(sessions):
            x = byi.get(i) or (rt[i] if i < len(rt) else {})
            if (x.get("title") or "").strip():
                s["title"] = x["title"].strip()
            if (x.get("summary") or "").strip():
                s["summary"] = x["summary"].strip()
            if (x.get("category") or "").strip():
                s["category"] = x["category"].strip()
            st = (x.get("status") or "").strip()
            if st in ("abouti", "en_cours", "abandonne"):
                s["status"] = st
            if isinstance(x.get("aligned"), bool):
                s["aligned"] = x["aligned"]
        sc = out.get("scores") or {}
        if sc:
            data["scores"] = {k: int(sc.get(k)) for k in
                              ("formulation", "mastery", "pugnacity", "global")
                              if isinstance(sc.get(k), (int, float))}
            data["relevance_score"] = data["scores"].get("global")
        data["verdict"] = str(out.get("verdict") or "").strip()[:400]
        data["synthesis"] = [str(x).strip() for x in (out.get("synthesis") or []) if str(x).strip()][:4]
        data["advice"] = [str(x).strip() for x in (out.get("advice") or []) if str(x).strip()][:3]
        data["strength"] = str(out.get("strength") or "").strip()[:300]
        data["habit"] = str(out.get("habit") or "").strip()[:300]
        log(f"  [IA] évaluation globale du jour ({len(sessions)} tâche(s)) : "
            f"global {data.get('relevance_score')}/100.")
        return True
    log(f"  [IA] évaluation non appliquée ({out.get('detail', '')}) -> résumé mécanique conservé.")
    return False


def finalize_metrics(data):
    """Après l'évaluation IA : temps ALIGNÉ entreprise (les tâches hors périmètre
    ne comptent pas pour l'objectif), tâches abouties, et alerte d'objectif."""
    sessions = data.get("sessions") or []
    tot = sum(int(s.get("duration_min") or 0) for s in sessions)
    ali = sum(int(s.get("duration_min") or 0) for s in sessions if s.get("aligned", True))
    if tot > 0:
        aligned = int(round(data["total_active_minutes"] * (ali / float(tot))))
    else:
        aligned = data["total_active_minutes"]
    data["aligned_minutes"] = min(aligned, data["total_active_minutes"])
    data["n_done"] = sum(1 for s in sessions if s.get("status") == "abouti")
    data["n_abandoned"] = sum(1 for s in sessions if s.get("status") == "abandonne")
    if data.get("tooling_score") is None:
        data["n_tooled"], data["tooling_score"] = _tooling_from(sessions)
    data["alert"] = data["aligned_minutes"] < data.get("min_minutes", 120)


def fetch_deliverables(cfg, data, log):
    """Livrables déposés par le collaborateur sur le dépôt GitHub
    (livrables-challenges) pendant la journée du rapport. Interrogé via la
    fonction serveur get-deliverables (le jeton GitHub reste côté serveur).
    Repli silencieux : section omise du rapport."""
    collab = cfg.get("collaborator") or ""
    if not collab:
        return False
    try:
        out = _post_json(cfg, "deliverables_function_url",
                         {"collaborator": collab, "date": data.get("period_end")}, 45)
        if out.get("ok"):
            items = out.get("items") or []
            # heure locale d'affichage (l'API renvoie de l'UTC ISO)
            tz = get_tz(cfg)
            for it in items:
                try:
                    dt = to_local(parse_ts(it.get("time")), tz)
                    it["hm"] = dt.strftime("%H:%M") if dt else ""
                except Exception:
                    it["hm"] = ""
            data["deliverables"] = {"folder": out.get("folder"), "items": items}
            log(f"  [livrables] {len(items)} fichier(s) déposé(s) sur GitHub"
                + (f" (dossier {out.get('folder')})." if out.get("folder") else " (pas de dossier)."))
            return True
    except Exception as e:
        log(f"  [livrables] indisponible ({e}) -> section omise.")
    return False


def fetch_trend(cfg, data, log):
    """Tendance : derniers jours enregistrés côté serveur (minutes + pertinence)
    pour le bloc comparatif du rapport. Repli silencieux : section omise."""
    collab = cfg.get("collaborator") or ""
    if not collab:
        return False
    try:
        out = _post_json(cfg, "trend_function_url", {"collaborator": collab, "limit": 8}, 30)
        days = out.get("days") or []
        # Exclut le jour du rapport (sera upserté après) et garde 6 jours max.
        days = [d for d in days if d.get("report_date") != data.get("period_end")][:6]
        days.reverse()  # chronologique
        data["trend"] = days
        log(f"  [tendance] {len(days)} jour(s) d'historique récupéré(s).")
        return True
    except Exception as e:
        log(f"  [tendance] indisponible ({e}) -> section omise.")
        return False


# ===========================================================================
# Chemins / config
# ===========================================================================
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def install_dir():
    # Emplacement standard des applis par-utilisateur (comme VS Code, Slack) : moins
    # suspect pour l'antivirus que %LOCALAPPDATA%\<App> directement.
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", CONFIG["install_dirname"])


def _old_install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, CONFIG["install_dirname"])


def schedule_time_label():
    """« 07:00 » -> « 7 h », « 18:30 » -> « 18 h 30 » (affichage utilisateur)."""
    st = str(CONFIG.get("schedule_time", "12:00"))
    try:
        h, m = int(st[:2]), int(st[3:5])
        return f"{h} h" + (f" {m:02d}" if m else "")
    except Exception:
        return st


# ---------------------------------------------------------------------------
# Rattrapage & statut de run (fichiers d'état dans le dossier d'installation)
# ---------------------------------------------------------------------------
def _retry_queue_path():
    return os.path.join(install_dir(), "retry_queue.json")


def _last_run_path():
    return os.path.join(install_dir(), "last_run.json")


def load_retry_queue():
    """Jours (objets date) en attente de renvoi, bornés à RETRY_MAX_AGE_DAYS.
    utf-8-sig et non utf-8 : un fichier réécrit à la main pendant un dépannage
    (Set-Content de PowerShell ajoute un BOM) ferait échouer json.load, et la
    file serait silencieusement vidée — les jours en attente perdus sans trace."""
    try:
        with open(_retry_queue_path(), "r", encoding="utf-8-sig") as fh:
            raw = (json.load(fh) or {}).get("days") or []
    except Exception:
        return []
    out = set()
    for s in raw:
        try:
            d = date.fromisoformat(str(s))
        except Exception:
            continue
        if 0 <= (date.today() - d).days <= RETRY_MAX_AGE_DAYS:
            out.add(d)
    return sorted(out)


def save_retry_queue(days):
    try:
        with open(_retry_queue_path(), "w", encoding="utf-8") as fh:
            json.dump({"days": sorted(d.isoformat() for d in set(days))}, fh)
    except Exception:
        pass


def read_last_run():
    try:
        with open(_last_run_path(), "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def write_last_run(target, sent, failed, ok):
    """Statut consommé par l'icône de la barre des tâches (notification d'échec)
    et par le run suivant (détection des jours jamais traités : PC éteint)."""
    try:
        with open(_last_run_path(), "w", encoding="utf-8") as fh:
            json.dump({
                "at": datetime.now().isoformat(),
                "target": target.isoformat(),
                "sent": sorted(d.isoformat() for d in sent),
                "failed": sorted(d.isoformat() for d in failed),
                "ok": bool(ok),
            }, fh)
    except Exception:
        pass


def days_to_process(target, log):
    """Jours à traiter pour ce run : la file de rattrapage, plus les jours
    jamais traités depuis le dernier run (PC resté éteint), plus le jour cible.
    Les jours en rattrapage sont plafonnés (les plus récents d'abord) pour
    borner la durée du run ; le surplus reste en file pour le run suivant."""
    pending = set(load_retry_queue())
    last_target = (read_last_run() or {}).get("target")
    if last_target:
        try:
            d = date.fromisoformat(str(last_target)) + timedelta(days=1)
            while d < target:
                if (date.today() - d).days <= RETRY_MAX_AGE_DAYS:
                    pending.add(d)
                d += timedelta(days=1)
        except Exception:
            pass
    pending.discard(target)
    retro = sorted(pending, reverse=True)[:RETRY_PER_RUN]
    deferred = sorted(set(pending) - set(retro))
    if retro:
        log(f"  [rattrapage] jour(s) à renvoyer : {', '.join(d.isoformat() for d in sorted(retro))}"
            + (f" (+{len(deferred)} reporté(s) au prochain run)" if deferred else ""))
    return sorted(retro) + [target], deferred


def load_config():
    # config.json ne fournit QUE l'identité du collaborateur. Tout le reste
    # (app_version, URLs des fonctions, clés, objectif par défaut) provient de
    # l'exe courant (CONFIG) afin qu'une mise à jour prenne toujours effet et
    # que la version remontée soit bien celle de l'exe installé.
    cfg = dict(CONFIG)
    ALLOW = ("collaborator", "collaborator_email")
    for d in (app_dir(), install_dir(), _old_install_dir()):
        p = os.path.join(d, "config.json")
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                for k in ALLOW:
                    if data.get(k):
                        cfg[k] = data[k]
            except Exception:
                pass
    return cfg


def get_tz(cfg):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(cfg["timezone"])
        except Exception:
            return None
    return None


def msgbox(text, title="Rapport d'activité Claude", style=0x40):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, style)
    except Exception:
        print(f"{title}: {text}")


def default_name():
    """Nom pré-rempli : nom complet du compte Windows, sinon login nettoyé."""
    try:
        import ctypes
        size = ctypes.c_ulong(0)
        ctypes.windll.secur32.GetUserNameExW(3, None, ctypes.byref(size))  # NameDisplay
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value)
            if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)) and buf.value.strip():
                return buf.value.strip()
    except Exception:
        pass
    u = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    return u.replace(".", " ").replace("_", " ").strip().title()


def ask_identity(def_name, def_email=""):
    """Mini-formulaire (nom + email). Renvoie dict ou None si indisponible/annulé."""
    try:
        import tkinter as tk
    except Exception:
        return None
    res = {}
    root = tk.Tk()
    root.title("Rapport d'activité Claude — installation")
    root.geometry("440x250")
    root.resizable(False, False)
    tk.Label(root, text="Confirmez vos informations",
             font=("Segoe UI", 12, "bold")).pack(pady=(18, 2))
    tk.Label(root, text="Elles servent à identifier vos rapports d'activité\net à vous en envoyer une copie.",
             fg="#555", justify="center").pack()
    frm = tk.Frame(root); frm.pack(padx=20, pady=12, fill="x")
    tk.Label(frm, text="Nom / prénom :").grid(row=0, column=0, sticky="w", pady=6)
    e_name = tk.Entry(frm, width=32); e_name.grid(row=0, column=1, pady=6)
    e_name.insert(0, def_name or "")
    tk.Label(frm, text="Votre email :").grid(row=1, column=0, sticky="w", pady=6)
    e_mail = tk.Entry(frm, width=32); e_mail.grid(row=1, column=1, pady=6)
    e_mail.insert(0, def_email or "")

    def ok():
        res["collaborator"] = e_name.get().strip()
        res["collaborator_email"] = e_mail.get().strip()
        root.destroy()

    tk.Button(root, text="Valider et installer", command=ok,
              width=24, height=1).pack(pady=10)
    try:
        root.attributes("-topmost", True)
        e_name.focus_set()
    except Exception:
        pass
    root.mainloop()
    return res or None


# ===========================================================================
# Job
# ===========================================================================
def run_job(test=False):
    cfg = load_config()
    tz = get_tz(cfg)
    idir = install_dir()
    logs = os.path.join(idir, "logs")
    os.makedirs(logs, exist_ok=True)
    logpath = os.path.join(logs, f"run_{date.today().isoformat()}.log")
    lf = open(logpath, "a", encoding="utf-8")

    def log(m):
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {m}"
        lf.write(line + "\n"); lf.flush()
        try:
            print(line)
        except Exception:
            try:
                print(line.encode("ascii", "replace").decode("ascii"))
            except Exception:
                pass

    log(f"=== RUN (test={test}) collaborateur={cfg.get('collaborator')!r} ===")
    ping_install(cfg, log)
    try:
        # Jour cible (la veille complète) + jours en attente de rattrapage
        # (runs en échec précédents, PC resté éteint).
        target = to_local(datetime.now().astimezone(), tz).date() - timedelta(
            days=cfg.get("report_day_offset", 0))
        days, deferred = days_to_process(target, log)
        # Abandon si le dossier Cowork est illisible : on n'envoie RIEN plutôt que d'envoyer
        # 0 (qui écraserait une journée déjà enregistrée). Le dossier Code seul ne suffit pas.
        # Les jours concernés sont mis en file : ils seront renvoyés au prochain run.
        _cowork = cowork_base()
        if not _source_ready(_cowork):
            log("  [abandon] dossier Cowork illisible — run abandonné (aucune donnée envoyée, "
                "pas d'écrasement). Jour(s) mis en file de rattrapage.")
            save_retry_queue(set(days) | set(deferred))
            write_last_run(target, [], days, ok=False)
            try:
                ping_install(cfg, log, run_status="error")
            except Exception:
                pass
            log("=== FIN (abandon : source Cowork illisible) ===")
            if test:
                msgbox("Le dossier de Claude (Cowork) est momentanément illisible.\n"
                       "Réessaie dans un instant.", "Rapport Claude")
            return 0
        # Objectif quotidien : lu côté serveur (par collaborateur) pour que le rapport
        # affiche le même seuil que le tableau de bord (sinon l'exe garderait le
        # défaut local 120 min et le rapport pourrait contredire le dashboard).
        try:
            m = fetch_objective(cfg, log)
            if m:
                cfg["min_minutes"] = m
                log(f"  [objectif] seuil serveur appliqué : {m} min.")
        except Exception as e:
            log(f"  [objectif] lecture échouée ({e}) -> seuil local conservé.")
        # Une seule collecte de transcripts pour tous les jours du run : la
        # fenêtre est élargie jusqu'au plus ancien jour rattrapé.
        lookback = (date.today() - min(days)).days
        files = collect_files(cfg, log, lookback)
        sent_days, failed_days = [], []
        data = None  # rapport du jour CIBLE (pour le msgbox de test)
        for day in days:
            retro = (day != target)
            tag = ("rattrapage " if retro else "") + day.isoformat()
            try:
                d = build_report(cfg, tz, log, day, files)
                if retro and not d["sessions"]:
                    # Un jour rattrapé sans activité n'apporte rien (le serveur
                    # ignore de toute façon les rapports vides) : on le lâche.
                    log(f"  [rattrapage] {day} : aucune activité — rien à renvoyer.")
                    continue
                # Évaluation IA GLOBALE du jour (une seule requête) AVANT l'envoi ->
                # base, Notion et email identiques. Note globale + 3 sous-notes,
                # verdict, résumés dirigeant, conseils.
                try:
                    ai_daily(cfg, d, log)
                except Exception as e:
                    log(f"  [IA] échec ({tag}) : {e}")
                # Temps aligné, tâches abouties/abandonnées, alerte (sur le temps aligné).
                try:
                    finalize_metrics(d)
                except Exception as e:
                    log(f"  [métriques] échec ({tag}) : {e}")
                # Livrables déposés sur GitHub pendant la journée (pour le rapport + serveur).
                try:
                    fetch_deliverables(cfg, d, log)
                except Exception as e:
                    log(f"  [livrables] échec ({tag}) : {e}")
                # Tendance des derniers jours (serveur) pour le bloc comparatif du rapport.
                try:
                    fetch_trend(cfg, d, log)
                except Exception as e:
                    log(f"  [tendance] échec ({tag}) : {e}")
                # L'upsert en base ET l'email sont faits côté serveur par send-report
                # (clé service). L'exe ne touche plus directement à Supabase.
                # send_email ne renvoie True que si le serveur a RÉELLEMENT
                # enregistré : un rapport vide ignoré remet le jour en file.
                if send_email(cfg, d, log):
                    sent_days.append(day)
                else:
                    log(f"  [envoi] {tag} : non enregistré -> jour mis en file de rattrapage.")
                    failed_days.append(day)
                if not retro:
                    data = d
            except Exception as e:
                log(f"  [envoi] ÉCHEC ({tag}) : {e} -> jour mis en file de rattrapage.")
                failed_days.append(day)
        save_retry_queue(set(failed_days) | set(deferred))
        sent = target in sent_days
        write_last_run(target, sent_days, failed_days, ok=sent)
        try:
            ping_install(cfg, log, run_status=("ok" if sent else "error"),
                         report_date=target.isoformat())
        except Exception:
            pass
        # Mise à jour forcée à distance : à la fin du rapport quotidien, si une
        # version plus récente est publiée, on l'installe silencieusement et on
        # sort tout de suite (l'exe --run doit se terminer pour libérer ses
        # fichiers, que l'installateur remplace). Garantit que tout le parc est
        # à la dernière version sans intervention des collaborateurs.
        if not test:
            try:
                if auto_update_if_available(cfg, log):
                    log("=== MAJ auto lancée — fin du run pour libérer les fichiers ===")
                    return 0
            except Exception as e:
                log(f"  [maj] auto-update ignorée : {e}")
        log("=== FIN ===")
        if test:
            # data peut être None si le jour cible n'a produit aucun rapport.
            chiffres = (f"{data['total_sessions']} tâche(s), {data['total_active_minutes']} min actives"
                        f" — {'ALERTE <2h' if data['alert'] else 'objectif atteint'}."
                        if data else "Aucune activité Claude détectée pour ce jour.")
            rattrapes = [d for d in sent_days if d != target]
            msgbox(f"Rapport généré :\n"
                   f"Collaborateur : {cfg.get('collaborator') or '(non défini)'}\n"
                   f"{chiffres}\n"
                   + (f"{len(rattrapes)} jour(s) rattrapé(s) et renvoyé(s).\n" if rattrapes else "")
                   + f"Rapport {'enregistré et envoyé' if sent else 'NON enregistré — voir le journal (aucune activité Claude détectée, ou envoi refusé)'}.",
                   "Test du rapport")
        return 0
    except Exception:
        log("ERREUR :\n" + traceback.format_exc())
        if test:
            msgbox("Une erreur est survenue. Voir le journal :\n" + logpath,
                   "Rapport d'activité Claude", 0x10)
        return 1
    finally:
        lf.close()


# ===========================================================================
# Installation
# ===========================================================================
UNINSTALL_REGKEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\RapportClaude"


def register_uninstall(idir, exe_path, version, log=None):
    """Inscrit l'app dans 'Programmes et fonctionnalités' (HKCU = per-user, sans admin).
    L'entrée appelle l'exe avec --uninstall pour une désinstallation propre."""
    try:
        import winreg
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_REGKEY, 0, winreg.KEY_WRITE)
        def s(n, v): winreg.SetValueEx(key, n, 0, winreg.REG_SZ, v)
        def dw(n, v): winreg.SetValueEx(key, n, 0, winreg.REG_DWORD, v)
        s("DisplayName", "Rapport d'activité Claude")
        s("DisplayVersion", version or "")
        s("Publisher", "Claude Agency")
        s("DisplayIcon", exe_path)
        s("InstallLocation", idir)
        s("UninstallString", f'"{exe_path}" --uninstall')
        s("QuietUninstallString", f'"{exe_path}" --uninstall')
        s("InstallDate", datetime.now().strftime("%Y%m%d"))
        dw("NoModify", 1)
        dw("NoRepair", 1)
        try:
            dw("EstimatedSize", int(os.path.getsize(exe_path) / 1024))
        except Exception:
            pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        if log:
            log(f"  [registre] inscription 'Programmes et fonctionnalités' échouée : {e}")
        return False


def unregister_uninstall():
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGKEY)
    except Exception:
        pass


def installed_version():
    """Version déjà installée (lue dans l'entrée 'Programmes et fonctionnalités'), ou ''."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGKEY)
        v, _ = winreg.QueryValueEx(key, "DisplayVersion")
        winreg.CloseKey(key)
        return v or ""
    except Exception:
        return ""


def confirm(text, title="Rapport d'activité Claude", extra=0):
    """Boîte Oui/Non. Renvoie True si l'utilisateur confirme (ou si l'UI est indisponible).
    extra=0x1000 (MB_SYSTEMMODAL) force la boîte au premier plan (pop-up de mise à jour)."""
    try:
        import ctypes
        # MB_YESNO (4) | MB_ICONQUESTION (0x20) ; IDYES = 6
        return ctypes.windll.user32.MessageBoxW(0, text, title, 0x24 | extra) == 6
    except Exception:
        return True


DASHBOARD_URL = "https://reporting.claudeagency.fr"
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "RapportClaude"
SHORTCUT_FILE = "Rapport Claude.lnk"


def _shortcut_create(folder_ps, exe_path, args="--tray", name=None):
    """Crée un raccourci .lnk (vers l'exe + arguments) dans un dossier spécial Windows."""
    name = name or SHORTCUT_FILE
    try:
        ps = (
            "$ws=New-Object -ComObject WScript.Shell;"
            "$d=" + folder_ps + ";"
            "$s=$ws.CreateShortcut((Join-Path $d '" + name + "'));"
            "$s.TargetPath=$env:RC_EXE;"
            "$s.Arguments='" + args + "';"
            "$s.IconLocation=$env:RC_EXE+',0';"
            "$s.Description='Rapport d''activite Claude';"
            "$s.Save()"
        )
        env = dict(os.environ)
        env["RC_EXE"] = exe_path
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, env=env,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def _shortcut_remove(folder_ps, name=None):
    name = name or SHORTCUT_FILE
    try:
        ps = ("$d=" + folder_ps + ";$p=Join-Path $d '" + name + "';"
              "if(Test-Path $p){Remove-Item $p -Force}")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def remove_desktop_shortcut():
    _shortcut_remove("[Environment]::GetFolderPath('Desktop')")


def _startup_lnk_path():
    appdata = os.environ.get("APPDATA", "") or os.path.join(
        os.environ.get("USERPROFILE", ""), "AppData", "Roaming")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup", SHORTCUT_FILE)


def add_to_startup(exe_path):
    """Démarrage automatique via un raccourci dans le dossier Démarrage de Windows
    (approche standard, moins suspecte qu'une clé de registre Run)."""
    # purge l'ancienne persistance par clé Run (versions <= 2.4.1) si présente
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_WRITE)
        winreg.DeleteValue(k, STARTUP_NAME)
        winreg.CloseKey(k)
    except Exception:
        pass
    _shortcut_create("[Environment]::GetFolderPath('Startup')", exe_path)


def remove_from_startup():
    _shortcut_remove("[Environment]::GetFolderPath('Startup')")
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_WRITE)
        winreg.DeleteValue(k, STARTUP_NAME)
        winreg.CloseKey(k)
    except Exception:
        pass


def kill_tray():
    """Arrête l'icône de la barre des tâches (RapportClaude.exe). L'installateur
    s'appelle RapportClaudeSetup.exe → il n'est pas touché. Outil natif (pas de
    PowerShell/CIM, moins susceptible de déclencher l'antivirus comportemental)."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "RapportClaude.exe"],
                       capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def is_in_startup():
    try:
        if os.path.isfile(_startup_lnk_path()):
            return True
        # compat : ancienne persistance par clé Run
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY)
        v, _ = winreg.QueryValueEx(k, STARTUP_NAME)
        winreg.CloseKey(k)
        return bool(v)
    except Exception:
        return False


def latest_log_path():
    """Chemin du dernier fichier journal de run (dossier logs), ou None."""
    try:
        ldir = os.path.join(install_dir(), "logs")
        logs = [os.path.join(ldir, f) for f in os.listdir(ldir) if f.lower().endswith(".log")]
        if logs:
            return max(logs, key=os.path.getmtime)
    except Exception:
        pass
    return None


def _ver_tuple(v):
    out = []
    for part in str(v or "").split("."):
        try:
            out.append(int(part))
        except Exception:
            out.append(0)
    return tuple(out)


def fetch_latest_version(cfg):
    url = (cfg.get("version_url") or "").strip()
    if not url:
        return None
    try:
        # User-Agent navigateur : Cloudflare (reporting.claudeagency.fr) renvoie 403
        # au user-agent par défaut de Python (Python-urllib).
        bust = ("&" if "?" in url else "?") + "t=" + str(int(time.time()))
        req = urllib.request.Request(url + bust, headers={
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RapportClaude",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8-sig"))
    except Exception:
        return None


def _snooze_path():
    return os.path.join(install_dir(), "update_snooze.json")


def update_snoozed(version):
    """True si l'utilisateur a déjà refusé CETTE version il y a moins de 24 h."""
    try:
        with open(_snooze_path(), "r", encoding="utf-8") as fh:
            d = json.load(fh) or {}
        if d.get("version") == str(version):
            until = datetime.fromisoformat(d.get("until", ""))
            return datetime.now() < until
    except Exception:
        pass
    return False


def snooze_update(version, hours=24):
    try:
        with open(_snooze_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": str(version),
                       "until": (datetime.now() + timedelta(hours=hours)).isoformat()}, fh)
    except Exception:
        pass


def self_update(cfg, d, log=None, ui=True):
    """Met à jour le logiciel automatiquement : télécharge le ZIP signé de la
    nouvelle version, l'extrait dans un dossier temporaire, puis lance son
    installateur en mode SILENCIEUX (--install-silent : conserve l'identité,
    remplace l'application, recrée la tâche planifiée, relance l'icône).
    Le processus appelant doit se terminer juste après (les fichiers de l'exe
    sont verrouillés tant qu'il tourne ; l'installateur réessaie la copie).
    ui=False (mise à jour de fond au run quotidien) : aucune fenêtre affichée."""
    import tempfile
    import zipfile
    import shutil
    url = (d.get("download") or "").strip()
    if not url:
        return False
    tmp = os.path.join(tempfile.gettempdir(), "RapportClaudeUpdate")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    zpath = os.path.join(tmp, "update.zip")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RapportClaude"})
    with urllib.request.urlopen(req, timeout=600) as r, open(zpath, "wb") as f:
        shutil.copyfileobj(r, f)
    # Verification d'integrite : si version.json publie un sha256, refuser d'installer
    # un ZIP dont l'empreinte differe (telechargement corrompu/altere). Absent -> on continue.
    expected = (d.get("sha256") or "").strip().lower()
    if expected:
        import hashlib
        _h = hashlib.sha256()
        with open(zpath, "rb") as _fh:
            for _chunk in iter(lambda: _fh.read(1 << 20), b""):
                _h.update(_chunk)
        if _h.hexdigest().lower() != expected:
            if log:
                log("  [maj] empreinte SHA-256 invalide -> mise a jour annulee.")
            return False
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    exe = None
    for root, _dirs, names in os.walk(tmp):
        if "RapportClaudeSetup.exe" in names:
            exe = os.path.join(root, "RapportClaudeSetup.exe")
            break
    if not exe:
        return False
    if log:
        log(f"  [maj] installation silencieuse lancée : {exe}")
    env = dict(os.environ)
    if not ui:
        env["RC_NO_UI"] = "1"  # mise à jour de fond : pas de fenêtre de confirmation
    subprocess.Popen([exe, "--install-silent"], creationflags=0x08000008, env=env)
    return True


def auto_update_if_available(cfg, log):
    """Force le poste à la dernière version, à distance, sans intervention de
    l'utilisateur : si `version.json` publie une version plus récente (et que
    l'auto-update n'est pas désactivé côté serveur via "auto": false), télécharge
    et lance l'installation silencieuse, puis renvoie True pour que l'appelant
    (`--run`) se termine et libère ses fichiers. C'est le levier de MAJ à distance :
    il suffit de publier une nouvelle version pour que tout le parc se mette à
    jour à son prochain rapport quotidien."""
    try:
        d = fetch_latest_version(cfg)
    except Exception as e:
        log(f"  [maj] vérification impossible ({e}).")
        return False
    if not d or not d.get("auto", True):
        return False
    latest = str(d.get("version", "")).strip()
    if _ver_tuple(latest) <= _ver_tuple(CONFIG.get("app_version", "")):
        return False
    # GARDE-FOU ANTI-BOUCLE : ne retente pas la MÊME version plus d'une fois par
    # 6 h. Protège contre un version.json qui annonce une version que l'exe
    # installé ne rejoint jamais (ex. mismatch de build version.json/zip) : au
    # lieu d'une boucle infinie, au plus une tentative toutes les 6 h.
    try:
        ap = os.path.join(install_dir(), "update_attempt.json")
        if os.path.isfile(ap):
            with open(ap, "r", encoding="utf-8") as fh:
                prev = json.load(fh) or {}
            if prev.get("version") == latest:
                try:
                    last = datetime.fromisoformat(prev.get("at", ""))
                except Exception:
                    last = None
                if last and (datetime.now() - last) < timedelta(hours=6):
                    log(f"  [maj] {latest} déjà tentée récemment -> pas de nouvelle "
                        f"tentative avant 6 h (anti-boucle).")
                    return False
        with open(ap, "w", encoding="utf-8") as fh:
            json.dump({"version": latest, "at": datetime.now().isoformat()}, fh)
    except Exception:
        pass
    log(f"  [maj] nouvelle version {latest} disponible -> mise à jour automatique.")
    try:
        return self_update(cfg, d, log, ui=False)
    except Exception as e:
        log(f"  [maj] mise à jour automatique échouée ({e}) -> réessai au prochain run.")
        return False


def edit_identity_mode():
    cfg = load_config()
    res = ask_identity(cfg.get("collaborator") or default_name(),
                       cfg.get("collaborator_email") or "")
    if not res:
        return 0
    name = res.get("collaborator") or cfg.get("collaborator") or default_name()
    email = res.get("collaborator_email") or cfg.get("collaborator_email") or ""
    try:
        with open(os.path.join(install_dir(), "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"collaborator": name, "collaborator_email": email}, fh,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass
    cfg["collaborator"] = name
    cfg["collaborator_email"] = email
    try:
        ping_install(cfg)
    except Exception:
        pass
    msgbox("Vos informations ont été mises à jour :\n\n" + name +
           (("\n" + email) if email else "") +
           "\n\nElles seront utilisées dès le prochain rapport.", "Rapport Claude")
    return 0


def run_tray():
    """Icône de la barre des tâches : logiciel actif + menu (rapport, tableau de bord,
    Paramètres). Persistant, instance unique."""
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "RapportClaudeTraySingleton")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return 0
    except Exception:
        pass
    try:
        import threading
        import webbrowser
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return 1

    def make_image():
        # Logo de l'entreprise (assets/logo.png), embarqué via PyInstaller (--add-data).
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            return Image.open(os.path.join(base, "assets", "logo.png")).convert("RGBA")
        except Exception:
            # Repli : icône dessinée si le logo est introuvable.
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([3, 3, 61, 61], radius=14, fill=(47, 93, 80, 255))
            d.ellipse([19, 19, 45, 45], outline=(255, 255, 255, 255), width=6)
            return img

    cfg = load_config()

    def header(item):
        return "Rapport Claude — actif (v%s)" % CONFIG.get("app_version", "")

    def do_run(icon, item):
        def worker():
            try:
                icon.notify("Génération du rapport en cours…", "Rapport Claude")
            except Exception:
                pass
            t0 = time.time()
            try:
                run_job(test=False)
            except Exception:
                try:
                    icon.notify("La génération du rapport a échoué.", "Rapport Claude")
                except Exception:
                    pass
                return
            # Ouvre le journal du run qui vient de s'exécuter (créé dans les dernières
            # secondes) pour que le collaborateur puisse vérifier ce qui s'est passé.
            # L'email part en parallèle vers contact@claudeagency.fr ET le
            # collaborateur (côté serveur), si le rapport a pu être généré.
            p = latest_log_path()
            fresh = False
            try:
                fresh = bool(p) and os.path.getmtime(p) >= t0 - 5
            except Exception:
                fresh = False
            if fresh:
                try:
                    icon.notify("Rapport traité, journal ouvert. Une copie est envoyée "
                                "par email à contact@claudeagency.fr et à ton adresse.",
                                "Rapport Claude")
                except Exception:
                    pass
                try:
                    os.startfile(p)
                except Exception:
                    pass
            else:
                try:
                    icon.notify("Aucun rapport généré : activité Claude introuvable. "
                                "Vérifie que Claude est bien lancé, puis réessaie.",
                                "Rapport Claude")
                except Exception:
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def do_dash(icon, item):
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception:
            pass


    def apply_update(d):
        """Télécharge et installe la nouvelle version, puis arrête l'icône
        (l'installateur silencieux la relance une fois la copie faite)."""
        latest = str(d.get("version", "")).strip()
        try:
            icon.notify("Téléchargement de la mise à jour v%s…" % latest, "Rapport Claude")
        except Exception:
            pass
        ok = False
        try:
            ok = self_update(cfg, d)
        except Exception:
            ok = False
        if ok:
            try:
                icon.notify("Installation en cours — l'icône va redémarrer automatiquement.",
                            "Rapport Claude")
            except Exception:
                pass
            do_quit(icon, None)  # libère l'exe installé pour permettre la copie
        else:
            msgbox("La mise à jour automatique a échoué.\n\n"
                   "La page de téléchargement va s'ouvrir pour une mise à jour manuelle.",
                   "Rapport Claude — mise à jour", 0x30)
            try:
                webbrowser.open(d.get("info_url") or (DASHBOARD_URL + "/info"))
            except Exception:
                pass

    def do_update(icon, item):
        d = fetch_latest_version(cfg)
        if not d:
            icon.notify("Vérification impossible (pas de connexion ?).", "Rapport Claude")
            return
        latest = str(d.get("version", "")).strip()
        if _ver_tuple(latest) > _ver_tuple(CONFIG.get("app_version", "")):
            if confirm("Une nouvelle version est disponible (v%s — vous avez la v%s).\n\n"
                       "Mettre à jour maintenant ?\n\nLa mise à jour est automatique (~1 minute), "
                       "conserve vos informations, et l'icône redémarre toute seule."
                       % (latest, CONFIG.get("app_version", "")),
                       "Rapport Claude — mise à jour", extra=0x1000):
                apply_update(d)
        else:
            icon.notify("Vous êtes à jour (v%s)." % CONFIG.get("app_version", ""), "Rapport Claude")

    def update_watch():
        """Veille de version : au démarrage de l'icône puis toutes les 6 h.
        Pop-up d'invitation si une nouvelle version existe ; en cas de refus,
        on ne redemande pas cette version pendant 24 h."""
        time.sleep(25)
        while True:
            try:
                d = fetch_latest_version(cfg)
                latest = str((d or {}).get("version", "")).strip()
                if (d and _ver_tuple(latest) > _ver_tuple(CONFIG.get("app_version", ""))
                        and not update_snoozed(latest)):
                    if confirm("Une nouvelle version du logiciel de rapport est disponible "
                               "(v%s — vous avez la v%s).\n\nMettre à jour maintenant ?\n\n"
                               "La mise à jour est automatique (~1 minute), conserve vos "
                               "informations, et l'icône redémarre toute seule."
                               % (latest, CONFIG.get("app_version", "")),
                               "Rapport Claude — mise à jour disponible", extra=0x1000):
                        apply_update(d)
                        return
                    snooze_update(latest, 24)
            except Exception:
                pass
            time.sleep(6 * 3600)

    def status_watch():
        """Veille du statut du dernier run (last_run.json) : si un envoi a
        échoué, prévient discrètement le collaborateur — une seule fois par
        échec — au lieu de laisser le problème invisible au fond d'un log.
        Le rapport concerné sera de toute façon retenté au run suivant."""
        seen_path = os.path.join(install_dir(), "notify_seen.json")
        time.sleep(40)
        while True:
            try:
                st = read_last_run()
                at = str(st.get("at") or "")
                if at and not st.get("ok"):
                    seen = ""
                    try:
                        with open(seen_path, "r", encoding="utf-8") as fh:
                            seen = str((json.load(fh) or {}).get("at") or "")
                    except Exception:
                        pass
                    if at != seen:
                        failed = st.get("failed") or []
                        day = str(failed[-1] if failed else (st.get("target") or "?"))
                        try:
                            icon.notify(
                                "Le rapport du %s n'a pas pu être envoyé. Il sera "
                                "retenté automatiquement au prochain rapport (ou : "
                                "clic droit → Générer le rapport maintenant)." % day,
                                "Rapport Claude")
                        except Exception:
                            pass
                        try:
                            with open(seen_path, "w", encoding="utf-8") as fh:
                                json.dump({"at": at}, fh)
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(300)

    def do_diag(icon, item):
        userprofile = os.environ.get("USERPROFILE", "")
        c_ok = _source_ready(cowork_base(), tries=2, delay=1.0)
        d_ok = _source_ready(os.path.join(userprofile, ".claude", "projects"), tries=2, delay=1.0)
        srv = False
        try:
            req = urllib.request.Request(
                (cfg.get("settings_function_url") or ""), data=b"{}",
                headers={"apikey": cfg.get("supabase_key", ""), "Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                srv = (getattr(r, "status", 200) == 200)
        except Exception:
            srv = False
        ok = c_ok and d_ok and srv
        msgbox("Diagnostic du logiciel :\n\n"
               "• Dossier Cowork : %s\n"
               "• Dossier Claude Code : %s\n"
               "• Connexion au serveur : %s\n\n%s"
               % ("OK" if c_ok else "INTROUVABLE",
                  "OK" if d_ok else "INTROUVABLE",
                  "OK" if srv else "ÉCHEC",
                  "Tout est opérationnel." if ok else
                  "Un élément pose problème. Vérifiez que Claude est lancé, réessayez dans quelques "
                  "minutes, ou contactez l'administrateur."),
               "Rapport Claude — diagnostic")

    def do_edit(icon, item):
        try:
            subprocess.Popen([sys.executable, "--edit-identity"], creationflags=0x08000008)
        except Exception:
            pass

    def do_state(icon, item):
        def worker():
            ver = CONFIG.get("app_version", "")
            nm = cfg.get("collaborator") or "—"
            last = "aucun pour l'instant"
            p = latest_log_path()
            if p:
                try:
                    last = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d/%m/%Y à %H:%M")
                except Exception:
                    pass
            mins = None
            try:
                tz = get_tz(cfg)
                files = collect_files(cfg, lambda m: None)
                today = to_local(datetime.now().astimezone(), tz).date()
                _entries, active, _nreq, _ns = extract_day(files, today, tz)
                mins = active
            except Exception:
                mins = None
            if isinstance(mins, int):
                mt = ("%d h %02d min" % (mins // 60, mins % 60)) if mins >= 60 else ("%d min" % mins)
            else:
                mt = "non calculé (Claude est-il lancé ?)"
            pend = load_retry_queue()
            ptxt = ("\nEn attente de renvoi automatique : " +
                    ", ".join(d.strftime("%d/%m") for d in pend)) if pend else ""
            msgbox("État de Rapport Claude\n\n"
                   "Version installée : v%s\n"
                   "Collaborateur : %s\n"
                   "Statut : actif ✓\n"
                   "Dernier run : %s\n"
                   "Activité Claude détectée aujourd'hui : %s\n"
                   "Prochain rapport : automatique, chaque jour à %s.%s"
                   % (ver, nm, last, mt, schedule_time_label(), ptxt),
                   "Rapport Claude — état")
        threading.Thread(target=worker, daemon=True).start()

    def do_startup(icon, item):
        exe = os.path.join(install_dir(), "RapportClaude.exe")
        if not os.path.isfile(exe):
            exe = sys.executable
        try:
            if is_in_startup():
                remove_from_startup()
            else:
                add_to_startup(exe)
            icon.update_menu()
        except Exception:
            pass

    def do_quit(icon, item):
        icon.visible = False
        icon.stop()

    settings = pystray.Menu(
        pystray.MenuItem("Démarrer avec Windows", do_startup,
                         checked=lambda item: is_in_startup()),
        pystray.MenuItem("Modifier mes informations…", do_edit),
        pystray.MenuItem("Diagnostic (tester les sources)", do_diag),
    )
    menu = pystray.Menu(
        pystray.MenuItem(header, None, enabled=False),
        pystray.MenuItem("Collaborateur : %s" % (cfg.get("collaborator") or "—"), None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Ouvrir le tableau de bord", do_dash),
        pystray.MenuItem("Générer le rapport maintenant", do_run),
        pystray.MenuItem("État du dernier run", do_state),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Mettre à jour le logiciel", do_update),
        pystray.MenuItem("Paramètres", settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quitter", do_quit),
    )
    icon = pystray.Icon("RapportClaude", make_image(),
                        "Rapport Claude — actif (v%s)" % CONFIG.get("app_version", ""), menu)
    threading.Thread(target=update_watch, daemon=True).start()
    threading.Thread(target=status_watch, daemon=True).start()
    icon.run()
    return 0


def install(silent=False):
    """Installation / mise à jour. En mode SILENCIEUX (--install-silent, utilisé
    par la mise à jour automatique) : aucune question — l'identité existante est
    conservée, l'ancienne version est remplacée d'office."""
    idir = install_dir()
    os.makedirs(idir, exist_ok=True)
    os.makedirs(os.path.join(idir, "logs"), exist_ok=True)

    # --- identité du collaborateur (formulaire, sinon auto) --------------
    existing = {}
    cfgpath = os.path.join(idir, "config.json")
    for _cp in (cfgpath, os.path.join(_old_install_dir(), "config.json")):
        if os.path.isfile(_cp):
            try:
                with open(_cp, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                break
            except Exception:
                existing = {}
    def_name = existing.get("collaborator") or CONFIG.get("collaborator") or default_name()
    def_mail = existing.get("collaborator_email") or CONFIG.get("collaborator_email") or ""
    if silent:
        ident = {"collaborator": def_name, "collaborator_email": def_mail}
    else:
        ident = ask_identity(def_name, def_mail) or {
            "collaborator": def_name, "collaborator_email": def_mail}

    merged = dict(CONFIG)
    merged["collaborator"] = ident.get("collaborator") or def_name
    merged["collaborator_email"] = ident.get("collaborator_email") or def_mail

    # --- réinstallation par-dessus une version existante : proposer le remplacement ---
    src = sys.executable if getattr(sys, "frozen", False) else None
    prev_ver = installed_version()
    if src and (prev_ver or os.path.isfile(cfgpath)):
        lbl = f" ({prev_ver})" if prev_ver else ""
        if not silent and not confirm(
            f"Une version{lbl} du logiciel est déjà installée sur ce poste.\n\n"
            f"La remplacer par la version {CONFIG.get('app_version')} ?\n\n"
            "L'ancienne sera retirée proprement — même emplacement, aucune double installation."):
            return 0
        # nettoyage de l'ancienne (tâche planifiée + entrée Windows + icône) avant de réinstaller
        subprocess.run(["schtasks", "/Delete", "/TN", CONFIG["task_name"], "/F"],
                       capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
        unregister_uninstall()
        kill_tray()
        if silent:
            time.sleep(1.5)  # laisse le tray appelant se terminer avant la copie

    # config.json ne stocke QUE l'identité (le reste vient de l'exe à jour)
    try:
        with open(cfgpath, "w", encoding="utf-8") as fh:
            json.dump({"collaborator": merged["collaborator"],
                       "collaborator_email": merged["collaborator_email"]},
                      fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # --- copie de l'application (build --onedir : exe + dossier _internal) ---
    target_exe = os.path.join(idir, "RapportClaude.exe")
    src = sys.executable if getattr(sys, "frozen", False) else None
    if src:
        import shutil
        src_dir = os.path.dirname(os.path.abspath(src))
        if os.path.abspath(src_dir) != os.path.abspath(idir):
            kill_tray()  # un tray ouvert verrouillerait l'ancien .exe / _internal
            copied, last_err = False, None
            for attempt in range(6):
                try:
                    for name in os.listdir(src_dir):
                        s = os.path.join(src_dir, name)
                        d = os.path.join(idir, name)
                        if os.path.isdir(s):
                            shutil.copytree(s, d, dirs_exist_ok=True)
                        else:
                            shutil.copy2(s, d)
                    copied = True
                    break
                except Exception as e:
                    last_err = e
                    kill_tray()
                    time.sleep(1.5)
            if not copied:
                msgbox("Impossible de copier l'application :\n%s\n\n"
                       "Si l'icône « Rapport Claude » est ouverte dans la barre des "
                       "tâches, faites un clic droit dessus → Quitter, puis relancez."
                       % last_err, "Installation", 0x10)
                return 1
        # l'exe copié porte le nom de l'installateur -> le renommer en RapportClaude.exe
        copied_exe = os.path.join(idir, os.path.basename(src))
        if os.path.abspath(copied_exe) != os.path.abspath(target_exe) and os.path.isfile(copied_exe):
            try:
                if os.path.isfile(target_exe):
                    os.remove(target_exe)
                os.replace(copied_exe, target_exe)
            except Exception:
                target_exe = copied_exe  # repli : conserver le nom d'origine

    # --- tâche planifiée (via XML : permet StartWhenAvailable = rattrapage si le
    #     PC était éteint à l'heure prévue, indisponible avec les options schtasks de base) ---
    if src:
        run_cmd, run_args = target_exe, "--run"
    else:
        run_cmd, run_args = sys.executable, f'"{os.path.abspath(__file__)}" --run'
    st = CONFIG.get("schedule_time", "07:00")
    if len(st) != 5:
        st = "07:00"
    start_boundary = date.today().isoformat() + "T" + st + ":00"
    task_xml = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo><Description>Rapport quotidien d\'activite Claude</Description></RegistrationInfo>\n'
        '  <Triggers>\n'
        '    <CalendarTrigger>\n'
        f'      <StartBoundary>{start_boundary}</StartBoundary>\n'
        '      <Enabled>true</Enabled>\n'
        '      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>\n'
        '    </CalendarTrigger>\n'
        '  </Triggers>\n'
        '  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType>'
        '<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>\n'
        '    <Enabled>true</Enabled>\n'
        '  </Settings>\n'
        '  <Actions Context="Author">\n'
        f'    <Exec><Command>{html.escape(run_cmd, quote=False)}</Command><Arguments>{html.escape(run_args, quote=False)}</Arguments></Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )
    xml_path = os.path.join(idir, "task.xml")
    try:
        with open(xml_path, "w", encoding="utf-16") as fh:
            fh.write(task_xml)
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", CONFIG["task_name"], "/XML", xml_path, "/F"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        msgbox(f"Échec de la planification :\n{e}", "Installation", 0x10)
        return 1
    finally:
        try:
            os.remove(xml_path)
        except Exception:
            pass
    if r.returncode != 0:
        msgbox("La tâche planifiée n'a pas pu être créée :\n"
               + (r.stderr or r.stdout), "Installation", 0x10)
        return 1

    # --- inscription "Programmes et fonctionnalités" ---
    if src:
        register_uninstall(idir, target_exe, CONFIG.get("app_version", ""))
        # Icône résidente dans la barre des tâches. L'exe étant SIGNÉ (éditeur vérifié),
        # l'auto-démarrage + tâche planifiée sont un comportement normal d'app installée.
        # Auto-démarrage via raccourci dans le dossier Démarrage + lancement immédiat.
        try:
            kill_tray()                 # stoppe une éventuelle ancienne instance
            # MAJ silencieuse : si le raccourci Démarrage existe déjà (l'emplacement
            # d'installation ne change pas d'une version à l'autre), NE PAS le recréer.
            # On évite ainsi les appels PowerShell en contexte détaché — cause de
            # l'erreur « powershell 0xc0000142 » observée pendant les mises à jour.
            # 1re installation (non silencieuse) ou raccourci manquant : on (re)crée.
            if silent and os.path.isfile(_startup_lnk_path()):
                pass
            else:
                remove_desktop_shortcut()   # purge l'ancien raccourci bureau s'il existe
                add_to_startup(target_exe)  # raccourci Démarrage -> "<exe> --tray"
        except Exception:
            pass
        try:
            subprocess.Popen([target_exe, "--tray"], creationflags=0x08000008)
        except Exception:
            pass
        # Nettoyage de l'ancien emplacement (%LOCALAPPDATA%\RapportClaude), si présent.
        try:
            _old = _old_install_dir()
            if os.path.isdir(_old) and os.path.abspath(_old) != os.path.abspath(idir):
                shutil.rmtree(_old, ignore_errors=True)
        except Exception:
            pass

    # --- signale le poste comme installé/actif (visible immédiatement côté admin) ---
    ping_install(merged)

    if silent:
        # Mise à jour de fond (auto-update au run quotidien) : aucune fenêtre.
        if os.environ.get("RC_NO_UI") != "1":
            msgbox(f"Rapport Claude a été mis à jour en version {CONFIG.get('app_version')} ✓\n\n"
                   "Vos informations et réglages ont été conservés. "
                   "Le rapport quotidien continue comme avant.",
                   "Rapport Claude — mise à jour")
        return 0
    msgbox(
        "Installation terminée ✓\n\n"
        f"Collaborateur : {merged['collaborator']}\n"
        f"Le rapport d'activité sera généré chaque jour à {CONFIG['schedule_time']} "
        f"(pour la journée précédente, complète) "
        f"et envoyé à {CONFIG['recipient']}"
        + (f" et à {merged['collaborator_email']}" if merged['collaborator_email'] else "")
        + ".\n\nLe rapport est généré et envoyé automatiquement chaque jour — "
        "il n'y a rien à lancer ni à faire.\n\nUne icône « Rapport Claude » est présente "
        "dans la barre des tâches (près de l'horloge) : clic droit dessus pour voir l'état, "
        "générer un rapport ou mettre à jour.\n\nVous pouvez fermer cette fenêtre.",
        "Rapport d'activité Claude — installé")
    return 0


def uninstall():
    # 1) Tâche planifiée
    subprocess.run(["schtasks", "/Delete", "/TN", CONFIG["task_name"], "/F"],
                   capture_output=True, text=True,
                   creationflags=CREATE_NO_WINDOW)
    # 2) Entrée "Programmes et fonctionnalités" + raccourci + démarrage + icône
    unregister_uninstall()
    remove_from_startup()
    remove_desktop_shortcut()
    kill_tray()
    # 3) Confirmation à l'utilisateur
    msgbox("Le logiciel de reporting Claude a été désinstallé.\n\n"
           "La tâche planifiée quotidienne et l'entrée Windows ont été supprimées, "
           "et les fichiers du programme vont être nettoyés.",
           "Rapport d'activité Claude — désinstallé")
    # 4) Suppression des fichiers installés. L'exe en cours d'exécution ne peut pas
    #    se supprimer lui-même : on diffère la suppression du dossier après la sortie.
    idir = install_dir()
    try:
        if getattr(sys, "frozen", False) and os.path.isdir(idir):
            subprocess.Popen(
                'cmd /c ping 127.0.0.1 -n 4 >nul & rmdir /s /q "{}"'.format(idir),
                cwd="C:\\", creationflags=0x08000000)
    except Exception:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--run", action="store_true", help="Exécution planifiée.")
    ap.add_argument("--run-now", action="store_true", help="Exécuter tout de suite (test).")
    ap.add_argument("--uninstall", action="store_true", help="Supprimer la tâche planifiée.")
    ap.add_argument("--edit-identity", action="store_true", help="Modifier l'identité (nom / email).")
    ap.add_argument("--tray", action="store_true", help="Icône résidente de la barre des tâches.")
    ap.add_argument("--install-silent", action="store_true",
                    help="Mise à jour silencieuse (conserve l'identité, aucune question).")
    args = ap.parse_args()
    # Contextes sans interface (MAJ silencieuse, tâche planifiée) : ne jamais laisser
    # Windows afficher une boîte d'erreur si un enfant échoue à démarrer (0xc0000142).
    if args.install_silent or args.run:
        _silence_child_error_dialogs()
    if args.uninstall:
        return uninstall()
    if args.install_silent:
        return install(silent=True)
    if args.tray:
        return run_tray()
    if args.edit_identity:
        return edit_identity_mode()
    if args.run:
        ensure_schedule_time()
        return run_job(test=False)
    if args.run_now:
        return run_job(test=True)
    return install()


if __name__ == "__main__":
    sys.exit(main())

