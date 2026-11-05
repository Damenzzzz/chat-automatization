export type Identity = { email: string } | { phone: string };

export function parseIdentity(raw: string): Identity | null {
  const value = raw.trim();
  if (value.includes("@"))
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? { email: value } : null;
  const digits = value.replace(/\D/g, "");
  if (digits.length === 10 && digits[0] === "7") return { phone: `+7${digits}` };
  if (digits.length === 11 && (digits[0] === "7" || digits[0] === "8"))
    return { phone: `+7${digits.slice(1)}` };
  return null;
}

export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/overview";
}
