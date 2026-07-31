import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Behavioural tests for the frontend (D-033).
 *
 * Until this existed the frontend had exactly two checks — `tsc --noEmit` and
 * `next build` — and neither can see a component render the wrong thing. The
 * defect that prompted this was type-correct and built cleanly: the preview
 * grid indexed row cells by their position among the *visible* columns while
 * the API returns one cell per column in the *file*, so hiding any column but
 * the last shifted every column to its right onto its neighbour's values.
 * Silently, and only once someone used the column picker as designed.
 *
 * `tests/test_frontend_wiring.py` stays. It answers a question no renderer test
 * can — *is anything built but unreachable from the UI* — by reading `api.ts`
 * statically. The two do not overlap.
 *
 * `globals` is deliberately off. Importing `describe`/`it`/`expect` costs one
 * line per file and keeps the global type space honest, which matters more here
 * than usual: tsconfig's `include` covers every TypeScript file in this
 * directory, so each test is type-checked by the same strict pass as the
 * application it tests.
 */
export default defineConfig({
  // `tsconfig.json` sets `jsx: "preserve"` because Next compiles the app, and
  // esbuild honours that here — which leaves the classic `React.createElement`
  // runtime and a `React is not defined` at the first render. The application
  // never imports React explicitly and should not have to start.
  esbuild: { jsx: "automatic" },

  // No `@vitejs/plugin-react`. It exists for Fast Refresh and Babel transforms,
  // neither of which a jsdom test run uses, and the line above already covers
  // the only thing that was wanted from it. It also could not be installed
  // honestly: the current plugin requires Vite 8 while Vitest 3 ships Vite 7,
  // so the tree carried two copies and `tsc` rejected the plugin type against
  // the config type it was passed to. One dependency fewer, one conflict fewer.
  resolve: {
    // Mirrors the `@/*` path in tsconfig.json. Without it every test would
    // import through a relative path the application never uses.
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // Worker threads, not child processes. Vitest 3 defaults to `forks`, and on
    // Windows that pool dropped its IPC channel as soon as three test files ran
    // at once — `ERR_IPC_CHANNEL_CLOSED`, before a single test executed, while
    // every file passed when run on its own. A suite that fails only when it is
    // whole is worse than a slow one: it teaches people to re-run until green.
    pool: "threads",
    // Colocated with the component under test, not in a parallel tree: a test
    // that sits beside its subject gets renamed and deleted along with it.
    include: ["src/**/*.test.{ts,tsx}"],
    // A stub that leaks into the next test is a failure that blames the wrong
    // file, and this suite mocks `api` in most of its cases.
    restoreMocks: true,
  },
});
