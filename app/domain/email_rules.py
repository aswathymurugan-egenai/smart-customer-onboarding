"""Deterministic email-domain rules: the disposable list and typo suggestions."""

from __future__ import annotations

from collections.abc import Iterable

from rapidfuzz.distance import DamerauLevenshtein

MAX_TYPO_DISTANCE = 2
SHORT_DOMAIN_LENGTH = 8
SHORT_DOMAIN_MAX_DISTANCE = 1

TLD_SLIPS: dict[str, str] = {
    "con": "com",
    "cmo": "com",
    "ocm": "com",
    "vom": "com",
    "xom": "com",
    "comm": "com",
    "cim": "com",
}


def parent_domains(domain: str) -> list[str]:
    """Return the domain and every parent that still has a dot, longest first."""
    labels = domain.lower().strip(".").split(".")
    return [".".join(labels[index:]) for index in range(len(labels) - 1)]


def is_disposable(domain: str, disposable: frozenset[str]) -> bool:
    """Report whether the domain, or any parent domain, is on the disposable list."""
    return any(candidate in disposable for candidate in parent_domains(domain))


def typo_suggestion(domain: str, free_mail: Iterable[str]) -> str | None:
    """Suggest the intended domain when `domain` looks like a slip for a free-mail domain.

    Two signals apply. A known TLD slip such as `.con` is corrected in place. Otherwise the
    domain must sit within Damerau-Levenshtein distance 2 of a free-mail domain, or distance
    1 when that domain is short, because short names collide by chance.
    """
    domain = domain.lower()
    known = sorted(set(free_mail))
    if domain in known:
        return None

    name, _, tld = domain.rpartition(".")
    corrected_tld = TLD_SLIPS.get(tld)
    if name and corrected_tld is not None:
        return f"{name}.{corrected_tld}"

    best: tuple[int, str] | None = None
    for candidate in known:
        limit = (
            SHORT_DOMAIN_MAX_DISTANCE if len(candidate) < SHORT_DOMAIN_LENGTH else MAX_TYPO_DISTANCE
        )
        distance = DamerauLevenshtein.distance(domain, candidate, score_cutoff=limit)
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, candidate)
    return best[1] if best else None
