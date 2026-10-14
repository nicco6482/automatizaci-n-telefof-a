// Renderiza el anuncio fotograma a fotograma y lo monta en MP4 con su audio.
// Uso: node presentacion/anuncio/render.mjs <url_anuncio> <mezcla.wav> <salida.mp4> [fps] [ruta_a_playwright]
// La página debe exponer window.__seek(t) y window.__total (dashboard/src/anuncio/main.ts con ?render).
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const [url, wav, out, fpsArg, pwPath] = process.argv.slice(2);
if (!url || !wav || !out) {
  console.error("uso: node render.mjs <url> <mezcla.wav> <salida.mp4> [fps] [playwright]");
  process.exit(1);
}
const fps = Number(fpsArg ?? 30);
const require = createRequire(import.meta.url);
const { chromium } = require(pwPath ?? "playwright");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
const total = await page.evaluate(() => window.__total);
const frames = Math.ceil(total * fps);

const ff = spawn("ffmpeg", [
  "-v", "error", "-y",
  "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
  "-i", wav,
  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-tune", "animation",
  "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out,
], { stdio: ["pipe", "inherit", "inherit"] });

const t0 = Date.now();
for (let i = 0; i < frames; i++) {
  await page.evaluate((t) => window.__seek(t), i / fps);
  const buf = await page.screenshot({ type: "jpeg", quality: 93 });
  if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
  if (i % (fps * 10) === 0) {
    const el = (Date.now() - t0) / 1000;
    console.log(`${(i / fps).toFixed(0)} s / ${total.toFixed(0)} s · ${el.toFixed(0)} s transcurridos`);
  }
}
ff.stdin.end();
await new Promise((r) => ff.on("close", r));
await browser.close();
console.log(`listo: ${out} (${frames} fotogramas)`);
