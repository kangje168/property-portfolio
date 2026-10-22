import argparse
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config

from .auth import digest
from .db import make_engine, session
from .models import ApiKey, Manager


def migrate(engine, revision="head"):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, revision)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Property Portfolio operations")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    manager = sub.add_parser("manager-create")
    manager.add_argument("name")
    key = sub.add_parser("key-create")
    key.add_argument("--label", required=True)
    key.add_argument("--role", choices=["admin", "manager", "reader"], required=True)
    key.add_argument("--manager-id", type=int)
    key.add_argument("--days", type=int, default=30)
    revoke = sub.add_parser("key-revoke")
    revoke.add_argument("id", type=int)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    engine = make_engine()
    try:
        if args.command == "migrate":
            migrate(engine)
            print(json.dumps({"schema": "head"}))
        elif args.command == "serve":
            from . import create_app

            create_app().run(host="127.0.0.1", port=args.port, debug=False)
        else:
            with session(engine) as db, db.begin():
                if args.command == "manager-create":
                    from .validation import text

                    obj = Manager(name=text(args.name, "name", 120))
                    db.add(obj)
                    db.flush()
                    output = {"manager_id": obj.id, "name": obj.name}
                elif args.command == "key-create":
                    from .validation import text

                    if not 1 <= args.days <= 365:
                        parser.error("days must be between 1 and 365")
                    if args.role != "admin" and not args.manager_id:
                        parser.error("manager and reader keys require --manager-id")
                    if args.role == "admin" and args.manager_id:
                        parser.error("admin keys are global; omit --manager-id")
                    if args.manager_id and not db.get(Manager, args.manager_id):
                        parser.error("Manager does not exist")
                    token = secrets.token_urlsafe(32)
                    obj = ApiKey(
                        digest=digest(token),
                        label=text(args.label, "label", 120),
                        role=args.role,
                        manager_id=args.manager_id,
                        expires_at=(
                            datetime.now(UTC) + timedelta(days=args.days)
                        ).isoformat(),
                    )
                    db.add(obj)
                    db.flush()
                    output = {
                        "key_id": obj.id,
                        "api_key": token,
                        "expires_at": obj.expires_at,
                    }
                else:
                    obj = db.get(ApiKey, args.id)
                    if not obj:
                        parser.error("Key does not exist")
                    obj.revoked = True
                    output = {"key_id": obj.id, "revoked": True}
            # Key is shown once, only after the transaction commits.
            print(json.dumps(output))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
