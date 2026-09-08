import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { Ellipsis } from "@/components/Ellipsis";

/**
 * Whether a name slides has to be decided by measuring it, and jsdom has no
 * layout engine — every width it reports is zero. So the two widths that
 * matter are defined here, which is the only honest way to test a decision
 * made from a measurement in an environment that cannot measure.
 *
 * **The two widths are stubbed on the two APIs the component actually uses**,
 * and that pairing is the point. The first version of this file stubbed
 * `scrollWidth`, the component asked for `scrollWidth`, and the tests passed
 * while nothing on screen ever moved — because `scrollWidth` is 0 on an inline
 * element and every run is inline. A stub that answers a question the browser
 * would refuse is a test agreeing with itself.
 *
 * What this proves is the wiring: the component asks the right question, and a
 * name that fits is left completely alone. What it cannot prove is that the
 * animation runs — that was checked in Chrome, against the real stylesheet.
 */
function withWidths(host: number, content: number) {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains("ellipsis") ? host : 0;
    },
  });
  Range.prototype.getBoundingClientRect = () =>
    ({
      width: content,
      height: 0,
      top: 0,
      left: 0,
      right: content,
      bottom: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
}

beforeEach(() => {
  withWidths(0, 0);
});

describe("text too long for its box", () => {
  it("slides, and says how far and how long for", () => {
    withWidths(200, 500);
    render(<Ellipsis>customer_lifetime_value_bucket_after_normalisation</Ellipsis>);

    const host = screen.getByTitle("customer_lifetime_value_bucket_after_normalisation");

    expect(host).toHaveClass("slides");
    // One run of 500px plus the 56px gap: the distance at which the second copy
    // is standing exactly where the first started, which is what makes the loop
    // seamless rather than a jump back.
    expect(host.style.getPropertyValue("--marquee-shift")).toBe("556px");
    expect(host.style.getPropertyValue("--marquee-time")).not.toBe("");
  });

  it("renders the name a second time, for the eye and not for the reader", () => {
    // The loop needs a copy to slide into place. A screen reader must not hear
    // the name twice, and the heading it sits in must not be *named* twice.
    withWidths(200, 500);
    render(<Ellipsis as="h3">order_reference_number_long_enough_to_move</Ellipsis>);

    const heading = screen.getByRole("heading", { level: 3 });

    expect(heading.querySelectorAll(".ellipsis-run")).toHaveLength(2);
    expect(heading.querySelectorAll("[aria-hidden=\"true\"]")).toHaveLength(1);
    expect(heading).toHaveAccessibleName("order_reference_number_long_enough_to_move");
  });

  it("leaves a name that fits completely alone", () => {
    withWidths(200, 120);
    render(<Ellipsis>region</Ellipsis>);

    const host = screen.getByTitle("region");

    expect(host).not.toHaveClass("slides");
    // No custom properties at all, rather than a distance of zero: an element
    // carrying animation variables it never uses invites someone to animate it.
    expect(host.getAttribute("style")).toBeNull();
    // And no second copy. A name that fits is one name.
    expect(host.querySelectorAll(".ellipsis-run")).toHaveLength(1);
  });

  const speedOf = (name: string, width: number, className?: string) => {
    withWidths(100, width);
    const view = render(<Ellipsis className={className}>{name}</Ellipsis>);
    const host = screen.getByTitle(name);
    const shift = Number.parseFloat(host.style.getPropertyValue("--marquee-shift"));
    const time = Number.parseFloat(host.style.getPropertyValue("--marquee-time"));
    view.unmount();
    return shift / time;
  };

  it("moves two names of one size at the same speed, whatever their length", () => {
    // The claim is not "longer takes longer" — that is true of almost any
    // formula. It is that pixels per second does not depend on how much there
    // is to say, so a grid of cards has no name racing past another.
    expect(speedOf("short overflow", 200)).toBeCloseTo(speedOf("a much longer one", 900), 0);
  });

  it("moves smaller type more slowly", () => {
    // 55px a second past a 24px dataset name reads; the same 55px a second past
    // a 12px bar label is a blur. Speed follows the type, and the dataset card
    // is the size everything else is scaled against.
    const style = document.createElement("style");
    style.textContent = ".big { font-size: 24px } .small { font-size: 12px }";
    document.head.append(style);

    const big = speedOf("a name at the reference size", 600, "big");
    const small = speedOf("a label at half the size", 600, "small");

    style.remove();

    expect(big).toBeCloseTo(55, 0);
    expect(small).toBeCloseTo(27.5, 0);
  });

  it("still carries the whole name for a pointer that waits", () => {
    // The `title` is what `prefers-reduced-motion` falls back on, and what a
    // touch screen — which has no hover to pause with — has instead.
    withWidths(200, 500);
    render(<Ellipsis>quarterly_recurring_revenue_in_local_currency</Ellipsis>);

    expect(
      screen.getByTitle("quarterly_recurring_revenue_in_local_currency"),
    ).toHaveTextContent("quarterly_recurring_revenue_in_local_currency");
  });
});
