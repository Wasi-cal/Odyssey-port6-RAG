/** @type {import('next').NextConfig} */
// BACKEND_URL is a build ARG (see Dockerfile) as well as a runtime env var --
// rewrites() destinations are resolved by `next build`, not re-read at
// `next start`, so it must be set at build time to actually take effect.
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

const nextConfig = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${BACKEND_URL}/:path*` }];
  },
};

export default nextConfig;
