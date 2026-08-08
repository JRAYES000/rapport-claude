// Verifie le prompt de verification fabrique par client.html, sans navigateur.
//
//   node tools/test-prompt-verif.js
//
// Ce qu'on protege : ce texte part au presse-papiers puis dans Claude, et une erreur
// dedans ne se voit pas — elle produit une analyse du mauvais dossier. Quatre pieges :
//   - le slug doit etre celui qui a nomme les dossiers du depot (meme regle que
//     `slugClient()` du tableau de bord), sinon le chemin n'existe pas ;
//   - c'est du TEXTE, pas du HTML : une apostrophe echappee en &#39; arrive telle quelle
//     dans le prompt ;
//   - « Challenge 1 » ne doit pas ramener l'enonce du challenge 10 ni celui du 2 ;
//   - le nom du collaborateur ne doit jamais sortir de cette page, qui est aussi celle
//     que le client charge.
//
// On extrait les fonctions de la page plutot que de les dupliquer ici : une copie
// diverge, et le test se met a valider du code que personne n'execute.
const fs = require("fs");
const vm = require("vm");

const page = fs.readFileSync(__dirname + "/../web/client.html", "utf8");
const src = [...page.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]).join("\n");

const bloc = (nom) => {
  const i = src.indexOf("function " + nom + "(");
  if (i < 0) throw new Error(nom + " introuvable dans client.html");
  let d = src.indexOf("{", i), n = 0, j = d;
  for (; j < src.length; j++) {
    if (src[j] === "{") n++;
    else if (src[j] === "}" && --n === 0) break;
  }
  return src.slice(i, j + 1);
};

const ctx = { FMT_COURT: new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" }) };
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('const DEPOT = "'), src.indexOf('const DEPOT = "') + 60), ctx);
vm.runInContext([bloc("jour"), bloc("dateCourte"), bloc("slugDepot"), bloc("deposeLe"), bloc("promptVerif")].join("\n"), ctx);
const rendu = (data, k, fs_) =>
  vm.runInContext("promptVerif(" + JSON.stringify(data) + "," + JSON.stringify(k) + "," + JSON.stringify(fs_) + ")", ctx);

let ko = 0;
const dit = (ok, quoi) => { console.log((ok ? "  ok    " : "  KO    ") + quoi); if (!ok) ko++; };

// Le slug reellement utilise par le depot, verifie sur GitHub le 08/08/2026.
dit(vm.runInContext('slugDepot("ECOLE DE NATUROPATHIE & SOPHROLOGIE")', ctx)
      === "ecole-de-naturopathie-sophrologie",
    "le slug est celui du dossier reel sur le depot");
dit(vm.runInContext('slugDepot("Boulangerie Duchêne (demo)")', ctx) === "boulangerie-duchene-demo",
    "accents et parentheses tombent, pas de tiret en fin de slug");

const data = {
  company: "ECOLE DE NATUROPATHIE & SOPHROLOGIE",
  answers: [
    { q: "Challenge 1 — votre priorité", a: "Améliorer l'application app.ecole-naturo.fr" },
    { q: "Challenge 2", a: "Améliorer le ranking dans Google" },
    { q: "Challenge 10", a: "Ne doit pas remonter pour le challenge 1" },
    { q: "Votre société", a: "pas un challenge" }
  ]
};
// Le cas reel du challenge 2 d'Ecole Naturo, verifie sur le depot le 08/08/2026 : la
// version la plus recente ne porte NI le numero du challenge NI le plus grand suffixe
// dans l'ordre alphabetique. Trie par nom, un correcteur auditerait la v3.
const V = (d) => [{ sha: "0".repeat(40), date: d }];
const p = rendu(data, 2, [
  { file: "challenge-2-v3.xlsx", versions: V("2026-08-06T18:50:53Z"), transmis: true },
  { file: "action-06-robots.png", versions: V("2026-08-05T09:00:00Z") },
  { file: "challenge-v4.xlsx", versions: V("2026-08-07T16:45:28Z") }
]);

dit(p.startsWith("/verification-travail-collaborateur"), "le prompt declenche la skill des la premiere ligne");
dit(p.includes("ecole-de-naturopathie-sophrologie/challenge-2/"), "le chemin du dossier est complet");
dit(p.includes("https://github.com/JRAYES000/livrables-Claude-Agency"), "le depot est nomme, en URL ouvrable");
dit(p.includes('gh api "repos/JRAYES000/livrables-Claude-Agency/git/trees/HEAD?recursive=1"')
    && p.includes('startswith("ecole-de-naturopathie-sophrologie/challenge-2/")'),
    "la commande de listage porte deja le bon chemin");
dit(p.includes("Améliorer le ranking dans Google"), "l'enonce du bon challenge est joint");
dit(!p.includes("app.ecole-naturo.fr") && !p.includes("Ne doit pas remonter"),
    "aucun autre challenge ne deborde dans le prompt");
dit(p.includes("portail (3)"), "les fichiers sont comptes");
dit(p.indexOf("- challenge-v4.xlsx") < p.indexOf("- challenge-2-v3.xlsx")
    && p.indexOf("- challenge-2-v3.xlsx") < p.indexOf("- action-06-robots.png"),
    "les fichiers sortent du plus recent au plus ancien, pas par nom");
dit(p.includes("- challenge-v4.xlsx — depose le 07/08/2026"), "chaque fichier porte sa date de depot");
dit(p.includes("challenge-2-v3.xlsx — depose le 06/08/2026 · deja transmis au client")
    && p.includes("action-06-robots.png — depose le 05/08/2026 · pas encore transmis"),
    "l'etat de transmission au client est dit");
dit(/\.png sont des captures/.test(p) && /OUVRE-LES comme images/.test(p),
    "les captures sont annoncees comme images, pas comme texte a decoder");
dit(p.includes("MISSION.md") && p.includes("regeneres par le serveur"),
    "les fiches regenerees sont ecartees des livrables");
dit(!/&#\d+;|&amp;|&quot;/.test(p), "c'est du texte brut : rien n'est echappe en entite HTML");

const p1 = rendu(data, 1, []);
dit(p1.includes("app.ecole-naturo.fr") && !p1.includes("Ne doit pas remonter"),
    "« challenge 1 » ne ramene pas le challenge 10");
dit(p1.includes("(0)"), "un challenge sans fichier reste demandable");

const p0 = rendu(data, 0, [{ file: "note.md" }]);
dit(p0.includes("ecole-de-naturopathie-sophrologie/\n") && !p0.includes("challenge-0"),
    "les documents generaux pointent la racine du client, pas un challenge-0");

console.log(ko === 0 ? "OK — 18 verifications sur le prompt de verification." : ko + " verification(s) en echec");
process.exit(ko ? 1 : 0);
