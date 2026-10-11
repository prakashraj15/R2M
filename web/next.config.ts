import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  // Live agent turns (model calls + remote DB) can exceed the proxy's 30 s default and end in "socket hang up".
  experimental: { proxyTimeout: 120_000 },
  // Live only: the mock design-preview routes redirect to the backend-connected pages.
  async redirects() {
    const agent = "2246399b-c8bd-5598-b1c7-32a0da4d3d96"; // OpsPilot's deterministic seed id (scripts/seed_demo.py)
    return [
      { source: "/", destination: "/demo/agent", permanent: false },
      { source: "/agents/opspilot", destination: `/agents/${agent}`, permanent: false },
      { source: "/agents/opspilot/:path*", destination: `/agents/${agent}/:path*`, permanent: false },
    ];
  },
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
