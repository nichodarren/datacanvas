/**
 * The handful of shapes the owner's mockup asks for, as inline SVG.
 *
 * The mockup pulls Material Symbols from Google's font CDN. Two reasons not to:
 * a request leaves the page for every icon on it, and an icon *font* renders as
 * a stray glyph — a box, a letter — for the moments before it lands and forever
 * if it never does. These are six paths totalling under a kilobyte.
 *
 * D-037 observed that this product has almost no iconography and said it should
 * stay that way. That still holds as a rule about *inventing* icons. Each of
 * these labels something a word also labels, or sits inside a control whose
 * accessible name is a word — none of them is the only thing telling you what
 * something is.
 *
 * `aria-hidden` on all of them, without exception. Every caller pairs the shape
 * with text, so an accessible name here would make screen readers announce the
 * same thing twice.
 */

type IconProps = {
  /** Matches the mockup's `text-[Npx]` on the corresponding Material Symbol. */
  size?: number;
  className?: string;
  /**
   * Set only when the icon **is** the information rather than decoration.
   *
   * It flips `aria-hidden` off in the same breath, because the two always move
   * together: an icon a screen reader is meant to announce cannot also be
   * hidden from it, and remembering to change both by hand is how one of them
   * gets forgotten.
   */
  "aria-label"?: string;
};

function svg(
  path: React.ReactNode,
  { size = 20, className, "aria-label": label }: IconProps,
) {
  return (
    <svg
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : "true"}
      focusable="false"
    >
      {path}
    </svg>
  );
}

/** Delete, on a dataset card. A bin rather than an `×`: a cross is dismissal. */
export const Trash = (props: IconProps) =>
  svg(
    <>
      <path d="M4 7h16" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </>,
    props,
  );

/**
 * Send what is in the composer, in the shape every chat composer uses now.
 *
 * An arrow up rather than a paper plane. Both are read as *send*; the arrow is
 * what current composers draw, and it says the direction the text goes — out of
 * the box above it — where a plane is a metaphor for delivery that this is not.
 *
 * It had a sibling: `Plus`, for the composer's manual door, removed with D-049
 * when the prompt became the only way in.
 */
export const Send = (props: IconProps) =>
  svg(
    <>
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </>,
    props,
  );

/** Back up a level. Points left because that is where the parent is. */
export const ArrowLeft = (props: IconProps) =>
  svg(
    <>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </>,
    props,
  );

/**
 * A disclosure triangle, pointing down when open.
 *
 * One icon rather than two: collapsed is the same shape rotated, and two
 * drawings of one arrow are two things that can disagree about which way is
 * up. CSS turns it; the component does not know the state.
 */
export const ChevronDown = (props: IconProps) => svg(<path d="m6 9 6 6 6-6" />, props);

/**
 * Go full screen. Four corners pushing outward, which is what the gesture
 * means everywhere else a person has seen it.
 */
export const Expand = (props: IconProps) =>
  svg(
    <>
      <path d="M8 3H3v5" />
      <path d="M16 3h5v5" />
      <path d="M3 16v5h5" />
      <path d="M21 16v5h-5" />
    </>,
    props,
  );

/**
 * The agent log. A paper plane, because the log is the record of what was
 * *sent* — and it is what the reference draws.
 */
export const Rocket = (props: IconProps) =>
  svg(
    <>
      <path d="M4 13 20 4l-5 16-3.5-6.5z" />
      <path d="m11.5 13.5-3 3" />
    </>,
    props,
  );

/** An answer that passed the citation check (§12.5). */
export const Verified = (props: IconProps) =>
  svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </>,
    props,
  );

/** The drop zone. */
export const CloudUpload = (props: IconProps) =>
  svg(
    <>
      <path d="M12 13v8" />
      <path d="m8 17 4-4 4 4" />
      <path d="M6.5 18.5A5.5 5.5 0 0 1 7 7.6a7 7 0 0 1 13.3 3A4.5 4.5 0 0 1 18.5 19" />
    </>,
    props,
  );

/** The search field. */
export const Search = (props: IconProps) =>
  svg(
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m21 21-5.9-5.9" />
    </>,
    props,
  );

/**
 * A dataset that reads as a table: CSV, TSV, XLSX, Parquet.
 *
 * A grid, because that is what the file becomes when you open it — which is
 * also the only claim this icon is making.
 */
export const Table = (props: IconProps) =>
  svg(
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M9 9.5V20" />
    </>,
    props,
  );

/** A dataset that arrived as nested records: JSON. */
export const Braces = (props: IconProps) =>
  svg(
    <>
      <path d="M8 4a2 2 0 0 0-2 2v3a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3a2 2 0 0 0 2 2" />
      <path d="M16 4a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3a2 2 0 0 1-2 2" />
    </>,
    props,
  );

/**
 * Account settings, in the account menu — an ordinary cog.
 *
 * The first version of this was hand-typed from memory and rendered as a
 * scribble: the arc flags were wrong, so the lobes folded back through the
 * middle instead of round the outside. It looked like a knot at 18px, which is
 * the size it is always drawn at.
 *
 * This path was **computed** rather than written — six teeth on a 10px outer
 * radius and a 7px root, the flanks joined by real arcs along the root circle.
 * Six rather than eight for one reason: at 18px, eight teeth stroked at 1.75
 * close up into a blur, and a cog that cannot be read as a cog is decoration.
 */
export const Settings = (props: IconProps) =>
  svg(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M9.58 2.30L14.42 2.30L14.62 5.51A7.0 7.0 0 0 1 16.31 6.48L19.19 5.05L21.61 9.24L18.93 11.03A7.0 7.0 0 0 1 18.93 12.97L21.61 14.76L19.19 18.95L16.31 17.52A7.0 7.0 0 0 1 14.62 18.49L14.42 21.70L9.58 21.70L9.38 18.49A7.0 7.0 0 0 1 7.69 17.52L4.81 18.95L2.39 14.76L5.07 12.97A7.0 7.0 0 0 1 5.07 11.03L2.39 9.24L4.81 5.05L7.69 6.48A7.0 7.0 0 0 1 9.38 5.51Z" />
    </>,
    props,
  );

/** Sign out, in the account menu. */
export const SignOut = (props: IconProps) =>
  svg(
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </>,
    props,
  );

/**
 * Which shape a dataset gets, from the name it arrived under.
 *
 * The filename is the only thing the list route returns that says anything
 * about format — there is no `format` field on `DatasetSummary`. That is an
 * honest source: the name *is* the uploaded file's name. It is also a guess,
 * which is why the table shape is the fallback rather than a third "unknown"
 * icon: every format this product accepts becomes a table, so the fallback is
 * true even when the extension tells us nothing.
 */
export function FormatIcon({ name, size }: { name: string; size?: number }) {
  return name.toLowerCase().endsWith(".json") ? (
    <Braces size={size} />
  ) : (
    <Table size={size} />
  );
}
