import json
import logging
import os
import uuid
from contextlib import contextmanager

from flask import Flask, g, request
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from werkzeug.exceptions import HTTPException

from .auth import authenticate
from .db import make_engine, session
from .intake import import_csv
from .models import Audit, ImportRun, Manager, Property, utcnow
from .validation import TYPES, Invalid, in_polygon, integer, money, polygon_from, text


class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def scope(value=None, required=False):
    manager_id = integer(value, "manager_id", 1) if value is not None else None
    if g.key.role != "admin":
        if manager_id is not None and manager_id != g.key.manager_id:
            raise ApiError("This API key cannot access that manager", 403)
        return g.key.manager_id
    if required and manager_id is None:
        raise Invalid("manager_id is required for an administrator")
    return manager_id


def require_write():
    if g.key.role not in ("admin", "manager"):
        raise ApiError("This API key is read-only", 403)


def serialize(prop):
    return {
        "id": prop.id,
        "manager_id": prop.manager_id,
        "external_id": prop.external_id,
        "name": prop.name,
        "address": prop.address,
        "city": prop.city,
        "property_type": prop.property_type,
        "bedrooms": prop.bedrooms,
        "price_eur": f"{prop.price_cents // 100}.{prop.price_cents % 100:02d}",
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "rating": prop.rating,
        "updated_at": prop.updated_at,
    }


@contextmanager
def transaction(engine):
    with session(engine) as db:
        if engine.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


