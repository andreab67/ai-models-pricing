/** @type {import('next').NextConfig} */
// Browser calls to /api/* are served by src/app/api/[...path]/route.ts, which
// reads API_BASE_URL at request time and forwards only an allowlist of public
// endpoints. Do not add a rewrite here: rewrites are frozen at `next build`
// and would forward every backend path.
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
};

export default nextConfig;
