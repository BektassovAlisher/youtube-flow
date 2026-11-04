import type { NextRequest } from "next/server";
import { API_TOKEN, API_URL } from "@/lib/server-api";
import { SESSION_COOKIE, validSession } from "@/lib/session";

// Runtime proxy to FastAPI: one origin for the browser (no CORS), the API token never reaches the browser.
const REQUEST_HEADERS = ["content-type", "range", "if-range", "if-none-match", "x-forwarded-for"];
const RESPONSE_HEADERS = ["content-type", "content-range", "accept-ranges", "etag", "cache-control", "content-disposition", "x-total-count"];

async function proxy(req: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const changes = req.method !== "GET";
  if (changes && !validSession(req.cookies.get(SESSION_COOKIE)?.value)) {
    return Response.json({ detail: "Войдите, чтобы это сделать." }, { status: 401 });
  }

  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (API_TOKEN) headers.set("authorization", `Bearer ${API_TOKEN}`);

  try {
    const res = await fetch(`${API_URL}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`, {
      method: req.method,
      headers,
      body: changes ? await req.arrayBuffer() : undefined, // bytes, not text: uploaded files pass through intact
      cache: "no-store",
      signal: req.signal, // a closed tab also closes the upstream request (event streams especially)
    });
    const out = new Headers();
    for (const name of RESPONSE_HEADERS) {
      const value = res.headers.get(name);
      if (value) out.set(name, value);
    }
    const length = res.headers.get("content-length");
    if (length && !res.headers.get("content-encoding")) out.set("content-length", length);
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    if (req.signal.aborted) return new Response(null, { status: 499 });
    return Response.json({ detail: "Сервер API недоступен. Попробуйте чуть позже." }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as DELETE };
