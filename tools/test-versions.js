// Verifie le bloc « versions precedentes » de client.html sans navigateur.
//
//   node tools/test-versions.js
//
// Ce qu'on protege : le serveur ne renvoie l'historique QUE des dates et des empreintes
// de commit, et la page doit en tirer des lignes telechargeables. Trois pieges, tous
// deja vus ailleurs dans ce projet :
//   - versions[0] est la version EN LIGNE (le bouton du dessus) : la repeter donnerait
//     deux fois le meme fichier a un clic d'ecart ;
//   - le nom du fichier doit voyager dans data-nom, parce que .txt porte une date sur
//     ces lignes-la et que le serveur compare ce nom a celui de l'indice (409 sinon) ;
//   - deux depots le meme jour sont le cas courant : sans l'heure, deux lignes
//     identiques.
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
  // Accolades equilibrees a partir de la premiere : suffisant, ces trois fonctions ne
  // portent ni accolade en chaine ni expression reguliere qui en contienne.
  let d = src.indexOf("{", i), n = 0, j = d;
  for (; j < src.length; j++) {
    if (src[j] === "{") n++;
    else if (src[j] === "}" && --n === 0) break;
  }
  return src.slice(i, j + 1);
};

const ctx = { FMT_COURT: new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" }) };
vm.createContext(ctx);
vm.runInContext([bloc("esc"), bloc("horodate"), bloc("blocVersions")].join("\n"), ctx);
const rendu = (f) => vm.runInContext("blocVersions(" + JSON.stringify(f) + ")", ctx);

const V = (sha, date) => ({ sha, date });
let ko = 0;
const dit = (ok, quoi) => { console.log((ok ? "  ok    " : "  KO    ") + quoi); if (!ok) ko++; };

dit(rendu({ i: 0, file: "a.md" }) === "", "aucune version : rien ne s'affiche");
dit(rendu({ i: 0, file: "a.md", versions: [V("a".repeat(40), "2026-08-04T17:51:36Z")] }) === "",
    "une seule version : rien ne s'affiche (c'est le bouton du dessus)");

const h = rendu({ i: 3, file: "carte des pains.md", versions: [
  V("1".repeat(40), "2026-08-04T17:51:36Z"),
  V("2".repeat(40), "2026-08-03T09:05:00Z"),
  V("3".repeat(40), "2026-08-03T08:00:00Z")
] });
dit(/2 versions précédentes/.test(h), "trois versions : deux lignes annoncees");
dit(!h.includes("1".repeat(40)), "la version en ligne n'est pas repetee");
dit(h.includes("2".repeat(40)) && h.includes("3".repeat(40)), "les deux precedentes sont la");
dit((h.match(/data-nom="carte des pains\.md"/g) || []).length === 2, "chaque ligne porte le nom du fichier");
dit((h.match(/data-i="3"/g) || []).length === 2, "chaque ligne porte l'indice du fichier");
dit(/03\/08\/2026 à \d\d:\d\d/.test(h), "l'heure distingue deux depots du meme jour");
dit(!/undefined|NaN|Invalid/.test(h), "aucune valeur perdue dans le rendu");

const sale = rendu({ i: 0, file: 'x" onerror="alert(1)', versions: [V("1".repeat(40), "2026-08-04T17:51:36Z"), V("2".repeat(40), "2026-08-03T09:05:00Z")] });
dit(!/onerror="alert/.test(sale), "un nom hostile ne sort pas de son attribut");

console.log(ko === 0 ? "OK — " + 10 + " verifications sur blocVersions." : ko + " verification(s) en echec");
process.exit(ko ? 1 : 0);
