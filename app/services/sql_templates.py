"""Loads and renders the SQL templates under `sql/`.

BigQuery parameters cannot name tables, so the project and dataset names are substituted
into the text. They are checked against strict patterns first. Every request value travels
as a query parameter instead.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from app.config import DATASET_ID_PATTERN, LOCATION_PATTERN, PROJECT_ID_PATTERN

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


class TemplateError(ValueError):
    """A template could not be found or rendered, or an identifier failed validation."""


def validate_identifiers(project: str, dataset: str, location: str | None = None) -> None:
    """Raise `TemplateError` unless every identifier matches its strict pattern."""
    if not PROJECT_ID_PATTERN.fullmatch(project):
        raise TemplateError("The project id is not a valid GCP project id.")
    if not DATASET_ID_PATTERN.fullmatch(dataset):
        raise TemplateError("The dataset name may contain only letters, digits, and underscores.")
    if location is not None and not LOCATION_PATTERN.fullmatch(location):
        raise TemplateError("The location may contain only letters, digits, and hyphens.")


def load_template(name: str, sql_dir: Path = SQL_DIR) -> str:
    """Read `sql/<name>.sql`. `name` may include a subdirectory, such as `checks/x`."""
    path = (sql_dir / f"{name}.sql").resolve()
    if sql_dir.resolve() not in path.parents:
        raise TemplateError(f"Template {name!r} is outside the sql directory.")
    if not path.is_file():
        raise TemplateError(f"Template {name!r} does not exist under {sql_dir}.")
    return path.read_text(encoding="utf-8")


def render_template(
    name: str,
    *,
    project: str,
    dataset: str,
    location: str | None = None,
    sql_dir: Path = SQL_DIR,
) -> str:
    """Substitute the validated identifiers into a template."""
    validate_identifiers(project, dataset, location)
    values = {"project": project, "dataset": dataset}
    if location is not None:
        values["location"] = location
    try:
        return Template(load_template(name, sql_dir)).substitute(values)
    except (KeyError, ValueError) as error:
        raise TemplateError(
            f"Template {name!r} has a placeholder that cannot be filled."
        ) from error


def split_statements(script: str) -> list[str]:
    """Split a SQL script on semicolons that sit outside strings, backticks, and comments."""
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    in_comment = False
    index = 0
    while index < len(script):
        char = script[index]
        if in_comment:
            current.append(char)
            in_comment = char != "\n"
        elif quote is not None:
            current.append(char)
            if char == "\\" and quote != "`" and index + 1 < len(script):
                index += 1
                current.append(script[index])
            elif char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
            current.append(char)
        elif char == "-" and script.startswith("--", index):
            in_comment = True
            current.append(char)
        elif char == ";":
            statements.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    statements.append("".join(current).strip())
    return [statement for statement in statements if _has_code(statement)]


def _has_code(statement: str) -> bool:
    return any(
        line.strip() and not line.strip().startswith("--") for line in statement.splitlines()
    )
