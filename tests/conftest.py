import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import make_url

from portfolio import create_app
from portfolio.auth import digest
from portfolio.cli import migrate
from portfolio.db import make_engine, session
from portfolio.models import ApiKey, Base, Manager

BACKENDS = ["sqlite"] + (
    ["postgres"] if os.environ.get("PORTFOLIO_TEST_DATABASE_URL") else []
)


@pytest.fixture(params=BACKENDS)
def setup(request, tmp_path):
    url = "sqlite:///" + str(tmp_path / "test.db")
    if request.param == "postgres":
        url = os.environ["PORTFOLIO_TEST_DATABASE_URL"]
        if not (make_url(url).database or "").endswith("_test"):
            pytest.fail(
                "Destructive PostgreSQL tests require a database name ending in _test"
            )
    engine = make_engine(url)
    if request.param == "postgres":
        Base.metadata.drop_all(engine)
        with engine.begin() as c:
            from sqlalchemy import text

            c.execute(text("DROP TABLE IF EXISTS alembic_version"))
    migrate(engine)
    with session(engine) as db, db.begin():
        db.add_all([Manager(id=1, name="East"), Manager(id=2, name="West")])
        db.flush()
        for token, role, manager in [
            ("admin", "admin", None),
            ("east", "manager", 1),
            ("west", "manager", 2),
            ("reader", "reader", 1),
        ]:
            db.add(
                ApiKey(
                    digest=digest(token),
                    label=token,
                    role=role,
                    manager_id=manager,
                    expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                )
            )
    app = create_app({"TESTING": True, "DATABASE_URL": url, "RATE_LIMIT": 1000})
    yield app, engine
    app.extensions["engine"].dispose()
    engine.dispose()


@pytest.fixture
def client(setup):
    return setup[0].test_client()


def headers(token="east"):
    return {"Authorization": "Bearer " + token}
