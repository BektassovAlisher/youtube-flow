import { connection } from "next/server";

// Server components call FastAPI directly; the browser goes through /api/* (app/api/[...path]/route.ts).
// Both are read at runtime, so Docker can point API_URL at http://api:8000.
export const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";
export const API_TOKEN = process.env.API_TOKEN ?? "";

// status 0: the API did not answer at all
export type Fetched<T> = { data: T | null; status: number; headers: Headers | null };

export async function serverApi<T>(path: string): Promise<Fetched<T>> {
  await connection(); // per-request data: render at request time, never at build time
  try {
    const res = await fetch(`${API_URL}/${path}`, { cache: "no-store" });
    return { data: res.ok ? await res.json() : null, status: res.status, headers: res.headers };
  } catch {
    return { data: null, status: 0, headers: null };
  }
}
