// Verifie que le JavaScript inline des pages web PARSE. Rien de plus, et c'est deja
// beaucoup : tout le code des pages vit dans des <script> inline, personne ne les
// compile, et une parenthese oubliee ne se voit qu'a l'ouverture de la page — donc en
// production, sur le poste de quelqu'un d'autre.
//
//   node tools/test-syntaxe-js.js
//
// On ne l'EXECUTE pas (il touche au DOM, au reseau, a sessionStorage) : on demande
// seulement a Node de le compiler. new vm.Script() fait exactement ca.
const fs = require("fs");
const vm = require("vm");

const PAGES = ["index.html", "client.html", "info.html"];
let ko = 0, blocs = 0;

for (const fichier of PAGES) {
  const chemin = __dirname + "/../web/" + fichier;
  if (!fs.existsSync(chemin)) { console.error("KO " + fichier + " : fichier absent"); ko++; continue; }
  const page = fs.readFileSync(chemin, "utf8");
  // Les <script src="..."> n'ont pas de corps a compiler ; il n'y en a pas ici, mais
  // les ignorer coute une condition et evite un faux echec le jour ou il y en aura un.
  const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
  let m, n = 0;
  while ((m = re.exec(page)) !== null) {
    n++; blocs++;
    // Le compteur de lignes rend l'erreur exploitable : sans lui, Node annonce
    // « ligne 12 » du bloc, et on cherche dans une page de 1200 lignes.
    const avant = page.slice(0, m.index).split("\n").length;
    try {
      new vm.Script(m[1], { filename: fichier + " (bloc " + n + ", vers la ligne " + avant + ")" });
    } catch (e) {
      console.error("KO " + fichier + " bloc " + n + " (vers la ligne " + avant + ") : " + e.message);
      ko++;
    }
  }
  if (!n) console.log("   " + fichier + " : aucun script inline");
}

console.log(ko === 0 ? "OK — " + blocs + " bloc(s) de script compile(s) sans erreur."
                     : ko + " bloc(s) en echec");
process.exit(ko ? 1 : 0);
