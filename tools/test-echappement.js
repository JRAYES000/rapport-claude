// Verifie que rien de ce qui sort de esc() ou encArg() ne peut casser l'attribut HTML
// dans lequel index.html les injecte. Un collaborateur nomme « O'Brien » suffisait :
// encodeURIComponent laisse passer l'apostrophe, la chaine JavaScript de l'attribut
// onclick se fermait, et sa fiche ne repondait plus.
//
//   node tools/test-echappement.js
//
// Sans dependance : on extrait les deux fonctions de la page et on les evalue.
const fs = require("fs");
const page = fs.readFileSync(__dirname + "/../web/index.html", "utf8");
const src = /function esc\(s\).*?\n/s.exec(page)[0] + /function encArg\(s\).*?\n/s.exec(page)[0];
const { esc, encArg } = new Function(src + "return { esc, encArg };")();

const NOMS = ["O'Brien", "d'Artagnan", `"; alert(1); //`, "<script>alert(1)</script>",
              "a'+alert(1)+'", "Élodie Ré", "Jean-Luc (test)", ""];
let ko = 0;
for (const n of NOMS) {
  // esc() : dans un attribut entre guillemets, aucun guillemet ni chevron ne survit.
  if (/["'<>]/.test(esc(n))) { console.error("KO esc a laisse passer :", n, "->", esc(n)); ko++; }
  // encArg() : dans onclick="f('...')", aucune apostrophe ne survit...
  if (encArg(n).includes("'")) { console.error("KO encArg a laisse passer :", n); ko++; }
  // ...et la valeur revient intacte de l'autre cote.
  if (decodeURIComponent(encArg(n)) !== n) { console.error("KO aller-retour casse :", n); ko++; }
}
console.log(ko === 0 ? "OK — " + NOMS.length + " noms hostiles, aucun ne casse l'attribut."
                     : ko + " echec(s)");
process.exit(ko ? 1 : 0);
