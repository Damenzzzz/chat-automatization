// Проверки лендинга: сборка, ссылки, вес страницы и то, что кабинет наружу не торчит.
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, readdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

import { build } from "../build.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, "..", "site");
const { out, renamed } = build(site, mkdtempSync(join(tmpdir(), "satushy-landing-")));
const html = readFileSync(join(out, "index.html"), "utf8");
const css = readFileSync(join(out, renamed["styles.css"]), "utf8");
const js = readFileSync(join(out, renamed["main.js"]), "utf8");

test("сборка переименовывает стили и скрипт и чинит ссылки на них", () => {
  for (const [from, to] of Object.entries(renamed)) {
    assert.match(to, /\.[0-9a-f]{10}\./);
    assert.ok(existsSync(join(out, to)), `${to} нет в dist`);
    assert.ok(!existsSync(join(out, from)), `${from} остался без хеша`);
    assert.ok(!html.includes(`"${from}"`), `в index.html осталась ссылка на ${from}`);
  }
  assert.ok(html.includes(`href="${renamed["styles.css"]}"`));
  assert.ok(html.includes(`src="${renamed["main.js"]}"`));
  const notFound = readFileSync(join(out, "404.html"), "utf8");
  assert.ok(notFound.includes(`href="/${renamed["styles.css"]}"`));
});

test("все локальные файлы, на которые ссылается страница, существуют", () => {
  const refs = [...html.matchAll(/(?:href|src)="([^"#][^"]*)"/g)].map((m) => m[1]);
  assert.ok(refs.length >= 5);
  for (const ref of refs) assert.ok(existsSync(join(out, ref)), `нет файла ${ref}`);
  for (const [, font] of css.matchAll(/url\("(fonts\/[^"]+)"\)/g)) {
    assert.ok(existsSync(join(out, font)), `нет шрифта ${font}`);
  }
});

test("страница ничего не грузит с чужих серверов", () => {
  for (const [name, text] of [
    ["index.html", html],
    ["styles.css", css],
    ["main.js", js],
  ]) {
    const external = text.match(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}/gi) ?? [];
    assert.deepEqual(external, [], `${name} ссылается наружу`);
  }
});

test("в разметке нет встроенных стилей и скриптов (их запрещает CSP)", () => {
  assert.ok(!/<style[\s>]/i.test(html), "встроенный <style>");
  assert.ok(!/\sstyle="/i.test(html), "атрибут style");
  assert.ok(!/<script(?![^>]*\ssrc=)[^>]*>/i.test(html), "встроенный <script>");
  assert.ok(!/\son[a-z]+="/i.test(html), "обработчик в атрибуте");
});

test("кабинет и API магазина на лендинге не упоминаются", () => {
  for (const hidden of ["/login", "/signup", "/overview", "/dialogs", "демо-кабинет"]) {
    assert.ok(!html.includes(hidden), `на лендинге осталось «${hidden}»`);
  }
});

test("каждая ссылка-якорь ведёт на существующий раздел", () => {
  const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
  const anchors = [...html.matchAll(/href="#([^"]+)"/g)].map((m) => m[1]);
  assert.ok(anchors.includes("contact"));
  for (const anchor of anchors) assert.ok(ids.has(anchor), `нет раздела #${anchor}`);
});

test("форма заявки: обязательные поля, ловушка для роботов и адрес отправки", () => {
  const form = html.slice(html.indexOf('<form'), html.indexOf("</form>"));
  assert.match(form, /name="name"[^>]*required/s);
  assert.match(form, /name="contact"[^>]*required/s);
  assert.match(form, /name="website"[^>]*tabindex="-1"/s);
  assert.match(form, /aria-live="polite"/);
  for (const field of ["name", "contact", "company", "task", "website"]) {
    assert.ok(form.includes(`for="f-${field}"`), `у поля ${field} нет подписи`);
  }
  assert.ok(js.includes('fetch("/api/lead"'));
});

test("без JavaScript журнал виден: есть запасной файл стилей", () => {
  assert.match(html, /<noscript><link rel="stylesheet" href="nojs\.[0-9a-f]{10}\.css"/);
  assert.equal((html.match(/shift__row is-waiting/g) ?? []).length, 6);
});

test("страница лёгкая: до первого экрана меньше 150 КБ по сети", () => {
  const gz = (text) => gzipSync(text).length;
  const code = gz(html) + gz(css) + gz(js);
  assert.ok(code < 20_000, `html+css+js в gzip: ${code} байт`);

  // Шрифты, которые нужны для русского текста; казахский набор догружается по требованию.
  const fonts = readdirSync(join(out, "fonts"))
    .filter((name) => !name.includes("cyrillic-ext"))
    .reduce((sum, name) => sum + statSync(join(out, "fonts", name)).size, 0);
  assert.ok(code + fonts < 150_000, `всего ${code + fonts} байт`);
  assert.ok(!readdirSync(out).some((name) => /\.(png|jpe?g|webp|gif|mp4)$/i.test(name)), "картинок быть не должно");
});
