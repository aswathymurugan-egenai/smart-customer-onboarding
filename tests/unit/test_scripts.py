"""The maintenance scripts: spec export, schema apply, and the disposable-list refresh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import apply_schema, export_openapi, refresh_disposable_domains

UPSTREAM = "Alpha.Test\n\n# comment\nbeta.test\nbeta.test\nnot a domain\n-bad-.test\n"


def test_refresh_writes_a_sorted_deduplicated_validated_list_with_a_provenance_header(
    tmp_path: Path,
) -> None:
    target = tmp_path / "disposable.txt"

    changed = refresh_disposable_domains.refresh(
        target, fetch=lambda _: UPSTREAM, today="2026-11-16"
    )

    assert changed
    lines = target.read_text().splitlines()
    assert lines[:5] == [
        "# Disposable email domains, one per line.",
        "# Source: https://github.com/disposable-email-domains/disposable-email-domains",
        "# License: CC0 1.0 Universal",
        "# Fetched: 2026-11-16",
        "# Refresh with: python scripts/refresh_disposable_domains.py",
    ]
    assert lines[5:] == ["alpha.test", "beta.test"]


def test_a_second_refresh_with_no_upstream_change_leaves_the_file_identical(tmp_path: Path) -> None:
    target = tmp_path / "disposable.txt"
    refresh_disposable_domains.refresh(target, fetch=lambda _: UPSTREAM, today="2026-11-16")
    before = target.read_bytes()

    changed = refresh_disposable_domains.refresh(
        target, fetch=lambda _: UPSTREAM, today="2027-01-01"
    )

    assert not changed
    assert target.read_bytes() == before


def test_refresh_refuses_an_empty_upstream_and_keeps_the_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "disposable.txt"
    refresh_disposable_domains.refresh(target, fetch=lambda _: UPSTREAM, today="2026-11-16")
    before = target.read_bytes()

    with pytest.raises(ValueError, match="no valid domains"):
        refresh_disposable_domains.refresh(target, fetch=lambda _: "# nothing\n")

    assert target.read_bytes() == before


def test_download_refuses_a_non_https_source() -> None:
    with pytest.raises(ValueError, match="non-HTTPS"):
        refresh_disposable_domains.download("http://example.com/list.txt")


def test_the_vendored_disposable_list_opens_with_source_license_and_fetch_date() -> None:
    header = Path(refresh_disposable_domains.TARGET).read_text(encoding="utf-8").splitlines()[:4]

    assert header[1].startswith("# Source: https://")
    assert header[2].startswith("# License: ")
    assert header[3].startswith("# Fetched: 20")


def test_apply_schema_runs_each_statement_as_a_query_job_and_lists_the_tables() -> None:
    client = MagicMock()
    client.list_tables.return_value = [
        MagicMock(table_id="registration_audit_logs"),
        MagicMock(table_id="customers"),
    ]

    tables = apply_schema.apply_schema(client, "test-project-1", "customer_ops", "US")

    assert tables == ["customers", "registration_audit_logs"]
    statements = [call.args[0] for call in client.query.call_args_list]
    assert len(statements) == 3
    assert all("IF NOT EXISTS" in statement for statement in statements)
    assert all(call.kwargs["location"] == "US" for call in client.query.call_args_list)


def test_apply_schema_refuses_an_invalid_identifier_before_running_anything() -> None:
    client = MagicMock()

    with pytest.raises(Exception, match="dataset"):
        apply_schema.apply_schema(client, "test-project-1", "bad name", "US")

    client.query.assert_not_called()


def test_the_export_script_check_mode_reports_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = tmp_path / "openapi.yaml"
    stale.write_text("openapi: 3.1.0\n")

    assert export_openapi.main(["--target", str(stale), "--check"]) == 1
    assert export_openapi.main(["--target", str(stale)]) == 0
    assert export_openapi.main(["--target", str(stale), "--check"]) == 0
    assert "out of date" in capsys.readouterr().out
