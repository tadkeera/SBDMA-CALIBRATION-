/** @type {import('next').NextConfig} */

/**
 * The browser talks to `/api/v1/*` on its own origin and Next rewrites that to
 * the FastAPI server. Consequences:
 *  - the session cookie is same-site, so `SameSite=Strict` actually holds;
 *  - no CORS preflight on every request;
 *  - the client never needs to know the backend host, which keeps the sandbox
 *    preview and the production deployment on the same code path.
 */
const API_ORIGIN = process.env.API_ORIGIN ?? 'http://127.0.0.1:8000';

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${API_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
