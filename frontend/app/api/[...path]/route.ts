// Runtime proxy to FastAPI: keeps one origin (no CORS) and reads API_URL at runtime, so Docker can point it at http://api:8000.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

async function proxy(req: Request, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  try {
    const res = await fetch(`${API_URL}/${path.map(encodeURIComponent).join("/")}`, {
      method: req.method,
      headers: { "content-type": "application/json" },
      body: req.method === "POST" ? await req.text() : undefined,
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/octet-stream" },
    });
  } catch {
    return Response.json({ detail: "API недоступен" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as DELETE };
