from evals.grading import grade, outcome_from_events
from lineup_lab.agent.events import DoneEvent, StepEvent
from lineup_lab.stats.db import SqlResult


def res(columns, rows):
    return SqlResult(columns, rows, len(rows), False, 1)


REF = res(["player_name", "targets"], [["Puka Nacua", 30], ["Davante Adams", 25]])


def test_equal_results_pass():
    assert grade(REF, res(["player_name", "targets"], [["Puka Nacua", 30], ["Davante Adams", 25]]))


def test_extra_actual_column_passes():
    actual = res(
        ["player_name", "team", "t"], [["Puka Nacua", "LA", 30], ["Davante Adams", "LA", 25]]
    )
    assert grade(REF, actual)


def test_reordered_rows_and_columns_pass():
    assert grade(REF, res(["t", "name"], [[25, "davante adams"], [30, "Puka Nacua"]]))


def test_wrong_value_fails():
    assert not grade(
        REF, res(["player_name", "targets"], [["Puka Nacua", 31], ["Davante Adams", 25]])
    )


def test_row_count_mismatch_fails():
    assert not grade(REF, res(["player_name", "targets"], [["Puka Nacua", 30]]))


def test_none_fails():
    assert not grade(REF, None)


def test_float_rounding_to_one_decimal():
    assert grade(res(["ppg"], [[12.0]]), res(["ppg"], [[12.04]]))
    assert not grade(res(["ppg"], [[12.0]]), res(["ppg"], [[12.1]]))


def test_int_and_float_compare_equal():
    assert grade(res(["t"], [[30]]), res(["t"], [[30.0]]))


def _step(id, kind, status, **detail):
    return StepEvent(id, kind, status, "", detail, 1)


DONE = DoneEvent(ttft_ms=900, total_ms=3000, cost_usd=0.05, input_tokens=1, output_tokens=1)


def test_outcome_stats_with_retry():
    events = [
        _step("route", "route", "done", route="stats"),
        _step("sql-1", "sql", "failed", sql="bad", error="x"),
        _step("sql-2", "sql", "done", sql="SELECT 1"),
        DONE,
    ]
    o = outcome_from_events(events)
    assert o == {
        "outcome": "stats",
        "final_sql": "SELECT 1",
        "attempts": 2,
        "cost_usd": 0.05,
        "ttft_ms": 900,
        "total_ms": 3000,
        "error": None,
    }


def test_outcome_ambiguous_name_counts_as_ambiguous():
    events = [
        _step("route", "route", "done", route="stats"),
        _step("resolve", "resolve", "done", resolutions=[{"status": "ambiguous"}]),
        DONE,
    ]
    assert outcome_from_events(events)["outcome"] == "ambiguous"
    assert outcome_from_events(events)["final_sql"] is None


def test_outcome_declined_route():
    events = [_step("route", "route", "done", route="out_of_scope"), DONE]
    assert outcome_from_events(events)["outcome"] == "out_of_scope"
