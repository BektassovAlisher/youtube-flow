"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { checkPassword, newSession, safeNext, SESSION_COOKIE } from "@/lib/session";

export async function login(form: FormData) {
  const next = safeNext(String(form.get("next") ?? "/"));
  if (!checkPassword(String(form.get("password") ?? ""))) {
    redirect(`/login?error=1&next=${encodeURIComponent(next)}`);
  }
  const { value, maxAge } = newSession();
  const https = (await headers()).get("x-forwarded-proto") === "https";
  (await cookies()).set(SESSION_COOKIE, value, { httpOnly: true, sameSite: "lax", secure: https, maxAge, path: "/" });
  redirect(next);
}

export async function logout() {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/");
}
