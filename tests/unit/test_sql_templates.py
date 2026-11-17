"""The SQL templates: rendering, parameters, and the position of the table lock."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.customer import (
    Address,
    AttemptAudit,
    AuditEvent,
    BlockingProbe,
    CustomerRecord,
    MatchProbe,
    NormalizedCustomer,
)
from app.services.bq_repository import (
    event_parameters,
    exact_match_parameters,
    fuzzy_parameters,
    register_parameters,
)
from app.services.sql_templates import (
    SQL_DIR,
    TemplateError,
    render_template,
    split_statements,
    validate_identifiers,
)

PROJECT = "test-project-1"
DATASET = "customer_ops"
TEMPLATES = [
    "register_customer",
    "find_exact_matches",
    "find_fuzzy_candidates",
    "insert_audit_event",
    "checks/duplicate_keys",
]
NAMED_PARAMETER = re.compile(r"(?<![@\w])@([a-z_][a-z0-9_]*)")


def render(name: str) -> str:
    return render_template(name, project=PROJECT, dataset=DATASET)


def parameter_names(sql: str) -> set[str]:
    code = "\n".join(line.split("--")[0] for line in sql.splitlines())
    return set(NAMED_PARAMETER.findall(code))


def sample_attempt() -> AttemptAudit:
    return AttemptAudit(
        event_id="e1",
        request_id="r1",
        idempotency_key=None,
        request_fingerprint="f",
        channel="form",
        email_hash="h",
        client_hash="c",
        mx_status="pass",
        advisory_status="ok",
        typo_suggested_domain=None,
        fuzzy_candidate_ids=(),
        fuzzy_max_confidence=None,
        advisory_model=None,
        lock_retries=0,
        latency_ms=5,
    )


def sample_record() -> CustomerRecord:
    customer = NormalizedCustomer(
        customer_type="individual",
        given_name="Jane",
        family_name=None,
        company_name=None,
        normalized_name="jane",
        name_key="jane",
        email="jane@example.com",
        email_as_entered="jane@example.com",
        email_local_part="jane",
        email_domain="example.com",
        phone_e164=None,
        tax_id_type=None,
        tax_id=None,
        address=Address(line1="1 St", city="X", country_code="US"),
        normalized_address="1 st x us",
        postal_code_key=None,
    )
    return CustomerRecord("c1", customer, "pass", None, None, "v1", "form")


@pytest.mark.parametrize("name", [*TEMPLATES, "001_customer_ops_schema"])
def test_every_template_renders_without_leftover_placeholders(name: str) -> None:
    sql = render_template(name, project=PROJECT, dataset=DATASET, location="US")

    assert "${" not in sql
    assert f"`{PROJECT}.{DATASET}" in sql


@pytest.mark.parametrize(
    ("project", "dataset", "location"),
    [
        ("Bad_Project", DATASET, None),
        ("p", DATASET, None),
        (PROJECT, "data`set", None),
        (PROJECT, "a; DROP TABLE x", None),
        (PROJECT, DATASET, "US'; --"),
    ],
)
def test_invalid_identifiers_are_refused_before_substitution(
    project: str, dataset: str, location: str | None
) -> None:
    with pytest.raises(TemplateError):
        validate_identifiers(project, dataset, location)
    with pytest.raises(TemplateError):
        render_template("register_customer", project=project, dataset=dataset, location=location)


@pytest.mark.parametrize("path", sorted(SQL_DIR.rglob("*.sql")), ids=lambda p: p.name)
def test_no_template_contains_python_format_fields_or_percent_placeholders(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    assert "%" not in text
    assert not re.search(r"\{(?!project\}|dataset\}|location\})", text.replace("${", "{"))


def test_register_template_parameters_match_the_builder_exactly() -> None:
    sent = {p.name for p in register_parameters(sample_record(), sample_attempt())}

    assert parameter_names(render("register_customer")) == sent


def test_exact_match_template_parameters_match_the_builder_exactly() -> None:
    sent = {p.name for p in exact_match_parameters(MatchProbe("a@b.co", None, None))}

    assert parameter_names(render("find_exact_matches")) == sent


def test_fuzzy_template_parameters_match_the_builder_exactly() -> None:
    probe = BlockingProbe("jane", "jane", None, None, None)

    assert parameter_names(render("find_fuzzy_candidates")) == {
        p.name for p in fuzzy_parameters(probe, 50)
    }


def test_audit_template_parameters_match_the_builder_exactly() -> None:
    event = AuditEvent(sample_attempt(), "register", "duplicate", 409)

    assert parameter_names(render("insert_audit_event")) == {
        p.name for p in event_parameters(event)
    }


def test_the_lock_delete_follows_begin_and_precedes_the_merge() -> None:
    sql = render("register_customer")

    begin = sql.index("BEGIN TRANSACTION")
    lock = sql.index(f"DELETE FROM `{PROJECT}.{DATASET}.customers` WHERE FALSE")
    merge = sql.index("MERGE `")
    assert begin < lock < merge


def test_the_duplicate_key_check_selects_no_key_values() -> None:
    sql = render("checks/duplicate_keys")

    assert re.search(r"SELECT\s+key_name,\s+ARRAY_AGG\(customer_id", sql)
    assert "key_value," not in sql.split("FROM (")[0]


def test_the_schema_file_splits_into_three_statements_despite_semicolons_in_strings() -> None:
    script = render_template(
        "001_customer_ops_schema", project=PROJECT, dataset=DATASET, location="US"
    )

    statements = split_statements(script)

    assert [s.split("`")[0].strip() for s in statements] == [
        "CREATE SCHEMA IF NOT EXISTS",
        "CREATE TABLE IF NOT EXISTS",
        "CREATE TABLE IF NOT EXISTS",
    ]
    assert "enforces email, phone, and tax-ID uniqueness; sql/checks" in statements[1]


def test_statement_splitting_ignores_semicolons_in_comments_and_backticks() -> None:
    script = "-- note; here\nSELECT 'a;b' AS x; SELECT `t;1`;"

    assert split_statements(script) == ["-- note; here\nSELECT 'a;b' AS x", "SELECT `t;1`"]


def test_a_template_name_cannot_escape_the_sql_directory() -> None:
    with pytest.raises(TemplateError):
        render_template("../pyproject", project=PROJECT, dataset=DATASET)
