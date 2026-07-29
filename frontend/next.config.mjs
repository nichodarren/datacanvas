/**
 * Next.js configuration.
 *
 * **Why the API is proxied rather than called directly.** Frontend and API are
 * one origin in production — §10.1 describes one system — and this rewrite
 * makes development match that. Calling the API origin directly instead would
 * need CORS with credentials: a second security surface, configured in a second
 * place, to reproduce something the deployment already gives for free.
 *
 * An earlier version of this comment claimed the proxy was *required* because
 * §13.2 uses `SameSite=Lax` cookies. **That was wrong**, and correcting it is
 * worth more than quietly deleting it: SameSite compares *sites*, and a port is
 * not part of a site, so `localhost:3000` and `localhost:8000` are same-site
 * and the cookie would travel fine. CORS is the actual blocker. The decision
 * stands; the reason did not.
 *
 * **The body limit is not optional.** Next buffers proxied request bodies and
 * caps them at 10 MB by default — 2% of what NFR-SCALE.4 permits. Found by
 * uploading a 480 MB file and getting a 500 from the *proxy*, with nothing in
 * the API log at all. Raised to the documented limit so development cannot
 * accept a size production would refuse, or refuse a size production allows.
 */
const backend = process.env.DATACANVAS_API_ORIGIN ?? "http://127.0.0.1:8000";

/**
 * Where the build output goes.
 *
 * `scripts/check.sh` sets this so a verification build writes somewhere else
 * than `.next`. Without it, running the checks while the demo is up corrupts
 * the dev server: both processes write the same chunk files, and the running
 * app starts serving half of one build and half of another. It presents as
 * `Cannot find module './833.js'` and, before that, as a page that renders
 * with **no CSS at all** — which is how it was found.
 *
 * A check script that breaks the application it is checking is worse than no
 * check script, because the damage looks like a bug in the code under test.
 */
const distDir = process.env.DATACANVAS_NEXT_DIST_DIR ?? ".next";

/** @type {import('next').NextConfig} */
export default {
  reactStrictMode: true,
  distDir,
  experimental: {
    // NFR-SCALE.4 is 500 MB. A refusal above that should come from the API,
    // which names the limit and why (P6) — not from a proxy default reporting
    // a socket hang-up.
    middlewareClientMaxBodySize: "512mb",
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};
