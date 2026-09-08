import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

// Matchers plus their type augmentation. The `/vitest` entry point registers
// against vitest's `expect` rather than jest's.
import "@testing-library/jest-dom/vitest";

// Testing Library only registers its own teardown when the test globals are
// present, and `vitest.config.ts` deliberately leaves them off. Without this
// every render stacks in the same jsdom document and `getByRole` starts
// finding two of everything — a failure that reads as a component defect.
afterEach(cleanup);

/**
 * **A React warning fails the test that caused it.**
 *
 * Every complaint React makes about how a component is written — a `key`
 * arriving through a spread, an unknown DOM attribute, a state update outside
 * `act` — goes to `console.error` and to nothing else. Nothing here was
 * listening, so on 2026-08-27 a donut shipped whose `key` was spread into JSX:
 * React cannot read a key that way, warned about it, fell back to position for
 * reconciliation, and **every check in this repository stayed green**.
 * TypeScript has no opinion about spreads, and the browser scripts listen for
 * `pageerror`, which a console message is not. The product owner found it in
 * his own dev overlay.
 *
 * Registered **after** `cleanup` so an unmount that warns is caught too:
 * vitest runs `afterEach` hooks in the order they were added.
 *
 * A test that *means* to provoke one asserts on `complaints` itself and clears
 * it; nothing does yet, and that is the point.
 */
let complaints: string[] = [];
const passThrough = console.error;

beforeEach(() => {
  complaints = [];
  console.error = (...args: unknown[]) => {
    complaints.push(args.map((arg) => String(arg)).join(" "));
    passThrough(...args);
  };
});

afterEach(() => {
  console.error = passThrough;
  if (complaints.length > 0) {
    const seen = complaints.join(" | ");
    complaints = [];
    throw new Error(`React complained, and a warning is a defect — ${seen}`);
  }
});

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

/**
 * jsdom implements no layout, so it ships no `ResizeObserver` either.
 *
 * `Ellipsis` uses one to notice when the box around a name changes size — the
 * preview grid lets people drag columns wider, and a name that fitted a moment
 * ago may not now. Stubbed here for the same reason `matchMedia` is: the
 * alternative is a `typeof ResizeObserver` branch in the component, which
 * exists only to satisfy a test environment and is never taken in a browser.
 *
 * It observes nothing and never fires. Every measurement in jsdom returns zero
 * anyway, so a callback would have nothing true to say — which is also why no
 * test here asserts that a name *slides*. What can be asserted is that the text
 * is rendered and reachable, and those assertions are real.
 */
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

/**
 * jsdom implements `Range`, but not `Range.prototype.getBoundingClientRect` —
 * measuring is layout, and jsdom does none.
 *
 * `Ellipsis` uses a Range to ask how wide a name would be if nothing stopped
 * it, which is a question `scrollWidth` cannot answer for inline content: it
 * returns 0 there. Getting that wrong is how a marquee shipped that never
 * moved, and how a suite of tests agreed with it — they stubbed the same wrong
 * API the component was calling.
 *
 * Zero by default, so a component under test never slides by accident. The
 * tests that are *about* sliding replace this with a width of their own.
 */
if (!Range.prototype.getBoundingClientRect) {
  Range.prototype.getBoundingClientRect = () =>
    ({
      width: 0,
      height: 0,
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
}
/**
 * `<dialog>`, which jsdom 29 parses and does not operate.
 *
 * `HTMLDialogElement` exists and `open` reflects the attribute, but
 * `showModal`, `show` and `close` are simply absent — calling one is a
 * `TypeError`, so `ConfirmDialog` cannot mount at all without this.
 *
 * What is stubbed is the part the component depends on and nothing more: the
 * `open` attribute goes on and off, and `close` fires a `close` event. The top
 * layer, the focus trap, the inert background and `::backdrop` are the reasons
 * the component uses a real `<dialog>` in the first place and none of them are
 * modelled here — they are browser behaviour, and a stub that pretended to
 * provide them would let a test claim they work.
 *
 * So the tests over this component assert what it renders and what it calls.
 * That Escape closes it and that focus cannot leave it are the browser's
 * promises, kept by using the element instead of a `<div>`.
 */
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.show = function show(this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function close(
    this: HTMLDialogElement,
    returnValue?: string,
  ) {
    this.open = false;
    if (returnValue !== undefined) this.returnValue = returnValue;
    this.dispatchEvent(new Event("close"));
  };
}

/**
 * `scrollIntoView`, which jsdom does not implement.
 *
 * It has no layout engine, so there is nothing to scroll and nothing a stub
 * could honestly pretend. What the tests over the workspace assert is that
 * selecting a turn **asks** to bring its cards into view — that the log and
 * the canvas are wired to each other. Whether the browser then scrolls
 * smoothly is the browser's promise, and it was checked in Chrome.
 *
 * Stubbed here rather than guarded in the component: production code should
 * not carry a workaround for a test environment's gaps.
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
