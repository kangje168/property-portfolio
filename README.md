# Property Portfolio

A small, runnable property-data service for validated intake and scoped search. Import a property CSV, receive a persistent data-quality report, search the accepted portfolio, and record human review ratings. API keys limit each manager to their own records.

The service is useful as a small portfolio intake backend, a data-engineering case study, or a structured tool for an assistant. It does not need a language model to validate, search or calculate. An assistant can discover the OpenAPI contract and call the same authenticated endpoints as any other client.

## Try it without an account or external service

Python **3.12** is the tested runtime. From this checkout:

```sh
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -e .
python tools/demo.py
```

The demo creates an isolated temporary SQLite database and an HTTP server on a random loopback port, imports **three valid properties and one rejected row**, repeats the import, updates a rating and searches a geographic area. It prints a JSON summary, then shuts down and removes its database. Addresses and coordinates in the example are fictitious demonstration records, not listings.

## Keep a local portfolio

The default database is `portfolio.db` in the current directory. Run all commands from the same project directory, or set an absolute `PORTFOLIO_DATABASE_URL`.

```sh
portfolio migrate
portfolio manager-create "East portfolio"
portfolio key-create --label "East intake" --role manager --manager-id 1
portfolio serve
```

Keep the generated API key securely: it is displayed **once**, expires after 30 days by default and is stored only as a SHA-256 digest. Treat it like a password. `portfolio key-revoke <key_id>` revokes it immediately. There is no public registration endpoint; operators create managers and keys through the CLI.

In a second terminal, activate the same environment and set `PORTFOLIO_API_KEY` to that key. Examples below use the included JSON-output client; do not place keys in files tracked by Git.

```sh
python tools/client.py import data/example-properties.csv
python tools/client.py search --city Vincennes
python tools/client.py search --bedrooms 0 --min-price 600000
python tools/client.py area data/example-area.json
python tools/client.py rate 1 4
python tools/client.py report 1
```

`PORTFOLIO_API_URL` defaults to `http://127.0.0.1:8000`. The client permits plaintext HTTP only on loopback and refuses redirects, so it does not forward a bearer key to another destination. `portfolio serve` is a loopback **development** server. Use the WSGI/Docker option and HTTPS termination for a separately reviewed deployment.

## What happens to imported data?

CSV header, in any order:

```text
external_id,name,address,city,property_type,bedrooms,price_eur,latitude,longitude
```

- Files are UTF-8, at most 2 MiB and 10,000 records. Malformed file structure rejects the whole request before writes. Invalid individual records are rejected while valid records are committed.
- Allowed types: `apartment`, `house`, `office`, `retail`. Bedrooms: 0–20. EUR prices: 0–1 billion with at most two decimals. Database storage uses **integer cents**; API amounts are decimal strings.
- `(manager_id, external_id)` identifies a record. Replaying the same values is unchanged; corrected values update it. Human ratings survive imports. A name/address pair must also be unique within one manager.
- Duplicate external IDs in one file are rejected after their first valid occurrence. The error report uses CSV record ordinals including the header, not physical line numbers inside quoted multiline fields.
- Every successful file submission creates an import report and an audit event, including repeat submissions. **Idempotent property state does not mean deduplicated request history.**
- Rows are never deleted because they disappear from a later file. Imports do not enforce source-version ordering: replaying an old file can restore old values.
- The uploaded file is not retained. Its SHA-256, counts and rejection reasons are stored in the report; property data is stored in the database. The audit table stores actor IDs, event IDs and rating changes, not a duplicate copy of addresses.

## API

The authoritative OpenAPI 3.0.3 contract is at **`GET /openapi.json`**. Health is `GET /health`; all `/v1/` endpoints require `Authorization: Bearer <key>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/managers` | Managers visible to this key |
| POST | `/v1/imports` | Multipart CSV upload, plus `manager_id` for administrators |
| GET | `/v1/imports/{id}` | Retrieve the scoped data-quality report |
| GET | `/v1/properties` | Filter by manager, type, city, bedrooms and EUR price range |
| PATCH | `/v1/properties/{id}/rating` | Set a human rating from 1 to 5 |
| POST | `/v1/properties/search-area` | Query using a GeoJSON Polygon |

Search returns `items`, `total`, `limit` and `offset`. `limit` is 1–100; results have stable ID ordering. Cities match exactly. Unknown or repeated query parameters are rejected.

GeoJSON positions are **`[longitude, latitude]`**. Closed, valid polygon rings are required. Exterior and hole boundaries are included; hole interiors are excluded. These are planar containment tests for local portfolios, not geodesic distance or area calculations. Antimeridian-spanning polygons are rejected. Bounding-box queries with more than 10,000 candidates return 422 and must be narrowed. No Google Maps key, map tiles or external geocoding is needed.

## Access and limits

| Key role | Read | Import and rate | Manager scope |
|---|---|---|---|
| `reader` | Yes | No | One manager |
| `manager` | Yes | Yes | One manager |
| `admin` | Yes | Yes | All managers; explicit manager required on import |

The authenticated-request limit defaults to **120 requests/minute/key**, shared across WSGI workers using an atomic database counter. It is a fixed window, not DDoS protection. Deployments still need edge limits for unauthenticated traffic. Override with `PORTFOLIO_RATE_LIMIT`.

## PostgreSQL with Docker Compose

Create `.env` from `.env.example`, supply a URL-safe random `PORTFOLIO_DB_PASSWORD`, then:

```sh
docker compose up --build -d
docker compose exec api portfolio manager-create "East portfolio"
docker compose exec api portfolio key-create --label "East intake" --role manager --manager-id 1
```

Compose starts PostgreSQL, runs Alembic once, and starts two Gunicorn workers. Only the API is exposed, on `127.0.0.1:8000`; the database has no published port. The API runs as an unprivileged user with a read-only filesystem. Credentials and data are not baked into the image. `docker compose down` preserves the database volume; adding `-v` deletes it.

The PostgreSQL URL format is `postgresql+psycopg://user:password@host/database`. Do not run a development server publicly. AWS Lambda and API Gateway adapters are not implemented.

## Tests and engineering notes

```sh
python -m pip install -r requirements-dev.txt -e .
python -m pytest -q
ruff check portfolio tests tools
ruff format --check portfolio tests tools
```

To additionally run the same service tests against a disposable PostgreSQL database, set `PORTFOLIO_TEST_DATABASE_URL`. **Its database name must end in `_test`; the suite drops its tables.** Never point it at data you want to keep. CI provisions a separate `portfolio_test` service database.

- [Architecture and operating limits](docs/architecture.md)
- [Validation evidence](docs/validation.md)

## License and scope

[MIT License](LICENSE), copyright 2026 kangje168. Dependencies retain their own licenses. This project is an independent engineering prototype with synthetic example data. It does not make property valuations, investment or lending decisions. Production use requires operational ownership, backups, a credential distribution process, realistic load tests and an appropriate retention policy for the actual dataset.
