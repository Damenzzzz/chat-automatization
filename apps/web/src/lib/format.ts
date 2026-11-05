const number = new Intl.NumberFormat("ru-RU");
const time = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const full = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
  hour: "2-digit",
  minute: "2-digit",
});

export function money(value: number | null | undefined): string {
  return value === null || value === undefined ? "нет цены" : `${number.format(value)} ₸`;
}

export function count(value: number): string {
  return number.format(value);
}

export function clock(value: string): string {
  return time.format(new Date(value));
}

export function shortDay(value: string): string {
  return day.format(new Date(value));
}

export function fullDate(value: string): string {
  return full.format(new Date(value));
}

export function whenShort(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? time.format(date) : day.format(date);
}

export function plural(value: number, one: string, few: string, many: string): string {
  const tens = Math.abs(value) % 100;
  const units = tens % 10;
  if (tens > 10 && tens < 20) return many;
  if (units === 1) return one;
  if (units >= 2 && units <= 4) return few;
  return many;
}
