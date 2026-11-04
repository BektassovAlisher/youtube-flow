import { createHmac, timingSafeEqual } from "node:crypto";

// Optional password for the whole app (APP_PASSWORD). Reading stays open; anything that spends API credits
// or deletes data needs a signed session cookie. Server-only: imported by route handlers and server actions.
export const SESSION_COOKIE = "vf_session";
const PASSWORD = process.env.APP_PASSWORD ?? "";
const SECRET = process.env.SESSION_SECRET || `videoflow:${PASSWORD}`; // changing the password signs everyone out
const DAYS = 30;

export const authRequired = () => PASSWORD.length > 0;

const sign = (payload: string) => createHmac("sha256", SECRET).update(payload).digest("base64url");

function same(a: string, b: string) {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export function checkPassword(input: string) {
  return authRequired() && same(sign(`pw:${input}`), sign(`pw:${PASSWORD}`));
}

export function newSession() {
  const payload = `v1.${Date.now() + DAYS * 864e5}`;
  return { value: `${payload}.${sign(payload)}`, maxAge: DAYS * 86400 };
}

export function validSession(value: string | undefined) {
  if (!authRequired()) return true;
  if (!value) return false;
  const i = value.lastIndexOf(".");
  if (i < 0) return false;
  const payload = value.slice(0, i);
  return same(value.slice(i + 1), sign(payload)) && Number(payload.split(".")[1]) > Date.now();
}

// only same-site paths after login, never "//evil.example"
export const safeNext = (next: string | null | undefined) => (next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
