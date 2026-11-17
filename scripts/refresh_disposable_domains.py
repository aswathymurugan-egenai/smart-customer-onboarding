"""Refresh `app/data/disposable_domains.txt` from a public blocklist.

Run `python scripts/refresh_disposable_domains.py`. The file is rewritten only when the
upstream domain set differs from the vendored one, so a run with no upstream change leaves
the file, including its fetch date, untouched.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/disposable-email-domains/"
    "disposable-email-domains/main/disposable_email_blocklist.conf"
)
DEFAULT_PROJECT_URL = "https://github.com/disposable-email-domains/disposable-email-domains"
DEFAULT_LICENSE = "CC0 1.0 Universal"
TARGET = Path(__file__).resolve().parents[1] / "app" / "data" / "disposable_domains.txt"
FETCH_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_BYTES = 5_000_000

_DOMAIN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def parse_domains(text: str) -> list[str]:
    """Return the sorted, de-duplicated, well-formed domains in a one-per-line list.

    Comment lines, blank lines, and anything that does not look like a domain name are
    dropped, because the downloaded text is data and never code.
    """
    domains = {
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return sorted(domain for domain in domains if _DOMAIN.fullmatch(domain))


def render(domains: list[str], *, project_url: str, license_name: str, fetched_on: str) -> str:
    """Build the vendored file: a provenance header, then one domain per line."""
    header = [
        "# Disposable email domains, one per line.",
        f"# Source: {project_url}",
        f"# License: {license_name}",
        f"# Fetched: {fetched_on}",
        "# Refresh with: python scripts/refresh_disposable_domains.py",
    ]
    return "\n".join([*header, *domains]) + "\n"


def download(source: str) -> str:
    """Fetch the list over HTTPS with a size cap."""
    if not source.startswith("https://"):
        raise ValueError(f"Refusing a non-HTTPS source: {source}")
    with urllib.request.urlopen(source, timeout=FETCH_TIMEOUT_SECONDS) as response:
        payload: bytes = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("The downloaded list exceeds the size cap.")
    return payload.decode("utf-8")


def refresh(
    target: Path,
    *,
    source: str = DEFAULT_SOURCE,
    project_url: str = DEFAULT_PROJECT_URL,
    license_name: str = DEFAULT_LICENSE,
    fetch: Callable[[str], str] = download,
    today: str | None = None,
) -> bool:
    """Rewrite `target` when the upstream set changed. Return whether the file changed."""
    upstream = parse_domains(fetch(source))
    if not upstream:
        raise ValueError("The source produced no valid domains; keeping the existing file.")
    current = parse_domains(target.read_text(encoding="utf-8")) if target.exists() else []
    if upstream == current:
        return False
    fetched_on = today or datetime.now(UTC).date().isoformat()
    target.write_text(
        render(upstream, project_url=project_url, license_name=license_name, fetched_on=fetched_on),
        encoding="utf-8",
    )
    return True


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="HTTPS URL of the list")
    parser.add_argument("--target", type=Path, default=TARGET, help="file to rewrite")
    args = parser.parse_args(argv)
    changed = refresh(args.target, source=args.source)
    print(f"{args.target}: {'updated' if changed else 'already current'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
