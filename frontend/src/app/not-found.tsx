import Link from "next/link";

import { Shell } from "@/components/Shell";

/**
 * A URL that points at nothing (D-036).
 *
 * ## What this replaces
 *
 * Next's built-in 404: a light background whatever the app's palette is, no
 * header, no shell, and — the part that matters — **no link anywhere**. The
 * only way out was the browser's own back button.
 *
 * §14.5 has forbidden that shape since 2026-07-31, and it was written about a
 * different screen: an API failure that rendered "Start by adding data" with
 * every means of adding it removed. The rule it produced is *always provide a
 * way forward*, and nobody had held a 404 up against it. This is the same class
 * of defect, found the same way — by looking at the screen rather than at a
 * test.
 *
 * ## Why it is not apologetic, and why it does not guess
 *
 * W-4: errors do not apologise and are never vague about what happened. A
 * mistyped or stale URL is not a fault worth an apology, and this page does not
 * know which of the two it was — so it says what is true (nothing is here) and
 * offers the one destination that always exists.
 *
 * It deliberately does **not** attempt "did you mean…". Guessing at intent from
 * a path is the kind of plausible answer P6 rules out; being sent confidently
 * to the wrong dataset is worse than being told plainly that this one is not
 * here.
 *
 * ## Why the shell is around it
 *
 * A 404 can be reached while signed in — a deleted dataset, a link from a
 * colleague, a typo in a version id — and stripping the header would take the
 * account menu and the way home off the screen at the moment they are the only
 * things left. The header renders brand-only here because this page has no
 * identity of its own to pass it, and that is still one working control more
 * than Next's default offered.
 */
export default function NotFound() {
  return (
    <Shell>
      <section className="start">
        <h1>There is nothing at this address</h1>
        <p className="muted">
          The link may be out of date, or the dataset it pointed at may have been deleted.
        </p>
        <p style={{ marginTop: 16 }}>
          <Link href="/" className="button-link">
            Go to your datasets
          </Link>
        </p>
      </section>
    </Shell>
  );
}
