// Copia el anuncio compilado a /anuncio en la raíz del repositorio para publicarlo en GitHub Pages.
// Se ejecuta después de `vite build` (npm run build:pages). El panel no se copia: necesita la API.
// Copia fichero a fichero: fs.cpSync recursivo falla en Windows con rutas que llevan «ñ».
import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, "..", "dist");
const out = join(here, "..", "..", "anuncio");

function copyDir(from, to) {
  mkdirSync(to, { recursive: true });
  for (const f of readdirSync(from)) {
    const src = join(from, f);
    if (statSync(src).isDirectory()) copyDir(src, join(to, f));
    else copyFileSync(src, join(to, f));
  }
}

if (!existsSync(join(dist, "anuncio.html"))) throw new Error("Falta dist/anuncio.html: ejecuta antes `npm run build`.");
rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "assets"), { recursive: true });
copyFileSync(join(dist, "anuncio.html"), join(out, "index.html"));
for (const f of readdirSync(join(dist, "assets"))) {
  if (!f.startsWith("main-")) copyFileSync(join(dist, "assets", f), join(out, "assets", f));
}
copyDir(join(dist, "anuncio"), join(out, "anuncio"));
console.log(`anuncio copiado a ${out}`);
