from datetime import UTC, datetime

from lineup_lab.api.limits import RateLimiter, SpendTracker


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


T0 = datetime(2026, 11, 18, 23, 0, tzinfo=UTC).timestamp()


def test_rate_limit_blocks_21st_request():
    clock = Clock(T0)
    rl = RateLimiter(per_hour=20, clock=clock)
    for _ in range(20):
        assert rl.check("1.2.3.4") is None
        clock.t += 1
    wait = rl.check("1.2.3.4")
    assert wait is not None and 0 < wait <= 3600
    assert rl.check("5.6.7.8") is None  # other visitors unaffected


def test_rate_limit_window_slides():
    clock = Clock(T0)
    rl = RateLimiter(per_hour=2, clock=clock)
    assert rl.check("ip") is None
    clock.t += 10
    assert rl.check("ip") is None
    assert rl.check("ip") is not None
    clock.t += 3591  # first request is now older than an hour
    assert rl.check("ip") is None


def test_spend_cap_and_reset_at_utc_midnight():
    clock = Clock(T0)
    sp = SpendTracker(cap_usd=5.0, clock=clock)
    sp.add(4.99)
    assert not sp.exhausted()
    sp.add(0.02)
    assert sp.exhausted()
    assert sp.resets_at() == datetime(2026, 11, 19, tzinfo=UTC)
    clock.t += 3600  # past midnight UTC
    assert not sp.exhausted()
    assert sp.spent == 0.0
