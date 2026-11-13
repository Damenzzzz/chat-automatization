import type { NextConfig } from "next";

const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8100";

// LANDING_ONLY=1 собирает один статический лендинг: маршрутами считаются только
// файлы *.landing.tsx, поэтому кабинет, вход и proxy.ts в сборку не попадают (ADR 0012).
const landingOnly = process.env.LANDING_ONLY === "1";

const turbopack: NextConfig["turbopack"] = {
  rules: {
    "*.css": {
      loaders: ["@tailwindcss/turbopack"],
      as: "*.css",
    },
  },
};

const landingConfig: NextConfig = {
  output: "export",
  distDir: "out",
  pageExtensions: ["landing.tsx"],
  turbopack,
};

const serviceConfig: NextConfig = {
  output: "standalone",
  experimental: { proxyTimeout: 300_000 },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiUrl}/:path*` },
      { source: "/auth/:path*", destination: `${apiUrl}/auth/:path*` },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack,
};

export default landingOnly ? landingConfig : serviceConfig;
