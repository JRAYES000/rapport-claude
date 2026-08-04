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
// Ce controle-ci est generique : il tourne sur TOUTES les pages. Les mesures de couleur
// qui suivent restent propres a client.html, ou vivent les variables ; info.html reprend
// exactement les memes valeurs hexadecimales, donc ses contrastes sont ceux deja mesures
// ici — mais rien ne protegeait sa syntaxe CSS avant le 02/08/2026.
for (const fichier of ["client.html", "info.html"]) {
  const src = fs.readFileSync(__dirname + "/../web/" + fichier, "utf8");
  const style = /<style>([\s\S]*?)<\/style>/.exec(src);
  if (!style) { console.error("ECHEC pas de bloc <style> dans " + fichier); process.exit(1); }
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
  if (pbs.length) { pbs.forEach((p) => console.error("  ECHEC " + fichier + " : " + p)); process.exit(1); }
  console.log("  ok    syntaxe du <style> de " + fichier + " : commentaires et accolades équilibrés");
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
    // Onglets : libelle ferme sur le creme, libelle ouvert sur son voile, pastille de
    // compteur en blanc sur la teinte pleine.
    ["canal " + n + " — onglet fermé",             v("c" + n + "-ink"),   CREME(),               4.5],
    ["canal " + n + " — onglet ouvert",            v("c" + n + "-noir"),  v("c" + n + "-voile"), 4.5],
    ["canal " + n + " — compteur sur la teinte",   BLANC(),               v("c" + n + "-noir"),  4.5],
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
// Bloc d'audit d'un livrable (onglet « Vos livrables », donc canal 2). Il ne s'affiche
// que pour le manager, ce qui est justement la raison de le mesurer ici : personne
// d'autre ne le verra, donc personne d'autre ne signalera qu'il est illisible.
CAS.push(["audit — note sur son voile",        v("c2-noir"),  v("c2-voile"), 4.5]);
CAS.push(["audit — « /100 » sur son voile",    v("c2-ink"),   v("c2-voile"), 4.5]);
CAS.push(["audit — repère d'envoi",            v("gris"),     v("c2-voile"), 4.5]);
CAS.push(["audit — « à garder » sur le voile", v("encre"),    v("c2-voile"), 4.5]);
// La jauge repose sur son rail, pas sur le creme : c'est un aplat, seuil 3:1.
CAS.push(["audit — jauge remplie",             v("c2"),       v("bord"),     3.0]);
CAS.push(["audit — raison d'une piste",        v("gris"),     BLANC(),       4.5]);
// « Vos livrables » : chaque challenge repose desormais sur le voile de sa teinte
// (05/08/2026). Trois textes tombent DIRECTEMENT dessus — titre, chapeau, note — et
// aucun n'etait mesure sur ce fond : les paires existantes portaient sur le creme, qui
// est plus clair. C'est exactement le cas ou l'oeil dit « ca passe » et ou le rapport
// dit non.
// Les CHALLENGES ont leurs propres teintes depuis le 05/08/2026 (violet, bleu, ambre) :
// `--cN` dit dans quel onglet on est, `--chN` de quelle mission on parle. Elles servent
// dans DEUX onglets — « Vos livrables » et « Analyse client » — donc sur le creme, sur
// leur propre voile et sur des cartes blanches. Tout est mesure, rien n'est juge a l'oeil.
for (const n of [1, 2, 3]) {
  const ink = v("ch" + n + "-ink"), noir = v("ch" + n + "-noir");
  const vif = v("ch" + n), voile = v("ch" + n + "-voile");
  CAS.push(
    ["challenge " + n + " — titre sur son voile",  ink,     voile,   4.5],
    ["challenge " + n + " — titre sur le crème",   ink,     CREME(), 4.5],
    ["challenge " + n + " — titre sur carte",      ink,     BLANC(), 4.5],
    ["challenge " + n + " — texte fort sur voile", noir,    voile,   4.5],
    ["challenge " + n + " — filet sur le crème",   vif,     CREME(), 3.0],
    ["challenge " + n + " — filet sur son voile",  vif,     voile,   3.0],
    ["challenge " + n + " — blanc sur la teinte",  BLANC(), noir,    4.5],
    ["challenge " + n + " — chapeau sur voile",    v("gris"), voile, 4.5],
    // Le voile doit se DETACHER du creme de la page : un fond de section qui s'y confond
    // ne separe plus rien, et c'est precisement ce qu'on cherchait a obtenir.
    ["challenge " + n + " — voile distinct du fond", voile, CREME(), 1.04],
  );
}

// ---------------------------------------------------------------- ecart perceptuel
//
// Le rapport de contraste ne repond PAS a « ces deux fonds se distinguent-ils ». Deux
// pastels de meme clarte et de teintes differentes rendent 1,0:1 tout en etant
// parfaitement distincts a l'oeil ; l'inverse existe aussi. Il faut une distance
// colorimetrique, et c'est elle qui a rattrape le violet et le bleu des challenges le
// 05/08/2026 : a 5,2 dE ils se ressemblaient, la ou les autres paires sont a 25.
//
// CIE76 sur Lab, pas CIEDE2000 : sur des pastels clairs et peu satures l'ecart entre les
// deux formules est negligeable, et celle-ci tient en dix lignes sans dependance.
// Reperes : < 2 imperceptible, 2 a 5 visible en comparant, > 5 franchement distinct.
function lab(h) {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const x = f((0.4124 * c[0] + 0.3576 * c[1] + 0.1805 * c[2]) / 0.95047);
  const y = f(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]);
  const z = f((0.0193 * c[0] + 0.1192 * c[1] + 0.9505 * c[2]) / 1.08883);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}
const dE = (a, b) => {
  const A = lab(a), B = lab(b);
  return Math.hypot(A[0] - B[0], A[1] - B[1], A[2] - B[2]);
};

// Les trois fonds de challenge doivent se distinguer ENTRE EUX, pas seulement du creme :
// c'est toute la raison d'etre de ces couleurs.
const ECARTS = [];
for (const [a, b] of [[1, 2], [1, 3], [2, 3]]) {
  ECARTS.push([`fonds des challenges ${a} et ${b}`, v(`ch${a}-voile`), v(`ch${b}-voile`), 6]);
}

let ko = 0;
for (const [quoi, c1, c2, mini] of ECARTS) {
  const d = dE(c1, c2);
  const ok = d >= mini;
  if (!ok) ko++;
  console.log(`  ${ok ? "ok  " : "ECHEC"}  ${quoi.padEnd(41)} ${c1} / ${c2} = ${d.toFixed(1)} dE (mini ${mini})`);
}
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
