import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Matchers plus their type augmentation. The `/vitest` entry point registers
// against vitest's `expect` rather than jest's.
import "@testing-library/jest-dom/vitest";

// Testing Library only registers its own teardown when the test globals are
// present, and `vitest.config.ts` deliberately leaves them off. Without this
// every render stacks in the same jsdom document and `getByRole` starts
// finding two of everything — a failure that reads as a component defect.
afterEach(cleanup);

/**
 * `matchMedia`, which jsdom does not implement at all.
 *
 * Stubbed here rather than guarded in the application: every browser this ships
 * to has had it for a decade, and `if (window.matchMedia)` in production code
 * would be a branch that exists only to satisfy a test environment — and a
 * branch nothing ever exercises in the browser it claims to protect.
 *
 * It answers `false`, i.e. "the machine prefers light". That is a *choice*, and
 * a test that cares which ground the OS reports must set it up itself rather
 * than inherit this.
 */
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
