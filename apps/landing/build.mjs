// Сборка лендинга: site/ -> dist/. Стили и скрипт получают хеш в имени,
// чтобы браузер держал их в кеше год, а новая версия подхватывалась сразу.
import { createHash } from "node:crypto";
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const HASHED = ["styles.css", "main.js", "nojs.css"];

export function build(src = join(here, "site"), out = join(here, "dist")) {
  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });

  const renamed = {};
  for (const name of HASHED) {
    const body = readFileSync(join(src, name));
    const hash = createHash("sha256").update(body).digest("hex").slice(0, 10);
    const dot = name.lastIndexOf(".");
    renamed[name] = `${name.slice(0, dot)}.${hash}${name.slice(dot)}`;
    writeFileSync(join(out, renamed[name]), body);
  }

  for (const name of readdirSync(src)) {
    if (HASHED.includes(name)) continue;
    if (name.endsWith(".html")) {
      let html = readFileSync(join(src, name), "utf8");
      for (const [from, to] of Object.entries(renamed)) {
        html = html.replaceAll(`"${from}"`, `"${to}"`).replaceAll(`"/${from}"`, `"/${to}"`);
      }
      writeFileSync(join(out, name), html);
    } else {
      cpSync(join(src, name), join(out, name), { recursive: true });
    }
  }
  return { out, renamed };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { out, renamed } = build();
  console.log(`dist: ${out}`);
  for (const [from, to] of Object.entries(renamed)) console.log(`  ${from} -> ${to}`);
}
