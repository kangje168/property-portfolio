import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from openapi_schema_validator import OAS30Validator
from openapi_spec_validator import validate
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from portfolio.auth import digest
from portfolio.db import session
from portfolio.models import ApiKey, Audit, ImportRun, Property
from portfolio.validation import COLUMNS

from .conftest import headers

ROOT = Path(__file__).resolve().parents[1]


def csv_data(rows=None):
    rows = (
        rows
        if rows is not None
        else [
            {
                "external_id": "P1",
                "name": "Apartment",
                "address": "1 Test Street",
                "city": "Vincennes",
                "property_type": "apartment",
                "bedrooms": "2",
                "price_eur": "450000.10",
                "latitude": "48.844",
                "longitude": "2.435",
            }
        ]
    )
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def upload(client, raw=None, token="east", manager_id=None):
    data = {
        "file": (io.BytesIO(raw if raw is not None else csv_data()), "properties.csv")
    }
    if manager_id is not None:
        data["manager_id"] = str(manager_id)
    return client.post("/v1/imports", data=data, headers=headers(token))


def polygon():
    return {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[2.4, 48.82], [2.46, 48.82], [2.46, 48.87], [2.4, 48.87], [2.4, 48.82]]
            ],
        }
    }


def test_health_and_contract_public(client):
    assert client.get("/health").json == {"status": "ok"}
    schema = client.get("/openapi.json").json
    validate(schema)
    assert schema["paths"]["/v1/properties"]["get"]["operationId"] == "searchProperties"


@pytest.mark.parametrize("path", ["/v1/managers", "/v1/properties", "/v1/imports/1"])
def test_requires_auth(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers("wrong")).status_code == 401


def test_full_intake_search_rate_audit_flow(client, setup):
    raw = (ROOT / "data/example-properties.csv").read_bytes()
    created = upload(client, raw)
    assert created.status_code == 201
    assert (created.json["created"], created.json["rejected"]) == (3, 1)
    repeated = upload(client, raw).json
    assert repeated["created"] == 0 and repeated["unchanged"] == 3
    assert repeated["rejected"] == 1
    page = client.get(
        "/v1/properties?bedrooms=0&min_price=600000&limit=1&offset=0", headers=headers()
    ).json
    assert page["total"] == 1 and page["items"][0]["external_id"] == "DEMO-003"
    prop = client.get("/v1/properties?city=Vincennes", headers=headers()).json["items"][
        0
    ]
    assert prop["price_eur"] == "450000.10"
    rated = client.patch(
        f"/v1/properties/{prop['id']}/rating", json={"rating": 4}, headers=headers()
    )
    assert rated.status_code == 200 and rated.json["rating"] == 4
    found = client.post(
        "/v1/properties/search-area", json=polygon(), headers=headers()
    ).json
    assert found["total"] == 1 and found["items"][0]["id"] == prop["id"]
    report = client.get(f"/v1/imports/{created.json['import_id']}", headers=headers())
    assert report.status_code == 200 and report.json["rejected"] == 1
    with session(setup[1]) as db:
        assert db.scalar(select(func.count()).select_from(Audit)) == 3
        assert len(db.scalars(select(Property)).all()) == 3
    from portfolio.spec import IMPORT, PAGE, PROPERTY

    for schema, value in [
        (PROPERTY, rated.json),
        (IMPORT, created.json),
        (PAGE, found),
    ]:
        # Inline refs for the local response contract assertion.
        schema = json.loads(json.dumps(schema))
        if "items" in schema.get("properties", {}):
            schema["properties"]["items"]["items"] = PROPERTY
        OAS30Validator(schema).validate(value)


