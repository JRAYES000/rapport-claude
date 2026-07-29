// Mesure le contraste de chaque couleur de texte de client.html sur le fond qu'elle
// touche vraiment. Les valeurs sont lues DANS la page, pas recopiées à la main : une
// variable qu'on modifie sans y penser est reprise au prochain lancement.
//
//   node tools/test-contraste.js
//
// Seuils WCAG AA : 4,5:1 pour du texte, 3:1 pour un trait ou un aplat porteur de sens.
// Le CLAUDE.md annonçait un `test-client.js` qui mesurait cela « sur le rendu ». Il
// n'existait pas. Celui-ci mesure les valeurs déclarées, ce qui couvre le vrai risque
// (choisir une teinte trop claire) sans dépendre d'un navigateur.
const fs = require("fs");
const css = fs.readFileSync(__dirname + "/../web/client.html", "utf8");

// Garde-fou de syntaxe. Un commentaire mal referme a fait disparaitre en silence toute
// la regle `.compris` le 29/07/2026 : la page se chargeait, le bloc s'affichait sans son
// fond, et seul un coup d'oeil au rendu l'a montre. Un navigateur ne dit rien d'une
// regle CSS invalide — il la saute. C'est donc ici que ca se controle.
{
  const style = /<style>([\s\S]*?)<\/style>/.exec(css);
  if (!style) { console.error("ECHEC pas de bloc <style> dans client.html"); process.exit(1); }
  const brut = style[1];
  const sans = brut.replace(/\/\*[\s\S]*?\*\//g, "");   // retire les commentaires bien formes
  const ouverts = (brut.match(/\/\*/g) || []).length;
  const fermes = (brut.match(/\*\//g) || []).length;
  const orphelin = sans.includes("*/") || sans.includes("/*");
  const acc = [...sans].reduce((n, c) => n + (c === "{") - (c === "}"), 0);
  const pbs = [];
  if (ouverts !== fermes) pbs.push(ouverts + " ouvertures de commentaire pour " + fermes + " fermetures");
  if (orphelin) pbs.push("un /* ou un */ orphelin hors commentaire — la règle qui suit est perdue");
  if (acc !== 0) pbs.push("accolades déséquilibrées (" + acc + ")");
  if (pbs.length) { pbs.forEach((p) => console.error("  ECHEC " + p)); process.exit(1); }
  console.log("  ok    syntaxe du <style> : commentaires et accolades équilibrés");
}

// --nom:#rrggbb, y compris quand la valeur renvoie à une autre variable.
const VARS = {};
for (const m of css.matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\s*;/g)) VARS[m[1]] = m[2];

function rgb(h) {
  h = h.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}
function lum(h) {
  const [r, g, b] = rgb(h).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const v = (nom) => {
  const c = VARS[nom];
  if (!c) throw new Error("variable CSS introuvable : --" + nom);
  return c;
};

const CREME = () => v("creme"), BLANC = () => v("blanc");

// [ce qui est mesuré, couleur, fond, seuil]. Le fond est celui sur lequel l'élément
// repose RÉELLEMENT : une pastille de challenge est sur son voile, pas sur le crème.
const CAS = [
  ["texte secondaire",              v("gris"),        CREME(), 4.5],
  ["indications, dates",            v("gris-clair"),  CREME(), 4.5],
  ["alerte (vigilance)",            v("alerte"),      BLANC(), 4.5],
];
// Les quatre canaux : encre sur crème et sur blanc, teinte en trait, chiffre sur voile.
for (const n of [1, 2, 3, 4]) {
  CAS.push(
    ["canal " + n + " — titre de section (crème)", v("c" + n + "-ink"),   CREME(),               4.5],
    ["canal " + n + " — texte sur carte blanche",  v("c" + n + "-ink"),   BLANC(),               4.5],
    ["canal " + n + " — filet, barre, aplat",      v("c" + n),            CREME(),               3.0],
    ["canal " + n + " — numéro sur son voile",     v("c" + n + "-noir"),  v("c" + n + "-voile"), 4.5],
    ["canal " + n + " — voile lisible du fond",    v("c" + n + "-voile"), CREME(),               1.02],
  );
}
// Prose du bloc « ce que nous avons compris » : encre sombre sur le voile du canal 4.
CAS.push(["« ce que nous avons compris »", "#3a3631", v("c4-voile"), 4.5]);
// Corps des cartes et des encarts.
CAS.push(["corps des cartes", "#514a43", BLANC(), 4.5]);
// L'encart de vigilance est le seul sur fond teinte : son libelle et ses puces doivent
// y tenir les 4,5:1, sinon l'exception se paie en lisibilite.
CAS.push(["vigilance — libelle sur son voile", v("alerte"), v("alerte-voile"), 4.5]);
CAS.push(["vigilance — puces sur son voile", "#514a43", v("alerte-voile"), 4.5]);

let ko = 0;
for (const [quoi, fg, bg, seuil] of CAS) {
  const r = ratio(fg, bg);
  const ok = r >= seuil;
  if (!ok) ko++;
  console.log(
    (ok ? "  ok   " : "  ECHEC") +
    " " + quoi.padEnd(42) +
    " " + fg + " sur " + bg +
    " = " + r.toFixed(2) + ":1 (seuil " + seuil.toFixed(1) + ")"
  );
}
console.log(ko === 0
  ? "\n" + CAS.length + " paires mesurées, toutes au-dessus du seuil."
  : "\n" + ko + " paire(s) sous le seuil.");
process.exit(ko ? 1 : 0);
