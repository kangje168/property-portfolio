# Architecture

## One cohesive service

```
CSV/client → Flask API → scoped SQLAlchemy operations → SQLite/PostgreSQL
                  ├→ pandas intake + row validation → durable import report
                  └→ bounding box + Shapely → geographic search results
CLI → migrations, manager creation and key lifecycle
```

The UI is intentionally an HTTP/JSON interface. A CRM, a human-operated client or an agent can use it without a bespoke dashboard. The initial use case is managing a curated property dataset, not scraping public listings.

## Boundaries

- `portfolio/models.py`: one shared data model and database constraints.
- `validation.py`: explicit numeric, text and geometry validation.
- `intake.py`: text-preserving pandas ingestion, upsert rules, row rejection reports.
- `auth.py`: opaque-key verification and database-backed rate windows.
- `__init__.py`: application factory, scoped API operations and JSON errors.
- `cli.py`: operator actions, outside the public HTTP surface.
- `spec.py`: versioned OpenAPI description; response shapes are exercised in tests.
- `migrations/`: initial schema plus the separate rating/uniqueness migration.

## Transactions and concurrent requests

An import locks its manager row on PostgreSQL; SQLite uses `BEGIN IMMEDIATE` for mutations. Concurrent imports for the same manager serialize, preventing duplicate creation races. The rate counter uses a database-specific atomic UPSERT with RETURNING, so independent WSGI processes share the same limit.

Row validation happens before a nested transaction. A uniqueness error rolls back that row's savepoint while preserving accepted records. File-structure errors reject the request before any property or import-record write. An unexpected error rolls back the complete import. Rate counters are committed separately and still count failed business requests.

Reports and property state commit together. Reports are not resumable checkpoints: a client retries the entire file and receives a new report. The dataset is an upsert feed, not an authoritative replace snapshot. There is no automatic removal, timestamp arbitration, external side-effect retry or background scheduler.

The second migration adds nullable ratings, a 1–5 check and per-manager name/address uniqueness. Existing duplicate addresses cause an explicit migration failure; an operator must reconcile them. Migration never silently removes properties. Tested SQLite upgrades preserve an existing row and support downgrade/re-upgrade.

## Security assumptions

Operators and host administrators are trusted. They can create admin keys and access the database. Manager scoping is enforced for imports, property search, geographic search, ratings and import reports. A resource ID from another manager returns 404, and an explicit unauthorized scope returns 403. There is no self-registration or role selection by API users.

API keys contain 256 random bits, have an expiry and can be revoked. Hashing random bearer tokens is distinct from password storage; the service does not implement user passwords. Bearer keys must be delivered securely, and remote clients must use HTTPS. There is no automatic browser key storage or remote telemetry.

Application logs use generated request IDs, method, endpoint and status; they omit query strings, headers, request bodies and SQL exception text. Reverse-proxy/Gunicorn logging must maintain the same discipline. The database and reports are not encrypted by the application. Backup, disk encryption, retention and deletion policies belong to the deployment owner.

The fixed-window limiter is not an edge firewall and permits bursts at window boundaries. PostgreSQL's authentication limiter is shared but adds database traffic. SQLite is for a small local installation; PostGIS indexes, streaming file processing, cursor pagination and a job queue should be considered only after measurements justify them.

## AI integration

An agent can read `/openapi.json`, receive a scoped API key, import a CSV, inspect `rejected`/`errors`, and query accepted records. All business operations are deterministic. There is no LLM bill and no model sending property documents elsewhere. Natural-language interpretation can be supplied by a caller later, without putting an unrestricted model inside the database boundary.

