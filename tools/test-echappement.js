// Verifie que rien de ce qui sort de esc() ou encArg() ne peut casser l'attribut HTML
// dans lequel les pages les injectent. Un collaborateur nomme « O'Brien » suffisait :
// encodeURIComponent laisse passer l'apostrophe, la chaine JavaScript de l'attribut
// onclick se fermait, et sa fiche ne repondait plus.
//
//   node tools/test-echappement.js
//
// LES DEUX PAGES sont couvertes depuis le 02/08/2026. Jusque-la seul index.html etait
// lu, et client.html avait derive sans que personne ne le voie : son esc() n'echappait
// pas l'apostrophe. Un test qui ne regarde qu'un fichier sur deux ne protege pas le
// second, il donne seulement l'impression qu'il est protege.
//
// Sans dependance : on extrait les fonctions de la page et on les evalue.
const fs = require("fs");

const NOMS = ["O'Brien", "d'Artagnan", `"; alert(1); //`, "<script>alert(1)</script>",
              "a'+alert(1)+'", "Élodie Ré", "Jean-Luc (test)", ""];
let ko = 0;

function extraire(page, nom) {
  const m = new RegExp("function " + nom + "\\(s\\).*?\\n", "s").exec(page);
  return m ? m[0] : null;
}

// esc() : dans un attribut entre guillemets OU entre apostrophes, rien ne survit.
for (const fichier of ["index.html", "client.html"]) {
  const page = fs.readFileSync(__dirname + "/../web/" + fichier, "utf8");
  const src = extraire(page, "esc");
  if (!src) { console.error("KO " + fichier + " : esc() introuvable"); ko++; continue; }
  const { esc } = new Function(src + "return { esc };")();
  for (const n of NOMS) {
    if (/["'<>]/.test(esc(n))) {
      console.error("KO " + fichier + " esc a laisse passer :", JSON.stringify(n), "->", esc(n));
      ko++;
    }
  }
}

// encArg() n'existe que dans index.html : c'est la seule page qui fabrique des
// attributs onclick="f('...')" a partir de donnees.
{
  const page = fs.readFileSync(__dirname + "/../web/index.html", "utf8");
  const src = extraire(page, "encArg");
  if (!src) { console.error("KO index.html : encArg() introuvable"); ko++; }
  else {
    const { encArg } = new Function(src + "return { encArg };")();
    for (const n of NOMS) {
      if (encArg(n).includes("'")) { console.error("KO encArg a laisse passer :", JSON.stringify(n)); ko++; }
      if (decodeURIComponent(encArg(n)) !== n) { console.error("KO aller-retour casse :", JSON.stringify(n)); ko++; }
    }
  }
}

console.log(ko === 0
  ? "OK — " + NOMS.length + " noms hostiles sur 2 pages, aucun ne casse l'attribut."
  : ko + " echec(s)");
process.exit(ko ? 1 : 0);
