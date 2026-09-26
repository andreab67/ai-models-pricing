/** @type {import('next').NextConfig} */
// Browser calls to /api/* are served by src/app/api/[...path]/route.ts, which
// reads API_BASE_URL at request time and forwards only an allowlist of public
// endpoints. Do not add a rewrite here: rewrites are frozen at `next build`
// and would forward every backend path.
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
