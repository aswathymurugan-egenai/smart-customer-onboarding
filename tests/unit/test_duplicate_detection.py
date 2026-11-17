"""Duplicate detection: exact keys, blocking, pre-scoring, and the model's verdicts."""

from __future__ import annotations

import pytest

from app.domain.customer import BlockingProbe, CandidateRow
from app.domain.errors import AdvisorFailure, RateLimited
from app.services.advisor import DisabledAdvisor
from app.services.memory_repository import InMemoryCustomerRepository
from tests.builders import make_attempt, make_record
from tests.fakes import FakeClock
from tests.support import customer_input, make_graph


class ScriptedRepository(InMemoryCustomerRepository):
    """The in-memory store with blocking results the test controls."""

    def __init__(self, rows: list[CandidateRow]) -> None:
        super().__init__(FakeClock())
        self.rows = rows
        self.probes: list[BlockingProbe] = []

    async def find_fuzzy_candidates(self, probe: BlockingProbe, limit: int) -> list[CandidateRow]:
        self.probes.append(probe)
        return self.rows


def row(customer_id: str, name: str = "jane doe", **overrides: object) -> CandidateRow:
    values: dict[str, object] = {
        "customer_id": customer_id,
        "customer_type": "individual",
        "company_name": None,
        "normalized_name": name,
        "name_key": " ".join(sorted(name.split())),
        "normalized_address": "100 example street springfield il 62701 us",
        "city": "Springfield",
        "postal_code_key": "62701",
        "country_code": "US",
        "email_domain": "mail.test",
        "email_local_part": "someone",
    }
    values.update(overrides)
    return CandidateRow(**values)  # type: ignore[arg-type]


async def test_exact_email_and_phone_matches_are_both_reported() -> None:
    graph = make_graph()
    await graph.repository.register(make_record("c1"), make_attempt())

    result = await graph.duplicates.check(
        customer_input(tax_id=None, tax_id_type=None), graph.ctx()
    )

    assert result.exact_matches == ["email", "phone"]


async def test_candidates_below_the_floor_never_reach_the_advisor() -> None:
    repo = ScriptedRepository([row("c1", name="zebra quokka")])
    graph = make_graph(repository=repo)

    result = await graph.duplicates.check(customer_input(), graph.ctx())

    assert graph.advisor.fuzzy_calls == []
    assert result.possible_duplicate is None
    assert result.advisory_status == "ok"


async def test_at_most_five_candidates_reach_the_advisor() -> None:
    repo = ScriptedRepository([row(f"c{n}") for n in range(8)])
    graph = make_graph(repository=repo)

    await graph.duplicates.check(customer_input(), graph.ctx())

    [(_, sent)] = graph.advisor.fuzzy_calls
    assert [view.ref for view in sent] == ["c1", "c2", "c3", "c4", "c5"]


async def test_refs_map_back_to_customer_ids_for_the_audit_row_and_stay_out_of_the_response() -> (
    None
):
    repo = ScriptedRepository([row("real-id-A"), row("real-id-B", name="jane doe")])
    graph = make_graph(repository=repo)
    graph.advisor.fuzzy_verdicts = {"c2": ("likely_same", 0.9, ["name_variant"])}

    result = await graph.duplicates.check(customer_input(), graph.ctx())

    assert result.possible_duplicate is not None
    assert "real-id" not in result.model_dump_json()
    assert '"c2"' not in result.model_dump_json()
    [event] = repo.audit_events
    assert event.attempt.fuzzy_candidate_ids == ("real-id-B",)
    assert event.attempt.fuzzy_max_confidence == 0.9
    assert event.operation == "check_duplicate"
    assert event.outcome == "checked"


async def test_a_verdict_below_the_warning_confidence_is_audited_but_not_warned() -> None:
    repo = ScriptedRepository([row("c1")])
    graph = make_graph(repository=repo)
    graph.advisor.fuzzy_verdicts = {"*": ("possibly_same", 0.5, ["nickname"])}

    result = await graph.duplicates.check(customer_input(), graph.ctx())

    assert result.possible_duplicate is None
    assert repo.audit_events[0].attempt.fuzzy_candidate_ids == ("c1",)


async def test_reason_codes_are_capped_at_three_strongest_first() -> None:
    repo = ScriptedRepository([row("c1"), row("c2")])
    graph = make_graph(repository=repo)
    graph.advisor.fuzzy_verdicts = {
        "c1": ("likely_same", 0.9, ["name_variant", "nickname"]),
        "c2": ("possibly_same", 0.7, ["address_variant", "corporate_alias"]),
    }

    result = await graph.duplicates.check(customer_input(), graph.ctx())

    assert result.possible_duplicate is not None
    assert result.possible_duplicate.reasons == ["name_variant", "nickname", "address_variant"]
    assert result.possible_duplicate.confidence == 0.9


async def test_an_advisor_failure_returns_exact_matches_with_unavailable_status() -> None:
    repo = ScriptedRepository([row("c1")])
    graph = make_graph(repository=repo)
    await repo.register(make_record("existing"), make_attempt())
    graph.advisor.fail_fuzzy = AdvisorFailure("unavailable")

    result = await graph.duplicates.check(customer_input(), graph.ctx())

    assert result.exact_matches == ["email", "phone"]
    assert result.possible_duplicate is None
    assert result.advisory_status == "unavailable"


async def test_a_disabled_advisor_reports_disabled_and_makes_no_call() -> None:
    repo = ScriptedRepository([row("c1")])
    graph = make_graph(repository=repo, advisor=DisabledAdvisor())

    result = await graph.duplicates.check(customer_input(), graph.ctx())

    assert result.advisory_status == "disabled"
    assert repo.probes == []


async def test_skipping_likely_duplicates_runs_no_blocking_query_or_model_call() -> None:
    repo = ScriptedRepository([row("c1")])
    graph = make_graph(repository=repo)

    await graph.duplicates.check(customer_input(), graph.ctx(), include_likely_duplicates=False)

    assert repo.probes == []
    assert graph.advisor.fuzzy_calls == []


async def test_a_rate_limited_check_is_audited_and_raised() -> None:
    graph = make_graph(rate_check_duplicate_limit=1)
    ctx = graph.ctx()
    await graph.duplicates.check(customer_input(), ctx)

    with pytest.raises(RateLimited):
        await graph.duplicates.check(customer_input(), ctx)

    outcomes = [event.outcome for event in graph.repository.audit_events]
    assert outcomes == ["checked", "rate_limited"]


async def test_the_model_sees_only_normalized_names_and_places_never_contact_keys() -> None:
    repo = ScriptedRepository([row("c1")])
    graph = make_graph(repository=repo)

    await graph.duplicates.check(customer_input(), graph.ctx())

    [(applicant, _)] = graph.advisor.fuzzy_calls
    assert applicant.normalized_name == "jane doe"
    assert not hasattr(applicant, "phone")
    assert not hasattr(applicant, "email")
