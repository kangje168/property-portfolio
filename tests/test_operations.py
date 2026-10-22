import json
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from portfolio.cli import migrate
from portfolio.db import make_engine


def test_migration_preserves_legacy_rows_and_downgrades(tmp_path):
    engine = make_engine("sqlite:///" + str(tmp_path / "upgrade.db"))
    migrate(engine, "0001")
    with engine.begin() as c:
        c.execute(text("INSERT INTO managers (id,name) VALUES (1,'Legacy')"))
        c.execute(
            text(
                "INSERT INTO properties (id,manager_id,external_id,name,address,city,property_type,bedrooms,price_cents,latitude,longitude,updated_at) VALUES (1,1,'old','Old','Street','City','house',1,100,48,2,'2023-03-05T00:00:00+00:00')"
            )
        )
    migrate(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT name,rating FROM properties")).one() == (
            "Old",
            None,
        )
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "portfolio/migrations"),
    )
    with engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "0001")
    assert "rating" not in {
        col["name"] for col in inspect(engine).get_columns("properties")
    }
    migrate(engine)
    engine.dispose()


def test_cli_bootstrap_and_revoke(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PORTFOLIO_DATABASE_URL", "sqlite:///" + str(tmp_path / "cli.db")
    )

    def run(*args):
        p = subprocess.run(
            [sys.executable, "-m", "portfolio.cli", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)

    assert run("migrate") == {"schema": "head"}
    mid = run("manager-create", "Demo")["manager_id"]
    token = run(
        "key-create", "--label", "test", "--role", "manager", "--manager-id", str(mid)
    )
    assert len(token["api_key"]) >= 40
    assert run("key-revoke", str(token["key_id"]))["revoked"] is True
    with make_engine().connect() as c:
        stored = c.execute(text("SELECT digest FROM api_keys")).scalar()
    assert stored != token["api_key"]
