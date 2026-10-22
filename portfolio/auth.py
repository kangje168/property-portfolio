import hashlib
import time
from datetime import UTC, datetime

from flask import current_app, g, request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .db import session
from .models import ApiKey, RateBucket


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header) > 300:
        return {"error": "A valid Bearer API key is required"}, 401
    with session(current_app.extensions["engine"]) as db:
        key = db.scalar(select(ApiKey).where(ApiKey.digest == digest(header[7:])))
        if (
            not key
            or key.revoked
            or datetime.fromisoformat(key.expires_at) <= datetime.now(UTC)
        ):
            return {"error": "A valid Bearer API key is required"}, 401
        g.key = key
    limit = current_app.config["RATE_LIMIT"]
    now = int(time.time()) // 60
    engine = current_app.extensions["engine"]
    insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
    with session(engine) as db, db.begin():
        # One atomic UPSERT for all workers, rather than per-process counters.
        stmt = insert(RateBucket).values(key_id=key.id, window=now, count=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key_id", "window"], set_={"count": RateBucket.count + 1}
        ).returning(RateBucket.count)
        count = db.scalar(stmt)
        db.execute(delete(RateBucket).where(RateBucket.window < now - 2))
    if count > limit:
        response = current_app.make_response(({"error": "Rate limit exceeded"}, 429))
        response.headers["Retry-After"] = str(60 - int(time.time()) % 60)
        return response
