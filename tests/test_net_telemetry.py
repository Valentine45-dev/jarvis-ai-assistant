"""Unit tests for core/net_telemetry (no network / subprocess)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import net_telemetry as nt


def test_format_rate_bps():
    assert "B/s" in nt.format_rate_bps(100)
    assert "K/" in nt.format_rate_bps(1536) or "1.5" in nt.format_rate_bps(1536)
    assert "M/" in nt.format_rate_bps(3 * 1024 * 1024)


def test_smooth_rtt_ema():
    assert nt.smooth_rtt_ema(100, None) == 100.0
    v = nt.smooth_rtt_ema(0, 100.0, alpha=0.35)
    assert 64 < v < 66
    assert nt.smooth_rtt_ema(None, 50.0) == 50.0


def test_parse_icmp_time_ms_english():
    assert nt._parse_icmp_time_ms("Reply from 1.1.1.1: bytes=32 time=14ms TTL=55") == 14
    assert nt._parse_icmp_time_ms("time<1ms") == 1
    assert nt._parse_icmp_time_ms("Request timed out.") is None


def test_throughput_sampler_first():
    s = nt.ThroughputSampler()
    a, b = s.sample()
    assert a == 0.0 and b == 0.0
