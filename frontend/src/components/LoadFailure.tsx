"use client";

/**
 * A screen that could not load, said plainly, with a way forward.
 *
 * ## The screen this replaces
 *
 * When `/auth/me` answered 500, the home page rendered:
 *
 * > **500 Internal Server Error**
 * > **Start by adding data** — Everything else in DataCanvas begins with a file.
 * > 1. Confirm how it reads · 2. Check the column types · 3. Browse the data
 *
 * …and no drop zone, no samples, and no account menu. Every one of those is
 * gated on an identity the page had just failed to fetch. So the screen told
 * someone to add data, removed every means of adding it, and gave them no way
 * out — not even sign out.
 *
 * §14.5 already had the rule and it was written about the *empty* state: *"daftar
 * nama tanpa jalan masuk bukan orientasi, ia jalan buntu"* — a list with no way
 * in is not orientation, it is a dead end. Nobody had held the error state up
 * against it.
 *
 * Two things follow, and this component exists to make them structural rather
 * than remembered:
 *
 * 1. **An error state replaces the body; it does not sit on top of it.** An
 *    instruction the page has disabled is worse than no instruction.
 * 2. **There is always a way forward.** Here that is Retry, because the failure
 *    this most often reports — the API not running — is fixed by someone else
 *    and then this page is one click from working.
 *
 * A failed *action* is different and deliberately not routed here: if loading a
 * sample fails, the page around it still works, and a banner above a working
 * page is the right shape for that.
 */
export function LoadFailure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="start">
      <h1>This did not load</h1>
      <p className="muted" role="alert">
        {message}
      </p>
      <p style={{ marginTop: 16 }}>
        <button type="button" className="primary" onClick={onRetry}>
          Try again
        </button>
      </p>
    </section>
  );
}
