/**
 * Citations, kept for the validator and taken off the screen (D-099).
 *
 * §12.5 asks the model to write `[ref: <id>]` after every figure, and the
 * planner's step 10 checks three things against those spans: that each id
 * resolves to something that ran in this turn, that every number in the
 * sentence appears in the result it cites, and that an uncited number is
 * flagged rather than hidden. **None of that changes here.** The model still
 * cites, the backend still checks, and the mark on a grounded answer still
 * means what it meant.
 *
 * What changes is who reads the id. A `computation_id` is a UUID — it cannot
 * be remembered, compared at a glance, or typed — and the receipt has now been
 * removed in four different shapes with the same verdict each time. The span
 * is stripped on the way to the screen; the receipt below the answer names the
 * tool and its arguments instead, which is the part a reader can actually act
 * on.
 *
 * ⚠️ **Stripping happens here and nowhere earlier.** If the system prompt ever
 * stops asking for citations, §12.5 rule 2 stops running and the grounded mark
 * becomes decoration — the one failure this module must not cause.
 */

/** `[ref: 4f2c…]`, the form the system prompt asks for. */
const CITATION = /\s*\[ref:\s*[0-9a-zA-Z-]+\s*\]/g;

/**
 * `[4f2c…]`, the form models write anyway.
 *
 * Read **only when the id resolves**, exactly as the backend reads it. Without
 * that check a note reading `[see above]` would be deleted from an answer as
 * though it were an id — and the backend has already walked into the mirror
 * image of this once, reading digits out of an id as though they were figures.
 */
const BARE = /\s*\[([0-9a-zA-Z-]{4,})\]/g;

/** What a step needs to be, to be named. Structural, so this module does not
 *  depend on the API's shapes. */
type Step = { ref: string; tool: string };

/** A step, plus the arguments that say what it read. */
type Linked = Step & { args: Record<string, unknown> };

/**
 * The steps whose output nothing else read — the turn's **results**.
 *
 * A histogram is `bin_column` then `plot`, and only the second is an answer:
 * the first exists to be read by it, which is knowable exactly rather than by
 * heuristic, because `plot(table: "comp-1")` names it.
 *
 * **Not *the last step*, which is the tempting shortcut and wrong.** A turn
 * that runs `missingness_report` and then bins and plots a column has two
 * results, and keeping only the last would drop the report. A turn cut short
 * by a rate limit has one result that happens to be an intermediate, and it
 * should still be drawn — you get to see what you got.
 *
 * Matched against known refs rather than any string, so an argument that
 * happens to read `dataset` or `bar` cannot consume anything.
 */
export function resultsOf<T extends Linked>(steps: readonly T[]): T[] {
  const refs = new Set(steps.map((step) => step.ref));
  const consumed = new Set<string>();
  for (const step of steps) {
    for (const value of Object.values(step.args)) {
      if (typeof value === "string" && refs.has(value)) consumed.add(value);
    }
  }
  return steps.filter((step) => !consumed.has(step.ref));
}

/** The narration as a person should read it: the sentence, without the ids. */
export function withoutCitations(text: string, known: ReadonlySet<string>): string {
  return text
    .replace(CITATION, "")
    .replace(BARE, (match, id: string) => (known.has(id) ? "" : match));
}

/**
 * A step's arguments, with any reference to an earlier step named rather than
 * spelled as a UUID.
 *
 * `table=bca9d582-0ece-434b-9c71-93b23bc6fcf1` is an id living **inside** the
 * arguments, so removing the receipt's own id column does not reach it. Naming
 * the tool that produced it says the thing the id was there to say — *this
 * step read that one* — and says it in a word.
 *
 * Disambiguated by position only when it has to be: two aggregates in one turn
 * need telling apart, one does not, and `aggregate #1` on its own would be a
 * number the reader has to ignore.
 *
 * Defaults are **not** filtered out. An argument is part of what identifies a
 * computation (§9.4 hashes it), so a threshold the model never typed still
 * decided the answer; hiding it would make two different results look like the
 * same one.
 */
export function describeArgs(args: Record<string, unknown>, steps: readonly Step[]): string {
  const total = new Map<string, number>();
  for (const step of steps) total.set(step.tool, (total.get(step.tool) ?? 0) + 1);

  const named = new Map<string, string>();
  const seen = new Map<string, number>();
  for (const step of steps) {
    const nth = (seen.get(step.tool) ?? 0) + 1;
    seen.set(step.tool, nth);
    named.set(step.ref, (total.get(step.tool) ?? 0) > 1 ? `${step.tool} #${nth}` : step.tool);
  }

  return Object.entries(args)
    .filter(([, value]) => value !== null && value !== "")
    .map(([name, value]) => `${name}=${named.get(String(value)) ?? String(value)}`)
    .join(" · ");
}
