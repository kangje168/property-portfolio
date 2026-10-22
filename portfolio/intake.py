import csv
import hashlib
import io
import json

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import Audit, ImportRun, Manager, Property, utcnow
from .validation import COLUMNS, Invalid, property_row

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000


def import_csv(db, key, manager_id, raw):
    if len(raw) > MAX_BYTES:
        raise Invalid("CSV exceeds 2 MiB")
    try:
        decoded = raw.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(decoded), strict=True)
        header = next(reader)
        if len(header) != len(set(header)) or set(header) != set(COLUMNS):
            raise Invalid(
                "CSV must contain exactly these columns: " + ", ".join(COLUMNS)
            )
        rows = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise Invalid(
                    "CSV has a malformed record with missing or extra columns"
                )
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise Invalid("CSV exceeds 10000 rows")
    except (UnicodeDecodeError, csv.Error, StopIteration):
        raise Invalid("CSV must be a nonempty, valid UTF-8 CSV file") from None
    # Pandas is used as a typed-as-text ingestion layer; monetary parsing is explicit.
    frame = pd.DataFrame(rows, columns=header, dtype=str)
    if not db.get(Manager, manager_id):
        raise Invalid("Manager does not exist")
    # All imports for one manager serialize against this parent on PostgreSQL.
    # SQLite serialization is established by the caller's BEGIN IMMEDIATE.
    db.scalar(select(Manager).where(Manager.id == manager_id).with_for_update())
    report = {
        "rows": len(frame),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0,
        "errors": [],
    }
    seen = set()
    for line, row in enumerate(frame.to_dict(orient="records"), start=2):
        try:
            values = property_row(row)
            if values["external_id"] in seen:
                raise Invalid("Duplicate external_id in the same file")
            seen.add(values["external_id"])
            with db.begin_nested():
                existing = db.scalar(
                    select(Property).where(
                        Property.manager_id == manager_id,
                        Property.external_id == values["external_id"],
                    )
                )
                if existing:
                    changed = any(getattr(existing, k) != v for k, v in values.items())
                    if changed:
                        for name, value in values.items():
                            setattr(existing, name, value)
                        existing.updated_at = utcnow()
                    outcome = "updated" if changed else "unchanged"
                else:
                    db.add(Property(manager_id=manager_id, **values))
                    outcome = "created"
                db.flush()
            report[outcome] += 1
        except (Invalid, IntegrityError) as error:
            report["rejected"] += 1
            report["errors"].append(
                {
                    "record": line,
                    "error": str(error)
                    if isinstance(error, Invalid)
                    else "Property name/address conflicts with an existing property for this manager",
                }
            )
    run = ImportRun(
        manager_id=manager_id,
        key_id=key.id,
        digest=hashlib.sha256(raw).hexdigest(),
        report=json.dumps(report),
    )
    db.add(run)
    db.flush()
    db.add(
        Audit(
            key_id=key.id,
            action="csv_import",
            resource_id=run.id,
            details=json.dumps({k: v for k, v in report.items() if k != "errors"}),
        )
    )
    return {
        "import_id": run.id,
        "manager_id": manager_id,
        "sha256": run.digest,
        **report,
    }
