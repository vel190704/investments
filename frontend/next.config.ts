import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Browser talks only to Next; /api/* is proxied to the FastAPI backend on 127.0.0.1.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  experimental: {
    // Price refresh calls yfinance per ticker and can take ~30-60 s.
    proxyTimeout: 120_000,
  },
};

export default nextConfig;
