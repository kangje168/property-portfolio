"""Small JSON-output HTTP client suitable for terminal users and agents."""

import argparse
import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Redirect refused; use the final trusted API URL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import")
    ingest.add_argument("file")
    ingest.add_argument("--manager-id", type=int)
    search = sub.add_parser("search")
    for name in [
        "city",
        "property-type",
        "bedrooms",
        "min-price",
        "max-price",
        "manager-id",
        "limit",
        "offset",
    ]:
        search.add_argument("--" + name)
    area = sub.add_parser("area")
    area.add_argument("file")
    rating = sub.add_parser("rate")
    rating.add_argument("id", type=int)
    rating.add_argument("rating", type=int)
    report = sub.add_parser("report")
    report.add_argument("id", type=int)
    args = parser.parse_args()
    base = os.environ.get("PORTFOLIO_API_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
        or not parsed.hostname
    ):
        parser.error("PORTFOLIO_API_URL must be a plain API origin")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        parser.error("Use HTTPS for remote APIs")
    token = os.environ.get("PORTFOLIO_API_KEY")
    if not token:
        parser.error("Set PORTFOLIO_API_KEY in the process environment")
    headers = {"Authorization": "Bearer " + token}
    data = None
    method = "GET"
    if args.command == "search":
        query = {
            k: v for k, v in vars(args).items() if k != "command" and v is not None
        }
        path = "/v1/properties?" + urlencode(query)
    elif args.command == "report":
        path = f"/v1/imports/{args.id}"
    elif args.command == "import":
        raw = Path(args.file).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            parser.error("File exceeds 2 MiB")
        boundary = "portfolio-" + uuid.uuid4().hex
        data = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="properties.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
            + raw
            + b"\r\n"
        )
        if args.manager_id is not None:
            data += f'--{boundary}\r\nContent-Disposition: form-data; name="manager_id"\r\n\r\n{args.manager_id}\r\n'.encode()
        data += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        path = "/v1/imports"
        method = "POST"
    else:
        body = (
            json.loads(Path(args.file).read_text(encoding="utf-8"))
            if args.command == "area"
            else {"rating": args.rating}
        )
        path = (
            "/v1/properties/search-area"
            if args.command == "area"
            else f"/v1/properties/{args.id}/rating"
        )
        method = "POST" if args.command == "area" else "PATCH"
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, allow_nan=False).encode()
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(req, timeout=30) as response:
            print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
    except HTTPError as error:
        print(
            json.dumps(
                {"status": error.code, "response": json.load(error)}, ensure_ascii=False
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
