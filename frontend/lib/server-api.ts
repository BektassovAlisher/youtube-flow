import { connection } from "next/server";

// Server components call FastAPI directly; the browser goes through /api/* (app/api/[...path]/route.ts).
// API_URL is read at runtime, so Docker can point it at http://api:8000.
export const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

// null when the API is down or answers with an error
export async function serverApi<T>(path: string): Promise<T | null> {
  await connection(); // per-request data: render at request time, never at build time
  const res = await fetch(`${API_URL}/${path}`, { cache: "no-store" }).catch(() => null);
  return res?.ok ? res.json() : null;
}
