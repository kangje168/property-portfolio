# Validation

Local verification, 22 October 2026, Python 3.12.14:

- 56 pytest cases passed against temporary SQLite databases.
- OpenAPI 3.0.3 validates; intake, property and geographic responses are checked against their response schemas.
- Authenticated manager isolation, read-only roles, expired/revoked keys and shared rate limits across app instances are exercised.
- Four concurrent imports of one file create one property; later reports identify unchanged records.
- Tests cover malformed files, row rejections, duplicates, exact money, SQL injection strings, invalid geometry, hole/exterior boundary behavior and missing resources.
- Alembic upgrade preserves an existing pre-rating record; downgrade/re-upgrade and ORM/schema comparison pass.
- CLI migration, manager/key creation and revocation pass. Plain API keys are not stored in the database.
- `python tools/demo.py` starts a real loopback HTTP server and drives it with the included client. It creates 3 records, rejects 1, creates 0 on replay, finds 1 area match and records rating 4.
- Ruff lint and formatting checks pass.

PostgreSQL and Docker cannot be run in the local execution environment because their executables are absent. The GitHub Actions workflow provisions PostgreSQL 17, runs the service suite against both backends, runs the HTTP demo, checks Compose configuration and builds/smoke-tests the image. Its result is separate evidence; the presence of that workflow is not itself a passing deployment.

This verifies prototype correctness for the supplied cases, not production load, high availability, a security audit or operation on real property data. No AWS resources were provisioned and no public service was published.

