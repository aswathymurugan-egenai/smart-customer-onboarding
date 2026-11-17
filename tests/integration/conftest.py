"""Platform check fixtures. These tests need a GCP dev project and credentials.

Set `GCP_PROJECT` (and optionally `BQ_LOCATION`, `GENAI_LOCATION`, `IT_FINDINGS_PATH`) and run
`make integration`. Each run creates the dataset `it_<run id>` with a one-day default table
expiration and deletes it in teardown, so a re-run after a crash starts clean.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from google.cloud import bigquery

from scripts.apply_schema import apply_schema

ONE_DAY_MS = 24 * 60 * 60 * 1000


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test in this directory as an integration test."""
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def project() -> str:
    value = os.environ.get("GCP_PROJECT")
    if not value:
        pytest.skip("Set GCP_PROJECT to run the platform check.")
    return value


@pytest.fixture(scope="session")
def location() -> str:
    return os.environ.get("BQ_LOCATION", "US")


@pytest.fixture(scope="session")
def client(project: str, location: str) -> Iterator[bigquery.Client]:
    bq = bigquery.Client(project=project, location=location)
    yield bq
    bq.close()


@pytest.fixture(scope="session")
def findings() -> Iterator[dict[str, Any]]:
    """Measurements the platform check records for the PR description."""
    record: dict[str, Any] = {}
    yield record
    print("\nPLATFORM CHECK FINDINGS\n" + json.dumps(record, indent=2, sort_keys=True))
    target = os.environ.get("IT_FINDINGS_PATH")
    if target:
        Path(target).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


@pytest.fixture(scope="session")
def dataset(client: bigquery.Client, project: str, location: str) -> Iterator[str]:
    """A scratch dataset with the schema applied, deleted afterward."""
    name = f"it_{uuid.uuid4().hex[:12]}"
    created = bigquery.Dataset(f"{project}.{name}")
    created.location = location
    created.default_table_expiration_ms = ONE_DAY_MS
    client.create_dataset(created)
    try:
        apply_schema(client, project, name, location)
        yield name
    finally:
        client.delete_dataset(f"{project}.{name}", delete_contents=True, not_found_ok=True)