def create_app(config=None):
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    app.config.update(
        MAX_CONTENT_LENGTH=3 * 1024 * 1024,
        RATE_LIMIT=int(os.environ.get("PORTFOLIO_RATE_LIMIT", "120")),
    )
    app.config.update(config or {})
    engine = make_engine(app.config.get("DATABASE_URL"))
    app.extensions["engine"] = engine
    app.json.sort_keys = False

    @app.before_request
    def before():
        g.request_id = uuid.uuid4().hex
        if request.path.startswith("/v1/"):
            return authenticate()

    @app.after_request
    def after(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        # Never log Authorization, request bodies, query strings or document data.
        app.logger.info(
            "request id=%s method=%s endpoint=%s status=%s",
            g.request_id,
            request.method,
            request.endpoint or "unknown",
            response.status_code,
        )
        return response

    @app.errorhandler(Invalid)
    def invalid(error):
        return {"error": str(error)}, 400

    @app.errorhandler(ApiError)
    def api_error(error):
        return {"error": error.message}, error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return {"error": error.name}, error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        # SQLAlchemy exception strings can contain bound values: do not log them.
        app.logger.error(
            "request id=%s failed type=%s", g.request_id, type(error).__name__
        )
        return {"error": "Internal error", "request_id": g.request_id}, 500

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/")
    def index():
        return {
            "service": "Property Portfolio",
            "version": "0.1.0",
            "schema": "/openapi.json",
            "health": "/health",
        }

    @app.get("/openapi.json")
    def specification():
        from .spec import SPEC

        return SPEC

    @app.get("/v1/managers")
    def managers():
        with session(engine) as db:
            query = select(Manager).order_by(Manager.id)
            if g.key.role != "admin":
                query = query.where(Manager.id == g.key.manager_id)
            return {"items": [{"id": m.id, "name": m.name} for m in db.scalars(query)]}

    @app.get("/v1/properties")
    def properties():
        allowed = {
            "manager_id",
            "property_type",
            "city",
            "bedrooms",
            "min_price",
            "max_price",
            "limit",
            "offset",
        }
        if set(request.args) - allowed or any(
            len(v) != 1 for _, v in request.args.lists()
        ):
            raise Invalid("Unknown or repeated search parameter")
        args = request.args
        manager_id = scope(args.get("manager_id"))
        conditions = (
            [Property.manager_id == manager_id] if manager_id is not None else []
        )
        if "property_type" in args:
            if args["property_type"] not in TYPES:
                raise Invalid("Invalid property_type")
            conditions.append(Property.property_type == args["property_type"])
        if "city" in args:
            conditions.append(Property.city == text(args["city"], "city", 100))
        if "bedrooms" in args:
            conditions.append(
                Property.bedrooms == integer(args["bedrooms"], "bedrooms", 0, 20)
            )
        low = money(args["min_price"], "min_price") if "min_price" in args else 0
        high = (
            money(args["max_price"], "max_price")
            if "max_price" in args
            else 100000000000
        )
        if low > high:
            raise Invalid("min_price must not exceed max_price")
        conditions.extend([Property.price_cents >= low, Property.price_cents <= high])
        limit = integer(args.get("limit", 50), "limit", 1, 100)
        offset = integer(args.get("offset", 0), "offset", 0, 1000000)
        with session(engine) as db:
            if manager_id is not None and not db.get(Manager, manager_id):
                raise ApiError("Manager not found", 404)
            total = db.scalar(
                select(func.count()).select_from(Property).where(*conditions)
            )
            rows = db.scalars(
                select(Property)
                .where(*conditions)
                .order_by(Property.id)
                .limit(limit)
                .offset(offset)
            )
            return {
                "items": [serialize(p) for p in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    @app.post("/v1/imports")
    def intake():
        require_write()
        manager_id = scope(request.form.get("manager_id"), required=True)
        upload = request.files.get("file")
        if not upload:
            raise Invalid("A CSV file is required in multipart field file")
        raw = upload.read(2 * 1024 * 1024 + 1)
        with transaction(engine) as db:
            report = import_csv(db, g.key, manager_id, raw)
        return report, 201

    @app.get("/v1/imports/<int:run_id>")
    def import_report(run_id):
        with session(engine) as db:
            run = db.get(ImportRun, run_id)
            if not run or (
                g.key.role != "admin" and run.manager_id != g.key.manager_id
            ):
                raise ApiError("Import not found", 404)
            return {
                "import_id": run.id,
                "manager_id": run.manager_id,
                "sha256": run.digest,
                "created_at": run.created_at,
                **json.loads(run.report),
            }

    @app.patch("/v1/properties/<int:property_id>/rating")
    def rating(property_id):
        require_write()
        body = request.get_json()
        if (
            not isinstance(body, dict)
            or set(body) != {"rating"}
            or type(body["rating"]) is not int
        ):
            raise Invalid("Body must contain only rating as an integer from 1 to 5")
        value = integer(body["rating"], "rating", 1, 5)
        with transaction(engine) as db:
            query = select(Property).where(Property.id == property_id)
            if g.key.role != "admin":
                query = query.where(Property.manager_id == g.key.manager_id)
            prop = db.scalar(query.with_for_update())
            if not prop:
                raise ApiError("Property not found", 404)
            old = prop.rating
            prop.rating, prop.updated_at = value, utcnow()
            db.add(
                Audit(
                    key_id=g.key.id,
                    action="rating_update",
                    resource_id=prop.id,
                    details=json.dumps({"before": old, "after": value}),
                )
            )
            response = serialize(prop)
        return response

    @app.post("/v1/properties/search-area")
    def area():
        body = request.get_json()
        if not isinstance(body, dict) or set(body) - {
            "geometry",
            "manager_id",
            "limit",
            "offset",
        }:
            raise Invalid("Expected geometry, optional manager_id, limit and offset")
        polygon = polygon_from(body.get("geometry"))
        manager_id = scope(body.get("manager_id"))
        limit = integer(body.get("limit", 50), "limit", 1, 100)
        offset = integer(body.get("offset", 0), "offset", 0, 1000000)
        west, south, east, north = polygon.bounds
        conditions = [
            Property.longitude.between(west, east),
            Property.latitude.between(south, north),
        ]
        if manager_id is not None:
            conditions.append(Property.manager_id == manager_id)
        with session(engine) as db:
            if manager_id is not None and not db.get(Manager, manager_id):
                raise ApiError("Manager not found", 404)
            candidates = list(
                db.scalars(
                    select(Property)
                    .where(*conditions)
                    .order_by(Property.id)
                    .limit(10001)
                )
            )
            if len(candidates) > 10000:
                raise ApiError(
                    "Area contains too many candidates; narrow the polygon or manager scope",
                    422,
                )
            matches = [
                p for p in candidates if in_polygon(polygon, p.longitude, p.latitude)
            ]
            return {
                "items": [serialize(p) for p in matches[offset : offset + limit]],
                "total": len(matches),
                "limit": limit,
                "offset": offset,
                "boundary": "included",
            }

    return app
