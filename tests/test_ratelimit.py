"""限流器纯逻辑：窗口内限额、窗口滑动、key 隔离。"""
from astrbot_plugin_pet_platform.pet_ratelimit import RateLimiter


def test_allows_up_to_limit_then_blocks_until_window_slides():
    now = [0.0]
    limiter = RateLimiter(limit=2, window_sec=10, now=lambda: now[0])
    assert limiter.allow("main") is True
    assert limiter.allow("main") is True
    assert limiter.allow("main") is False
    # 窗口未滑动前仍拒绝；超过窗口后放行。
    now[0] = 9.9
    assert limiter.allow("main") is False
    now[0] = 10.1
    assert limiter.allow("main") is True


def test_keys_are_isolated():
    limiter = RateLimiter(limit=1, window_sec=60, now=lambda: 0.0)
    assert limiter.allow("main") is True
    assert limiter.allow("other") is True
    assert limiter.allow("main") is False
