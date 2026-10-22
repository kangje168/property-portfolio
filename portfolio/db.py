import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def make_engine(url=None):
    url = url or os.environ.get("PORTFOLIO_DATABASE_URL", "sqlite:///portfolio.db")
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_settings(conn, record):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")

    return engine


def session(engine):
    return Session(engine, expire_on_commit=False)
