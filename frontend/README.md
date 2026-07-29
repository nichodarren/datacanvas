# Frontend — DataCanvas

Next.js (App Router) + TypeScript strict. Built in Phase 2 for P0-14.

```bash
npm ci
npm run dev        # http://localhost:3000
```

The API must be running too (`python -m app` from the repo root, with
`PYTHONPATH=backend`). Everything the browser fetches goes through `/api/*`,
which `next.config.mjs` rewrites to the API — see that file for why, including
the two things about it that were wrong the first time.

## What exists

| Surface | Requirement |
|---|---|
| Sign in / register | FR-A.1 |
| Upload with a dialect confirmation step | FR-B.3, D-025 |
| Preview grid, virtualised, server-paginated | FR-D.1, FR-D.2 |
| Column headers carrying type + confidence, clickable to correct | FR-D.4, FR-C.2 |
| Schema tab: what was decided and **why** | FR-C.1, FR-C.3 |

## What is visibly missing, on purpose

The shell renders the full §14.2 layout — Library, Steps, Findings, the Run Log,
the copilot composer — with each region **saying which phase it belongs to**.

That is a decision, not laziness. §14.1 says the mental model has to land in the
first thirty seconds; a layout that grows new regions later teaches it twice.
What the shell must never do is *fake* them: placeholder rows in the Run Log
would imply traceability that does not exist, and P3 is the one promise this
product cannot be casual about.

## Conventions

- **No component library.** §10.3 chose a headless grid so the *header* could
  carry quality signals; a design system would sit in front of the one component
  whose design is load-bearing. One hand-written stylesheet (`globals.css`).
- **Every quality signal has a word, not only a colour** (NFR-UX.3).
- Cells are strings, because the stored table is strings and the SchemaContract
  is what interprets them (D-029). Typed JSON would let the grid form a second,
  quieter opinion about a type the user cannot see or correct.
