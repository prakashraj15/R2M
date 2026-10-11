import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  // Live agent turns (model calls + remote DB) can exceed the proxy's 30 s default and end in "socket hang up".
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};
export default config;
