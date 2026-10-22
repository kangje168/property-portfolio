"""Exercise the actual HTTP API with disposable synthetic data; no user setup."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Thread

from werkzeug.serving import make_server

from portfolio import create_app

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="portfolio-demo-") as directory:
        url = "sqlite:///" + str(Path(directory) / "demo.db")
        env = {**os.environ, "PORTFOLIO_DATABASE_URL": url}

        def operate(*args):
            result = subprocess.run(
                [sys.executable, "-m", "portfolio.cli", *args],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(result.stdout)

        operate("migrate")
        manager = operate("manager-create", "Synthetic demo")["manager_id"]
        issued = operate(
            "key-create",
            "--label",
            "demo",
            "--role",
            "manager",
            "--manager-id",
            str(manager),
            "--days",
            "1",
        )
        app = create_app({"DATABASE_URL": url})
        server = make_server("127.0.0.1", 0, app)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        env.update(
            PORTFOLIO_API_URL=f"http://127.0.0.1:{server.server_port}",
            PORTFOLIO_API_KEY=issued["api_key"],
        )

        def call(*args):
            p = subprocess.run(
                [sys.executable, str(ROOT / "tools/client.py"), *args],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(p.stdout)

        try:
            initial = call("import", str(ROOT / "data/example-properties.csv"))
            repeated = call("import", str(ROOT / "data/example-properties.csv"))
            found = call("search", "--city", "Vincennes")
            rated = call("rate", str(found["items"][0]["id"]), "4")
            area = call("area", str(ROOT / "data/example-area.json"))
            report = call("report", str(initial["import_id"]))
            assert initial["created"] == 3 and initial["rejected"] == 1
            assert repeated["unchanged"] == 3 and repeated["created"] == 0
            assert area["total"] == 1 and rated["rating"] == 4 and report["errors"]
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "transport": "HTTP over loopback",
                        "initial_import": {
                            "created": initial["created"],
                            "rejected": initial["rejected"],
                        },
                        "repeat_import": {
                            "created": repeated["created"],
                            "unchanged": repeated["unchanged"],
                        },
                        "area_matches": area["total"],
                        "human_rating": rated["rating"],
                        "credentials": "ephemeral; not printed",
                        "storage": "temporary; removed on exit",
                    },
                    indent=2,
                )
            )
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
            app.extensions["engine"].dispose()


if __name__ == "__main__":
    main()
