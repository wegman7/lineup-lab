from types import SimpleNamespace

import pytest

from lineup_lab.llm.pricing import cost_usd


def usage(i=0, o=0, cw=0, cr=0):
    return SimpleNamespace(
        input_tokens=i, output_tokens=o, cache_creation_input_tokens=cw, cache_read_input_tokens=cr
    )


def test_cost_opus():
    assert cost_usd("claude-opus-5-5", usage(i=1_000_000, o=1_000_000)) == pytest.approx(24.0)
    assert cost_usd("claude-opus-5-5", usage(cr=1_000_000)) == pytest.approx(0.20)
    assert cost_usd("claude-opus-5-5", usage(cw=1_000_000)) == pytest.approx(5.0)


def test_none_usage_fields_are_zero():
    u = SimpleNamespace(
        input_tokens=1000,
        output_tokens=None,
        cache_creation_input_tokens=None,
        cache_read_input_tokens=None,
    )
    assert cost_usd("claude-opus-5-5", u) == pytest.approx(0.004)


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        cost_usd("gpt-whatever", usage(i=1))
