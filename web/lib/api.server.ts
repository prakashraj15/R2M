import "server-only";
import { headers } from "next/headers";
import { parseResponse } from "./api";
// Reads only: session mutations must use the browser proxy so Set-Cookie reaches it.
export async function serverRequest<T = unknown>(path: string): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw Error("Use an API-relative path.");
  const origin = process.env.R2M_INTERNAL_API_URL || "http://127.0.0.1:8000";
  const cookie = (await headers()).get("cookie");
  return parseResponse<T>(
    await fetch(`${origin.replace(/\/$/, "")}/api/v1${path}`, {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    }),
  );
}
