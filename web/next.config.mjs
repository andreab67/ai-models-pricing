/** @type {import('next').NextConfig} */
const apiBase = process.env.API_BASE_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Pin the Turbopack project root to this directory. Without this,
  // Turbopack's auto-detection can walk up past the repo and pick up an
  // unrelated package-lock.json in the parent user directory, which Next 16
  // warns about at build time.
  turbopack: {
    root: import.meta.dirname,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/:path*`,
      },
    ];
  },
};

export default nextConfig;
