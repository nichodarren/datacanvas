# DataCanvas

Exploratory data analysis where every number can be traced back to the step that produced it.

Upload a dataset, browse it, and ask questions in plain language. Answers are computed by tools
rather than written by a model, and each figure carries a reference to the computation behind it.

## Stack

- Backend: FastAPI on Python 3.13, DuckDB for analytics, PostgreSQL for metadata
- Frontend: Next.js 15 and React 19
- Storage: Parquet files, written once and never edited

## Requirements

- Python 3.13 or newer
- Node.js 20 or newer
- PostgreSQL 16 or newer

## Setup

Copy the environment template and fill in the values.

```
cp .env.example .env
```

Install the backend and apply the database schema.

```
pip install -e .
alembic upgrade head
```

Install the frontend.

```
cd frontend
npm ci
```

## Running

Start the API from the repository root.

```
PYTHONPATH=backend python -m app
```

Run it with `python -m app` instead of calling uvicorn directly. The application installs its own
event loop policy, which psycopg needs on Windows.

Start the frontend in a second terminal.

```
cd frontend
npm run dev
```

The app is then at http://localhost:3000. Requests to `/api` are proxied to the API on port 8000,
so both run on one origin.

A local PostgreSQL instance is also available through Docker.

```
docker compose up -d
```

## Layout

```
backend/app/
  api/            HTTP routes
  auth/           accounts and sessions
  authz/          the only door to dataset files
  domain/         entities and value objects
  expressions/    the closed expression grammar and its compiler
  ingest/         upload, format detection, Parquet normalisation
  llm/            provider clients, planner loop, privacy gate
  repositories/   database access
  schema/         type inference and schema contracts
  storage/        DuckDB engine and object store
  tools/          analysis tools and their registry
backend/migrations/
  Alembic revisions
frontend/src/
  app/            routes and global styles
  components/     UI
  lib/            API client and helpers
```

## Environment

`.env.example` lists every variable with a short note. The ones needed to start are the database
URL, the storage root, and at least one LLM provider key. Model names in that file are expected to
go stale, so treat them as defaults rather than as a contract.