def test_manager_scopes_and_readonly(client):
    first = upload(client).json
    other = upload(client, token="west").json
    assert other["created"] == 1
    assert client.get("/v1/properties", headers=headers()).json["total"] == 1
    assert client.get("/v1/properties", headers=headers("admin")).json["total"] == 2
    assert (
        client.get("/v1/properties?manager_id=2", headers=headers()).status_code == 403
    )
    assert client.get("/v1/managers", headers=headers()).json["items"] == [
        {"id": 1, "name": "East"}
    ]
    assert upload(client, manager_id=2).status_code == 403
    assert upload(client, token="reader").status_code == 403
    assert (
        client.patch(
            "/v1/properties/1/rating", json={"rating": 3}, headers=headers("reader")
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/v1/properties/1/rating", json={"rating": 3}, headers=headers("west")
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/imports/{first['import_id']}", headers=headers("west")
        ).status_code
        == 404
    )
    body = polygon()
    body["manager_id"] = 2
    assert (
        client.post(
            "/v1/properties/search-area", json=body, headers=headers()
        ).status_code
        == 403
    )


def test_admin_explicit_import_scope(client):
    assert upload(client, token="admin").status_code == 400
    assert upload(client, token="admin", manager_id=99).status_code == 400
    assert upload(client, token="admin", manager_id=2).json["created"] == 1
    assert (
        client.get("/v1/properties?manager_id=99", headers=headers("admin")).status_code
        == 404
    )


def test_update_keeps_human_rating(client):
    upload(client)
    pid = client.get("/v1/properties", headers=headers()).json["items"][0]["id"]
    client.patch(f"/v1/properties/{pid}/rating", json={"rating": 5}, headers=headers())
    raw = csv_data().replace(b"450000.10", b"490000.99")
    assert upload(client, raw).json["updated"] == 1
    p = client.get("/v1/properties", headers=headers()).json["items"][0]
    assert p["rating"] == 5 and p["price_eur"] == "490000.99"
    # Replaying an older file restores its values; it is not a digest cache.
    assert upload(client).json["updated"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "bedrooms=-1",
        "bedrooms=1.5",
        "bedrooms=30",
        "limit=0",
        "offset=-1",
        "min_price=NaN",
        "min_price=1e5",
        "max_price=Infinity",
        "min_price=100&max_price=10",
        "property_type=castle",
        "manager_id=1 OR 1=1",
        "city=a&city=b",
        "unknown=x",
    ],
)
def test_bad_search_parameters(client, query):
    assert client.get("/v1/properties?" + query, headers=headers()).status_code == 400


def test_sql_injection_is_data(client):
    upload(client)
    assert (
        client.get(
            "/v1/properties",
            query_string={"city": "Vincennes' OR 1=1 --"},
            headers=headers(),
        ).json["total"]
        == 0
    )
    assert client.get("/v1/properties", headers=headers()).json["total"] == 1


@pytest.mark.parametrize("value", [0, 6, -1, True, 2.5, "3", None])
def test_rating_validation(client, value):
    upload(client)
    assert (
        client.patch(
            "/v1/properties/1/rating", json={"rating": value}, headers=headers()
        ).status_code
        == 400
    )


def test_partial_rejections_and_unique_conflict(client):
    raw = csv_data().decode()
    line = raw.splitlines()[1]
    data = (raw + line.replace("P1", "P2") + "\r\n" + line + "\r\n").encode()
    result = upload(client, data).json
    assert (result["created"], result["rejected"]) == (1, 2)
    assert result["errors"][0]["record"] == 3
    assert result["errors"][1]["record"] == 4


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"name,name\na,b",
        b"unknown\na",
        csv_data() + b"too,many,columns\n",
        b'"unclosed',
    ],
)
def test_malformed_csv_has_no_writes(client, setup, raw):
    assert upload(client, raw).status_code == 400
    with session(setup[1]) as db:
        assert db.scalar(select(func.count()).select_from(Property)) == 0
        assert db.scalar(select(func.count()).select_from(ImportRun)) == 0


@pytest.mark.parametrize(
    "old,new",
    [
        (b"450000.10", b"NaN"),
        (b"450000.10", b"3.14159"),
        (b"450000.10", b"-1"),
        (b"48.844", b"91"),
        (b"2.435", b"nan"),
        (b",2,450", b",21,450"),
    ],
)
def test_invalid_row_quarantine(client, old, new):
    result = upload(client, csv_data().replace(old, new)).json
    assert result["created"] == 0 and result["rejected"] == 1


def test_intake_size_bounds(client):
    assert upload(client, b"a" * (2 * 1024 * 1024 + 1)).status_code == 400
    assert upload(client, b"a" * (3 * 1024 * 1024 + 1)).status_code == 413


