import type { NextConfig } from "next";

// One codebase, two separately built and deployed apps (NEXT_PUBLIC_R2M_APP at build time):
//   control: R2M Control Plane, proxies /api/* to the private R2M platform API (127.0.0.1:8000)
//   desk:    OpsPilot Operations Desk, proxies /agent-api/* to the private OpsPilot agent API (127.0.0.1:8100)
const APP = process.env.NEXT_PUBLIC_R2M_APP === "desk" ? "desk" : "control";
const CONTROL = (process.env.NEXT_PUBLIC_CONTROL_URL || "http://localhost:3000").replace(/\/$/, "");

const config: NextConfig = {
  output: "standalone",
  // Live agent turns (model calls + remote DB) can exceed the proxy's 30 s default and end in "socket hang up".
  experimental: { proxyTimeout: 120_000 },
  async redirects() {
    if (APP === "desk") {
      return [
        { source: "/approvals", destination: `${CONTROL}/approvals`, permanent: false },
        { source: "/agents/:path*", destination: `${CONTROL}/agents/:path*`, permanent: false },
      ];
    }
    return [];
  },
  async rewrites() {
    return APP === "desk"
      ? [{ source: "/agent-api/:path*", destination: "http://127.0.0.1:8100/agent-api/:path*" }]
      : [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
  },
};
export default config;
