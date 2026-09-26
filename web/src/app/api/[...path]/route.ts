/**
 * Same-origin proxy from the browser to the FastAPI backend.
 *
 * Replaces the old `next.config.mjs` rewrite, which had two problems:
 *  - it forwarded every backend path, so account spend, /metrics, /docs and
 *    `?refresh=true` (an uncached upstream fetch) were public;
 *  - rewrites are resolved at `next build`, so API_BASE_URL set at runtime
 *    (Deployment env, compose) had no effect.
 *
 * This handler reads API_BASE_URL per request and forwards only an allowlist
 * of public, read-only endpoints. Account endpoints (your real spend and
 * credit) are forwarded only when EXPOSE_ACCOUNT_DATA=true; enable that only
 * when the site sits behind authentication (for example a Traefik
 * basicAuth/forwardAuth middleware).
 */
import { type NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const UPSTREAM_TIMEOUT_MS = 20_000;

const PUBLIC_ROUTES: RegExp[] = [
  /^models$/,
  /^models\/top$/,
  /^models\/.+$/, // /models/{id} and /models/{id}/history
  /^compare\/.+$/,
  /^kilo\/plans$/,
  /^kilo\/models(\/.+)?$/,
  /^kilo\/projection$/,
  /^healthz$/,
];

const ACCOUNT_ROUTES: RegExp[] = [
  /^accounts\/usage$/,
  /^accounts\/activity$/,
  /^accounts\/openai-activity$/,
];

// Query parameters that must never be forwarded from the public internet.
const BLOCKED_PARAMS = ["refresh"];

function accountsExposed(): boolean {
  return (process.env.EXPOSE_ACCOUNT_DATA ?? "").toLowerCase() === "true";
}

function isAllowed(path: string): boolean {
  if (PUBLIC_ROUTES.some((re) => re.test(path))) return true;
  return accountsExposed() && ACCOUNT_ROUTES.some((re) => re.test(path));
}

function notFound(): NextResponse {
  return NextResponse.json({ detail: "Not Found" }, { status: 404 });
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path: segments } = await params;

  // Reject dot segments and empty segments outright: URL normalisation would
  // otherwise turn "models/../accounts/usage" into an allowlist bypass.
  if (
    !segments.length ||
    segments.some((s) => s === "" || s === "." || s === ".." || s.includes("/"))
  ) {
    return notFound();
  }

  const path = segments.join("/");
  if (!isAllowed(path)) return notFound();

  const base = (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
  const upstream = new URL(`${base}/${segments.map(encodeURIComponent).join("/")}`);
  req.nextUrl.searchParams.forEach((value, key) => {
    if (!BLOCKED_PARAMS.includes(key)) upstream.searchParams.append(key, value);
  });

  let res: Response;
  try {
    res = await fetch(upstream, {
      method: "GET",
      headers: { accept: req.headers.get("accept") ?? "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (err) {
    const timedOut = err instanceof Error && err.name === "TimeoutError";
    return NextResponse.json(
      { detail: timedOut ? "Upstream timeout" : "Upstream unavailable" },
      { status: timedOut ? 504 : 502 },
    );
  }

  const headers = new Headers();
  const contentType = res.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("cache-control", "no-store");
  return new Response(res.body, { status: res.status, headers });
}
