import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { buildEnvProblem } from "./src/lib/buildenv";

// Local dev: the browser calls /api on this server and it is proxied to BACKEND_URL (default 127.0.0.1:8000).
// Deployed (Vercel): NEXT_PUBLIC_API_URL is set and the browser calls the backend directly (CORS-restricted there);
// no proxy. No secrets here or anywhere in client code.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
const backend = process.env.BACKEND_URL ?? (apiUrl ? "" : "http://127.0.0.1:8000");
const supabase = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const isDev = process.env.NODE_ENV !== "production";

const csp = [
  "default-src 'self'",
  // Next.js needs inline scripts for hydration; dev mode also needs eval for fast refresh
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${[apiUrl, supabase].filter(Boolean).join(" ")}${isDev ? " ws: http://127.0.0.1:*" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  env: {
    // Vercel sets VERCEL_ENV during every build; exposing it this way makes the preview guard (src/lib/envguard.ts)
    // independent of the "Automatically expose System Environment Variables" setting. Not a secret.
    BUILD_VERCEL_ENV: process.env.VERCEL_ENV ?? "",
  },
  async rewrites() {
    return backend ? [{ source: "/api/:path*", destination: `${backend}/api/:path*` }] : [];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: csp },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
  experimental: {
    // Local dev proxy only: a price refresh calls yfinance per ticker and can take ~30-60 s.
    proxyTimeout: 120_000,
  },
};

export default function config(phase: string): NextConfig {
  // `next typegen` (make check) loads the config in the same phase: only the real `next build` is checked
  if (phase === PHASE_PRODUCTION_BUILD && process.argv.slice(2).includes("build")) {
    const problem = buildEnvProblem(process.env);  // names only, never values
    if (problem) throw new Error(problem);
  }
  return nextConfig;
}
