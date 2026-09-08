"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Text that is clipped when it fits, and slides to show its tail when it does
 * not — a dataset called `2024_Q3_regional_sales_FINAL_v2_reviewed.csv`, or a
 * column called `customer_lifetime_value_bucket`.
 *
 * ## It runs on its own, and hovering stops it
 *
 * The first attempt only moved on hover, on the strength of WCAG **SC 2.2.2
 * (Pause, Stop, Hide)** — Level A, and it does say that content which moves by
 * itself for more than five seconds beside other content needs a way to be
 * stopped. The product owner asked for the movement to be there without being
 * asked for, so the mechanism moved rather than disappearing: **pointing at a
 * name pauses it.**
 *
 * That is a real mechanism and it is the one a reader wants anyway — you point
 * at the thing you are trying to read. What it is not is a *discoverable* one,
 * and it is unavailable to a touch screen with no hover at all. Recorded as
 * owed rather than claimed as met.
 *
 * `prefers-reduced-motion` removes the movement entirely, which is SC 2.3.3 and
 * is not negotiable; the `title` on every one of these is what still gives the
 * whole name when it does.
 *
 * ## Why the text is rendered twice
 *
 * A marquee that only travels the *overflow* has to come back, and coming back
 * is either a jump or a bounce. Both were tried; the bounce reads as the text
 * changing its mind.
 *
 * A loop needs a second copy. The two runs sit in a row with a gap between
 * them, and the track slides left by exactly one run plus one gap — at which
 * point the second copy is standing precisely where the first began, and the
 * animation can restart with nothing to see. One direction, no stop, no seam.
 *
 * The copy is `aria-hidden`, so a screen reader hears the name once and the
 * heading's accessible name is unchanged. It exists only for the eye.
 *
 * ## Why it measures instead of always animating
 *
 * A name that already fits must not move at all, and must not be duplicated
 * either. Nothing in CSS can ask *is this overflowing*, so the element is
 * measured — and re-measured when the column it sits in is resized, which the
 * preview grid lets people do.
 *
 * The distance and the duration go out as custom properties rather than into a
 * style attribute full of transforms: the animation stays in the stylesheet
 * where the reduced-motion rule can reach it, and only the two numbers that
 * depend on the text come from here.
 *
 * ## Speed is a function of type size
 *
 * One constant for every site was wrong in a way that is easy to miss: 55px a
 * second past a 24px dataset name is a comfortable read, and the same 55px a
 * second past a 12px bar label is a blur. Small type has less to look at per
 * pixel travelled, so it has to travel more slowly to be read at all.
 *
 * So the speed is scaled by the element's own computed `font-size`, against the
 * dataset card's name as the reference — the one the product owner looked at
 * and approved. Everything else falls out of that:
 *
 *     dataset name, page title   24px   55 px/s   (the reference)
 *     upload filename            16px   37 px/s
 *     column name, email         14px   32 px/s
 *     sample values, bar labels  12px   28 px/s
 *
 * `font-size` rather than the width of the box, and the two were offered as
 * alternatives. Width is already accounted for: duration is distance over
 * speed, so a narrow box holding a long name takes longer without anyone
 * choosing that. What speed has to answer is *can this be read while it moves*,
 * and that is a question about the type, not about the container around it.
 */
//: Pixels per second **at the reference size**. Slow enough to read a name at,
//: which is the only reason the movement exists.
const REFERENCE_SPEED = 55;

//: The dataset card's name, in `--text-title`. Every other site is scaled
//: against it because it is the one that was looked at and approved.
const REFERENCE_SIZE = 24;

//: Clear space between the tail of one run and the head of the next, so the
//: name does not appear to run into itself.
const GAP = 56;

export function Ellipsis({
  as: Tag = "span",
  children,
  className,
  title,
}: {
  as?: "span" | "h1" | "h2" | "h3" | "strong" | "li" | "div";
  children: string;
  className?: string;
  title?: string;
}) {
  const host = useRef<HTMLElement>(null);
  const [motion, setMotion] = useState<{ shift: number; seconds: number } | null>(null);

  useEffect(() => {
    const element = host.current;
    if (element === null) return;

    const measure = () => {
      const run = element.querySelector(".ellipsis-run");
      if (run === null) return;

      // A Range, not `scrollWidth`.
      //
      // This is where the first version was wrong and looked right. A run is an
      // inline span, and `scrollWidth` on an inline element is **0** — it has no
      // box to report. So the comparison was always `0 > width`, `.slides` was
      // never applied, and nothing ever moved. Measuring the element that *did*
      // have a box measured the clamped width instead of the natural one, which
      // is the same bug wearing a different number.
      //
      // A Range over the run's contents answers the question actually being
      // asked — how wide is this text if nothing stops it — and it answers it
      // for inline content, which is what this always is at rest.
      const range = document.createRange();
      range.selectNodeContents(run);
      const width = range.getBoundingClientRect().width;
      range.detach();

      // One pixel of slack: sub-pixel text metrics otherwise make a name that
      // exactly fits report a one-hundredth of a pixel of overflow and crawl.
      if (width <= element.clientWidth + 1) {
        setMotion(null);
        return;
      }

      // Read from the element rather than passed in, so a site that changes its
      // type scale changes its marquee with it and nobody has to remember.
      const size = Number.parseFloat(getComputedStyle(element).fontSize) || REFERENCE_SIZE;
      const shift = Math.ceil(width) + GAP;
      setMotion({ shift, seconds: shift / (REFERENCE_SPEED * (size / REFERENCE_SIZE)) });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [children]);

  const style = motion
    ? ({
        "--marquee-shift": `${motion.shift}px`,
        "--marquee-gap": `${GAP}px`,
        "--marquee-time": `${motion.seconds.toFixed(2)}s`,
      } as React.CSSProperties)
    : undefined;

  return (
    <Tag
      ref={host as React.Ref<never>}
      className={["ellipsis", motion ? "slides" : "", className].filter(Boolean).join(" ")}
      style={style}
      title={title ?? children}
    >
      <span className="ellipsis-text">
        <span className="ellipsis-run">{children}</span>
        {motion ? (
          <span className="ellipsis-run" aria-hidden="true">
            {children}
          </span>
        ) : null}
      </span>
    </Tag>
  );
}
