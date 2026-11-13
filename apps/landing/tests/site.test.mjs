// Проверки собранного лендинга (apps/web/out, сборка LANDING_ONLY=1):
// наружу уходит только главная, без кабинета, входа и обращений к API сервиса.
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const out = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web", "out");
assert.ok(existsSync(join(out, "index.html")), "нет apps/web/out — сначала make landing-build");
const html = readFileSync(join(out, "index.html"), "utf8");

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}
const files = walk(out);
const scripts = files.filter((path) => path.endsWith(".js") && path.includes("_next"));
const bundle = scripts.map((path) => readFileSync(path, "utf8")).join("\n");

test("в сборку попала только главная страница", () => {
  const pages = files
    .filter((path) => path.endsWith(".html"))
    .map((path) => path.slice(out.length + 1))
    .sort();
  assert.deepEqual(pages, ["404.html", "_not-found.html", "index.html"]);
  for (const route of ["login", "signup", "overview", "dialogs", "leads", "balance", "settings"]) {
    assert.ok(!existsSync(join(out, route)), `в сборке есть маршрут кабинета /${route}`);
  }
});

test("на странице нет ссылок на вход, регистрацию и кабинет", () => {
  for (const hidden of ['href="/login', 'href="/signup', "Войти в кабинет", "демо-кабинет"]) {
    assert.ok(!html.includes(hidden), `на лендинге осталось «${hidden}»`);
  }
});

test("скрипты лендинга не обращаются к API сервиса сами", () => {
  // Чат на лендинге отвечает записанными репликами, кнопки демо-входа нет.
  assert.ok(!bundle.includes("/demo/login"), "в сборке остался демо-вход");
  assert.ok(bundle.includes("/api/lead"), "форма должна отправлять заявку на /api/lead");
});

test("есть разделы лендинга и каждая ссылка-якорь куда-то ведёт", () => {
  const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]));
  for (const id of ["main", "night", "skills", "team", "start", "price", "contact"]) {
    assert.ok(ids.has(id), `нет раздела #${id}`);
  }
  const anchors = [...html.matchAll(/href="#([^"]+)"/g)].map((match) => match[1]);
  assert.ok(anchors.includes("contact") && anchors.includes("team"));
  for (const anchor of anchors) assert.ok(ids.has(anchor), `ссылка на несуществующий #${anchor}`);
});

test("форма заявки: поля, ловушка для роботов, статус для экранных читалок", () => {
  const form = html.slice(html.indexOf("<form", html.indexOf('id="contact"')));
  for (const field of ["name", "contact", "company", "task", "website"]) {
    assert.ok(form.includes(`name="${field}"`), `нет поля ${field}`);
  }
  assert.match(form, /name="website"[^>]*tabindex="-1"|tabindex="-1"[^>]*name="website"/i);
  assert.match(form, /aria-live="polite"/);
  assert.ok(form.includes("Отправить заявку"));
});

test("ночь магазина: журнал виден без JavaScript, шесть событий до утра", () => {
  const night = html.slice(html.indexOf('id="night"'), html.indexOf('id="skills"'));
  for (const time of ["23:41", "00:15", "01:30", "03:00", "05:00", "07:00"]) {
    assert.ok(night.includes(time), `в журнале нет ${time}`);
  }
  assert.ok(!/<li[^>]*opacity-0/.test(night), "строки журнала скрыты в исходной разметке");
});

test("страница ничего не грузит с чужих серверов и обходится без картинок", () => {
  const external = [...html.matchAll(/(?:src|href)="(https?:)?\/\/[^"]+"/g)].map((match) => match[0]);
  assert.deepEqual(external, []);
  const images = files.filter((path) => /\.(png|jpe?g|webp|gif|mp4)$/i.test(path));
  assert.deepEqual(images, []);
});
