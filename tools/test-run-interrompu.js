// Le badge « Run interrompu » du tableau de bord (onglet Postes).
//
// Ce qu'il doit prouver : un poste qui a commence un rapport sans jamais le finir
// est signale, et un poste sain ne l'est pas. Le 20/08/2026, celui de Nomena s'est
// arrete en attendant la redaction : le tableau affichait « Aucune activite 2 j »,
// c'est-a-dire l'inverse de ce qui se passait, et rien n'a alerte.
//
// La fonction est extraite de la page elle-meme : un test qui recopierait la regle
// resterait vert le jour ou la page cesse de l'appliquer.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const page = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
const src = page.match(/function runInterrompu\(i\)\{[\s\S]*?\n\}/);
if (!src) {
  console.error("ECHEC : runInterrompu() introuvable dans web/index.html.");
  process.exit(1);
}

// Instant de reference fige : sans cela le test change de verdict selon l'heure.
const MAINTENANT = Date.parse("2026-08-20T14:30:00Z");
const bac = { Date: class extends Date { static now() { return MAINTENANT; } } };
vm.createContext(bac);
vm.runInContext(src[0] + "\nglobalThis.f = runInterrompu;", bac);
const f = bac.f;

const cas = [
  ["poste arrete pendant la redaction (Nomena, 20/08/2026)",
   { last_seen_at: "2026-08-20T08:59:38Z", last_run_at: "2026-08-19T09:04:05Z" }, true],
  ["run alle au bout : depart et arrivee au meme instant",
   { last_seen_at: "2026-08-20T11:24:04Z", last_run_at: "2026-08-20T11:24:04Z" }, false],
  ["ping de mise a jour quelques minutes apres le run",
   { last_seen_at: "2026-08-20T09:15:25Z", last_run_at: "2026-08-20T09:06:02Z" }, false],
  ["poste eteint depuis des jours : absent, pas en panne",
   { last_seen_at: "2026-08-15T10:15:25Z", last_run_at: "2026-08-10T09:00:00Z" }, false],
  ["poste jamais alle au bout d'un seul run : rien a comparer",
   { last_seen_at: "2026-08-20T08:59:38Z", last_run_at: null }, false],
  ["horodatage illisible : on n'invente pas une panne",
   { last_seen_at: "2026-08-20T08:59:38Z", last_run_at: "hier matin" }, false],
];

let ko = 0;
for (const [nom, inst, attendu] of cas) {
  const obtenu = f(inst);
  if (obtenu === attendu) {
    console.log("  ok    " + nom);
  } else {
    ko++;
    console.log("  ECHEC " + nom + " : attendu " + attendu + ", obtenu " + obtenu);
  }
}

if (ko) {
  console.error("\nECHEC — " + ko + " cas sur " + cas.length + ".");
  process.exit(1);
}
console.log("\nOK — " + cas.length + " verifications sur runInterrompu.");
