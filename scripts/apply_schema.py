"""Apply `sql/001_customer_ops_schema.sql` to a BigQuery project.

Run `python -m scripts.apply_schema`.

Every statement uses `IF NOT EXISTS`, so a second run changes nothing. Configure with
`--project`, `--dataset`, and `--location`, or the `GCP_PROJECT`, `BQ_DATASET`, and
`BQ_LOCATION` environment variables.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from google.cloud import bigquery

from app.services.sql_templates import render_template, split_statements, validate_identifiers

SCHEMA_TEMPLATE = "001_customer_ops_schema"
DEFAULT_DATASET = "customer_ops"
DEFAULT_LOCATION = "US"


def render_statements(project: str, dataset: str, location: str) -> list[str]:
    """Render the schema file and split it into statements. Validates every identifier."""
    validate_identifiers(project, dataset, location)
    script = render_template(SCHEMA_TEMPLATE, project=project, dataset=dataset, location=location)
    return split_statements(script)


def apply_schema(client: Any, project: str, dataset: str, location: str) -> list[str]:
    """Run each statement as a query job, then return the names of the tables that exist."""
    for statement in render_statements(project, dataset, location):
        client.query(statement, location=location).result()
    return sorted(table.table_id for table in client.list_tables(f"{project}.{dataset}"))


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT"))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", DEFAULT_LOCATION))
    args = parser.parse_args(argv)
    if not args.project:
        print("Set --project or GCP_PROJECT.", file=sys.stderr)
        return 2
    client = bigquery.Client(project=args.project, location=args.location)
    tables = apply_schema(client, args.project, args.dataset, args.location)
    print(f"{args.project}.{args.dataset}: {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
