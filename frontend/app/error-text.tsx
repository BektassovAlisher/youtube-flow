"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ApiError } from "@/lib/api";

// an error message; a 401 also links to the login page and back
export default function ErrorText({ error }: { error: Error | string }) {
  const path = usePathname();
  const message = typeof error === "string" ? error : error.message;
  return (
    <p className="error fade" role="alert">
      {message}
      {error instanceof ApiError && error.status === 401 && (
        <>
          {" "}
          <Link href={`/login?next=${encodeURIComponent(path)}`}>Войти →</Link>
        </>
      )}
    </p>
  );
}
