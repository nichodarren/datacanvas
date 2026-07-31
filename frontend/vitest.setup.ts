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