def test_expired_and_revoked_keys(client, setup):
    with session(setup[1]) as db, db.begin():
        key = db.scalar(select(ApiKey).where(ApiKey.digest == digest("east")))
        key.revoked = True
        key = db.scalar(select(ApiKey).where(ApiKey.digest == digest("west")))
        key.expires_at = "2000-01-01T00:00:00+00:00"
    assert client.get("/v1/properties", headers=headers()).status_code == 401
    assert client.get("/v1/properties", headers=headers("west")).status_code == 401


def test_rate_limit_shared_between_app_instances(setup):
    from portfolio import create_app

    app, engine = setup
    app.config["RATE_LIMIT"] = 2
    second = create_app({"DATABASE_URL": engine.url, "RATE_LIMIT": 2})
    try:
        assert (
            app.test_client().get("/v1/properties", headers=headers()).status_code
            == 200
        )
        assert (
            second.test_client().get("/v1/properties", headers=headers()).status_code
            == 200
        )
        response = app.test_client().get("/v1/properties", headers=headers())
        assert (
            response.status_code == 429
            and 1 <= int(response.headers["Retry-After"]) <= 60
        )
        assert (
            second.test_client()
            .get("/v1/properties", headers=headers("west"))
            .status_code
            == 200
        )
    finally:
        second.extensions["engine"].dispose()


def test_concurrent_replay_does_not_duplicate(setup):
    app, engine = setup

    def run(_):
        with app.test_client() as client:
            r = upload(client)
            return r.status_code, r.json

    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(run, range(4)))
    assert all(code == 201 for code, _ in reports), reports
    assert sum(r["created"] for _, r in reports) == 1
    with session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Property)) == 1


def test_geo_boundary_hole_and_scope(client):
    upload(client)
    upload(client, token="west")
    body = polygon()
    found = client.post("/v1/properties/search-area", json=body, headers=headers()).json
    assert found["total"] == 1
    body["geometry"]["coordinates"].append(
        [[2.43, 48.84], [2.44, 48.84], [2.44, 48.85], [2.43, 48.85], [2.43, 48.84]]
    )
    assert (
        client.post("/v1/properties/search-area", json=body, headers=headers()).json[
            "total"
        ]
        == 0
    )
    body = polygon()
    body["geometry"]["coordinates"][0] = [
        [2.435, 48.844],
        [2.46, 48.844],
        [2.46, 48.87],
        [2.435, 48.87],
        [2.435, 48.844],
    ]
    assert (
        client.post("/v1/properties/search-area", json=body, headers=headers()).json[
            "total"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {"type": "Point", "coordinates": [2, 48]},
        {
            "type": "Polygon",
            "coordinates": [[[2, 48], [3, 49], [2, 49], [3, 48], [2, 48]]],
        },
        {"type": "Polygon", "coordinates": [[[2, 48], [3, 48], [3, 49], [2, 49]]]},
        {"type": "Polygon", "coordinates": [[["2", 48], [3, 48], [3, 49], ["2", 48]]]},
    ],
)
def test_invalid_geometry(client, geometry):
    assert (
        client.post(
            "/v1/properties/search-area", json={"geometry": geometry}, headers=headers()
        ).status_code
        == 400
    )


def test_constraints_and_schema_match(setup):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from portfolio.models import Base

    engine = setup[1]
    with engine.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert differences == []
    with pytest.raises(IntegrityError), session(engine) as db, db.begin():
        db.add(
            Property(
                manager_id=1,
                external_id="bad",
                name="Bad",
                address="Bad",
                city="Bad",
                property_type="house",
                bedrooms=1,
                price_cents=0,
                latitude=48,
                longitude=2,
                rating=6,
            )
        )


def test_errors_are_json_and_do_not_leak_values(client):
    assert client.get("/missing").status_code == 404
    assert client.get("/missing").json == {"error": "Not Found"}
    assert (
        client.post(
            "/v1/properties/search-area", data="bad", headers=headers()
        ).status_code
        == 415
    )
    response = client.get("/health")
    assert response.headers["Cache-Control"] == "no-store"
    assert len(response.headers["X-Request-ID"]) == 32
