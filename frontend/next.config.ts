import type { NextConfig } from "next";
import path from "node:path";

const repositoryRoot = path.resolve(__dirname, "..");

const nextConfig: NextConfig = {
  outputFileTracingRoot: repositoryRoot,
  poweredByHeader: false,
  turbopack: { root: repositoryRoot },
  async headers() {
    return [
      {
        source: "/respond/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store, private" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
